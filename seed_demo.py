from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Account, Base, Event, Recording, Run, RuntimeWorker, SchedulerState


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def main() -> None:
    database_path = Path(os.getenv("DEMO_DATABASE_PATH", "state/cm_downloader.db"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    now = utc_now_naive()

    with Session(engine) as session:
        accounts = [Account(name=f"Account {number}") for number in range(1, 6)]
        session.add_all(accounts)
        session.flush()

        quarantined = Recording(
            recording_id="900001",
            conference_id="700001",
            account=accounts[0],
            recording_name="Webinar ABC",
            recorded_at=now - timedelta(hours=4),
            status="QUARANTINED",
            attention_required=True,
            expected_size=912 * 1024 * 1024,
            attempt_count=1,
            last_error="Download failed, file size mismatch",
            first_seen_at=now - timedelta(hours=4, minutes=10),
            last_attempt_at=now - timedelta(hours=3, minutes=55),
        )
        delete_failed = Recording(
            recording_id="900002",
            conference_id="700002",
            account=accounts[1],
            recording_name="Training XYZ",
            recorded_at=now - timedelta(hours=8),
            status="DELETE_FAILED",
            attention_required=True,
            expected_size=540 * 1024 * 1024,
            local_path="/recordings/Training XYZ.mp4",
            attempt_count=1,
            last_error="ClickMeeting DELETE returned HTTP 500",
            first_seen_at=now - timedelta(hours=8, minutes=5),
            last_attempt_at=now - timedelta(hours=7, minutes=45),
        )
        downloading_a = Recording(
            recording_id="900003",
            conference_id="700003",
            account=accounts[2],
            recording_name="Current Live Session",
            recorded_at=now - timedelta(minutes=40),
            status="DOWNLOADING",
            attention_required=False,
            expected_size=824 * 1024 * 1024,
            attempt_count=1,
            first_seen_at=now - timedelta(minutes=42),
            last_attempt_at=now - timedelta(minutes=12),
        )
        completed = Recording(
            recording_id="900004",
            conference_id="700004",
            account=accounts[0],
            recording_name="Completed Webinar",
            recorded_at=now - timedelta(days=1),
            status="COMPLETED",
            attention_required=False,
            resolution="automatic",
            expected_size=630 * 1024 * 1024,
            local_path="/recordings/Completed Webinar.mp4",
            attempt_count=1,
            first_seen_at=now - timedelta(days=1, minutes=10),
            last_attempt_at=now - timedelta(days=1),
            completed_at=now - timedelta(days=1) + timedelta(minutes=8),
        )
        resolved = Recording(
            recording_id="900005",
            conference_id="700005",
            account=accounts[3],
            recording_name="Problem Resolved Manually",
            recorded_at=now - timedelta(days=2),
            status="RESOLVED_EXTERNALLY",
            attention_required=False,
            resolution="manual_external",
            expected_size=300 * 1024 * 1024,
            attempt_count=1,
            last_error="Download failed, file size mismatch",
            first_seen_at=now - timedelta(days=2, minutes=10),
            last_attempt_at=now - timedelta(days=2),
            completed_at=now - timedelta(days=1, hours=20),
        )
        downloading_b = Recording(
            recording_id="900006",
            conference_id="700006",
            account=accounts[3],
            recording_name="Parallel Training A",
            recorded_at=now - timedelta(minutes=55),
            status="DOWNLOADING",
            attention_required=False,
            expected_size=1350 * 1024 * 1024,
            attempt_count=1,
            first_seen_at=now - timedelta(minutes=57),
            last_attempt_at=now - timedelta(minutes=10),
        )
        downloading_c = Recording(
            recording_id="900007",
            conference_id="700007",
            account=accounts[4],
            recording_name="Parallel Training B",
            recorded_at=now - timedelta(minutes=65),
            status="DOWNLOADING",
            attention_required=False,
            expected_size=710 * 1024 * 1024,
            attempt_count=1,
            first_seen_at=now - timedelta(minutes=67),
            last_attempt_at=now - timedelta(minutes=8),
        )
        session.add_all(
            [
                quarantined,
                delete_failed,
                downloading_a,
                completed,
                resolved,
                downloading_b,
                downloading_c,
            ]
        )
        session.flush()

        session.add_all(
            [
                Event(
                    recording=quarantined,
                    event_type="QUARANTINED",
                    message="File size mismatch. Automatic redownload disabled; manual action required.",
                    created_at=now - timedelta(hours=3, minutes=55),
                ),
                Event(
                    recording=delete_failed,
                    event_type="DELETE_FAILED",
                    message="Local file verified, but ClickMeeting deletion failed. Manual deletion required.",
                    created_at=now - timedelta(hours=7, minutes=45),
                ),
                Event(
                    recording=completed,
                    event_type="COMPLETED",
                    message="Recording downloaded, verified and deleted from ClickMeeting automatically.",
                    created_at=completed.completed_at,
                ),
                Event(
                    recording=resolved,
                    event_type="RESOLVED_EXTERNALLY",
                    message="Recording disappeared from ClickMeeting while quarantined. Manual/external handling inferred.",
                    created_at=resolved.completed_at,
                ),
                Event(
                    recording=downloading_a,
                    event_type="DOWNLOADING",
                    message="Download started by worker-1.",
                    created_at=now - timedelta(minutes=12),
                ),
                Event(
                    recording=downloading_b,
                    event_type="DOWNLOADING",
                    message="Download started by worker-2.",
                    created_at=now - timedelta(minutes=10),
                ),
                Event(
                    recording=downloading_c,
                    event_type="DOWNLOADING",
                    message="Download started by worker-3.",
                    created_at=now - timedelta(minutes=8),
                ),
            ]
        )

        previous_run = Run(
            status="COMPLETED",
            started_at=now - timedelta(minutes=32),
            finished_at=now - timedelta(minutes=26),
            recordings_found=3,
            downloaded_count=3,
            failed_count=0,
        )
        current_run = Run(
            status="RUNNING",
            started_at=now - timedelta(minutes=12),
            recordings_found=6,
            downloaded_count=1,
            failed_count=0,
        )
        session.add_all([previous_run, current_run])
        session.flush()

        session.add(
            SchedulerState(
                id=1,
                state="RUNNING",
                heartbeat_at=now,
                next_run_at=None,
                interval_seconds=300,
                current_run=current_run,
            )
        )

        session.add_all(
            [
                RuntimeWorker(
                    worker_name="worker-1",
                    run=current_run,
                    recording=downloading_a,
                    state="DOWNLOADING",
                    downloaded_bytes=521 * 1024 * 1024,
                    total_bytes=824 * 1024 * 1024,
                    speed_bps=18.4 * 1024 * 1024,
                    started_at=now - timedelta(minutes=12),
                    updated_at=now,
                ),
                RuntimeWorker(
                    worker_name="worker-2",
                    run=current_run,
                    recording=downloading_b,
                    state="DOWNLOADING",
                    downloaded_bytes=418 * 1024 * 1024,
                    total_bytes=1350 * 1024 * 1024,
                    speed_bps=11.2 * 1024 * 1024,
                    started_at=now - timedelta(minutes=10),
                    updated_at=now,
                ),
                RuntimeWorker(
                    worker_name="worker-3",
                    run=current_run,
                    recording=downloading_c,
                    state="DOWNLOADING",
                    downloaded_bytes=468 * 1024 * 1024,
                    total_bytes=710 * 1024 * 1024,
                    speed_bps=8.7 * 1024 * 1024,
                    started_at=now - timedelta(minutes=8),
                    updated_at=now,
                ),
            ]
        )

        session.commit()

    print(f"Demo database created: {database_path}")


if __name__ == "__main__":
    main()
