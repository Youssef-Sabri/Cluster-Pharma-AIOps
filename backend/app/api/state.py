"""Process-wide singletons the API depends on.

FastAPI lifespan runs once at startup and populates :data:`state`; every request
handler reads the loaded catalogue matcher and forecasting runtime from here
rather than reconstructing them.  Rebuilding a 60-SKU fuzzy index or reloading
three LightGBM boosters per request would be both slow and pointless.

The module deliberately holds *no* MLflow or database imports at import time, so
the app can be imported (for OpenAPI generation or tests) without a live backend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from app.logging_config import get_logger

logger: Final[logging.Logger] = get_logger("api.state")


@dataclass
class AppState:
    """Everything the lifespan handler pre-loads for the request path."""

    #: In-memory catalogue used by the order matcher.
    catalogue: Any | None = None
    #: Loaded Production forecasting runtime, or ``None`` when unavailable.
    runtime: Any | None = None
    #: Order matcher bound to ``catalogue``.
    matcher: Any | None = None
    #: Errors raised while pre-loading, surfaced by ``/health`` for debuggability.
    startup_errors: list[str] = field(default_factory=list)

    @property
    def models_loaded(self) -> bool:
        """``True`` when a Production forecasting model is resident."""
        return bool(self.runtime is not None and self.runtime.models_loaded)

    @property
    def catalogue_loaded(self) -> bool:
        return self.catalogue is not None and len(self.catalogue) > 0

    def require_matcher(self) -> Any:
        """Return the matcher or raise :class:`ServiceNotReadyError`."""
        if self.matcher is None:
            raise ServiceNotReadyError(
                "the order catalogue is not loaded; the service is still starting or the database was unreachable"
            )
        return self.matcher

    def require_runtime(self) -> Any:
        """Return the forecasting runtime or raise :class:`ServiceNotReadyError`."""
        if self.runtime is None or not self.models_loaded:
            raise ServiceNotReadyError(
                "no Production demand model is loaded; train and register one with "
                "`python -m app.ml.forecast_model --train --register`"
            )
        return self.runtime

    def describe(self) -> dict[str, Any]:
        return {
            "models_loaded": self.models_loaded,
            "catalogue_loaded": self.catalogue_loaded,
            "catalogue_entries": len(self.catalogue) if self.catalogue is not None else 0,
            "startup_errors": list(self.startup_errors),
            "runtime": self.runtime.describe() if self.runtime is not None else None,
        }


class ServiceNotReadyError(RuntimeError):
    """Raised when a handler needs a dependency the lifespan could not load.

    Mapped to **503 Service Unavailable** so a client can distinguish "this
    service is not ready" from "your request was wrong" (4xx).
    """


#: The single application state instance.
state: Final[AppState] = AppState()


def reset_state() -> None:
    """Clear pre-loaded resources (used by tests between cases)."""
    state.catalogue = None
    state.runtime = None
    state.matcher = None
    state.startup_errors.clear()


__all__ = ["AppState", "ServiceNotReadyError", "reset_state", "state"]