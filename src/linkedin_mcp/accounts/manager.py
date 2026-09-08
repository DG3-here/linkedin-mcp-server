"""High-level operations over the local, non-secret LinkedIn account registry."""

from __future__ import annotations

from datetime import UTC, datetime

from linkedin_mcp.accounts.models import AccountRecord, AccountSummary
from linkedin_mcp.accounts.store import AccountRegistryStore
from linkedin_mcp.application.process_lock import inspect_account_runtime
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import (
    Settings,
    accounts_root_path,
    validate_account_id_value,
)
from linkedin_mcp.errors import ConfigurationError


class LinkedInAccountManager:
    """Track and report on every LinkedIn account configured on this machine.

    Each account is a separate local profile/runtime, isolated by `account_id`
    (see `Settings.account_id`). This manager only maintains non-secret
    bookkeeping (labels, timestamps) and reports live, non-secret status by
    inspecting the existing per-account profile and runtime lock - it never
    starts a browser or reads session/credential material itself.
    """

    def __init__(self, store: AccountRegistryStore | None = None) -> None:
        self._store = store or AccountRegistryStore(accounts_root_path() / "registry.json")

    @staticmethod
    def settings_for(account_id: str) -> Settings:
        """Build `Settings` scoped to `account_id`, deriving its isolated paths."""
        return Settings(account_id=account_id)

    def register(self, account_id: str, *, label: str | None = None) -> AccountRecord:
        """Create or update the registry entry for `account_id`. Idempotent."""
        account_id = validate_account_id_value(account_id)
        now = datetime.now(UTC)
        records = self._store.load()
        existing = records.get(account_id)
        record = AccountRecord(
            account_id=account_id,
            label=label if label is not None else (existing.label if existing else None),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            last_authenticated_at=existing.last_authenticated_at if existing else None,
            last_used_at=existing.last_used_at if existing else None,
        )
        records[account_id] = record
        self._store.save(records)
        return record

    def forget(self, account_id: str) -> bool:
        """Remove `account_id` from the registry only; profile/lock files are kept."""
        account_id = validate_account_id_value(account_id)
        records = self._store.load()
        if account_id not in records:
            return False
        del records[account_id]
        self._store.save(records)
        return True

    def record_authenticated(self, account_id: str) -> AccountRecord:
        """Mark `account_id` as having just completed authentication."""
        return self._touch(account_id, authenticated=True)

    def record_used(self, account_id: str) -> AccountRecord:
        """Mark `account_id` as having just been used (e.g. server start)."""
        return self._touch(account_id, used=True)

    def _touch(
        self, account_id: str, *, authenticated: bool = False, used: bool = False
    ) -> AccountRecord:
        account_id = validate_account_id_value(account_id)
        now = datetime.now(UTC)
        records = self._store.load()
        existing = records.get(account_id)
        if existing is None:
            raise ConfigurationError(f"Account '{account_id}' is not registered.")
        record = AccountRecord(
            account_id=account_id,
            label=existing.label,
            created_at=existing.created_at,
            updated_at=now,
            last_authenticated_at=now if authenticated else existing.last_authenticated_at,
            last_used_at=now if used else existing.last_used_at,
        )
        records[account_id] = record
        self._store.save(records)
        return record

    def get(self, account_id: str) -> AccountSummary:
        """Report one account's non-secret status. Raises if it has never been connected."""
        account_id = validate_account_id_value(account_id)
        records = self._store.load()
        summary = self._summarize(account_id, records.get(account_id))
        known = summary.registered or summary.profile_initialized or summary.runtime_running
        if not known:
            raise ConfigurationError(f"Account '{account_id}' has not been connected yet.")
        return summary

    def list(self) -> tuple[AccountSummary, ...]:
        """Report every known account: registered ones, plus any profile directory on disk."""
        records = self._store.load()
        discovered = set(records)
        root = accounts_root_path()
        if root.is_dir():
            for entry in root.iterdir():
                if entry.is_dir():
                    discovered.add(entry.name)
        return tuple(
            self._summarize(account_id, records.get(account_id))
            for account_id in sorted(discovered)
        )

    def _summarize(self, account_id: str, record: AccountRecord | None) -> AccountSummary:
        settings = self.settings_for(account_id)
        profile = BrowserProfileManager(settings).inspect()
        runtime = inspect_account_runtime(settings.runtime_lock_path)
        owner = runtime.owner
        return AccountSummary(
            account_id=account_id,
            registered=record is not None,
            label=record.label if record else None,
            created_at=record.created_at if record else None,
            updated_at=record.updated_at if record else None,
            last_authenticated_at=record.last_authenticated_at if record else None,
            last_used_at=record.last_used_at if record else None,
            profile_initialized=profile.initialized,
            runtime_running=runtime.running,
            runtime_pid=owner.pid if owner else None,
            runtime_started_at=owner.started_at if owner else None,
            runtime_endpoint=owner.endpoint if owner else None,
        )
