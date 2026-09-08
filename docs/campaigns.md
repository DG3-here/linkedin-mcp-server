# Campaigns, job queue, and audit log — proposed design (not yet built)

**Status: not implemented.** This document exists so the intended design is
written down, and so it is obvious what is proposed versus what actually
exists in the codebase today. Nothing in this file should be read as a
description of current behavior — see [backend-architecture.md](backend-architecture.md)
for what is actually built.

## Why this was not built alongside the account manager

A durable job queue, a campaign state machine, duplicate/eligibility
protection, and an audit log are each a real subsystem with their own
correctness surface — worker crash-recovery semantics, idempotent retries,
and a persistence format that has to survive a process restart mid-campaign.
The existing executor already invests real care in exactly these problems for
*single, ephemeral* calls (idempotent call replay keyed by
`account_id + client_id + capability + request_id`, `ActionResult` with
`verified | failed | uncertain` outcomes). Extending that correctness to a
durable, multi-step queue is worth its own focused implementation and test
pass, not a rushed addition alongside a core account-model change.

## Proposed shape

```text
Campaign (draft → review → queued → running → paused/completed/failed/cancelled)
    │  message template, target account_id, candidate list
    ▼
Job queue (persistent — survives process restart)
    │  one row per (campaign_id, candidate, action)
    ▼
Worker (per account — reuses the existing CapabilityWorker's
        "one browser operation at a time" serialization)
    │
    ▼
Eligibility check (before executing)
    │  already_connected / invitation_pending / connect_unavailable /
    │  messaging_unavailable / authentication_required / profile_not_found
    │  → skip with a typed reason, never retried
    ▼
One LinkedIn action via the existing executor/capability path
    │  (reuses ActionResult: verified / failed / uncertain)
    ▼
Persist result + audit event
    │
    ▼
Next job
```

### Job record (proposed)

```text
job_id, campaign_id, account_id, candidate_reference, action, payload,
status (queued|running|completed|failed|skipped|paused|cancelled),
attempt_count, created_at, started_at, completed_at, result, error,
verification_state
```

### Why "one job queue per account," not one global queue

Each account already has its own serialized `CapabilityWorker` and its own
runtime process (see [backend-architecture.md](backend-architecture.md)). A
campaign queue should live and recover *within that same account's runtime*,
not as a separate global service — otherwise a campaign for Account A could
end up competing with, or worse, executing against, Account B's browser.

### Persistence

The existing `persistence/` layer (`MemoryRepository`) is intentionally
process-local and ephemeral — it is not a queue and should not be stretched
into one. A campaign queue needs its own on-disk store (e.g. one SQLite file
per account, or an append-only JSON-lines log with a compaction pass),
written with the same "atomic write, fail closed on corruption" discipline
already used by the account registry (`accounts/store.py`).

### Crash/restart recovery

On startup, before accepting new work: load the account's job queue, find
any job left `running` from a previous process (it was interrupted, not
necessarily failed), and requeue it as `queued` for re-attempt — mirroring
how `ActionOutcome.uncertain` already models "we don't know if the write
actually landed" for a single action today. A job must never be silently
dropped, and it must never be silently marked `completed` without a verified
postcondition (reusing `ActionResult`'s `verified | failed | uncertain`
distinction).

### Duplicate / eligibility protection

Checked immediately before executing a job, using the same page objects
that already detect these states live (e.g.
`InvitationActionPage`/`ConnectionsListPage` already surface
"not eligible for a new invitation" from the visible page). A campaign layer
should read that live signal rather than maintain its own separate,
potentially stale eligibility ledger.

### Audit log

One append-only, non-secret event per action attempt:
`timestamp, account_id, campaign_id, candidate_reference, action, status,
verification, error`. Never logs passwords, cookies, or session tokens —
same constraint the account registry already follows.

### MCP tools (proposed, not added)

`linkedin.campaign.create`, `.start`, `.pause`, `.resume`, `.status`,
`.cancel` — each delegating to the persistent queue above, never executing
actions directly from the tool handler. No tool should accept "send N
invitations right now" as a single synchronous call.
