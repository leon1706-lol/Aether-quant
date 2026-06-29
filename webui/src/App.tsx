import { Route, Routes } from 'react-router-dom'
import { useRuntimeState } from './api/hooks'
import { AppShell } from './components/layout/AppShell'
import { Overview } from './pages/Overview'
import { RiskPage } from './pages/RiskPage'

function App() {
  const { data: state, isError } = useRuntimeState()

  return (
    <AppShell state={state} isError={isError}>
      <Routes>
        <Route path="/" element={<Overview state={state} />} />
        <Route path="/risk" element={<RiskPage state={state} />} />
      </Routes>
    </AppShell>
  )
}

export default App
