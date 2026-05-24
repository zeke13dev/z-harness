#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys

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
            
    # Default roles binding (just a proposal)
    roles = {}
    if "codex" in found:
        roles["consultant_primary"] = "codex"
        roles["reviewer"] = "codex"
    if "gemini" in found:
        roles["consultant_secondary"] = "gemini"
    elif "claude" in found:
        roles["consultant_secondary"] = "claude"
    elif "ollama" in found:
        roles["consultant_secondary"] = "ollama"
        
    return {
        "version": 1,
        "providers": found,
        "roles": roles
    }

if __name__ == "__main__":
    result = discover()
    print(json.dumps(result, indent=2))
