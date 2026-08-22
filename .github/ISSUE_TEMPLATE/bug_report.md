---
name: Bug report
about: Something is broken, wrong, or behaves differently than documented.
title: "[bug] "
labels: ["bug"]
---

## What happened

<!-- One or two sentences. Lead with the observable failure. -->

## Where

<!-- File(s)/module(s)/CLI command(s) involved, e.g. `aq evaluate --rank-book`, portfolio/book_construction.py -->

## Expected vs actual

- **Expected:**
- **Actual:**

## Reproduction

<!--
  Minimal steps from a clean clone. Include the exact command(s) and any
  config.json keys involved (`aq config get <dotted.key>` output helps).
-->

```text
<commands / steps>
```

## Evidence

<!-- Test output, log excerpt, or backtest artifact reference. Paste the
smallest relevant slice; link large files instead of pasting them. -->

```text
<output>
```

## Environment

- OS:
- Python version:
- Commit / tag:

## Checklist

- [ ] I ran `aq test` and can name the failing/passing state
- [ ] I checked `development/Problems.md` for a known entry covering this
