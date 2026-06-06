#!/usr/bin/env sh
# shellcheck shell=dash
# curl-install.sh — bootstrap uv and install the z-harness CLI wheel
#
# Usage (curl | sh):
#   curl -fsSL https://releases.zeketools.dev/z-harness/install.sh | sh
#
# Usage (local):
#   sh scripts/curl-install.sh
#
# Environment:
#   Z_HARNESS_RELEASE_URL   Override manifest URL (default: https://releases.zeketools.dev/z-harness/latest.json)
#
# What this script does:
#   1. Bootstraps uv if absent (via astral.sh)
#   2. Fetches the release manifest (latest.json)
#   3. Downloads the wheel from manifest.wheel_url
#   4. Verifies sha256 against manifest.sha256 BEFORE installing
#   5. Installs the wheel with: uv tool install <wheel>
#
# On any failure the script exits non-zero with a specific, actionable message
# and copy-paste manual instructions. No bespoke venv+wrapper in v1.
#
# Note: cursor/agy plugin injection is handled by each adapter's inject() method,
# not by this script. install.sh handles claude/codex plugin install.

set -eu

DEFAULT_RELEASE_URL="https://releases.zeketools.dev/z-harness/latest.json"
MANIFEST_URL="${Z_HARNESS_RELEASE_URL:-$DEFAULT_RELEASE_URL}"

# The maximum manifest schema_version this installer understands.
# Keep in sync with z_harness_cli/release.py::SUPPORTED_SCHEMA_VERSION.
SUPPORTED_SCHEMA_VERSION=1

# Strip query parameters from MANIFEST_URL for constructing sibling URLs
# e.g. https://example.com/z-harness/latest.json?cache=1 → https://example.com/z-harness
_manifest_base() {
    local url="${MANIFEST_URL%%\?*}"
    printf '%s' "${url%/*}"
}

# ── helpers ──────────────────────────────────────────────────────────────────

die() {
    printf '\nerror: %s\n' "$1" >&2
    shift
    if [ "$#" -gt 0 ]; then
        printf '\n%s\n' "$*" >&2
    fi
    exit 1
}

info() {
    printf 'curl-install: %s\n' "$1"
}

# ── dependency checks ─────────────────────────────────────────────────────────

need_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        die "'$1' not found on PATH." \
            "Please install $1 and re-run this script."
    fi
}

# ── sha256 verification ───────────────────────────────────────────────────────

verify_sha256() {
    local file="$1"
    local expected="$2"
    local actual

    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$file" | cut -d' ' -f1)"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$file" | cut -d' ' -f1)"
    else
        die "Neither sha256sum nor shasum found." \
            "Install one of: coreutils (sha256sum) or shasum (macOS/perl)\n  Then re-run: $(_manifest_base)/install.sh | sh"
    fi

    # Normalise to lower-case for comparison
    actual="$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')"
    expected="$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')"

    if [ "$actual" != "$expected" ]; then
        printf '\nsha256 mismatch!\n' >&2
        printf '  expected: %s\n' "$expected" >&2
        printf '  got:      %s\n' "$actual" >&2
        return 1
    fi
    return 0
}

# ── download ──────────────────────────────────────────────────────────────────

download() {
    local url="$1"
    local dest="$2"

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 "$url" -o "$dest" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$url" -O "$dest" || return 1
    else
        die "Neither curl nor wget found." \
            "Install curl or wget, then re-run:\n  curl -fsSL $(_manifest_base)/install.sh | sh"
    fi
}

# ── manifest parsing ──────────────────────────────────────────────────────────

# Extract a string value for a top-level key from a JSON file.
# Uses python3 (a hard dependency of this project) for correctness.
json_get() {
    local file="$1"
    local key="$2"
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[sys.argv[2]])" \
        "$file" "$key" 2>/dev/null || true
}

# ── uv bootstrap ─────────────────────────────────────────────────────────────

bootstrap_uv() {
    if command -v uv >/dev/null 2>&1; then
        info "uv already installed: $(uv --version 2>&1 | head -1)"
        return 0
    fi

    info "uv not found — bootstrapping via astral.sh..."

    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        die "Cannot bootstrap uv: neither curl nor wget found." \
            "Install uv manually, then re-run this script:\n  https://docs.astral.sh/uv/getting-started/installation/"
    fi

    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || {
            die "uv bootstrap failed (curl | sh exited non-zero)." \
                "Install uv manually:\n  https://docs.astral.sh/uv/getting-started/installation/\nThen re-run this script."
        }
    else
        wget -qO- https://astral.sh/uv/install.sh | sh || {
            die "uv bootstrap failed (wget | sh exited non-zero)." \
                "Install uv manually:\n  https://docs.astral.sh/uv/getting-started/installation/\nThen re-run this script."
        }
    fi

    # The installer adds uv to ~/.cargo/bin or ~/.local/bin; reload PATH
    export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"

    if ! command -v uv >/dev/null 2>&1; then
        die "uv was installed but is not on PATH." \
            "Add the following to your shell profile and re-run:\n  export PATH=\"\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH\"\n\nOr install z-harness manually:\n  uv tool install z-harness"
    fi

    info "uv bootstrapped: $(uv --version 2>&1 | head -1)"
}

# ── main ──────────────────────────────────────────────────────────────────────

main() {
    # 1. Check OS (macOS and Linux only in v1)
    case "$(uname -s)" in
        Darwin|Linux) ;;
        *)
            die "Unsupported OS: $(uname -s)" \
                "z-harness supports macOS and Linux in v1.\n  For manual installation see: https://github.com/zeketools/z-harness"
            ;;
    esac

    # 2. Require python3 (used for JSON parsing)
    need_cmd python3

    # 3. Bootstrap uv
    bootstrap_uv

    # 4. Create private temp dir immediately and register cleanup trap before
    #    any operation that could call die(), so no orphaned files on early exit.
    #    tmpdir is global (not local) so the EXIT trap can reference it after
    #    main() returns without hitting an unbound-variable error under set -u.
    #    The trap is registered BEFORE chmod so any failure after mktemp still cleans up.
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT
    chmod 700 "$tmpdir"

    # 5. Fetch manifest
    info "Fetching release manifest from ${MANIFEST_URL}..."

    local manifest_file
    manifest_file="${tmpdir}/manifest.json"

    if ! download "$MANIFEST_URL" "$manifest_file"; then
        die "Failed to download release manifest from ${MANIFEST_URL}." \
            "Check your network connection and try again.\n\nManual install:\n  uv tool install z-harness"
    fi

    if [ ! -s "$manifest_file" ]; then
        die "Empty response fetching release manifest from ${MANIFEST_URL}." \
            "Manual install:\n  uv tool install z-harness"
    fi

    # 6. Extract fields from manifest using python3 JSON parser
    local schema_version version wheel_url sha256
    schema_version="$(json_get "$manifest_file" "schema_version")"
    version="$(json_get "$manifest_file" "version")"
    wheel_url="$(json_get "$manifest_file" "wheel_url")"
    sha256="$(json_get "$manifest_file" "sha256")"

    if [ -z "$version" ] || [ -z "$wheel_url" ] || [ -z "$sha256" ]; then
        die "Manifest is missing required fields (version, wheel_url, sha256)." \
            "This may indicate a corrupted release. Try again later or report to https://github.com/zeketools/z-harness\n\nManifest URL: ${MANIFEST_URL}"
    fi

    # Validate schema_version is present and is a non-negative integer
    if ! printf '%s' "$schema_version" | grep -Eq '^[0-9]+$'; then
        die "Manifest missing or non-integer 'schema_version' field (got: '${schema_version}')." \
            "This may indicate a corrupted or tampered manifest.\n\nManifest URL: ${MANIFEST_URL}"
    fi

    # Reject manifests with a schema_version newer than this installer supports
    if [ "$schema_version" -gt "$SUPPORTED_SCHEMA_VERSION" ]; then
        die "Manifest schema_version ${schema_version} is newer than this installer supports (${SUPPORTED_SCHEMA_VERSION})." \
            "Update z-harness / re-run the installer:\n  curl -fsSL $(_manifest_base)/install.sh | sh"
    fi

    # Validate sha256 is exactly 64 hex characters before use
    if ! printf '%s' "$sha256" | grep -Eq '^[0-9a-fA-F]{64}$'; then
        die "Manifest sha256 field is not a valid 64-character hex digest." \
            "This may indicate a corrupted or tampered manifest.\n\nManifest URL: ${MANIFEST_URL}"
    fi

    # Enforce wheel_url uses https:// scheme (reject http/ftp/file/etc.)
    case "$wheel_url" in
        https://*) ;;
        *)
            die "Manifest wheel_url does not use https:// scheme: ${wheel_url}" \
                "A non-https wheel URL may indicate a tampered manifest.\n\nManifest URL: ${MANIFEST_URL}"
            ;;
    esac

    info "Latest z-harness version: ${version}"

    # 7. Download wheel into private temp dir
    info "Downloading wheel: ${wheel_url}"

    local wheel_file
    wheel_file="${tmpdir}/z-harness.whl"

    if ! download "$wheel_url" "$wheel_file"; then
        die "Failed to download wheel from ${wheel_url}." \
            "Check your network connection and try again.\n\nManual install:\n  uv tool install ${wheel_url}"
    fi

    # 8. Verify sha256 BEFORE install
    info "Verifying sha256..."
    if ! verify_sha256 "$wheel_file" "$sha256"; then
        die "sha256 mismatch — aborting install. The download may be corrupt or tampered with." \
            "Do not install this wheel.\n\nTo retry:\n  curl -fsSL $(_manifest_base)/install.sh | sh\n\nIf the problem persists, report to https://github.com/zeketools/z-harness"
    fi
    info "sha256 verified."

    # 9. Install wheel via uv tool install
    info "Installing z-harness ${version} via uv tool install..."
    if ! uv tool install --upgrade "$wheel_file"; then
        die "uv tool install failed for z-harness ${version}." \
            "Manual install options:\n  1. uv tool install ${wheel_url}\n  2. pip install --user ${wheel_url}\n\nIf uv is not yet on PATH, try:\n  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    # Ensure uv tool bins are on PATH for the remainder of this shell invocation
    export PATH="${HOME}/.local/bin:${PATH}"

    info "z-harness ${version} installed successfully."
    printf '\nQuick start:\n'
    printf '  z-harness doctor          # verify host detection + fidelity\n'
    printf '  z-harness install         # install claude/codex plugins\n'
    printf '  z-harness launch          # inject + launch a host in the current project\n'
    printf '\nFor help: z-harness --help\n'
}

main "$@"
