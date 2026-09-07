from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class OpaqueIdError(ValueError):
    """The private opaque-ID mapping is unavailable or invalid."""


def initialize_mapping(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS opaque_athlete (
                opaque_id TEXT PRIMARY KEY,
                athlete_id TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                issued_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS opaque_athlete_active
                ON opaque_athlete(active, opaque_id);
            """
        )


def sync_active_opaque_ids(path: Path, athlete_ids: Iterable[str]) -> dict[str, str]:
    """Issue durable public IDs and return active athlete_id-to-opaque_id mappings."""

    requested = sorted({athlete_id.strip() for athlete_id in athlete_ids if athlete_id.strip()})
    initialize_mapping(path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE opaque_athlete SET active = 0")
        for athlete_id in requested:
            row = connection.execute(
                "SELECT opaque_id FROM opaque_athlete WHERE athlete_id = ?",
                (athlete_id,),
            ).fetchone()
            if row is None:
                opaque_id = _new_opaque_id(connection)
                connection.execute(
                    """
                    INSERT INTO opaque_athlete (opaque_id, athlete_id, active, issued_at)
                    VALUES (?, ?, 1, ?)
                    """,
                    (opaque_id, athlete_id, now),
                )
            else:
                connection.execute(
                    "UPDATE opaque_athlete SET active = 1 WHERE athlete_id = ?",
                    (athlete_id,),
                )
        rows = connection.execute(
            "SELECT athlete_id, opaque_id FROM opaque_athlete WHERE active = 1 ORDER BY athlete_id"
        ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def load_active_opaque_ids(path: Path) -> dict[str, str]:
    """Return opaque_id-to-athlete_id mappings using a physically read-only SQLite URI."""

    with open_readonly_connection(path) as connection:
        rows = connection.execute(
            "SELECT opaque_id, athlete_id FROM opaque_athlete WHERE active = 1 ORDER BY opaque_id"
        ).fetchall()
    mappings: dict[str, str] = {}
    for opaque_id, athlete_id in rows:
        opaque_text = str(opaque_id)
        athlete_text = str(athlete_id)
        if not OPAQUE_ID_RE.fullmatch(opaque_text) or not athlete_text:
            raise OpaqueIdError("[error] 비공개 opaque ID 매핑 형식이 올바르지 않습니다.")
        mappings[opaque_text] = athlete_text
    return mappings


def open_readonly_connection(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"[error] 비공개 opaque ID 매핑 파일이 없습니다: {resolved}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _new_opaque_id(connection: sqlite3.Connection) -> str:
    while True:
        candidate = secrets.token_urlsafe(18)
        if connection.execute("SELECT 1 FROM opaque_athlete WHERE opaque_id = ?", (candidate,)).fetchone() is None:
            return candidate
