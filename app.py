from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import Flask, Response, render_template, request
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from models import Account, Event, Recording, Run, RuntimeWorker, SchedulerState


WARSAW = ZoneInfo("Europe/Warsaw")
HISTORY_LIMIT = 100
HEARTBEAT_STALE_SECONDS = int(os.getenv("HEARTBEAT_STALE_SECONDS", "120"))

app = Flask(__name__)


def build_database_url() -> str:
    database_path = Path(os.getenv("DATABASE_PATH", "state/cm_downloader.db")).resolve()
    encoded_path = quote(str(database_path), safe="/:")
    return f"sqlite+pysqlite:///file:{encoded_path}?mode=ro&uri=true"


engine = create_engine(build_database_url(), future=True)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_filters() -> tuple[str, int | None, date | None]:
    q = request.args.get("q", "").strip()[:200]

    account_id = None
    raw_account = request.args.get("account", "").strip()
    if raw_account.isdigit():
        account_id = int(raw_account)

    selected_date = None
    raw_date = request.args.get("date", "").strip()
    if raw_date:
        try:
            selected_date = date.fromisoformat(raw_date)
        except ValueError:
            selected_date = None

    return q, account_id, selected_date


def recording_filter_conditions(q: str, account_id: int | None, selected_date: date | None):
    conditions = []

    if q:
        pattern = f"%{escape_like(q)}%"
        conditions.append(Recording.recording_name.ilike(pattern, escape="\\"))

    if account_id is not None:
        conditions.append(Recording.account_id == account_id)

    if selected_date is not None:
        local_start = datetime.combine(selected_date, time.min, tzinfo=WARSAW)
        local_end = local_start + timedelta(days=1)
        start_utc = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = local_end.astimezone(timezone.utc).replace(tzinfo=None)
        conditions.extend(
            [
                Recording.recorded_at >= start_utc,
                Recording.recorded_at < end_utc,
            ]
        )

    return conditions


def get_runtime_context(session: Session) -> dict:
    now = utc_now_naive()

    scheduler = session.execute(
        select(SchedulerState)
        .options(joinedload(SchedulerState.current_run))
        .where(SchedulerState.id == 1)
    ).scalar_one_or_none()

    last_finished_run = session.execute(
        select(Run)
        .where(Run.finished_at.is_not(None))
        .order_by(Run.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    workers = session.execute(
        select(RuntimeWorker)
        .options(joinedload(RuntimeWorker.recording).joinedload(Recording.account))
        .order_by(RuntimeWorker.worker_name)
    ).scalars().all()

    effective_state = "UNKNOWN"
    heartbeat_age_seconds = None
    next_run_in_seconds = None

    if scheduler is not None:
        heartbeat_age_seconds = max(0, int((now - scheduler.heartbeat_at).total_seconds()))
        if heartbeat_age_seconds > HEARTBEAT_STALE_SECONDS:
            effective_state = "OFFLINE"
        else:
            effective_state = scheduler.state

        if scheduler.next_run_at is not None:
            next_run_in_seconds = max(0, int((scheduler.next_run_at - now).total_seconds()))

    worker_views = []
    for worker in workers:
        percent = 0.0
        if worker.total_bytes > 0:
            percent = min(100.0, worker.downloaded_bytes * 100 / worker.total_bytes)
        worker_views.append({"worker": worker, "percent": percent})

    current_run = scheduler.current_run if scheduler is not None else None
    current_run_seconds = None
    if current_run is not None:
        current_run_seconds = max(0, int((now - current_run.started_at).total_seconds()))

    last_run_seconds = None
    if last_finished_run is not None and last_finished_run.finished_at is not None:
        last_run_seconds = max(
            0,
            int((last_finished_run.finished_at - last_finished_run.started_at).total_seconds()),
        )

    return {
        "scheduler": scheduler,
        "effective_state": effective_state,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "next_run_in_seconds": next_run_in_seconds,
        "current_run": current_run,
        "current_run_seconds": current_run_seconds,
        "last_finished_run": last_finished_run,
        "last_run_seconds": last_run_seconds,
        "worker_views": worker_views,
        "active_worker_count": len(worker_views),
        "total_speed_bps": sum(worker.speed_bps for worker in workers),
        "heartbeat_stale_seconds": HEARTBEAT_STALE_SECONDS,
    }


def get_attention_context(session: Session) -> dict:
    attention_records = session.execute(
        select(Recording)
        .options(joinedload(Recording.account))
        .where(Recording.attention_required.is_(True))
        .order_by(Recording.first_seen_at.asc())
    ).scalars().all()

    return {
        "attention_records": attention_records,
        "total_attention": len(attention_records),
    }


def get_history_context(session: Session) -> dict:
    q, account_id, selected_date = parse_filters()
    conditions = recording_filter_conditions(q, account_id, selected_date)

    accounts = session.execute(select(Account).order_by(Account.name)).scalars().all()

    history_stmt = (
        select(Event)
        .join(Event.recording)
        .options(joinedload(Event.recording).joinedload(Recording.account))
        .where(*conditions)
        .order_by(Event.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    history_events = session.execute(history_stmt).scalars().all()

    return {
        "accounts": accounts,
        "q": q,
        "account_id": account_id,
        "selected_date": selected_date.isoformat() if selected_date else "",
        "filters_active": bool(q or account_id or selected_date),
        "history_events": history_events,
        "history_limit": HISTORY_LIMIT,
    }


def database_error_response(exc: OperationalError, fragment: bool = False) -> Response | tuple[str, int]:
    message = (
        "CMDownloaderUI cannot open the SQLite database in read-only mode. "
        "Check DATABASE_PATH and ensure the database already exists and is readable."
    )
    if fragment:
        return (
            f'<div class="alert alert-danger mb-0" role="alert">{message}</div>',
            503,
        )
    return Response(
        render_template("database_error.html", message=message, detail=str(exc.orig)),
        status=503,
    )


@app.get("/")
def index():
    is_htmx = request.headers.get("HX-Request") == "true"
    try:
        with Session(engine) as session:
            history_context = get_history_context(session)
            if is_htmx:
                return render_template("_record_browser.html", **history_context)

            return render_template(
                "index.html",
                **get_runtime_context(session),
                **get_attention_context(session),
                **history_context,
            )
    except OperationalError as exc:
        return database_error_response(exc, fragment=is_htmx)


@app.get("/current")
def current_activity():
    try:
        with Session(engine) as session:
            return render_template("_current_activity.html", **get_runtime_context(session))
    except OperationalError as exc:
        return database_error_response(exc, fragment=True)


@app.get("/attention")
def attention_queue():
    try:
        with Session(engine) as session:
            return render_template("_attention.html", **get_attention_context(session))
    except OperationalError as exc:
        return database_error_response(exc, fragment=True)


@app.template_filter("filesize")
def format_size(value: int | float | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


@app.template_filter("speed")
def format_speed(value: int | float | None) -> str:
    if not value:
        return "—"
    return f"{format_size(value)}/s"


@app.template_filter("duration")
def format_duration(value: int | float | None) -> str:
    if value is None:
        return "—"

    total_seconds = max(0, int(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@app.template_filter("localtime")
def format_local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(WARSAW).strftime("%Y-%m-%d %H:%M:%S")


@app.template_filter("status_class")
def status_class(value: str | None) -> str:
    return {
        "COMPLETED": "text-bg-success",
        "COMPLETED_MANUAL_DELETE": "text-bg-success",
        "COMPLETED_WITH_ERRORS": "text-bg-warning",
        "RESOLVED_EXTERNALLY": "text-bg-secondary",
        "RUNNING": "text-bg-primary",
        "WAITING": "text-bg-secondary",
        "CHECKING": "text-bg-info",
        "DOWNLOADING": "text-bg-primary",
        "OFFLINE": "text-bg-danger",
        "FAILED": "text-bg-danger",
        "DELETE_FAILED": "text-bg-warning",
        "RETRYABLE_ERROR": "text-bg-info",
        "QUARANTINED": "text-bg-danger",
    }.get(value or "", "text-bg-secondary")
