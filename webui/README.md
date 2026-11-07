# webui

The React/Vite dashboard over `monitoring/api_server.py`. Runtime state is polled every 5 seconds through TanStack Query (`src/api/hooks.ts`), and Tracing feeds every 15.

| Page (`src/pages/`) | Shows |
|---|---|
| `Overview.tsx` | Scorecards, 3D market scene, heatmap, signal board, positions |
| `OperationsPage.tsx` | Kill switch, reconciliation, triggers, retraining, generations, paper readiness, multi-asset readiness, audit log |
| `RiskPage.tsx` | Per-asset sizing with multiplier chips and book role, macro snapshot |
| `OptionsStrategyPage.tsx` | The strategy registry and selector scores |
| `TopologyPage.tsx` | The 3D topology and clusters |
| `NeuralNetworkPage.tsx` | Each exported network, and per-head ranking gates |
| `EvaluationPage.tsx` | `aq evaluate` reports, from `/api/evaluation` |
| `TracingPage.tsx` | Equity curves, asset performance and metrics, from `/api/grafana/*` |

## Develop

```powershell
aq api          # backend on :8001
npm install
npm run dev     # http://localhost:3002, proxying /api to :8001
```

In Docker the same build is served by the `engine` service on port 8001.

```powershell
npm run build   # tsc -b && vite build
npm run lint    # oxlint
npm run test    # vitest run
```

- **Tests:** Vitest and Testing Library. `src/test/setup.ts` stubs `@react-three/fiber` and `drei`, because jsdom has no WebGL.
- **Low memory:** if workers time out, use `npx vitest run --no-file-parallelism`.

## Topology modes

`TopologyScene3D.tsx` reads the backend's `dimensions.depth`:

- **`depth === 1` (default):** x and y are the embedding, and z encodes volatility on a shallower scale.
- **`depth === 100` (`phase_v2.topology.embedding_dimensions: 3`):** all three axes are the embedding, on one scale, and node radius carries volatility.
