# Phase 1 Context: plan-variant-bail-routing

## Problem

The request is to make the z-plan family able to bail between variants instead of each command only knowing one or two hard-coded exits. The immediate design question is how to classify task scope and route between `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, and `/z-audit-plan` without adding a heavyweight planning ceremony to every invocation.

## Context

Current light-mode guidance only auto-bails upward to `/z-plan` when more than five files, more than two non-obvious decisions, or cross-module impact appear. `/z-do` can recommend `/z-plan-light` or `/z-plan`; `/z-plan-split` refuses topics with too few or too many clusters; `/z-research` currently points users toward `/z-brainstorm` or `/z-plan` after producing a note. The docs lookup also found that `z-audit-plan` exists in command/skill/export surfaces but is not fully reflected in the LLM docs index. A complete mutual-bail change would need to touch more than five source/export/doc files, so it exceeds `/z-plan-light` thresholds.
