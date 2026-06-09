"""
NexusIQ — observability/langsmith_tracer.py

LangSmith tracing decorator for async pipeline functions.

Usage:
    from app.observability.langsmith_tracer import traced

    @traced(name="my_function")
    async def my_function(...):
        ...

When LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY is set in .env,
every decorated function call is automatically logged to LangSmith as
a run, including inputs, outputs, latency, and any child LLM calls.

If LangSmith is disabled or unreachable, the decorator is a transparent
no-op — it never raises or disrupts normal execution.
"""

import functools
import logging
from typing import Any, Callable, Coroutine, TypeVar

from app.config import settings

logger = logging.getLogger("nexusiq.observability")

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def traced(name: str) -> Callable[[F], F]:
    """
    Decorator factory that wraps an async function with LangSmith tracing.

    Args:
        name: Human-readable run name shown in the LangSmith UI.

    Returns:
        Decorator that transparently wraps the target async function.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Fast path: tracing disabled or no API key configured
            # FIX: was settings.LANGCHAIN_TRACING_V2 / settings.LANGCHAIN_API_KEY
            #      Correct attrs: settings.langchain_tracing_v2 / settings.langchain_api_key
            if not (settings.langchain_tracing_v2 and settings.langchain_api_key):
                return await fn(*args, **kwargs)

            # Attempt LangSmith tracing — fail silently on any error
            try:
                from langsmith import traceable

                # langsmith.traceable wraps sync + async callables
                traced_fn = traceable(fn, name=name, run_type="chain")
                return await traced_fn(*args, **kwargs)

            except ImportError:
                logger.warning(
                    "langsmith package not installed — "
                    "install it with: pip install langsmith"
                )
            except Exception as exc:
                logger.warning(
                    "LangSmith trace for '%s' failed (%s) — running without tracing",
                    name,
                    exc,
                )

            # Fallback: run without tracing
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def log_retrieval_trace(trace: dict) -> None:
    """
    Log a retrieval trace dict to the standard Python logger.

    Args:
        trace: The retrieval_trace dict returned by hybrid_retrieve().
    """
    logger.debug(
        "Retrieval trace | sem=%d | bm25=%d | merged=%d | reranked=%s",
        trace.get("semantic_count", 0),
        trace.get("bm25_count", 0),
        trace.get("merged_count", 0),
        trace.get("reranked", False),
    )