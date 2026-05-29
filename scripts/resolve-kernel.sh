#!/usr/bin/env bash
# resolve-kernel.sh — resolve the absolute KERNEL.md path a subagent should read.
#
# Prints the absolute path to stdout (exit 0) or nothing (exit 1) when no
# kernel exists anywhere.
#
# Resolution chain (first hit wins):
#   1. $Z_HARNESS_KERNEL_PATH     if set AND the file exists
#   2. ${Z_HARNESS_REPO_ROOT:-$(git rev-parse --show-toplevel)}/.z-harness/KERNEL.md
#   3. ${XDG_CONFIG_HOME:-$HOME/.config}/z-harness/KERNEL.md
#   4. else exit 1
#
# Staleness check (R5/SC3, NON-BLOCKING):
#   After resolving, parse source_hash: from the header, shell out to
#   build-kernel.py --print-hash --scope <s>, compare. On mismatch emit a
#   LOUD stderr warning. On any failure (missing script, non-zero exit,
#   unparseable) silently skip. Never changes exit code or resolved path.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
_BUILD_KERNEL="${_SCRIPT_DIR}/build-kernel.py"

# ---------------------------------------------------------------------------
# Resolution chain
# ---------------------------------------------------------------------------

_resolved_path=""
_resolved_scope=""   # "explicit" | "project" | "global"

# Branch 1: explicit override
if [[ -n "${Z_HARNESS_KERNEL_PATH:-}" && -f "${Z_HARNESS_KERNEL_PATH}" ]]; then
    _resolved_path="${Z_HARNESS_KERNEL_PATH}"
    _resolved_scope="explicit"
fi

# Branch 2: project-scope KERNEL.md
if [[ -z "${_resolved_path}" ]]; then
    _repo_root="${Z_HARNESS_REPO_ROOT:-}"
    if [[ -z "${_repo_root}" ]]; then
        _repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    fi
    if [[ -n "${_repo_root}" ]]; then
        _candidate="${_repo_root}/.z-harness/KERNEL.md"
        if [[ -f "${_candidate}" ]]; then
            _resolved_path="${_candidate}"
            _resolved_scope="project"
        fi
    fi
fi

# Branch 3: global KERNEL.md
if [[ -z "${_resolved_path}" ]]; then
    _xdg_cfg="${XDG_CONFIG_HOME:-${HOME}/.config}"
    _candidate="${_xdg_cfg}/z-harness/KERNEL.md"
    if [[ -f "${_candidate}" ]]; then
        _resolved_path="${_candidate}"
        _resolved_scope="global"
    fi
fi

# Branch 4: nothing found
if [[ -z "${_resolved_path}" ]]; then
    exit 1
fi

# ---------------------------------------------------------------------------
# Staleness check (R5/SC3 — non-blocking, best-effort)
# ---------------------------------------------------------------------------

_staleness_check() {
    local path="$1"
    local scope_hint="$2"

    # Parse source_hash: <12hex> from the kernel header.
    local header_hash
    header_hash="$(grep -m1 'source_hash:' "${path}" 2>/dev/null \
        | sed 's/.*source_hash:[[:space:]]*//' \
        | sed 's/[[:space:]].*//' \
        | tr -d '[:space:]')" || return 0
    [[ -z "${header_hash}" ]] && return 0

    # Determine scope for the recompute call.
    local scope
    case "${scope_hint}" in
        project)   scope="project" ;;
        global)    scope="global" ;;
        explicit)
            # Infer from the resolved path itself.
            local xdg_cfg="${XDG_CONFIG_HOME:-${HOME}/.config}"
            if [[ "${path}" == "${xdg_cfg}/z-harness/"* ]]; then
                scope="global"
            else
                # Best-effort: try to detect if path is inside a git repo's .z-harness.
                local dir
                dir="$(dirname "${path}")"
                local repo_top
                repo_top="$(git -C "${dir}" rev-parse --show-toplevel 2>/dev/null || true)"
                if [[ -n "${repo_top}" && "${path}" == "${repo_top}/.z-harness/"* ]]; then
                    scope="project"
                else
                    scope="global"
                fi
            fi
            ;;
        *)  return 0 ;;
    esac

    # Build the recompute args.
    local -a recompute_args=("${_BUILD_KERNEL}" "--print-hash" "--scope" "${scope}")

    # For project scope we need a --repo-root.
    if [[ "${scope}" == "project" ]]; then
        local repo_root_arg
        case "${scope_hint}" in
            project)
                repo_root_arg="${Z_HARNESS_REPO_ROOT:-}"
                if [[ -z "${repo_root_arg}" ]]; then
                    repo_root_arg="$(git rev-parse --show-toplevel 2>/dev/null || true)"
                fi
                ;;
            explicit)
                local kdir
                kdir="$(dirname "${path}")"
                repo_root_arg="$(git -C "${kdir}" rev-parse --show-toplevel 2>/dev/null || true)"
                ;;
        esac
        if [[ -n "${repo_root_arg}" ]]; then
            recompute_args+=("--repo-root" "${repo_root_arg}")
        fi
    fi

    # Shell out to build-kernel.py --print-hash (non-mutating).
    local recomputed_hash
    recomputed_hash="$(python3 "${recompute_args[@]}" 2>/dev/null)" || return 0
    recomputed_hash="$(printf '%s' "${recomputed_hash}" | tr -d '[:space:]')"
    [[ -z "${recomputed_hash}" ]] && return 0

    # Compare.
    if [[ "${header_hash}" != "${recomputed_hash}" ]]; then
        echo "WARNING: KERNEL.md is stale (header ${header_hash} != recomputed ${recomputed_hash}); run /z-axiom-scan or rebuild" >&2
    fi
}

# Run staleness check (errors here must not affect resolution output/exit code).
_staleness_check "${_resolved_path}" "${_resolved_scope}" || true

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

printf '%s\n' "${_resolved_path}"
exit 0
