# Phase 0: Premise Check

Premise accepted with one constraint: "all z-plan variants can bail to each other" should not mean unrestricted pairwise handoffs that can loop or create noisy recommendations. The goal is a shared routing policy that every planning-family entry point can invoke early and at phase boundaries, with deterministic thresholds first and an optional cheap classifier only for borderline cases. The plan should make each command able to recommend or hand off to the best-fit neighboring workflow while preserving each command's existing purpose, telemetry, and artifact shape.
