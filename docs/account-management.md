# Account management

This document covers the local, non-secret account registry and its CLI.
For the design rationale (why process-per-account, what problem this solves),
see [backend-architecture.md](backend-architecture.md).

## Concepts

An **account** is identified by `account_id` (default `"personal"`), and maps
1:1 to an isolated, persistent Chromium profile and runtime lock:

```text
<data_root>/accounts/<account_id>/profile        # Chromium user-data-dir
<data_root>/accounts/<account_id>/runtime.lock    # singleton ownership
<data_root>/accounts/registry.json                # non-secret bookkeeping (this doc)
```

The **registry** (`accounts/registry.json`) is separate from both of the
above. It only tracks:

| Field | Meaning |
| --- | --- |
| `account_id` | Same identifier used for the profile/lock paths. |
| `label` | Optional human-readable name (e.g. a recruiter's name). |
| `created_at` | First time this account was registered. |
| `updated_at` | Last time any field on this record changed. |
| `last_authenticated_at` | Last time `account connect` completed a login. |
| `last_used_at` | Last time this account's MCP server started. |

It never contains credentials, cookies, session tokens, or anything read
from an authenticated page. Losing or corrupting this file loses convenience
bookkeeping only — it never affects whether an account can still log in or
use its existing browser profile.

`linkedin-mcp account list` also reports every profile directory found on
disk under `accounts/`, even one that predates the registry or was never
explicitly registered — so a real, working account is never silently hidden
just because its registry row is missing.

## CLI

```text
linkedin-mcp account list
linkedin-mcp account connect <account_id> [--label "Recruiter Name"]
linkedin-mcp account status <account_id>
linkedin-mcp account forget <account_id> [--yes]
```

### `account list`

Prints a JSON array, one entry per known account (registered or merely
present on disk):

```json
[
  {
    "account_id": "personal",
    "registered": true,
    "label": null,
    "created_at": "2026-09-04T12:38:00Z",
    "updated_at": "2026-09-07T10:08:00Z",
    "last_authenticated_at": null,
    "last_used_at": "2026-09-07T10:08:00Z",
    "profile_initialized": true,
    "runtime_running": true,
    "runtime_pid": 20468,
    "runtime_started_at": "2026-09-04T14:31:32+00:00",
    "runtime_endpoint": "http://127.0.0.1:8000/mcp"
  }
]
```

### `account connect <account_id>`

Onboarding for a new (or existing) recruiter account:

1. Registers `account_id` in the registry (idempotent — safe to re-run).
2. Opens LinkedIn in that account's own persistent, isolated Chromium
   profile, exactly like `linkedin-mcp login` — this **requires a real,
   interactive LinkedIn login**; nothing here bypasses or automates
   authentication.
3. On success, records `last_authenticated_at`.

This acquires that account's own runtime lock for the duration of the login,
so it cannot race a second `connect`/`login` against the *same* account_id.
It has no effect on any other account.

### `account status <account_id>`

Reports one account's registry + live status (same shape as one `account
list` entry). Raises a clear error — never a blank/successful-looking
report — if `account_id` has never been registered and has no profile or
runtime on disk.

### `account forget <account_id>`

Removes only the registry row. It requires either an interactive `FORGET`
confirmation or `--yes`. **It never deletes the browser profile or runtime
lock file** — those remain on disk, and the account can be re-registered
(`account connect`) and continue using the same, already-authenticated
profile.

## In the MCP tool surface

Per-recruiter registry metadata (`label`, `created_at`,
`last_authenticated_at`, `last_used_at`) is also exposed through the existing
`linkedin.session.status` tool — scoped only to the account that server
process is already running as. There is deliberately **no** MCP tool that
lists or manages accounts other than the caller's own — cross-account
listing is CLI/ops-only, so one recruiter's Claude session can never observe
another recruiter's accounts.
