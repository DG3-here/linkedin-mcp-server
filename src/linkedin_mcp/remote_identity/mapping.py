from __future__ import annotations

import json
from pathlib import Path


class RemoteAccountMapping:
    """
    Maps an authenticated remote user to exactly one local LinkedIn account.

    This file contains bookkeeping only.
    LinkedIn session material remains inside the account's browser profile.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}

        try:
            value = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

        return {
            str(user_id): str(account_id)
            for user_id, account_id in value.items()
        }

    def account_for(self, user_id: str) -> str | None:
        return self._read().get(user_id)

    def bind(self, user_id: str, account_id: str) -> None:
        data = self._read()

        existing = data.get(user_id)

        if existing is not None and existing != account_id:
            raise ValueError(
                "Remote user is already bound to a different LinkedIn account."
            )

        data[user_id] = account_id

        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2))
        temporary.replace(self.path)
