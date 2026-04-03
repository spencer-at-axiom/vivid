# Queue State Machine (V1)

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Last updated: 2026-04-01

Primary implementation:
- [`services/inference/vivid_inference/state.py`](../services/inference/vivid_inference/state.py)

## Status Set

Runtime job statuses:
- `queued`
- `recovered`
- `running`
- `cancel_requested`
- `completed`
- `failed`
- `cancelled`

## Allowed Transitions

Defined in code via `_ALLOWED_JOB_TRANSITIONS` and exposed by `allowed_job_transitions()`.

| From | Allowed To |
| --- | --- |
| `queued` | `running`, `cancelled` |
| `recovered` | `running`, `cancelled` |
| `running` | `completed`, `failed`, `cancel_requested`, `cancelled` |
| `cancel_requested` | `failed`, `cancelled` |
| `completed` | none |
| `failed` | none |
| `cancelled` | none |

Transition enforcement:
- `_transition_job_status(...)` raises on invalid transitions.

## Restart Recovery Rules

Applied when loading persisted jobs at startup (`_load_jobs_from_db` -> `_recover_job_after_restart`):

| Persisted Status | Restart Result | Queue Action |
| --- | --- | --- |
| `running` | `failed` with restart error reason | not queued |
| `cancel_requested` | `failed` with restart error reason | not queued |
| `queued` | `recovered` | rehydrated into queue order |
| `paused` (legacy persisted value) | `recovered` | rehydrated into queue order |
| `recovered` | `recovered` | rehydrated into queue order |
| `completed` / `failed` / `cancelled` | unchanged terminal | not queued |
| unknown/invalid | `failed` with explicit recovery error reason | not queued |

## Queue Ordering on Recovery

- Persisted query order is `queue_position ASC, created_at ASC`.
- Recovered pending jobs are reloaded into `_queue_order` in persisted order.
- `_persist_queue_positions()` rewrites queue positions for:
  - pending/running jobs first
  - terminal jobs after active queue to preserve deterministic replay ordering.

## Invariants

- At most one running job (`_running_job_id`) is active.
- Only `queued`/`recovered` statuses are considered pending for scheduling.
- Queue state API (`/jobs/queue/state`) reports:
  - `paused`
  - `running_job_id`
  - `running_status`
  - `queued_job_ids` (pending only)
  - `queued_count`
  - `active_job` (running summary for UI)
  - `progress_contract_version` (current: `v1`)

## Progress and ETA Contract (`v1`)

Job payload fields:
- `progress`: normalized to `[0.0, 1.0]`
- `progress_state`: `queued`, `running`, `finalizing`, `cancelling`, `terminal`
- `eta_confidence`: `none`, `low`, `high`
- `eta_seconds`: only surfaced when confidence is `high`

Rules:
- `queued`/`recovered`: `progress_state=queued`, `eta_confidence=low`, `eta_seconds=null`
- `running`: `progress_state=running` or `finalizing` (>= 0.9 progress)
- `cancel_requested`: `progress_state=cancelling`, ETA hidden
- terminal states: `progress_state=terminal`, ETA hidden, `completed` forces `progress=1.0`

Frontend contract:
- ETA must be rendered only when `eta_confidence=high` and `eta_seconds>0`.
- `cancel_requested` must be visually distinct from `cancelled`.

## SQLite Durability and Queue Maintenance

Primary implementation:
- [`services/inference/vivid_inference/db.py`](../services/inference/vivid_inference/db.py)

Runtime defaults:
- `PRAGMA journal_mode=WAL`
- `PRAGMA synchronous=NORMAL`
- `PRAGMA busy_timeout=5000`
- `PRAGMA wal_autocheckpoint=1000`

Queue maintenance behavior:
- `clear_queue(...)` runs `PRAGMA wal_checkpoint(PASSIVE)` and returns maintenance details:
  - `busy`
  - `log_frames`
  - `checkpointed_frames`
  - `mode`
- Queue/database write paths use retry-on-`SQLITE_BUSY` behavior (`execute_with_retry`).
