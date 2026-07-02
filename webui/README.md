# webui

React/Vite single-page dashboard that replaced the earlier `dashboard.html`
and `volatility_dashboard.html`. Polls `monitoring/api_server.py`'s
`/api/state` (plus `/api/scene`, `/api/topology`) every 5 seconds via
TanStack React Query (`src/api/hooks.ts`'s `useRuntimeState()`).

Pages (`src/pages/`):

- `Overview.tsx` — scorecards, 3D market scene, asset heatmap, signal board,
  positions, strategy/risk cards, monitoring feeds, and the right-column
  monitoring stack: Performance Triggers, Retraining Status (V2-17),
  Observation Mode, raw state viewer.
- `RiskPage.tsx` — risk core panel, asset volatility/sizing table, liquidity
  and execution-impact panel.
- `TopologyPage.tsx` — 3D cluster view with regime/risk colouring.

Monitoring panels live under `src/components/monitoring/`
(`PerformanceTriggersPanel.tsx`, `RetrainingStatusPanel.tsx`,
`ObservationPanel.tsx`, `MonitoringFeeds.tsx`, `CountTable.tsx`,
`RawStateViewer.tsx`) and all read nested fields off the single
`/api/state` blob — none of them fetch the `/api/grafana/*` routes
directly, those exist only for external Grafana dashboards.

Runtime types for the `/api/state` payload live in `src/types/state.ts`.

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
`aether-quant` container itself on port 8001 — no separate webui container
or port.

## Build / lint

```powershell
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```
