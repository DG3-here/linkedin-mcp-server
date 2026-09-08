# Local development

This is a short index for working on this repository day-to-day. It does not
repeat [TESTING.md](TESTING.md) or [CONFIGURATION.md](CONFIGURATION.md) —
read those first for the full test-layer breakdown and environment variables.

## Setup

```bash
uv sync
uv run linkedin-mcp setup        # installs the managed Playwright Chromium runtime
```

## Everyday loop

```bash
uv run ruff check .
uv run pyright
uv run pytest -q
```

The full suite is offline by design (`tests/conftest.py` blocks external
network access for the whole run) and must never touch your real,
already-authenticated local LinkedIn profile or account registry. A second
`conftest.py` guard specifically forbids any test from resolving the account
registry to the real per-user data directory — if you see
`AssertionError: A test attempted to write the LinkedIn account registry to
the real local data directory`, a new test is missing its `tmp_path`
sandboxing (see any test in `tests/unit/accounts/` for the pattern: patch
`linkedin_mcp.config.user_data_path` before constructing `Settings` or
`LinkedInAccountManager`).

## Working with multiple local accounts during development

You do not need multiple machines or containers to exercise multi-account
behavior locally:

```bash
uv run linkedin-mcp account connect dev_recruiter_a --label "Dev A"
uv run linkedin-mcp account connect dev_recruiter_b --label "Dev B"
uv run linkedin-mcp account list
LINKEDIN_MCP_ACCOUNT_ID=dev_recruiter_a uv run linkedin-mcp serve
```

Each `account_id` gets its own isolated profile directory and runtime lock
under `<data_root>/accounts/<account_id>/` — see
[account-management.md](account-management.md). `account connect` opens a
real, interactive LinkedIn login for that profile; use a real or disposable
test LinkedIn account, never your primary one, for local multi-account
experiments.

## Where things live

See the "Code layout" table in [ARCHITECTURE.md](ARCHITECTURE.md) for the
request-handling layers, and [backend-architecture.md](backend-architecture.md)
for the account/process model this document builds on.

## Future: HR Dashboard / HTTP API

No authenticated HTTP API for a dashboard exists yet. If one is added, it
should call into service-level operations (account status, campaign status,
audit log reads) rather than reaching into `BrowserManager`/Playwright
directly — see the "not yet built" framing in
[campaigns.md](campaigns.md) and the process-per-account design in
[backend-architecture.md](backend-architecture.md), which keeps a future
dashboard from ever needing direct access to browser internals for any
single account.
