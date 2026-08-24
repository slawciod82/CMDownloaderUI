from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Account, Base, Event, Recording, RuntimeState


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
        downloading = Recording(
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
        session.add_all([quarantined, delete_failed, downloading, completed, resolved])
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
            ]
        )

        session.add(
            RuntimeState(
                id=1,
                state="DOWNLOADING",
                recording=downloading,
                downloaded_bytes=521 * 1024 * 1024,
                total_bytes=824 * 1024 * 1024,
                speed_bps=18.4 * 1024 * 1024,
                started_at=now - timedelta(minutes=12),
                updated_at=now,
            )
        )

        session.commit()

    print(f"Demo database created: {database_path}")


if __name__ == "__main__":
    main()
