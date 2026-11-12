# webui

The React/Vite dashboard over `monitoring/api_server.py`. Runtime state is polled every 5 seconds through TanStack Query (`src/api/hooks.ts`), and Tracing feeds every 15.

| Page (`src/pages/`) | Shows |
|---|---|
| `Overview.tsx` | Scorecards, 3D market scene, heatmap, signal board, positions |
| `OperationsPage.tsx` | Kill switch, the trade lock (operators lock, admins unlock), reconciliation, triggers, retraining, generations, paper readiness, multi-asset readiness, audit log |
| `RiskPage.tsx` | Per-asset sizing with multiplier chips and book role, macro snapshot |
| `OptionsStrategyPage.tsx` | The strategy registry and selector scores |
| `TopologyPage.tsx` | The 3D topology and clusters |
| `NeuralNetworkPage.tsx` | Each exported network, and per-head ranking gates |
| `EvaluationPage.tsx` | `aq evaluate` reports, from `/api/evaluation` |
| `TracingPage.tsx` | Equity curves, asset performance and metrics, from `/api/grafana/*` |
| `ReadinessPage.tsx` | The paper-to-live scorecard by group, from `/api/readiness` |

## Develop

```powershell
aq api          # backend on :8001
npm install
npm run dev     # http://localhost:3002, proxying /api to :8001
```

In Docker the same build is served by the `engine` service on port 8001. Alternatively, the light `dashboard` image serves it with demo data on port 8000: `aq webui --docker`, or `docker run --rm -p 8080:8000 ghcr.io/leon1706-lol/aether-quant-dashboard:latest`.

- **Access (`src/components/access/`):**
  - a demo banner when `/api/health` says `demo`
  - an onboarding empty state when there is no runtime feed
  - sign-in with a bearer token, kept in `sessionStorage`, when the API requires auth
  - an account selector that adds `?account=` to the state calls

```powershell
npm run build   # tsc -b && vite build
npm run lint    # oxlint, with the jsx-a11y plugin
npm run test    # vitest run
npm run test:coverage   # vitest with v8 coverage into coverage/
```

- **Tests:** Vitest and Testing Library. `src/test/setup.ts` stubs `@react-three/fiber` and `drei`, because jsdom has no WebGL.
- **Low memory:** if workers time out, use `npx vitest run --no-file-parallelism`.

## Topology modes

`TopologyScene3D.tsx` reads the backend's `dimensions.depth`:

- **`depth === 1` (default):** x and y are the embedding, and z encodes volatility on a shallower scale.
- **`depth === 100` (`phase_v2.topology.embedding_dimensions: 3`):** all three axes are the embedding, on one scale, and node radius carries volatility.
