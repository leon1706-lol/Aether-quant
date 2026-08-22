# development/backups

Pre-condensation snapshots of the two large append-only development
records, kept so a condensing pass can never lose history. These are
**frozen restore points, not living documents** — never edit them; if a
condensation goes wrong, copy the file back over the live one and redo it.

| File | What it is |
|---|---|
| `Changelog.md.bak_pre_condense` (368KB) | Full Changelog before the V5.2.8 condensation pass |
| `Problems.md.bak_pre_condense` (479KB) | Full Problems.md before the V5.2.8 condensation pass |
| `Changelog.md.bak_pre_condense_v54` (187KB) | Full Changelog as of V5.3.5.3 (2026-08-21), before the second condensation pass started |
| `Problems.md.bak_pre_condense_v54` (158KB) | Full Problems.md as of V5.3.5.3 (2026-08-21), before its second condensation pass |

Naming convention: `<file>.bak_pre_condense` for the first pass,
`.bak_pre_condense_<tag>` for later passes (suffix = the version round the
snapshot was taken in). New condensation passes add a new snapshot here
first and never overwrite an existing one.

The current, maintained versions live one level up:
[`development/Changelog.md`](../Changelog.md) and
[`development/Problems.md`](../Problems.md).
