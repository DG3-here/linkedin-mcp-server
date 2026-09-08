from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


@dataclass
class UserAccount:
    user_id: str
    email: str
    account_id: str
    created_at: str
    linkedin_connected: bool = False


class IdentityStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "users.json"
        self._lock = Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2))
        temporary.replace(self.path)

    def get_by_user_id(self, user_id: str) -> UserAccount | None:
        with self._lock:
            item = self._read().get(user_id)
            return UserAccount(**item) if item else None

    def get_by_email(self, email: str) -> UserAccount | None:
        email = email.lower().strip()

        with self._lock:
            for item in self._read().values():
                if item["email"].lower() == email:
                    return UserAccount(**item)

        return None

    def get_or_create(self, email: str) -> UserAccount:
        email = email.lower().strip()

        with self._lock:
            data = self._read()

            for item in data.values():
                if item["email"].lower() == email:
                    return UserAccount(**item)

            user_id = secrets.token_urlsafe(18)
            account_id = f"recruiter-{secrets.token_hex(8)}"

            from datetime import datetime, timezone

            account = UserAccount(
                user_id=user_id,
                email=email,
                account_id=account_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            data[user_id] = asdict(account)
            self._write(data)

            return account

    def mark_linkedin_connected(self, user_id: str) -> None:
        with self._lock:
            data = self._read()

            if user_id not in data:
                raise KeyError(user_id)

            data[user_id]["linkedin_connected"] = True
            self._write(data)
