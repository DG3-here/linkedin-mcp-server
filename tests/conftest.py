from __future__ import annotations

import ipaddress
import socket
from collections.abc import Generator
from typing import Any, cast

import pytest

from linkedin_mcp.accounts.store import AccountRegistryStore
from linkedin_mcp.config import default_data_path

# Captured once, at collection time, before any test can monkeypatch `user_data_path` -
# this must stay the genuine platform data root, never a value a test could control.
_REAL_LOCAL_DATA_ROOT = default_data_path()
_real_account_registry_save = AccountRegistryStore.save


def _forbid_writes_under_the_real_local_data_root(
    self: AccountRegistryStore, records: dict[str, Any]
) -> None:
    """Fail loudly if a test ever resolves the account registry to the real data root.

    Every test must construct `Settings`/`LinkedInAccountManager` with paths rooted
    under a fixture-provided `tmp_path` (directly, or by patching `user_data_path`).
    This is a last-resort backstop, not a substitute for that sandboxing.
    """
    if self.path == _REAL_LOCAL_DATA_ROOT or _REAL_LOCAL_DATA_ROOT in self.path.parents:
        raise AssertionError(
            f"A test attempted to write the LinkedIn account registry to the real "
            f"local data directory: {self.path}. Sandbox `user_data_path` or pass an "
            f"explicit tmp_path-rooted store instead."
        )
    _real_account_registry_save(self, records)


AccountRegistryStore.save = _forbid_writes_under_the_real_local_data_root  # type: ignore[method-assign]


def is_permitted_test_address(address: object) -> bool:
    """Allow local IPC and loopback sockets while rejecting external test traffic."""

    if isinstance(address, (str, bytes)):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    parts = cast(tuple[object, ...], address)
    host = parts[0]
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    if not isinstance(host, str):
        return False
    normalized = host.strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Keep the complete test suite offline."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(instance: socket.socket, address: Any) -> None:
        if not is_permitted_test_address(address):
            raise AssertionError(f"External network access is forbidden in tests: {address!r}")
        original_connect(instance, address)

    def guarded_connect_ex(instance: socket.socket, address: Any) -> int:
        if not is_permitted_test_address(address):
            raise AssertionError(f"External network access is forbidden in tests: {address!r}")
        return original_connect_ex(instance, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
