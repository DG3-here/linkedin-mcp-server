from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from linkedin_mcp.accounts.models import AccountRecord
from linkedin_mcp.accounts.store import AccountRegistryStore
from linkedin_mcp.errors import ConfigurationError


def _record(account_id: str) -> AccountRecord:
    now = datetime.now(UTC)
    return AccountRecord(account_id=account_id, created_at=now, updated_at=now)


def test_store_round_trips_records(tmp_path: Path) -> None:
    store = AccountRegistryStore(tmp_path / "registry.json")
    assert store.load() == {}

    store.save({"recruiter_001": _record("recruiter_001")})
    loaded = store.load()

    assert set(loaded) == {"recruiter_001"}
    assert loaded["recruiter_001"].account_id == "recruiter_001"


def test_store_creates_parent_directory_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "registry.json"
    store = AccountRegistryStore(path)

    store.save({"recruiter_001": _record("recruiter_001")})

    assert path.is_file()
    assert list(path.parent.glob("*.tmp-*")) == []
    if os.name != "nt":
        assert (path.stat().st_mode & 0o777) == 0o600


def test_store_rejects_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("not json", encoding="utf-8")
    store = AccountRegistryStore(path)

    with pytest.raises(ConfigurationError, match="corrupted"):
        store.load()


def test_store_rejects_a_registry_missing_the_accounts_object(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{}", encoding="utf-8")
    store = AccountRegistryStore(path)

    with pytest.raises(ConfigurationError, match="corrupted"):
        store.load()
