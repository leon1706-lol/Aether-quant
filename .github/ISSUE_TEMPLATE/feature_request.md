---
name: Feature request
about: A new subsystem, module, CLI capability, or behavioral improvement.
title: "[feature] "
labels: ["enhancement"]
---

## Problem to solve

<!-- What can't you do today? Describe the user-facing need, not the implementation. -->

## Proposed behavior

<!-- What should exist after this ships? Include the intended CLI/config surface if any:
     new `aq` command/flag? new `phase_v2.*` config block (remember: flags ship `false`
     until verified)? new output artifact? -->

## Scope guardrails

<!-- This repo's conventions shape every feature. Confirm how yours fits: -->

- [ ] Ships backward-compatible: additive `None`-default parameters / default-off config keys; an unmodified `config.json` reproduces today's behavior exactly.
- [ ] Testable without Lean: pure logic lives in a package module, not `main.py`; tests planned/attached.
- [ ] Docs plan: README/sub-readmes + `development/Changelog.md` entry (and `development/architecture.md` when it changes system structure).

## Alternatives considered

<!-- What did you rule out and why? -->

## Extra context

<!-- Related Problems.md entries (#N), prior Changelog rounds, or backtest evidence. -->
