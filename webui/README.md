# webui

React/Vite single-page dashboard that replaced the earlier `dashboard.html`
and `volatility_dashboard.html`. Polls `monitoring/api_server.py`'s
`/api/state` (plus `/api/scene`, `/api/topology`) every 5 seconds via
TanStack React Query (`src/api/hooks.ts`'s `useRuntimeState()`).

Pages (`src/pages/`):

- `Overview.tsx` — scorecards, 3D market scene, asset heatmap (left) and the
  trading-side stack: Observation Mode, signal board, positions,
  strategy/risk cards (right). V4-W1 moved the operational/health panels
  out to `OperationsPage.tsx`; this page had grown to 11 stacked panels in
  a single column.
- `OperationsPage.tsx` (V4-W1) — the operational/health half of the old
  Overview, in a balanced two-column layout: Performance Triggers,
  Retraining Status (V2-17), Paper Trading Readiness, Multi-Asset-Class
  Readiness (left); Audit Log, Monitoring Feeds, Raw State (right).
- `RiskPage.tsx` — risk core panel, asset volatility/sizing table, liquidity
  and execution-impact panel.
- `TopologyPage.tsx` — 3D cluster view with regime/risk colouring.
- `TracingPage.tsx` (V2-18) — runtime metrics snapshot, backtest equity
  curve (per-ticker selector, strategy vs buy-and-hold) and
  observation-mode equity/drawdown curves stacked in the wider left
  column; asset performance (diverging Sharpe bars) alone in the right.
  V4-W2 chose that split so the interactive charts get the width while the
  asset table — which grows a row per asset — has room to grow downward.
  Replaces the Grafana instance that used to be the only consumer of these
  feeds — Grafana has been removed from `docker-compose.yml` entirely.
- `NeuralNetworkPage.tsx` (V2-20) — interactive 3D diagram
  (`components/neuralnet/NeuralNetworkScene3D.tsx`) plus a stats panel
  (`NeuralNetworkStatsPanel.tsx`) of every trained network's layer/node/edge
  structure: the baseline model, the 4 MoE experts, and the optional
  learned gating blend (`moe/gating.py`'s `ml/gating_model.json`, once
  `train_gating.py`/`aq train --gating-only` has produced one). Fetches
  `GET /api/neural-network` on its own hook (`useNeuralNetwork()`), not the
  shared `/api/state` blob. The scene's `NETWORK_ORDER` array controls
  which networks actually render and in what order — a new network
  returned by the backend needs adding there too, or it silently appears
  only in the stats panel's list. `topology/learned_topology.py`'s KMeans
  cluster prototypes are the one thing deliberately left out entirely (not
  a layered network), shown instead as a labelled `excluded` entry.

Monitoring panels live under `src/components/monitoring/`
(`PerformanceTriggersPanel.tsx`, `RetrainingStatusPanel.tsx`,
`ObservationPanel.tsx`, `MonitoringFeeds.tsx`, `CountTable.tsx`,
`RawStateViewer.tsx`) and all read nested fields off the single
`/api/state` blob.

Tracing panels live under `src/components/tracing/`
(`MetricsSnapshotPanel.tsx`, `AssetPerformancePanel.tsx`,
`BacktestEquityPanel.tsx`, `ObservationEquityPanel.tsx`) and fetch the
`/api/grafana/*` routes directly (`src/api/hooks.ts`'s `useMetricsSnapshot()`,
`useEquityCurves()`, `useAssetPerformance()`, `useObservationEquityCurve()`,
each on a 15s refresh). `LineChart.tsx` and `DivergingBarChart.tsx` in the
same folder are small dependency-free SVG chart primitives shared by those
panels — no charting library was added.

Runtime types for the `/api/state` payload live in `src/types/state.ts`;
tracing feed types live in `src/types/tracing.ts`.

## Local dev

```powershell
npm install
npm run dev
```

Serves on `http://localhost:3002` (moved from 3000 in V2-17 so a local
Aether-Quant stack never collides with the separate Aether-Vault sibling
project's own webui, which also defaults to 3000). `/api` calls proxy to
`http://localhost:8001` (`vite.config.ts`) — start the backend locally with:

```powershell
uvicorn monitoring.api_server:app --port 8001 --reload
```

In Docker, the same build is instead bundled into and served by the
`aether-quant-engine` container (the `engine` service) itself on port
8001 — no separate webui container or port.

## Build / lint / test

```powershell
npm run build   # tsc -b && vite build
npm run lint    # oxlint
npm run test    # vitest run
```

Vitest + Testing Library were added in V4-W1 (this was the first frontend
test infrastructure in the project). `src/test/setup.ts` globally stubs
`@react-three/fiber` and `@react-three/drei`, since jsdom has no WebGL and
the page-composition tests care about which panels render, not about the
renderer. Current suites: `src/pages/pages.test.tsx` (V4-W1/W2 — which
panels live on which page, nav-pill routing) and
`src/components/topology/TopologyScene3D.test.tsx` (V4-W3 — the 2D/3D
embedding-mode legend switch).

## Topology 3D modes (V4-W3)

`TopologyScene3D.tsx`'s `toVec3()` reads the backend's declared
`dimensions.depth` to tell the two embedding modes apart:

- `depth === 1` — 2D mode (the default). x/y are the SMACOF
  correlation-distance embedding, z is the volatility encoding, mapped on
  a deliberately shallower scale.
- `depth === 100` — 3D mode
  (`phase_v2.topology.embedding_dimensions: 3`). All three axes are a real
  distance-preserving embedding, so z maps with the *same* factor as x/y —
  scaling it differently would squash the very distances the embedding
  exists to preserve. Volatility is carried by node radius, which already
  encoded it in both modes.
