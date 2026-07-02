# execution

Pure, Lean-free order gating and simulated-fill math shared between `main.py`
and its test suite (V2-15, Observation Mode). Owns the
`phase_v2.runtime.mode` -> real-vs-simulated order decision table
(`resolve_order_permission`), the safe-fallback mode normalizer
(`resolve_runtime_mode`), and the hypothetical fill-price/quantity math used
by `experience/simulated_portfolio.py` (`simulate_fill`). No `AlgorithmImports`
or QCAlgorithm dependency, so it is unit-testable without a Lean runtime.
