"""Regression tests for ingestion and search robustness fixes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backends.postgres.routes.menu import _like_pattern
from app.collections import DOCS_COLLECTIONS, INVENTORY_COLLECTIONS, MENU_COLLECTIONS
from app.ingestion._parsers import _opt_float, _req_dec, _req_float, _req_int
from app.ingestion.chunker import chunk_text
from app.ingestion.json_ingest import wipe_domains
from app.ingestion.json_store import read_collection, write_collection


class _FakeCollection:
    def __init__(self) -> None:
        self.delete_calls = 0

    async def delete_many(self, query):
        assert query == {}
        self.delete_calls += 1
        return SimpleNamespace(deleted_count=2)


class _FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self.collections.setdefault(name, _FakeCollection())


@pytest.mark.asyncio
async def test_wipe_domains_only_touches_requested_collections():
    db = _FakeDB()

    deleted = await wipe_domains(db, ["menu"])

    assert set(deleted) == set(MENU_COLLECTIONS)
    assert not set(deleted) & set(INVENTORY_COLLECTIONS)
    assert not set(deleted) & set(DOCS_COLLECTIONS)
    assert sum(deleted.values()) == 2 * len(MENU_COLLECTIONS)


def test_write_collection_leaves_no_temporary_files(tmp_path):
    write_collection("sample", [{"value": 1}], tmp_path)
    assert read_collection("sample", tmp_path) == [{"value": 1}]

    write_collection("sample", [{"value": 2}], tmp_path)
    assert read_collection("sample", tmp_path) == [{"value": 2}]
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (-1, 0), (10, 10), (10, 11), (10, -1)],
)
def test_chunk_text_rejects_invalid_parameters(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=chunk_size, overlap=overlap)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "-inf"])
def test_required_parsers_reject_non_finite_numbers(value):
    row = {"amount": value}
    with pytest.raises(ValueError):
        _req_float(row, "amount")
    with pytest.raises(ValueError):
        _req_int(row, "amount")
    with pytest.raises(ValueError):
        _req_dec(row, "amount")


def test_optional_float_treats_nan_as_missing_but_rejects_infinity():
    assert _opt_float({"amount": float("nan")}, "amount") is None
    with pytest.raises(ValueError):
        _opt_float({"amount": float("inf")}, "amount")


def test_like_pattern_escapes_wildcards():
    assert _like_pattern("50%_off\\now") == r"%50\%\_off\\now%"
