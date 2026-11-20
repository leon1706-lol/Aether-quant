"""Example models (V6.6.10): small networks trained on the bundled public sample, published with each GitHub release. Install one,
load it, score a close table with the numpy forward pass; no torch.

    from aether_quant import models, samples
    models.install("example-crypto-mlp")                  # downloads from the latest release, checks its sha256
    model = models.load("example-crypto-mlp")
    scores = models.score(model, samples.load_sample_prices())   # date, ticker, score

The project's own trading models are not published; `load` also opens any folder holding an exported model (your own retrain's
`ml/versions/<id>/`). `aq models list | install | info | score` is the same from the command line.
"""

from retraining.model_catalog import (
    EXAMPLES,
    catalog,
    example_dataset,
    example_features,
    install,
    install_zip,
    load,
    production_collisions,
    release_url,
    score,
    sha256_file,
    zip_problems,
)

__all__ = [
    "EXAMPLES",
    "catalog",
    "example_dataset",
    "example_features",
    "install",
    "install_zip",
    "load",
    "production_collisions",
    "release_url",
    "score",
    "sha256_file",
    "zip_problems",
]
