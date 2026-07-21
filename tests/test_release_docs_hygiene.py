"""Documentation hygiene and public release-contract drift checks."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import subprocess
from pathlib import Path

import pytest

from z_harness_cli import release_surface

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITY_HUMAN_PATH = REPO_ROOT / "docs" / "human" / "capabilities-matrix.md"
CAPABILITY_LLM_PATH = REPO_ROOT / "docs" / "llm" / "capabilities-matrix.json"
PROVIDER_REGISTRY_PATH = REPO_ROOT / ".z-harness" / "providers.json"
PROVIDER_HUMAN_PATHS = (
    REPO_ROOT / "docs" / "human" / "PROVIDERS.md",
    REPO_ROOT / "docs" / "human" / "pi-setup.md",
    REPO_ROOT / "docs" / "human" / "providers-registry.md",
)
PROVIDER_INDEX_PATH = REPO_ROOT / "docs" / "llm" / "INDEX.json"
PROVIDER_LLM_PATH = REPO_ROOT / "docs" / "llm" / "providers-registry.json"
PI_AUTH_CHECK_PATH = REPO_ROOT / "scripts" / "check-pi-auth.sh"
PROVIDER_ROLES = ("consultant_primary", "consultant_secondary", "reviewer")


def _release_reference() -> dict[str, object]:
    """Load the machine-readable capability reference; malformed JSON hard-fails."""

    document = json.loads(CAPABILITY_LLM_PATH.read_text(encoding="utf-8"))
    return document["release_contract_reference"]


def _assert_machine_reference_matches_contract(reference: dict[str, object]) -> None:
    """Assert that documented C1 fields exactly match the canonical contract."""

    contract = release_surface.release_contract()
    for field in ("train", "excluded_experiments", "host_claims", "clean_candidate_requirements"):
        assert reference[field] == contract[field]
    assert "prod_inventory" not in reference
    assert reference["consumers"] == {
        "C2": "deterministic_assembly",
        "C3": "dependency_closure",
        "C4": "transactional_lifecycle",
        "C5": "version_provenance",
        "C6": "verification_and_promotion",
    }


def _assert_human_reference_matches_contract(text: str) -> None:
    """Assert the public human section preserves the evidence-bounded contract."""

    public_section = text.split("## Public release contract", 1)[1].split("## Overview", 1)[0]
    contract = release_surface.release_contract()
    assert contract["train"]["channel"] in public_section
    assert "stable-1.x" not in public_section.lower()

    exclusions = contract["excluded_experiments"]
    for skill in exclusions["skills"]:
        assert f"`/{skill}`" in public_section
        assert not re.search(
            rf"`/{re.escape(skill)}`[^.\n]*\bis (?:an? )?public (?:release )?default\b",
            public_section,
            re.IGNORECASE,
        )
    assert "`z-axiom-*`" in public_section
    for agent in exclusions["agents"]:
        assert f"`{agent}`" in public_section

    expected_claim_rows = {
        "claude": "| Claude Code | `native` | `primary` | `blocking_clean_plugin` |",
        "cli": "| CLI | `supported` | `release` | bootstrap, install, and update |",
        "codex": "| Codex | `partial` | `preview` | `blocking_clean_plugin` |",
        "omp": "| OMP | `native` | `conditional` | `clean_installed_wheel_proof` |",
        "dev": "| Antigravity, Cursor | `dev_advanced` | `not_release_default` | development/advanced use only |",
        "export": "| Cline, Copilot, Kiro, pi, Windsurf | `export_only` | `not_release_default` | export use only |",
    }
    assert all(row in public_section for row in expected_claim_rows.values())

    clean_candidate = contract["clean_candidate_requirements"]
    required_values = {
        clean_candidate["source_identity"],
        clean_candidate["source_origin"],
        clean_candidate["home"],
        clean_candidate["wheel"],
        clean_candidate["host_claim_evidence"],
        *clean_candidate["forbidden_inputs"],
    }
    assert all(f"`{value}`" in public_section for value in required_values)
    assert all(f"C{cluster}" in public_section for cluster in range(2, 7))


def _default_provider_bindings(registry: dict[str, object]) -> dict[str, dict[str, str]]:
    """Derive the public role/provider/model/auth truth from the shipped registry."""

    roles = registry["roles"]
    providers = registry["providers"]
    bindings: dict[str, dict[str, str]] = {}
    for role in PROVIDER_ROLES:
        provider_name = roles[role]
        provider = providers[provider_name]
        model = provider["args_template"][0]
        auth = model.split("/", 1)[0]
        bindings[role] = {"provider": provider_name, "model": model, "auth": auth}
    return bindings


def _assert_role_binding_on_one_line(text: str, role: str, binding: dict[str, str]) -> None:
    """Require a readable current/default statement, not scattered token mentions."""

    assert any(
        role in line and binding["provider"] in line and binding["model"] in line
        for line in text.splitlines()
    ), f"missing current {role} provider/model statement"


_STALE_PROVIDER_TOKENS = ("omp-cursor-sol", "omp-cursor-terra", "omp-codex", "codex-cli")
_HISTORY_LABEL = re.compile(
    r"^\s*(?:\*\*)?(?:Compatibility history|History)(?:\*\*)?:|"
    r"^\s*(?:\*\*)?(?:Historically|Previously)\b",
    re.I,
)
_PREDICATE = re.compile(
    r"\b(?:is|isn['’]?t|are|was|were|supports?|remains?|defaults?|used|requires?|required|"
    r"includes?|excludes?|bound)\b",
    re.I,
)
_ELIDED_PREDICATE = re.compile(
    r"^\s*(?:is|isn['’]?t|are|was|were|supports?|remains?|defaults?|requires?|required|"
    r"includes?|excludes?|not\b|no longer\b)",
    re.I,
)
_CONTRAST_CONJUNCTIONS = ("but", "yet", "although", "though", "even though", "whereas")
_CONCESSIVE_PREFIXES = ("although", "though", "even though", "despite", "while", "whereas")
_DISCOURSE_MARKERS = ("however", "nevertheless", "nonetheless", "still", "on the other hand", "conversely")
_CONTRAST_PATTERN = "|".join(sorted(_CONTRAST_CONJUNCTIONS, key=len, reverse=True))
_CONCESSIVE_PATTERN = "|".join(sorted(_CONCESSIVE_PREFIXES, key=len, reverse=True))
_DISCOURSE_PATTERN = "|".join(sorted(_DISCOURSE_MARKERS, key=len, reverse=True))
_POSITIONAL_MARKERS = tuple(
    dict.fromkeys((*_CONTRAST_CONJUNCTIONS, *_CONCESSIVE_PREFIXES, *_DISCOURSE_MARKERS))
)
_POSITIONAL_PATTERN = "|".join(sorted(_POSITIONAL_MARKERS, key=len, reverse=True))
_LEADING_DISCOURSE = re.compile(
    rf"^\s*(?:{_POSITIONAL_PATTERN})\s*,?\s*", re.I
)
_ELIDED_PRONOUN = re.compile(r"^\s*(?:it|this route|that route)\s+", re.I)


def _is_predicated(text: str) -> bool:
    stripped = _ELIDED_PRONOUN.sub("", _LEADING_DISCOURSE.sub("", text).strip()).strip()
    return bool(_PREDICATE.search(stripped))


def _split_contrast(sentence: str) -> list[str]:
    """Split centralized contrast/discourse boundaries into local propositions."""

    stripped = sentence.strip()
    leading = re.match(rf"^({_CONCESSIVE_PATTERN})\b", stripped, re.I)
    if leading and "," in stripped:
        concessive, asserted = stripped.split(",", 1)
        normalized_concessive = _LEADING_DISCOURSE.sub("", concessive).strip()
        if leading.group(1).lower() != "while" or (
            re.search(
                r"\b(?:current|default|required|manual|optional|reviewer|consultant_secondary|cursor)\b",
                stripped,
                re.I,
            )
            and _is_predicated(normalized_concessive)
            and _is_predicated(asserted)
        ):
            return [normalized_concessive, asserted.strip()]
    boundary = re.compile(
        rf"\s*(?:;|,\s*(?:{_CONTRAST_PATTERN})\s+|\s+(?:{_CONTRAST_PATTERN})\s+|"
        rf",\s*(?:{_DISCOURSE_PATTERN})\s*,\s*|,\s+and\s+|\s+[—–]\s+)\s*",
        re.I,
    )
    parts = [part for part in boundary.split(stripped) if part.strip()]

    guarded: list[str] = []
    for part in parts:
        while_match = re.search(r"\s*,?\s+while\s+", part, re.I)
        if while_match:
            left, right = part[: while_match.start()], part[while_match.end() :]
            routing_context = bool(
                re.search(
                    r"\b(?:current|default|required|manual|optional|reviewer|consultant_secondary|cursor)\b",
                    part,
                    re.I,
                )
            )
            if routing_context and _is_predicated(left) and _is_predicated(right):
                guarded.extend((left, right))
                continue
        colon_match = re.search(r":\s+", part)
        if colon_match:
            left, right = part[: colon_match.start()], part[colon_match.end() :]
            if _is_predicated(left) and _is_predicated(right):
                guarded.extend((left, right))
                continue
        guarded.append(part)
    return guarded


def _split_plain_and(clause: str) -> list[str]:
    """Split `and` only when its right side introduces another predicate."""

    for match in re.finditer(r"\s+and\s+", clause, re.I):
        left, right = clause[: match.start()], clause[match.end() :]
        explicit_right_predicate = bool(
            re.search(
                r"\b(?:reviewer|consultant_secondary|cursor|omp-[\w-]+|codex-cli)\b"
                r"[^.]{0,80}" + _PREDICATE.pattern,
                right,
                re.I,
            )
        )
        if _PREDICATE.search(left) and (
            _ELIDED_PREDICATE.search(right) or explicit_right_predicate
        ):
            return _split_plain_and(left) + _split_plain_and(right)
    return [clause]


def _inherit_elided_subject(previous: str, proposition: str) -> str:
    """Carry only the stale/auth subject into an elided coordinated predicate."""

    proposition = _LEADING_DISCOURSE.sub("", proposition).strip()
    without_pronoun = _ELIDED_PRONOUN.sub("", proposition).strip()
    if _ELIDED_PREDICATE.search(without_pronoun):
        proposition = without_pronoun
    else:
        return proposition
    lowered = proposition.lower()
    for provider in _STALE_PROVIDER_TOKENS:
        if provider in previous.lower() and provider not in lowered:
            return f"{provider} {proposition}"
    if "cursor" in previous.lower() and "cursor" not in lowered:
        topic = "Cursor authentication" if re.search(
            r"\b(?:oauth|auth|authentication|backend)\b", previous, re.I
        ) else "Cursor"
        return f"{topic} {proposition}"
    return proposition


def _active_release_propositions(text: str) -> list[str]:
    """Return non-historical propositions with coordinated subject elision resolved."""

    normalized = re.sub(r"(?m)^> ?", "", text).replace("`", "")
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n", normalized):
        compact = re.sub(r"\s*\n\s*", " ", paragraph).strip()
        sentences.extend(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", compact)
            if sentence.strip()
        )
    active: list[str] = []
    previous = ""
    for sentence in sentences:
        if re.match(r"^\s*(?:\*\*)?(?:Compatibility history|History)(?:\*\*)?:", sentence, re.I):
            continue
        coarse = _split_contrast(sentence)
        parts = [part for clause in coarse for part in _split_plain_and(clause) if part.strip()]
        for raw_part in parts:
            proposition = _inherit_elided_subject(previous, raw_part.strip())
            previous = proposition
            if _HISTORY_LABEL.search(proposition):
                continue
            active.append(proposition)
    return active


def _without_bounded_compatibility_history(text: str) -> str:
    """Compatibility wrapper for active-prose assertions."""

    return "\n".join(_active_release_propositions(text))


def _assert_no_unqualified_retired_defaults(text: str) -> None:
    """Classify sentences so stale claim detection is independent of token order."""

    clauses = _active_release_propositions(text)
    stale_by_role = {
        "omp-cursor-sol": "consultant_secondary",
        "omp-cursor-terra": "reviewer",
        "omp-codex": "consultant_secondary",
        "codex-cli": "reviewer",
    }
    routing_predicate = re.compile(r"\b(?:current|currently|default)\b", re.I)
    compatibility_qualifier = re.compile(
        r"\b(?:manual|optional|former|retired|historical|previous|previously|superseded|custom)\b",
        re.I,
    )
    negated_default = re.compile(
        r"\b(?:not|isn['’]?t|no longer)\b[^.]{0,50}\b(?:current|default|bound)\b|"
        r"\b(?:current|default|bound)\b[^.]{0,50}\b(?:not|isn['’]?t|no longer)\b",
        re.I,
    )
    violations: list[str] = []
    for clause in clauses:
        lowered = clause.lower()
        has_routing_predicate = bool(routing_predicate.search(clause))
        for stale_provider, role in stale_by_role.items():
            if stale_provider not in lowered:
                continue
            has_role = role in lowered
            is_safe_compatibility = bool(compatibility_qualifier.search(clause)) or bool(
                negated_default.search(clause)
            )
            if (has_routing_predicate or has_role) and not is_safe_compatibility:
                violations.append(clause)
                break

        has_cursor = bool(re.search(r"\bcursor\b", clause, re.I))
        has_auth = bool(re.search(r"\b(?:oauth|auth|authentication|backend)\b", clause, re.I))
        has_required = bool(re.search(r"\brequired\b", clause, re.I))
        cursor_auth_is_exempt = bool(
            re.search(r"\b(?:optional|not role-bound)\b", clause, re.I)
            or re.search(r"\b(?:not|isn['’]?t|no longer)\s+required\b", clause, re.I)
            or re.search(r"\b(?:does\s+not\s+include|excludes?)\s+cursor\b", clause, re.I)
            or re.search(r"\bcursor\b[^.]{0,60}\b(?:is\s+)?excluded\b", clause, re.I)
        )
        if has_cursor and has_auth and has_required and not cursor_auth_is_exempt:
            violations.append(clause)

    assert not violations, f"unqualified retired/current provider claim(s): {violations}"


def _assert_current_auth_prose(text: str) -> None:
    """Require the registry-derived required/optional auth posture in active human prose."""

    active = _without_bounded_compatibility_history(text)
    assert re.search(
        r"(?:google-antigravity[^.]{0,180}openai-codex|openai-codex[^.]{0,180}google-antigravity)"
        r"[^.]{0,100}\brequired\b",
        active,
        re.I | re.S,
    )
    assert re.search(r"\bcursor\b[^.]{0,140}\boptional\b", active, re.I | re.S)
    assert re.search(r"\bcursor\b[^.]{0,180}\bnot role-bound\b", active, re.I | re.S)


def _assert_provider_release_docs(
    registry: dict[str, object],
    human_docs: dict[Path, str],
    index: dict[str, object],
    provider_llm: dict[str, object],
    auth_script: str,
) -> None:
    """Validate all public provider/auth surfaces against one registry-derived truth."""

    bindings = _default_provider_bindings(registry)
    for text in human_docs.values():
        for role, binding in bindings.items():
            _assert_role_binding_on_one_line(text, role, binding)
        _assert_no_unqualified_retired_defaults(text)
        _assert_current_auth_prose(text)

    index_entry = next(item for item in index["concepts"] if item["slug"] == "providers-registry")
    index_summary = index_entry["summary"]
    for role, binding in bindings.items():
        _assert_role_binding_on_one_line(index_summary, role, binding)
    _assert_no_unqualified_retired_defaults(index_summary)

    assert provider_llm["default_role_bindings"] == bindings
    _assert_no_unqualified_retired_defaults("\n\n".join(provider_llm["invariants"]))

    required_auth = {binding["auth"] for binding in bindings.values()}
    assert required_auth == {"google-antigravity", "openai-codex"}
    for auth in required_auth:
        assert re.search(rf'^  "{re.escape(auth)}\|1\|', auth_script, re.MULTILINE)
    assert re.search(r'^  "cursor\|0\|[^\n]*(?:optional|not bound)', auth_script, re.MULTILINE)
    assert not re.search(r'^  "cursor\|1\|', auth_script, re.MULTILINE)
    for role, binding in bindings.items():
        _assert_role_binding_on_one_line(auth_script, role, binding)


def _active_docs_and_wrappers() -> list[Path]:
    paths = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "Makefile",
        REPO_ROOT / "skills" / "z-export" / "SKILL.md",
    ]
    paths.extend((REPO_ROOT / "docs" / "human").glob("*.md"))
    paths.extend((REPO_ROOT / "scripts" / "pi_assets").rglob("*.md"))
    return sorted(paths)


def test_active_docs_do_not_point_at_removed_command_source_tier() -> None:
    forbidden = [
        re.compile(r"commands/(?:z-[A-Za-z0-9-]+|_fragments)[^`\s)]*\.md"),
        re.compile(r"commands/\*\.md"),
        re.compile(r"commands/ frontmatter", re.IGNORECASE),
        re.compile(r"skills/ dir(?:ectory)? (?:was )?removed|only commands/|only crawls commands/", re.IGNORECASE),
    ]

    violations: list[str] = []
    for path in _active_docs_and_wrappers():
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")

    assert not violations


def test_generated_export_mirrors_are_documented_as_scratch_not_release_source() -> None:
    forbidden = [
        re.compile(r"LEGACY-ALLOWLIST|REMOVE-AT: v<next-minor>"),
        re.compile(r"--commands-dir commands"),
        re.compile(r"committed `exports/|--out exports/|Path\('exports"),
    ]

    violations: list[str] = []
    for path in _active_docs_and_wrappers() + [REPO_ROOT / "scripts" / "audit-tarball.sh"]:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")

    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/exports/" in gitignore
    assert "/temp/exports/" in gitignore
    assert "/.pi/" in gitignore
    assert "/.omp/z-harness/" in gitignore
    assert release_surface.path_excluded_from_prod("exports/pi/prompts/z-plan.md")
    assert release_surface.path_excluded_from_prod(".pi/agents/doc-updater.md")
    assert release_surface.path_excluded_from_prod("temp/exports/omp/.omp/z-harness/manifest.yml")
    assert not violations


def test_z_do_wrapper_is_deleted() -> None:
    # /z-do was a deprecated pass-through wrapper; it is now fully removed.
    assert not (REPO_ROOT / "skills" / "z-do" / "SKILL.md").exists()


def test_capability_references_match_canonical_release_contract() -> None:
    _assert_machine_reference_matches_contract(_release_reference())
    _assert_human_reference_matches_contract(CAPABILITY_HUMAN_PATH.read_text(encoding="utf-8"))


def test_capability_reference_rejects_stable_1x_language() -> None:
    human = CAPABILITY_HUMAN_PATH.read_text(encoding="utf-8")
    drifted = human.replace("pre-1.0-beta", "stable-1.x", 1)

    with pytest.raises(AssertionError):
        _assert_human_reference_matches_contract(drifted)


def test_capability_reference_rejects_public_excluded_experiment() -> None:
    human = CAPABILITY_HUMAN_PATH.read_text(encoding="utf-8")
    drifted = human.replace(
        "experiments or development resources unless a later release-readiness decision\n"
        "promotes them with blocking evidence.",
        "`/z-research` is a public release default.",
        1,
    )

    assert drifted != human
    with pytest.raises(AssertionError):
        _assert_human_reference_matches_contract(drifted)


def test_capability_reference_rejects_host_tier_drift() -> None:
    reference = deepcopy(_release_reference())
    reference["host_claims"]["codex"]["tier"] = "native"

    with pytest.raises(AssertionError):
        _assert_machine_reference_matches_contract(reference)


def test_provider_and_auth_docs_match_repository_registry() -> None:
    registry = json.loads(PROVIDER_REGISTRY_PATH.read_text(encoding="utf-8"))
    human_docs = {path: path.read_text(encoding="utf-8") for path in PROVIDER_HUMAN_PATHS}
    index = json.loads(PROVIDER_INDEX_PATH.read_text(encoding="utf-8"))
    provider_llm = json.loads(PROVIDER_LLM_PATH.read_text(encoding="utf-8"))
    auth_script = PI_AUTH_CHECK_PATH.read_text(encoding="utf-8")

    _assert_provider_release_docs(registry, human_docs, index, provider_llm, auth_script)


@pytest.mark.parametrize(
    "contradiction",
    (
        "The current default is omp-cursor-sol.",
        "Current consultant_secondary -> omp-codex.",
        "The default is omp-cursor-terra.",
        "Current reviewer = codex-cli.",
        "Cursor authentication is required.",
        "omp-cursor-sol is the current default.",
        "omp-cursor-terra remains the default.",
        "omp-codex is currently the consultant_secondary default.",
        "codex-cli is currently the reviewer default.",
        "Cursor is the required authentication backend.",
        "Cursor OAuth remains required.",
        "omp-cursor-terra is optional to install but is the current reviewer default.",
        "omp-codex supports manual overrides and remains the consultant_secondary default.",
        "History: reviewer used codex-cli. Current reviewer default is omp-cursor-terra.",
        "Historically, reviewer used codex-cli, and reviewer currently defaults to omp-cursor-terra.",
        "Cursor authentication is optional for legacy use but required for release defaults.",
        "Cursor authentication is not required for custom use but is required for release defaults.",
        "omp-cursor-terra is optional for manual use, although it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use; however, it remains the current reviewer default.",
        "omp-codex supports manual overrides, yet remains the consultant_secondary default.",
        "Cursor authentication is optional for legacy use; however, it is required for release defaults.",
        "Cursor authentication is optional for legacy use, although it is required for release defaults.",
        "Although omp-cursor-terra is optional for manual use, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. However, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use, though it remains the current reviewer default.",
        "Though omp-cursor-terra is optional for manual use, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use; nevertheless, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. Nevertheless, it remains the current reviewer default.",
        "omp-codex supports manual overrides, while it remains the consultant_secondary default.",
        "Cursor authentication is optional for legacy use: it is required for release defaults.",
        "omp-cursor-terra is optional for manual use, whereas it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use; nonetheless, it remains the current reviewer default.",
        "Even though omp-cursor-terra is optional for manual use, it remains the current reviewer default.",
        "Despite omp-cursor-terra being optional for manual use, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. Still, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. On the other hand, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. Conversely, it remains the current reviewer default.",
        "While omp-cursor-terra is optional for manual use, it remains the current reviewer default.",
        "Whereas omp-cursor-terra is optional for manual use, it remains the current reviewer default.",
        "omp-cursor-terra is optional for manual use. Yet it remains the current reviewer default.",
        "Cursor authentication is optional for legacy use. Yet it is required for release defaults.",
    ),
)
def test_provider_docs_reject_appended_retired_default_claim(contradiction: str) -> None:
    registry = json.loads(PROVIDER_REGISTRY_PATH.read_text(encoding="utf-8"))
    human_docs = {path: path.read_text(encoding="utf-8") for path in PROVIDER_HUMAN_PATHS}
    path = PROVIDER_HUMAN_PATHS[1]
    human_docs[path] += f"\n\n## Erroneous current note\n\n{contradiction}\n"

    with pytest.raises(AssertionError):
        _assert_provider_release_docs(
            registry,
            human_docs,
            json.loads(PROVIDER_INDEX_PATH.read_text(encoding="utf-8")),
            json.loads(PROVIDER_LLM_PATH.read_text(encoding="utf-8")),
            PI_AUTH_CHECK_PATH.read_text(encoding="utf-8"),
        )


def test_provider_docs_reject_embedded_retired_default_claim() -> None:
    registry = json.loads(PROVIDER_REGISTRY_PATH.read_text(encoding="utf-8"))
    human_docs = {path: path.read_text(encoding="utf-8") for path in PROVIDER_HUMAN_PATHS}
    path = PROVIDER_HUMAN_PATHS[2]
    human_docs[path] = human_docs[path].replace(
        "The repository registry is the release authority for current defaults:",
        "The repository registry is the release authority for current defaults: "
        "Current reviewer -> omp-cursor-terra. ",
        1,
    )

    with pytest.raises(AssertionError):
        _assert_provider_release_docs(
            registry,
            human_docs,
            json.loads(PROVIDER_INDEX_PATH.read_text(encoding="utf-8")),
            json.loads(PROVIDER_LLM_PATH.read_text(encoding="utf-8")),
            PI_AUTH_CHECK_PATH.read_text(encoding="utf-8"),
        )


@pytest.mark.parametrize(
    "qualified_history",
    (
        "omp-codex is available for manual consultant_secondary binding.",
        "Manual compatibility provider omp-codex can be bound by a consultant_secondary override.",
        "omp-cursor-terra is an optional compatibility provider for reviewer customization.",
        "Former reviewer default: omp-cursor-terra.",
        "omp-cursor-sol is retired and not current.",
        "omp-codex is not the default for consultant_secondary.",
        "codex-cli is no longer the reviewer default.",
        "omp-cursor-sol is not role-bound.",
        "History: reviewer used codex-cli.",
        "Historically, consultant_secondary used omp-codex.",
        "Previously reviewer=omp-cursor-terra.",
        "Authentication is not required for Cursor.",
        "Required authentication does not include Cursor.",
        "The required backends exclude Cursor.",
        "Cursor OAuth isn't required.",
        "Cursor OAuth is no longer required.",
        "Optional authentication backend: Cursor.",
        "Current defaults are omp-openai-sol and omp-openai-terra; omp-cursor-sol remains manual.",
        "Historically, reviewer used codex-cli, and reviewer currently defaults to omp-openai-terra.",
        "Although omp-cursor-terra remains optional for manual use, the current reviewer default is omp-openai-terra.",
        "Current reviewer default is omp-openai-terra; however, omp-cursor-terra remains manual.",
        "omp-codex supports custom overrides, yet it remains optional and not the default.",
        "OpenAI Codex authentication is required; however, Cursor authentication remains optional.",
        "Though omp-cursor-terra remains optional for manual use, the current reviewer default is omp-openai-terra.",
        "Current reviewer default is omp-openai-terra; nevertheless, omp-cursor-terra remains manual.",
        "Current reviewer default is omp-openai-terra. Nonetheless, omp-cursor-terra remains optional.",
        "omp-cursor-terra remains manual while the current reviewer default remains omp-openai-terra.",
        "Cursor authentication is optional: openai-codex authentication is required for release defaults.",
        "Current reviewer default is omp-openai-terra, whereas omp-cursor-terra remains optional.",
        "Even though omp-cursor-terra remains optional, the current reviewer default is omp-openai-terra.",
        "Despite omp-cursor-terra remaining manual, the current reviewer default is omp-openai-terra.",
        "Current reviewer default is omp-openai-terra. Still, omp-cursor-terra remains manual.",
        "Current reviewer default is omp-openai-terra. On the other hand, omp-cursor-terra remains optional.",
        "Current reviewer default is omp-openai-terra. Conversely, omp-cursor-terra remains manual.",
        "While omp-cursor-terra remains optional for manual use, the current reviewer default is omp-openai-terra.",
        "Whereas omp-cursor-terra remains optional, the current reviewer default is omp-openai-terra.",
        "omp-cursor-terra remains optional for manual use. Yet the current reviewer default is omp-openai-terra.",
        "Cursor authentication remains optional. Yet openai-codex authentication is required for release defaults.",
    ),
)
def test_provider_docs_allow_explicit_manual_optional_compatibility(
    qualified_history: str,
) -> None:
    _assert_no_unqualified_retired_defaults(qualified_history)


def test_provider_auth_docs_reject_retired_required_backend() -> None:
    registry = json.loads(PROVIDER_REGISTRY_PATH.read_text(encoding="utf-8"))
    auth_script = PI_AUTH_CHECK_PATH.read_text(encoding="utf-8")
    drifted = auth_script.replace('"openai-codex|1|', '"openai-codex|0|', 1).replace(
        '"cursor|0|', '"cursor|1|', 1
    )
    assert drifted != auth_script

    with pytest.raises(AssertionError):
        _assert_provider_release_docs(
            registry,
            {path: path.read_text(encoding="utf-8") for path in PROVIDER_HUMAN_PATHS},
            json.loads(PROVIDER_INDEX_PATH.read_text(encoding="utf-8")),
            json.loads(PROVIDER_LLM_PATH.read_text(encoding="utf-8")),
            drifted,
        )


def _write_fake_auth_commands(bin_dir: Path, *, include_omp: bool) -> None:
    """Create a hermetic timeout shim and optional auth probe for script behavior tests."""

    bin_dir.mkdir()
    timeout = bin_dir / "timeout"
    timeout.write_text("#!/bin/sh\nshift\nexec \"$@\"\n", encoding="utf-8")
    timeout.chmod(0o755)
    if include_omp:
        omp = bin_dir / "omp"
        omp.write_text(
            "#!/bin/sh\n"
            "case \",${FAKE_MISSING_AUTH:-},\" in\n"
            "  *,\"$2\",*) exit 1 ;;\n"
            "esac\n"
            "printf 'FAKE_SECRET_TOKEN_%s\\n' \"$2\"\n"
            "printf 'FAKE_SECRET_STDERR_%s\\n' \"$2\" >&2\n",
            encoding="utf-8",
        )
        omp.chmod(0o755)


def _run_auth_check(
    tmp_path: Path,
    *,
    strict: bool,
    include_omp: bool,
    missing_auth: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    _write_fake_auth_commands(bin_dir, include_omp=include_omp)
    args = ["/bin/bash", str(PI_AUTH_CHECK_PATH)]
    if strict:
        args.append("--strict")
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": str(bin_dir),
            "FAKE_MISSING_AUTH": ",".join(missing_auth),
            "GEMINI_API_KEY": "",
        },
    )


@pytest.mark.parametrize(("strict", "expected_rc"), ((False, 0), (True, 1)))
def test_pi_auth_checker_handles_missing_omp(
    tmp_path: Path, strict: bool, expected_rc: int
) -> None:
    result = _run_auth_check(tmp_path, strict=strict, include_omp=False)

    assert result.returncode == expected_rc
    assert "'omp' not on PATH" in result.stderr
    assert "FAKE_SECRET" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("missing_auth", "expected_rc", "expected_missing"),
    (
        (("google-antigravity",), 1, "google-antigravity"),
        (("openai-codex",), 1, "openai-codex"),
        (("cursor",), 0, "cursor"),
        ((), 0, None),
    ),
)
def test_pi_auth_checker_strict_registry_auth_matrix(
    tmp_path: Path,
    missing_auth: tuple[str, ...],
    expected_rc: int,
    expected_missing: str | None,
) -> None:
    result = _run_auth_check(
        tmp_path,
        strict=True,
        include_omp=True,
        missing_auth=missing_auth,
    )

    assert result.returncode == expected_rc
    if expected_missing is None:
        assert "MISSING" not in result.stdout
    else:
        missing_line = next(line for line in result.stdout.splitlines() if line.startswith(expected_missing))
        assert "MISSING" in missing_line
    assert "FAKE_SECRET" not in result.stdout + result.stderr
