# CMDownloaderUI

Read-only operator dashboard for CMDownloader.

The viewer is intentionally separated from the downloader:

- **CMDownloader** owns ClickMeeting API credentials, downloads, verification, deletion and writes operational state.
- **CMDownloaderUI** only reads the shared SQLite database and exposes a Bootstrap + HTMX dashboard.
- The UI has no ClickMeeting API key, no recordings mount and no write actions.

## MVP scope

- Downloader scheduler health: `RUNNING`, `WAITING` or derived `OFFLINE` when the heartbeat becomes stale.
- Last run, current run, next scheduled run and run duration.
- Multiple parallel download workers with per-recording progress and speed.
- `Requires attention` operator queue pinned above history and never affected by history filters.
- Append-only operational history.
- HTMX live search by `recording_name` only.
- Account dropdown filter.
- Recording-date filter interpreted in `Europe/Warsaw` while timestamps are stored in UTC.
- Read-only SQLite access through SQLAlchemy.
- Bootstrap dark-mode UI.
- Docker image and Compose example with the database mounted read-only.

## Data model

The current schema contains six tables:

- `accounts` — configured ClickMeeting accounts without API credentials.
- `recordings` — one row per ClickMeeting recording and its current operational state.
- `events` — append-only significant recording history.
- `runs` — downloader execution history and run result counters.
- `scheduler_state` — singleton scheduler heartbeat, current state, interval and next run time.
- `runtime_workers` — current worker slots and live progress for zero or more parallel downloads.

Important recording states include:

- `DOWNLOADING`
- `COMPLETED`
- `DELETE_FAILED`
- `RETRYABLE_ERROR`
- `QUARANTINED`
- `RESOLVED_EXTERNALLY`
- `COMPLETED_MANUAL_DELETE`

`attention_required=true` is deliberately separate from `status`. `QUARANTINED` and `DELETE_FAILED` are expected to require operator attention. When reconciliation later detects that a problematic recording disappeared from ClickMeeting, the downloader can clear the attention flag and append an event such as `RESOLVED_EXTERNALLY` or `COMPLETED_MANUAL_DELETE`.

The viewer derives `OFFLINE` when `scheduler_state.heartbeat_at` is older than `HEARTBEAT_STALE_SECONDS` (120 seconds by default). This allows the UI to distinguish a healthy process waiting for the next cycle from a downloader that stopped unexpectedly.

## Quick start with demo data

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed_demo.py
DATABASE_PATH=state/cm_downloader.db flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

The application opens SQLite in **read-only mode**. `seed_demo.py` is a development helper that creates/replaces only the demo database path. The seed includes five accounts, unresolved attention items, run history and three parallel active workers.

## Docker

Create demo data first:

```bash
python seed_demo.py
docker compose up --build
```

Open `http://127.0.0.1:8080`.

Compose mounts `./state` as `/state:ro`, runs the container with a read-only root filesystem and drops Linux capabilities. In production, point the mount at the state directory written by CMDownloader.

## History filters

The history query string is bookmarkable, for example:

```text
/?q=webinar&account=2&date=2026-08-24
```

- `q` searches only `recording_name`.
- `account` is the local `accounts.id`.
- `date` is the recording calendar date in `Europe/Warsaw`.

Filters apply **only to History**. `Requires attention` remains a complete operator work queue regardless of the current history filter.

## Integration contract for CMDownloader

CMDownloader will become the single writer of this database. The intended runtime model is one long-lived downloader process with a controlled worker pool.

It should:

1. hold a process-level lock so a second downloader instance cannot run against the same state directory,
2. maintain the scheduler heartbeat while running and while waiting,
3. start the next cycle after the configured interval measured from the end of the previous cycle,
4. append a `runs` row for each cycle and finish it with result counters,
5. expose active downloads in `runtime_workers` without fixing the UI to a specific worker count,
6. upsert accounts and recordings discovered from ClickMeeting,
7. set `attention_required=true` for failures requiring manual action,
8. avoid automatic redownload of quarantined recordings,
9. retry only the appropriate operation for `DELETE_FAILED`,
10. reconcile local problem rows against the current ClickMeeting recording list,
11. append significant events to `events` rather than writing progress events there.

The UI never starts, resolves, retries, deletes or changes an operational record.
