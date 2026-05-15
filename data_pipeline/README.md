# data_pipeline

Owns the V2 Lean-data pipeline contract.

The current rule stays simple and important: training and backtesting use the local Lean `data/` folder. This package describes that contract for later V2 modules such as MoE experts, regime detection, topology modeling, dynamic risk and the volatility dashboard.

It does not replace `train.py`; it wraps and documents the existing dataset pipeline so later modules can depend on a stable manifest.

