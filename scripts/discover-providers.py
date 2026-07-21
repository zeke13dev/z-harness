#!/usr/bin/env python3
import json
import shutil

MANDATORY_ROLES = (
    "consultant_primary",
    "consultant_secondary",
    "reviewer",
)

KNOWN_CLIS = {
    "codex": {
        "kind": "cli",
        "command": "codex",
        "args_template": ["exec", "-"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "gpt-5-codex"
    },
    "gemini": {
        "kind": "cli",
        "command": "gemini",
        "args_template": ["-p", "-", "--approval-mode", "plan", "--output-format", "text"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "gemini-2.5-pro"
    },
    "claude": {
        "kind": "cli",
        "command": "claude",
        "args_template": ["--print"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "claude-3-opus"
    },
    "ollama": {
        "kind": "cli",
        "command": "ollama",
        "args_template": ["run", "llama3"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "llama3"
    },
    "agy": {
        "kind": "cli",
        "command": "agy",
        "args_template": ["exec", "-"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "agy-model"
    },
    "gpt": {
        "kind": "cli",
        "command": "gpt",
        "args_template": ["-"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": "gpt-4"
    }
}

def discover():
    found = {}
    for name, spec in KNOWN_CLIS.items():
        if shutil.which(spec["command"]):
            found[name] = spec

    # A complete proposal is safe to approve only when every mandatory role
    # can use a distinct provider. KNOWN_CLIS insertion order is the stable
    # preference order, independent of PATH ordering.
    provider_names = list(found)
    roles = (
        dict(zip(MANDATORY_ROLES, provider_names[:len(MANDATORY_ROLES)]))
        if len(provider_names) >= len(MANDATORY_ROLES)
        else {}
    )

    return {
        "version": 1,
        "providers": found,
        "roles": roles
    }

if __name__ == "__main__":
    result = discover()
    print(json.dumps(result, indent=2, sort_keys=True))
