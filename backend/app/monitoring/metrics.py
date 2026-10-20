"""Prometheus instrumentation for the ClusterOps API.

Six custom collectors cover the signals an AIOps dashboard actually needs: request
throughput and latency, forecast error per product, order-match confidence, the
human-review rate, and the current drift PSI per monitored feature.

Cardinality control
-------------------
``endpoint`` labels are taken from the **route template** (``/api/v1/orders/
review-queue/{item_id}``), never from the concrete request path.  Labelling by raw
path would mint a new time series for every review-queue item UUID — tens of
thousands of series from a single busy endpoint, which is how a Prometheus server
gets killed.  Requests that match no route collapse onto a single ``unmatched``
label instead.

Synthetic data only — these counters describe requests against generated data.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Mapping

from prometheus_client import Counter, Gauge, Histogram

from app.logging_config import get_logger

logger: Final[logging.Logger] = get_logger("monitoring.metrics")

#: Buckets for request latency, in seconds.  The 0.5 s edge is the documented p95
#: SLA, and 2.5 s is the ceiling of the phase specification.
LATENCY_BUCKETS: Final[tuple[float, ...]] = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

#: Buckets for matcher confidence.  0.50 and 0.70 are included deliberately: they
#: are the human-review threshold and the Stage-1 auto-accept threshold, so the
#: histogram shows exactly how much traffic sits in each safety band.
CONFIDENCE_BUCKETS: Final[tuple[float, ...]] = (
    0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0,
)

#: Label used for requests that matched no route (404/405/500 before routing).
UNMATCHED_ENDPOINT: Final[str] = "unmatched"


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

REQUESTS: Final[Counter] = Counter(
    "clusterops_requests_total",
    "Total HTTP requests handled by the ClusterOps API",
    ["endpoint", "method", "status_code"],
)

REQUEST_LATENCY: Final[Histogram] = Histogram(
    "clusterops_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=LATENCY_BUCKETS,
)

FORECAST_MAE: Final[Gauge] = Gauge(
    "clusterops_forecast_mae",
    "Most recent forecast mean absolute error per product",
    ["product_id"],
)

#: Named without the ``_bucket`` suffix on purpose: prometheus_client appends it,
#: so the exposed series is exactly ``clusterops_match_confidence_bucket`` as the
#: specification requires.  Naming it ``..._bucket`` would emit
#: ``..._bucket_bucket``.
MATCH_CONFIDENCE: Final[Histogram] = Histogram(
    "clusterops_match_confidence",
    "Distribution of order-matcher confidence scores",
    buckets=CONFIDENCE_BUCKETS,
)

LOW_CONFIDENCE: Final[Counter] = Counter(
    "clusterops_low_confidence_total",
    "Order items whose final confidence fell below the human-review threshold",
)

DRIFT_PSI: Final[Gauge] = Gauge(
    "clusterops_drift_psi_score",
    "Latest Population Stability Index per monitored feature",
    ["feature_name"],
)


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def endpoint_label(request: Any) -> str:
    """Return a low-cardinality label for ``request``.

    Prefers the matched route template and falls back to :data:`UNMATCHED_ENDPOINT`
    so a flood of unknown paths cannot explode the metric cardinality.
    """
    route = getattr(request, "scope", {}).get("route")
    path = getattr(route, "path", None)
    return str(path) if path else UNMATCHED_ENDPOINT


def observe_request(
    endpoint: str,
    method: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record one completed HTTP request."""
    REQUESTS.labels(endpoint=endpoint, method=method, status_code=str(status_code)).inc()
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(max(duration_seconds, 0.0))


def record_match(confidence: float, needs_review: bool) -> None:
    """Record one matched order item.

    The review counter is keyed off ``needs_review`` rather than recomputing the
    threshold, so it stays consistent with the matcher even if that threshold is
    retuned.
    """
    MATCH_CONFIDENCE.observe(float(confidence))
    if needs_review:
        LOW_CONFIDENCE.inc()


def set_forecast_mae(per_product_mae: Mapping[str, float]) -> None:
    """Publish the per-product MAE of the most recent forecast."""
    for product_id, mae in per_product_mae.items():
        FORECAST_MAE.labels(product_id=str(product_id)).set(float(mae))


def set_drift_psi(per_feature_psi: Mapping[str, float]) -> None:
    """Publish the latest PSI for each monitored feature."""
    for feature_name, psi in per_feature_psi.items():
        DRIFT_PSI.labels(feature_name=str(feature_name)).set(float(psi))


__all__ = [
    "CONFIDENCE_BUCKETS",
    "DRIFT_PSI",
    "FORECAST_MAE",
    "LATENCY_BUCKETS",
    "LOW_CONFIDENCE",
    "MATCH_CONFIDENCE",
    "REQUESTS",
    "REQUEST_LATENCY",
    "UNMATCHED_ENDPOINT",
    "endpoint_label",
    "observe_request",
    "record_match",
    "set_drift_psi",
    "set_forecast_mae",
]