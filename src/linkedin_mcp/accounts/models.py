"""Non-secret local metadata describing configured LinkedIn accounts."""

from __future__ import annotations

from datetime import datetime

from pydantic import field_validator

from linkedin_mcp.config import validate_account_id_value
from linkedin_mcp.domain.models import StrictModel


class AccountRecord(StrictModel):
    """Registry bookkeeping for one locally configured LinkedIn account.

    Never stores credentials, cookies, or session tokens - only when the
    account was created, an optional recruiter-facing label, and when it was
    last authenticated or used. The persistent browser profile itself is
    tracked separately by `account_id` on disk, not by this record.
    """

    account_id: str
    label: str | None = None
    created_at: datetime
    updated_at: datetime
    last_authenticated_at: datetime | None = None
    last_used_at: datetime | None = None

    @field_validator("account_id")
    @classmethod
    def _validate_account_id(cls, value: str) -> str:
        return validate_account_id_value(value)


class AccountSummary(StrictModel):
    """Registry metadata merged with live, non-secret runtime/profile state."""

    account_id: str
    registered: bool
    label: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_authenticated_at: datetime | None = None
    last_used_at: datetime | None = None
    profile_initialized: bool
    runtime_running: bool
    runtime_pid: int | None = None
    runtime_started_at: str | None = None
    runtime_endpoint: str | None = None
