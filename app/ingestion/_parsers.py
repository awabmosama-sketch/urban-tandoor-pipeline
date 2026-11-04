"""Shared cell-cleaning helpers for source workbook ingestion.

These are intentionally duplicated from the Phase 6 menu ingester so that
``excel_menu.py`` does not need to change; both phases now share the same
cleaning semantics.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "_null",
    "_req_str",
    "_opt_str",
    "_req_int",
    "_opt_int",
    "_req_float",
    "_opt_float",
    "_req_dec",
    "_opt_dec",
    "_req_bool",
]


def _null(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    if isinstance(v, str):
        s = v.strip()
        if s == "" or s.lower() == "none":
            return None
        return s
    return v


def _req_str(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required string {k}: {r}")
    return str(v)


def _opt_str(r, k):
    v = _null(r.get(k))
    return None if v is None else str(v)


def _req_int(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required int {k}: {r}")
    return int(float(v))


def _opt_int(r, k):
    v = _null(r.get(k))
    return None if v is None else int(float(v))


def _req_float(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required float {k}: {r}")
    return float(v)


def _opt_float(r, k):
    v = _null(r.get(k))
    return None if v is None else float(v)


def _req_dec(r, k):
    v = _null(r.get(k))
    if v is None:
        raise ValueError(f"Missing required decimal {k}: {r}")
    return Decimal(str(v))


def _opt_dec(r, k):
    v = _null(r.get(k))
    return None if v is None else Decimal(str(v))


def _req_bool(r, k):
    v = _null(r.get(k))
    if isinstance(v, bool):
        return v
    if v is None:
        raise ValueError(f"Missing required bool {k}: {r}")
    s = str(v).strip().lower()
    if s == "yes":
        return True
    if s == "no":
        return False
    raise ValueError(f"Invalid bool {k}={v!r} — must be Yes/No: {r}")
