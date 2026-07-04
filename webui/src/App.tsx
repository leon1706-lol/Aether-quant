import { Route, Routes } from 'react-router-dom'
import { useRuntimeState } from './api/hooks'
import { AppShell } from './components/layout/AppShell'
import { NeuralNetworkPage } from './pages/NeuralNetworkPage'
import { Overview } from './pages/Overview'
import { RiskPage } from './pages/RiskPage'
import { TopologyPage } from './pages/TopologyPage'
import { TracingPage } from './pages/TracingPage'

function App() {
  const { data: state, isError } = useRuntimeState()

  return (
    <AppShell state={state} isError={isError}>
      <Routes>
        <Route path="/" element={<Overview state={state} />} />
        <Route path="/risk" element={<RiskPage state={state} />} />
        <Route path="/topology" element={<TopologyPage state={state} />} />
        <Route path="/neural-network" element={<NeuralNetworkPage state={state} />} />
        <Route path="/tracing" element={<TracingPage />} />
      </Routes>
    </AppShell>
  )
}

export default App
