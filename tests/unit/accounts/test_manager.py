from __future__ import annotations

from pathlib import Path

import pytest

import linkedin_mcp.config as config_module
from linkedin_mcp.accounts import LinkedInAccountManager
from linkedin_mcp.errors import ConfigurationError


@pytest.fixture(autouse=True)
def sandbox_data_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_user_data_path(*_args: object, **_kwargs: object) -> Path:
        return tmp_path

    monkeypatch.setattr(config_module, "user_data_path", fake_user_data_path)


def test_register_is_idempotent_and_preserves_created_at() -> None:
    manager = LinkedInAccountManager()

    first = manager.register("recruiter_001", label="Recruiter One")
    second = manager.register("recruiter_001", label="Recruiter One (renamed)")

    assert first.created_at == second.created_at
    assert second.label == "Recruiter One (renamed)"
    assert second.updated_at >= first.updated_at


def test_accounts_are_isolated_by_profile_and_lock_path() -> None:
    manager = LinkedInAccountManager()

    settings_a = manager.settings_for("recruiter_001")
    settings_b = manager.settings_for("recruiter_002")

    assert settings_a.browser_profile_path != settings_b.browser_profile_path
    assert settings_a.runtime_lock_path != settings_b.runtime_lock_path
    assert "recruiter_001" in str(settings_a.browser_profile_path)
    assert "recruiter_002" in str(settings_b.browser_profile_path)


def test_get_raises_for_a_never_connected_account() -> None:
    manager = LinkedInAccountManager()

    with pytest.raises(ConfigurationError, match="has not been connected"):
        manager.get("ghost")


def test_get_reports_a_registered_but_never_started_account() -> None:
    manager = LinkedInAccountManager()
    manager.register("recruiter_001")

    summary = manager.get("recruiter_001")

    assert summary.registered is True
    assert summary.profile_initialized is False
    assert summary.runtime_running is False


def test_list_includes_a_profile_directory_discovered_without_a_registry_entry(
    tmp_path: Path,
) -> None:
    manager = LinkedInAccountManager()
    (tmp_path / "accounts" / "legacy_account" / "profile").mkdir(parents=True)

    summaries = {summary.account_id: summary for summary in manager.list()}

    assert "legacy_account" in summaries
    assert summaries["legacy_account"].registered is False


def test_record_authenticated_and_used_require_prior_registration() -> None:
    manager = LinkedInAccountManager()

    with pytest.raises(ConfigurationError, match="not registered"):
        manager.record_authenticated("ghost")

    manager.register("recruiter_001")
    authenticated = manager.record_authenticated("recruiter_001")
    assert authenticated.last_authenticated_at is not None

    used = manager.record_used("recruiter_001")
    assert used.last_used_at is not None
    assert used.last_authenticated_at == authenticated.last_authenticated_at


def test_forget_removes_the_registry_entry_but_keeps_profile_files(tmp_path: Path) -> None:
    manager = LinkedInAccountManager()
    manager.register("recruiter_001")
    profile_dir = tmp_path / "accounts" / "recruiter_001" / "profile"
    profile_dir.mkdir(parents=True)
    (profile_dir / "marker").write_text("keep me", encoding="utf-8")

    removed = manager.forget("recruiter_001")
    removed_again = manager.forget("recruiter_001")

    assert removed is True
    assert removed_again is False
    assert (profile_dir / "marker").read_text(encoding="utf-8") == "keep me"
