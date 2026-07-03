# development

Development-process documentation for Aether Quant, kept separate from the
root `README.md` so that file stays short and scannable.

- `v2_architecture.md` — the V2 system architecture: process-flow and
  tech-stack Mermaid diagrams, the module map, per-phase "contract"
  sections (one per shipped phase — regime, liquidity, observation mode,
  performance triggers, controlled retraining, ...) describing what each
  module owns and how it's wired together, the Docker port layout, and the
  full V2 build-order checklist.
- `infrastructure.md` — Docker Compose runbook: exact start commands for
  every service (`redis`, `postgres`, `experience-worker`,
  `performance-trigger-worker`, `retraining-worker`, the `lean` profile;
  `grafana` was removed in V2-18),
  one-off batch-processing commands, SQL snippets for inspecting each
  service's Postgres tables, and the container-to-container vs.
  host-machine port reference.
- `Changelog.md` — detailed, append-only, per-phase results: what was
  built, when, and why, across every V2 phase. Historical record — past
  entries describe what was true *at the time*, so they're never rewritten
  when a later phase changes something they mention.
- `Problems.md` — audit log of bugs and infrastructure issues found in this
  codebase, each with a severity rating (1 = cosmetic, 10 = critical
  data-loss/safety issue) and a `fixed`/`open` status. Also append-only for
  the same reason as the changelog.

More development-process documents can live here over time.
