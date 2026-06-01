"""App version shown in the dashboard so you can tell which code is live.

`APP_VERSION` is injected at image-build time from the git commit SHA (see the
Dockerfile `GIT_SHA` build-arg, passed by .github/workflows/fly-deploy.yml), so
it updates automatically on every deploy — nothing to remember to bump. `VERSION`
is a human-readable label you can bump for notable releases.
"""
from __future__ import annotations

import os

VERSION = "1.1"  # bump for notable releases (optional, cosmetic)


def build_id() -> str:
    """e.g. 'v1.1 · a1b2c3d' in prod, 'v1.1 · dev' locally."""
    sha = (os.environ.get("APP_VERSION") or "").strip()
    short = sha[:7] if sha and sha.lower() != "dev" else "dev"
    return f"v{VERSION} · {short}"
