import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { useRuntimeState } from './api/hooks'
import { AppShell } from './components/layout/AppShell'

// V4.10 - route-level code-splitting. Overview/TopologyPage/NeuralNetworkPage
// pull in @react-three/fiber/three.js scene renderers, which used to be
// bundled into every page's single 1.27MB/348KB-gzip production chunk
// regardless of which route was actually visited - the other 4 pages
// never touch three.js at all. React.lazy() + one shared <Suspense> below
// lets Vite/Rollup split each page into its own chunk, so a page like
// /operations or /tracing no longer downloads three.js on first paint.
// Named exports (not default), so each lazy() call needs the .then()
// adapter rather than a bare `import()` - keeps every page file's
// existing export shape untouched.
const Overview = lazy(() => import('./pages/Overview').then((m) => ({ default: m.Overview })))
const OperationsPage = lazy(() => import('./pages/OperationsPage').then((m) => ({ default: m.OperationsPage })))
const RiskPage = lazy(() => import('./pages/RiskPage').then((m) => ({ default: m.RiskPage })))
const OptionsStrategyPage = lazy(() =>
  import('./pages/OptionsStrategyPage').then((m) => ({ default: m.OptionsStrategyPage })),
)
const TopologyPage = lazy(() => import('./pages/TopologyPage').then((m) => ({ default: m.TopologyPage })))
const NeuralNetworkPage = lazy(() =>
  import('./pages/NeuralNetworkPage').then((m) => ({ default: m.NeuralNetworkPage })),
)
const TracingPage = lazy(() => import('./pages/TracingPage').then((m) => ({ default: m.TracingPage })))
// V5.1 Phase 0 - the cost-aware evaluation dashboard (net Sharpe/turnover/
// capacity/cost-stress), a plain 2D dashboard with no three.js scene, so it
// doesn't strictly need the code-splitting rationale above - kept lazy
// anyway for consistency with every other route in this file.
const EvaluationPage = lazy(() => import('./pages/EvaluationPage').then((m) => ({ default: m.EvaluationPage })))

function RouteLoadingFallback() {
  return <div className="flex items-center justify-center py-24 text-sm text-white/40">Loading…</div>
}

function App() {
  const { data: state, isError } = useRuntimeState()

  return (
    <AppShell state={state} isError={isError}>
      <Suspense fallback={<RouteLoadingFallback />}>
        <Routes>
          <Route path="/" element={<Overview state={state} />} />
          <Route path="/operations" element={<OperationsPage state={state} />} />
          <Route path="/risk" element={<RiskPage state={state} />} />
          <Route path="/options-strategy" element={<OptionsStrategyPage state={state} />} />
          <Route path="/topology" element={<TopologyPage state={state} />} />
          <Route path="/neural-network" element={<NeuralNetworkPage state={state} />} />
          <Route path="/evaluation" element={<EvaluationPage state={state} />} />
          <Route path="/tracing" element={<TracingPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  )
}

export default App
