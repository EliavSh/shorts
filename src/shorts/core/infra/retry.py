"""Shared retry decorator for transient external-API failures.

Used by every provider wrapper. Keeps the retry policy in one place so it's
easy to tune without scanning the codebase.
"""
from __future__ import annotations

import logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

# Transient errors worth retrying. We deliberately don't catch ValueError /
# pydantic.ValidationError — those are programmer errors.
_TRANSIENT = (ConnectionError, TimeoutError, OSError)


def transient_retry(max_attempts: int = 3, min_wait: float = 1.0, max_wait: float = 8.0):
    """Decorator: retry on transient network errors with exponential backoff."""
    return retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=min_wait, max=max_wait),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
