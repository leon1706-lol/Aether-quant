# aether_quant.costs

Trading costs, grouped by the job (V6.6.5): composable cost models with the live path's fee presets, the square-root impact term, and the round-trip and net-edge checks the order path runs.

::: aether_quant.costs
    options:
      members:
        - CompositeCostModel
        - CostModel
        - LinearCostModel
        - SquareRootImpactModel
        - build_net_edge_decision
        - coinbase_model
        - compute_sqrt_impact_bps
        - cost_usd
        - estimate_round_trip_cost_bps
        - expected_edge_bps
        - ib_equity_model
        - route_aware_fee_bps
