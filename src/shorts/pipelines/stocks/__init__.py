"""stocks pipeline package."""
from shorts.core.usage import set_pipeline as _set_pipeline

__version__ = "0.1.0"

# Tag all usage events emitted from this pipeline's modules.
_set_pipeline("stocks")

# Ensure the stocks-specific SQLite tables (Topic/Script/Render/Upload/Performance)
# exist before any subcommand tries to query them. Cheap on subsequent runs
# (SQLModel.metadata.create_all is idempotent).
def _bootstrap_db() -> None:
    try:
        from .db import init_db
        init_db()
    except Exception:
        # Don't block import if something's misconfigured; the failure will
        # surface clearly the first time a query runs.
        pass

_bootstrap_db()
