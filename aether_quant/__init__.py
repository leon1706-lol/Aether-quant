"""Aether Quant as a library: the pure, Lean-free building blocks of the trading system (risk, book construction,
execution gates, features, evaluation and research tools), re-exported from the modules the live algorithm uses."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aether-quant")
except PackageNotFoundError:  # running from a checkout without `pip install -e .`
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
