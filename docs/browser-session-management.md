# Browser session management

This document is an honest inventory of what exists today for browser
lifecycle and session health, per account. It does not describe aspirational
behavior — where something is not built, it says so.

## What exists

### Lifecycle (`browser/manager.py`, `BrowserManager`)

- **Lazy start.** The browser is not launched until the first operation
  needs a page. `launch_persistent_context` runs under a double-checked
  start lock, so concurrent callers within one process never race a double
  launch.
- **Reuse.** Once started, the same persistent context and profile are
  reused for every subsequent operation in that process; a fresh Playwright
  *page* is opened and closed per call, not per process.
- **Serialization.** All page operations serialize through one operation
  lock — only one browser action runs at a time per account.
- **Reactive restart.** There is no proactive health-check loop. A dead or
  broken context surfaces reactively: any `LinkedInMCPError` raised during
  navigation routes through `_handle_access_error`, and outright Playwright
  failures raise `BrowserUnavailableError` to the caller. `_reset_for_
  authentication` explicitly closes and re-starts the browser when
  re-authentication is required; there is no separate automatic "the
  process crashed, relaunch it" loop beyond that.
- **Safety guard.** Every navigation is checked by `guard.assert_safe_
  linkedin_page`, which detects checkpoint/authwall/login redirects and
  restriction banners and raises typed errors rather than attempting to
  click through them.

### Runtime process lifecycle (`application/shared_runtime.py`, `application/process_lock.py`)

- **One persistent runtime process per account.** A stdio MCP client (e.g. a
  Claude Desktop connection) spawns or attaches to one long-lived background
  `linkedin-mcp _runtime` process, elected via `AccountProcessLock` (a
  cross-platform advisory file lock keyed by that account's own
  `runtime.lock`).
- **Reuse across client connections.** If a healthy runtime is already
  running for that account, a new stdio connection attaches to it via a
  transparent stdio↔Streamable-HTTP proxy instead of spawning a second one.
  Ownership metadata (PID, version, config fingerprint, transport, endpoint)
  is published into the lock file, and a new connection validates against it
  before reusing an existing owner.
- **Graceful, signal-independent stop.** `linkedin-mcp stop` writes an
  instance-bound stop-request file rather than relying on POSIX signals,
  so shutdown works the same way on Windows and POSIX.
- **Crash recovery today = "start fresh."** If the persistent runtime
  process itself has actually died, its lock is released and the *next*
  `linkedin-mcp serve` naturally elects a fresh runtime and relaunches the
  browser against the same, unchanged persistent profile — no separate
  supervisor process watches for this and restarts it proactively.

### Authentication state (`domain/models.SessionAuthenticationState`, `auth/coordinator.py`)

States: `UNVERIFIED`, `LOGIN_REQUIRED`, `LOGIN_IN_PROGRESS`, `VALIDATING`,
`AUTHENTICATED`, `ATTENTION_REQUIRED`. `AuthenticationCoordinator.ensure_
ready()` blocks callers until a scheduled authentication check completes,
raising `AuthenticationRequiredError` if the account is not authenticated.
`request_reauthentication()` is the single trigger for "this account needs a
human to log in again" — invoked whenever `BrowserManager` sees an
`AuthenticationRequiredError`, or a restriction lands on an interactive-auth
path. Nothing in this path attempts to guess, resupply, or automate past a
credential prompt.

### Reporting

Two existing tools together cover the "session health" surface:

- `linkedin.session.status` — `account_id`, `profile_present`,
  `browser_setup_state`, `browser_started`, `authentication_state`,
  `automatic_login_enabled`, `login_browser_open`, `paused`, `pause_reason`,
  `status_message`, and (new) `account_label`/`account_created_at`/
  `account_last_authenticated_at`/`account_last_used_at`.
- `linkedin.server.status` — queue depth, connected/queued clients, whether
  a browser operation is currently active, which capability it is running.

`linkedin-mcp status` (CLI) reports the same information plus the runtime
owner's PID and endpoint, without starting anything.

## What this phase does not add

- No proactive polling health-check loop for the browser process (only
  reactive, error-triggered handling as described above).
- No automatic external supervisor that detects a crashed `_runtime` process
  and relaunches it — the existing "next `serve` call elects a fresh owner"
  behavior is the extent of "recovery" today.
- No stealth, fingerprint spoofing, CAPTCHA bypass, or anti-detection
  mechanism of any kind — out of scope by design, not an oversight.

Building a dedicated always-on supervisor (a small process whose only job is
to watch each account's runtime lock and `linkedin-mcp serve` it back up)
would be a natural, low-risk next step and was intentionally left out of this
phase to keep the change set reviewable; see
[backend-architecture.md](backend-architecture.md) for scope boundaries.
