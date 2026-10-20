"""FastAPI routers for the ClusterOps API."""

from app.api import drift, forecast, health, match_order, registry, retrain, review_queue

#: Every router, in the order they are mounted on the application.
ALL_ROUTERS = (
    health.router,
    forecast.router,
    match_order.router,
    drift.router,
    retrain.router,
    registry.router,
    review_queue.router,
)

__all__ = [
    "ALL_ROUTERS",
    "drift",
    "forecast",
    "health",
    "match_order",
    "registry",
    "retrain",
    "review_queue",
]