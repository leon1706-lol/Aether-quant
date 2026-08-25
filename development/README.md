# development

Development-process documentation for Aether Quant, kept separate from the
root `README.md` so that file stays short and scannable.

- `architecture.md` — the full system architecture: process-flow and
  tech-stack Mermaid diagrams, the module map, per-subsystem "contract"
  sections (one per shipped subsystem — regime, liquidity, observation mode,
  performance triggers, controlled retraining, ...) describing what each
  module owns and how it's wired together, the multi-asset-class/ranking
  design, and the Docker port layout
- `infrastructure.md` — Docker Compose runbook: exact start commands for
  every service (`redis`, `postgres`, `experience-worker`,
  `performance-trigger-worker`, `retraining-worker`, the `lean` profile;
  `grafana` was removed in V2-18),
  one-off batch-processing commands, SQL snippets for inspecting each
  service's Postgres tables, cloud training via GitHub Codespaces, and the
  container-to-container vs. host-machine port reference.
- `asset_universe.md` — the full trading universe: every ticker with its
  asset class and trading-vs-observation role, how the universe was grown,
  the bond-ETF duration/credit coverage, and a group-level diagram.
- `project_structure.md` — the annotated directory tree: what every folder
  and top-level file is for.
- `Changelog.md` — detailed, append-only, per-phase results: what was
  built, when, and why, across every phase. Historical record — past
  entries describe what was true *at the time*, so they're never rewritten
  when a later phase changes something they mention.
- `Problems.md` — audit log of bugs and infrastructure issues found in this
  codebase, each with a severity rating (1 = cosmetic, 10 = critical
  data-loss/safety issue) and a `fixed`/`open` status. Also append-only for
  the same reason as the changelog.
- `backups/` — frozen pre-condensation snapshots of Changelog.md and
  Problems.md taken before each condensing pass (restore points only, see
  `backups/README.md`).

More development-process documents can live here over time.
