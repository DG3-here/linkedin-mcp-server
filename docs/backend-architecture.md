# Backend architecture: from one account to many

This document covers two things: what already existed in this repository
before multi-account work started, and the target architecture chosen for
letting one deployment serve several recruiters' LinkedIn accounts. For the
low-level, single-process request lifecycle (scheduler, executor, evidence,
browser safety), see [ARCHITECTURE.md](ARCHITECTURE.md), which this document
does not repeat.

## 1. What already existed (inspected before anything changed)

The server is more mature than "a single-account MCP tool wrapper." Before any
multi-account work, the codebase already had:

- **Per-process, per-account isolation.** `Settings.account_id` (default
  `"personal"`) derives an isolated profile directory and runtime lock file:
  `<data_root>/accounts/<account_id>/profile` and
  `<data_root>/accounts/<account_id>/runtime.lock`. Two different
  `account_id` values never share a browser profile or a lock file. This
  isolation was added on this branch (commits `8d1164f`, `8453eec`) but the
  *isolation model itself* (one account = one process/profile/lock) predates
  this document.
- **A cross-platform singleton lock per account**
  (`application/process_lock.py`, `AccountProcessLock`): advisory file
  locking (POSIX `flock`, Windows byte-range lock) that publishes non-secret
  owner metadata (PID, transport, endpoint, version, config fingerprint) into
  the lock file itself, and supports a graceful, signal-independent stop
  protocol. This is what "prevent two workers from operating the same account
  concurrently" already means in this codebase.
- **A shared runtime with election and reuse**
  (`application/shared_runtime.py`): a stdio MCP client spawns or attaches to
  one long-lived background process per account (`linkedin-mcp _runtime`,
  loopback Streamable HTTP). If a healthy owner already exists, it is reused;
  if not, a new one is elected and spawned. This is most of "browser lifecycle
  management" already built, scoped to one account at a time.
- **A single in-process worker/executor/scheduler** (`application/`):
  `CapabilityWorker` serializes every browser-backed call through one lane,
  `CapabilityExecutor` runs capabilities against typed provider protocols with
  idempotent call replay, `FairClientScheduler` gives per-client fairness.
  All of this state is **ephemeral** (in-memory, bound to one process
  lifetime) — there is no persistent job queue, campaign, or audit log
  anywhere in the codebase.
- **A browser-side authentication state machine**
  (`domain/models.SessionAuthenticationState`,
  `auth/coordinator.AuthenticationCoordinator`): `UNVERIFIED`,
  `LOGIN_REQUIRED`, `LOGIN_IN_PROGRESS`, `VALIDATING`, `AUTHENTICATED`,
  `ATTENTION_REQUIRED`. `BrowserManager` routes navigation/authentication
  failures into `request_reauthentication()`; nothing here ever attempts to
  guess or resupply credentials.
- **26 MCP tools** covering jobs, people, companies, posts, invitations,
  connections, messaging, server/session/capability status — see
  [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md).
- An **optional, partially-wired Unipile provider** (`Settings.provider`,
  default `"browser"`) for people-search only. This project's direction is
  Browser Provider only; Unipile is out of scope and is not extended further
  by this work. (A separate, unrelated in-progress branch of work had begun
  building a Unipile-hosted-auth *account* model — `owner_id` →
  `unipile_account_id` — directly in conflict with "Browser Provider is the
  only production direction." That work was uncommitted and was removed
  rather than built upon; see the account manager design below for what
  replaced it.)

What did **not** exist: any concept of multiple accounts being tracked,
labeled, or reported on together; any persistent registry of "which LinkedIn
accounts has this machine ever connected"; and any CLI/tool surface for
onboarding a *new* account without hand-rolling environment variables.

## 2. The multi-account fork in the road

The requested end state is one MCP service fronting several recruiter
accounts. There are two structurally different ways to get there:

- **(A) Process-per-account + a thin manager.** Keep today's model —one
  persistent runtime process per account, isolated profile/lock, already
  mature and tested. Add a small, separate `LinkedInAccountManager` that
  tracks known accounts and can register/inspect them, reusing the existing
  spawn/lock/status primitives. Each recruiter's Claude/dashboard talks to
  that recruiter's own account/endpoint.
- **(B) Single shared process, per-call account routing.** One MCP endpoint
  for everyone; every tool call carries an `account_id` and is routed
  in-process to a pool of per-account browser sessions/queues. This matches
  the "one MCP Service box" reading of the target diagram literally, but
  requires rearchitecting `BrowserManager`, `CapabilityExecutor`,
  `CapabilityWorker`, and every tool's signature to become
  account-parameterized, plus in-process per-account resource limits.

**Chosen: (A).** It reuses mature, tested infrastructure instead of touching
the execution core that 26 tools and 500+ tests already depend on, and it
avoids a new cross-tenant attack surface (a shared in-process pool serving
every recruiter through one endpoint is a much larger blast radius for a
mistake than N isolated processes). This also resolves a subtler
correctness question for free: under (A), "list other accounts" is naturally
an *operator/ops* concern (a human running the CLI to provision recruiters),
never something exposed inside one recruiter's own MCP tool surface — so
there is no risk of recruiter A's Claude session enumerating recruiter B's
accounts.

## 3. What this phase adds

```text
                    Recruiter
                        │
                        ▼
                Claude / HR Dashboard
                        │
                        ▼
       one MCP endpoint per connected account
    (unchanged: stdio bridge → shared runtime,
     see ARCHITECTURE.md)
                        │
             ┌──────────┼──────────┐
             │          │          │
        Account A   Account B   Account C
     profile+lock  profile+lock  profile+lock
     (already isolated by account_id, pre-existing)

Ops-only, cross-account layer (new, this phase):

  linkedin-mcp account connect/list/status/forget
                        │
                        ▼
              LinkedInAccountManager
                        │
                        ▼
      accounts/registry.json  (non-secret: label,
      created_at, updated_at, last_authenticated_at,
      last_used_at - never credentials/cookies/tokens)
                        │
        reads existing, unmodified primitives:
      inspect_account_runtime() · BrowserProfileManager
```

New module: `src/linkedin_mcp/accounts/`

- `models.py` — `AccountRecord` (registry row) and `AccountSummary` (registry
  row merged with live, non-secret runtime/profile status).
- `store.py` — `AccountRegistryStore`: atomic (`temp file + os.replace`),
  `0o600`-permissioned JSON persistence for the registry. Fails closed on a
  corrupted file rather than silently discarding it.
- `manager.py` — `LinkedInAccountManager`: `register`, `forget`,
  `record_authenticated`, `record_used`, `get`, `list`. Every "live" field it
  reports is computed by calling the pre-existing
  `inspect_account_runtime()` and `BrowserProfileManager.inspect()` — it never
  starts a browser, never reads profile/session contents, and never invents
  new locking (an account's own runtime lock, acquired via the existing
  `AccountProcessLock`/`_run_owned_operation`, already prevents two `connect`
  attempts against the same account from racing).

Wiring:

- `AppContainer` gets an `account_manager` field (default-constructed, so
  every existing call site — production and test — keeps working unchanged).
  On `start()`, it best-effort registers the running `account_id` and touches
  `last_used_at`; failures here are swallowed (`with suppress(Exception)`)
  because registry bookkeeping must never be able to block the real MCP
  server from starting.
- `linkedin.session.status` (existing tool, enriched, not replaced) now also
  returns `account_label`, `account_created_at`,
  `account_last_authenticated_at`, `account_last_used_at` — for **this**
  process's own account only, so there is no cross-tenant exposure.
- New CLI surface (`linkedin-mcp account ...`) — see
  [account-management.md](account-management.md).

## 4. What this phase deliberately does not build

The full spec this work responds to also asks for a persistent job queue,
campaigns, duplicate/eligibility protection, an audit log, and an HTTP API
for a future HR dashboard. None of those are implemented in this phase. They
are each a substantial, independently testable subsystem (a durable queue
alone touches persistence, worker recovery, and idempotency semantics that
took real care to get right even for the *existing*, ephemeral executor), and
bolting them on quickly alongside a core account-model change would risk
shipping all of it undertested. See the "not yet built" sections of
[campaigns.md](campaigns.md) for the proposed design and how it would build
on the primitives above without touching them.

## 5. Safety notes specific to this phase

- The account registry never stores credentials, cookies, or session tokens
  — only `account_id`, an optional label, and four timestamps.
- Registering an account does not create or touch its browser profile;
  `account connect` still requires a real interactive LinkedIn login the
  first time, exactly like the pre-existing `linkedin-mcp login` command.
- `account forget` removes only the registry row. It never deletes a profile
  directory or lock file — that remains an explicit, separate operation
  (`linkedin-mcp profile reset`), unchanged by this work.
- The full test suite must never write to the real per-user data directory.
  `tests/conftest.py` enforces this as a hard, permanent guard (parallel to
  the existing `block_external_network` guard): `AccountRegistryStore.save`
  is wrapped to raise if a test ever resolves to the genuine platform data
  root, captured once at collection time before any test can monkeypatch
  `user_data_path`.
