"""Fingerprints drive automatic, domain-scoped JSON re-ingestion."""
from app.collections import ALL_COLLECTIONS
from app.services.auto_ingest import DOMAINS, compute_fingerprints


def test_fingerprints_are_stable_and_domain_scoped(tmp_path):
    for name in ALL_COLLECTIONS:
        (tmp_path / f"{name}.json").write_text("[]", encoding="utf-8")

    first = compute_fingerprints(tmp_path)
    assert set(first) == set(DOMAINS)
    assert first == compute_fingerprints(tmp_path)

    # Editing one menu file must only change the menu domain fingerprint.
    (tmp_path / "menu_items.json").write_text(
        '[{"menu_id": "MENU001"}]', encoding="utf-8"
    )
    second = compute_fingerprints(tmp_path)

    assert second["menu"] != first["menu"]
    assert second["inventory"] == first["inventory"]
    assert second["docs"] == first["docs"]


def test_missing_snapshot_is_a_change(tmp_path):
    for name in ALL_COLLECTIONS:
        (tmp_path / f"{name}.json").write_text("[]", encoding="utf-8")

    before = compute_fingerprints(tmp_path)
    (tmp_path / "branches.json").unlink()
    after = compute_fingerprints(tmp_path)

    assert after["inventory"] != before["inventory"]
    assert after["menu"] == before["menu"]
