"""Local persistent registry of configured LinkedIn accounts (non-secret metadata)."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path
from typing import cast
from uuid import uuid4

from linkedin_mcp.accounts.models import AccountRecord
from linkedin_mcp.errors import ConfigurationError


class AccountRegistryStore:
    """Read/write the shared JSON registry of known local LinkedIn accounts."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, AccountRecord]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return {}

        try:
            payload = cast("object", json.loads(raw))
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                "The local LinkedIn account registry is corrupted."
            ) from error

        if not isinstance(payload, dict):
            raise ConfigurationError("The local LinkedIn account registry is corrupted.")
        accounts = cast("dict[str, object]", payload).get("accounts")
        if not isinstance(accounts, dict):
            raise ConfigurationError("The local LinkedIn account registry is corrupted.")
        accounts = cast("dict[object, object]", accounts)

        records: dict[str, AccountRecord] = {}
        for account_id, entry in accounts.items():
            if not isinstance(account_id, str):
                raise ConfigurationError("The local LinkedIn account registry is corrupted.")
            records[account_id] = AccountRecord.model_validate(entry)
        return records

    def save(self, records: dict[str, AccountRecord]) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            with suppress(OSError):
                self._path.parent.chmod(0o700)

        payload = {
            "accounts": {
                account_id: json.loads(record.model_dump_json())
                for account_id, record in records.items()
            }
        }
        data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")

        tmp_path = self._path.with_name(f"{self._path.name}.tmp-{uuid4().hex[:8]}")
        descriptor = os.open(
            tmp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            with suppress(OSError):
                tmp_path.unlink()
            raise

        if os.name != "nt":
            with suppress(OSError):
                self._path.chmod(0o600)
