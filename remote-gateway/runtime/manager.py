from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from config import get_settings
from identity.store import IdentityStore


@dataclass
class RuntimeProcess:
    user_id: str
    account_id: str
    port: int
    process: asyncio.subprocess.Process
    started_at: float


class RuntimeManager:
    """
    Owns one LinkedIn MCP runtime per authenticated user/account.

    Each runtime receives:
      - its own account_id
      - its own browser profile
      - its own runtime lock
      - its own HTTP port
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._runtimes: dict[str, RuntimeProcess] = {}
        self._lock = asyncio.Lock()

    def _identity_store(self) -> IdentityStore:
        return IdentityStore(self.settings.data_dir)

    def account_for_user(self, user_id: str):
        account = self._identity_store().get_by_user_id(user_id)

        if account is None:
            raise RuntimeError(
                "Authenticated user is not registered."
            )

        return account

    def _account_root(self, account_id: str) -> Path:
        root = (
            Path(self.settings.data_dir)
            / "accounts"
            / account_id
        )

        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        return root

    def _port_for_account(self, account_id: str) -> int:
        """
        Derive a stable runtime port from the account ID.
        """

        digest = hashlib.sha256(
            account_id.encode("utf-8")
        ).digest()

        offset = (
            int.from_bytes(
                digest[:4],
                "big",
            )
            % 1000
        )

        return (
            self.settings.runtime_base_port
            + offset
        )

    def _runtime_environment(
        self,
        *,
        account_id: str,
        port: int,
    ) -> dict[str, str]:
        account_root = self._account_root(
            account_id
        )

        profile_path = account_root / "profile"
        lock_path = account_root / "runtime.lock"
        asset_path = account_root / "assets"

        profile_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        asset_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        environment = os.environ.copy()

        environment.update(
            {
                "LINKEDIN_MCP_ACCOUNT_ID": account_id,
                "LINKEDIN_MCP_BROWSER_PROFILE_PATH": str(
                    profile_path
                ),
                "LINKEDIN_MCP_RUNTIME_LOCK_PATH": str(
                    lock_path
                ),
                "LINKEDIN_MCP_ASSET_ROOT_PATH": str(
                    asset_path
                ),
                "LINKEDIN_MCP_TRANSPORT": "streamable-http",
                "LINKEDIN_MCP_HTTP_HOST": "127.0.0.1",
                "LINKEDIN_MCP_HTTP_PORT": str(port),
                "LINKEDIN_MCP_BROWSER_HEADLESS": "true",
                "LINKEDIN_MCP_BROWSER_AUTO_INSTALL": "false",
                "LINKEDIN_MCP_AUTO_LOGIN_ON_START": "false",
            }
        )

        return environment

    async def _wait_until_ready(
        self,
        port: int,
        process: asyncio.subprocess.Process,
    ) -> None:
        deadline = (
            time.monotonic()
            + self.settings.runtime_start_timeout_seconds
        )

        url = f"http://127.0.0.1:{port}/"

        while time.monotonic() < deadline:
            if process.returncode is not None:
                raise RuntimeError(
                    "LinkedIn MCP runtime exited before becoming ready "
                    f"(exit code {process.returncode})."
                )

            try:
                async with httpx.AsyncClient(
                    timeout=1.5
                ) as client:
                    response = await client.get(url)

                if response.status_code < 500:
                    return

            except Exception:
                pass

            await asyncio.sleep(0.25)

        raise RuntimeError(
            "LinkedIn MCP runtime did not become ready "
            f"on port {port} within "
            f"{self.settings.runtime_start_timeout_seconds} seconds."
        )

    async def get_or_start(
        self,
        user_id: str,
    ) -> RuntimeProcess:
        account = self.account_for_user(user_id)

        async with self._lock:
            existing = self._runtimes.get(user_id)

            if existing is not None:
                if existing.process.returncode is None:
                    return existing

                self._runtimes.pop(
                    user_id,
                    None,
                )

            port = self._port_for_account(
                account.account_id
            )

            for runtime in self._runtimes.values():
                if (
                    runtime.port == port
                    and runtime.process.returncode is None
                ):
                    raise RuntimeError(
                        "Runtime port collision detected for "
                        f"account {account.account_id}."
                    )

            environment = self._runtime_environment(
                account_id=account.account_id,
                port=port,
            )

            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "linkedin_mcp",
                "_runtime",
                cwd="/app",
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )

            runtime = RuntimeProcess(
                user_id=user_id,
                account_id=account.account_id,
                port=port,
                process=process,
                started_at=time.time(),
            )

            self._runtimes[user_id] = runtime

        try:
            await self._wait_until_ready(
                port,
                process,
            )

            return runtime

        except Exception:
            await self.stop(user_id)
            raise

    async def stop(
        self,
        user_id: str,
    ) -> None:
        async with self._lock:
            runtime = self._runtimes.pop(
                user_id,
                None,
            )

        if runtime is None:
            return

        process = runtime.process

        if process.returncode is not None:
            return

        try:
            os.killpg(
                process.pid,
                signal.SIGTERM,
            )
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=10,
            )

        except asyncio.TimeoutError:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )
            except ProcessLookupError:
                pass

            await process.wait()

    async def stop_all(self) -> None:
        users = list(
            self._runtimes.keys()
        )

        for user_id in users:
            await self.stop(user_id)

    async def upstream_url(
        self,
        user_id: str,
    ) -> str:
        runtime = await self.get_or_start(
            user_id
        )

        return (
            f"http://127.0.0.1:{runtime.port}/mcp"
        )

    async def status_for_user(
        self,
        user_id: str,
    ) -> dict[str, object]:
        async with self._lock:
            runtime = self._runtimes.get(
                user_id
            )

        if runtime is None:
            return {
                "running": False,
                "port": None,
                "pid": None,
                "started_at": None,
                "endpoint": None,
            }

        return {
            "running": runtime.process.returncode is None,
            "port": runtime.port,
            "pid": runtime.process.pid,
            "started_at": runtime.started_at,
            "endpoint": (
                f"http://127.0.0.1:{runtime.port}/mcp"
            ),
        }

    async def status(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []

        async with self._lock:
            runtimes = list(
                self._runtimes.values()
            )

        for runtime in runtimes:
            result.append(
                {
                    "user_id": runtime.user_id,
                    "account_id": runtime.account_id,
                    "port": runtime.port,
                    "pid": runtime.process.pid,
                    "running": (
                        runtime.process.returncode
                        is None
                    ),
                    "started_at": runtime.started_at,
                    "endpoint": (
                        f"http://127.0.0.1:{runtime.port}/mcp"
                    ),
                }
            )

        return result


_runtime_manager: RuntimeManager | None = None


def get_runtime_manager() -> RuntimeManager:
    global _runtime_manager

    if _runtime_manager is None:
        _runtime_manager = RuntimeManager()

    return _runtime_manager
