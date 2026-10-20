"""Machine learning core for ClusterOps.

Module boundaries that matter for correctness:

* :mod:`app.ml.features` — the **single source of truth** for feature
  engineering. Training and serving both call ``build_features``; nothing here
  may reimplement a transformation.
* :mod:`app.ml.dataset` — panel assembly (SQL) that feeds the feature pipeline.
* :mod:`app.ml.forecast_model` — LightGBM forecaster with quantile intervals.
* :mod:`app.ml.mlflow_utils` — experiment tracking, registry, promotion gate.

Synthetic data only.
"""

from __future__ import annotations

__all__: list[str] = []