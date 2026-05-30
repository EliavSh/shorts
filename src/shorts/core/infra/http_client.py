"""Shared httpx client factory.

Honors SSL_NO_VERIFY=1 for local development on networks with TLS inspection.
Production VPS leaves the default (verify on).
"""
from __future__ import annotations

import os

import httpx


def _no_verify() -> bool:
    return os.environ.get("SSL_NO_VERIFY", "").strip() in {"1", "true", "yes"}


def client(**kwargs) -> httpx.Client:
    if _no_verify() and "verify" not in kwargs:
        kwargs["verify"] = False
    return httpx.Client(**kwargs)


def get(url: str, **kwargs) -> httpx.Response:
    if _no_verify() and "verify" not in kwargs:
        kwargs["verify"] = False
    return httpx.get(url, **kwargs)


def stream(method: str, url: str, **kwargs):
    if _no_verify() and "verify" not in kwargs:
        kwargs["verify"] = False
    return httpx.stream(method, url, **kwargs)
