# CMDownloaderUI

Read-only operator dashboard for CMDownloader.

The viewer is intentionally separated from the downloader:

- **CMDownloader** owns ClickMeeting API credentials, downloads, verification, deletion and writes operational state.
- **CMDownloaderUI** only reads the shared SQLite database and exposes a Bootstrap + HTMX dashboard.
- The UI has no ClickMeeting API key and no write actions.

## MVP scope

- `Requires attention` queue pinned above history.
- Current download state with progress, speed and last update.
- Append-only operational history.
- HTMX live search by `recording_name` only.
- Account dropdown filter.
- Recording-date filter interpreted in `Europe/Warsaw` while timestamps are stored in UTC.
- Read-only SQLite access through SQLAlchemy.
- Bootstrap UI.
- Docker image and Compose example with the database mounted read-only.

## Data model

The first schema contains four tables:

- `accounts` — configured ClickMeeting accounts without API credentials.
- `recordings` — one row per ClickMeeting recording and its current operational state.
- `events` — append-only significant history events.
- `runtime_state` — current downloader activity/progress; MVP uses row `id=1`.

Important recording states include:

- `DOWNLOADING`
- `COMPLETED`
- `DELETE_FAILED`
- `RETRYABLE_ERROR`
- `QUARANTINED`
- `RESOLVED_EXTERNALLY`
- `COMPLETED_MANUAL_DELETE`

`attention_required=true` is deliberately separate from `status`. `QUARANTINED` and `DELETE_FAILED` are expected to require operator attention. When reconciliation later detects that a problematic recording disappeared from ClickMeeting, the downloader can clear the attention flag and append an event such as `RESOLVED_EXTERNALLY` or `COMPLETED_MANUAL_DELETE`.

## Quick start with demo data

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python seed_demo.py
DATABASE_PATH=state/cm_downloader.db flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

The application opens SQLite in **read-only mode**. `seed_demo.py` is a development helper that creates/replaces only the demo database path.

## Docker

Create demo data first:

```bash
python seed_demo.py
docker compose up --build
```

Open `http://127.0.0.1:8080`.

Compose mounts `./state` as `/state:ro`, runs the container with a read-only root filesystem and drops Linux capabilities. In production, point the mount at the state directory written by CMDownloader.

## Filters

The dashboard query string is bookmarkable, for example:

```text
/?q=webinar&account=2&date=2026-08-24
```

- `q` searches only `recording_name`.
- `account` is the local `accounts.id`.
- `date` is the recording calendar date in `Europe/Warsaw`.

Filtering never changes the global `Requires attention` count. When filters hide problems, the UI shows both the total and the number currently displayed.

## Integration contract for CMDownloader

CMDownloader will become the single writer of this database. It should:

1. upsert accounts and recordings discovered from ClickMeeting,
2. update `runtime_state` while a download is active,
3. set `attention_required=true` for failures requiring manual action,
4. avoid automatic redownload of quarantined recordings,
5. retry only the appropriate operation for `DELETE_FAILED`,
6. reconcile local problem rows against the current ClickMeeting recording list,
7. append significant events to `events` rather than writing progress events there.

The UI never resolves, retries, deletes or changes an operational record.
