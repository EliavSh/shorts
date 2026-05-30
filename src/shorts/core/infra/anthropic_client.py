"""Factory for Anthropic SDK clients that respect SSL_NO_VERIFY for local dev,
add tenacity retry on transient errors, and meter token usage per pipeline.
"""
from __future__ import annotations

import logging
import os

import httpx
from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from shorts.core.usage.record import record as record_usage

log = logging.getLogger(__name__)

_anthropic_retry = retry(
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIStatusError,
                                    ConnectionError, TimeoutError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)


def _no_verify() -> bool:
    return os.environ.get("SSL_NO_VERIFY", "").strip() in {"1", "true", "yes"}


class _MeteredMessages:
    """Wrapper that records token usage every successful messages.create call.

    Usage is attributed to the pipeline set via shorts.core.usage.set_pipeline();
    if none is set the record is dropped (logged as warning).
    """

    def __init__(self, inner):
        self._inner = inner

    @_anthropic_retry
    def create(self, *args, **kwargs):
        resp = self._inner.create(*args, **kwargs)
        try:
            usage = getattr(resp, "usage", None)
            model = kwargs.get("model") or "unknown"
            if usage is not None:
                record_usage(
                    "anthropic", "messages",
                    units_in=getattr(usage, "input_tokens", 0) or 0,
                    units_out=getattr(usage, "output_tokens", 0) or 0,
                    model=model,
                )
        except Exception:
            pass  # never let metering break a successful call
        return resp

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _MeteredAnthropic:
    def __init__(self, inner: Anthropic):
        self._inner = inner
        self.messages = _MeteredMessages(inner.messages)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def make_client(api_key: str | None = None) -> Anthropic:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    if _no_verify():
        inner = Anthropic(api_key=key, http_client=httpx.Client(verify=False, timeout=60.0))
    else:
        inner = Anthropic(api_key=key)
    return _MeteredAnthropic(inner)  # type: ignore[return-value]
