"""Single source of truth for the package version."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_PACKAGE = "urban-tandoor-pipeline"


def app_version() -> str:
    """Return the installed distribution version, with a source-tree fallback."""
    try:
        return version(_PACKAGE)
    except PackageNotFoundError:
        return "0.1.0"


__all__ = ["app_version"]
