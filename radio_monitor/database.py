import sqlite3
import threading
from typing import Optional


class RadioDatabase:
    """Thread-safe SQLite store for radio play history."""

    def __init__(self, db_path: str = "radio_analytics.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS plays (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        station     TEXT NOT NULL,
                        artist      TEXT NOT NULL,
                        title       TEXT NOT NULL,
                        played_at   TEXT NOT NULL,
                        spotify_uri TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_played_at ON plays(played_at);
                """)
                conn.commit()
                # Idempotent migration for existing DBs that lack the column
                try:
                    conn.execute("ALTER TABLE plays ADD COLUMN spotify_uri TEXT")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # column already exists
            finally:
                conn.close()

    def record_play(self, station: str, artist: str, title: str, spotify_uri=None, retention_days: int = 30) -> None:
        """Insert a play record and prune rows for this station older than retention_days."""
        from datetime import datetime, timezone
        played_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO plays (station, artist, title, played_at, spotify_uri) VALUES (?, ?, ?, ?, ?)",
                    (station, artist, title, played_at, spotify_uri),
                )
                conn.execute(
                    "DELETE FROM plays WHERE station = ? AND played_at < datetime('now', ?)",
                    (station, f"-{retention_days} days"),
                )
                conn.commit()
            finally:
                conn.close()

    def _where(self, station: Optional[str], days: Optional[int]) -> tuple[str, list]:
        """Build a WHERE clause and params list for the given filters."""
        conditions: list[str] = []
        params: list = []
        if station:
            conditions.append("station = ?")
            params.append(station)
        if days:
            conditions.append("played_at >= datetime('now', ?)")
            params.append(f"-{days} days")
        if conditions:
            return "WHERE " + " AND ".join(conditions), params
        return "", params

    def top_songs(self, station: Optional[str] = None, limit: int = 20, days: Optional[int] = None) -> list[dict]:
        where, params = self._where(station, days)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT artist, title, COUNT(*) as count, MAX(spotify_uri) as spotify_uri "
                f"FROM plays {where} GROUP BY artist, title ORDER BY "
                f"CASE WHEN COUNT(*) > 1 THEN 0 ELSE 1 END, "
                f"COUNT(*) DESC, MAX(played_at) DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def top_artists(self, station: Optional[str] = None, limit: int = 20, days: Optional[int] = None) -> list[dict]:
        where, params = self._where(station, days)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT artist, COUNT(*) as count FROM plays {where} "
                f"GROUP BY artist ORDER BY "
                f"CASE WHEN COUNT(*) > 1 THEN 0 ELSE 1 END, "
                f"COUNT(*) DESC, MAX(played_at) DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def plays_by_hour(self, station: Optional[str] = None, days: Optional[int] = None) -> list[dict]:
        """Returns 24 entries (hour 0-23) each with a play count."""
        where, params = self._where(station, days)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT CAST(strftime('%H', played_at) AS INTEGER) as hour, COUNT(*) as count "
                f"FROM plays {where} GROUP BY hour ORDER BY hour",
                params,
            ).fetchall()
            counts = {r["hour"]: r["count"] for r in rows}
            return [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]
        finally:
            conn.close()

    def plays_by_dow(self, station: Optional[str] = None, days: Optional[int] = None) -> list[dict]:
        """Returns 7 entries (0=Sun … 6=Sat) each with a play count."""
        where, params = self._where(station, days)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT CAST(strftime('%w', played_at) AS INTEGER) as dow, COUNT(*) as count "
                f"FROM plays {where} GROUP BY dow ORDER BY dow",
                params,
            ).fetchall()
            counts = {r["dow"]: r["count"] for r in rows}
            labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            return [{"dow": d, "label": labels[d], "count": counts.get(d, 0)} for d in range(7)]
        finally:
            conn.close()

    def plays_by_day(self, station: Optional[str] = None, days: Optional[int] = None, artist: Optional[str] = None) -> list[dict]:
        where, params = self._where(station, days)
        if artist:
            connector = "AND" if where else "WHERE"
            where += f" {connector} artist = ?"
            params.append(artist)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT date(played_at) as day, COUNT(*) as count "
                f"FROM plays {where} GROUP BY day ORDER BY day",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def songs_by_artist(self, artist: str, station: Optional[str] = None, days: Optional[int] = None, limit: int = 20) -> list[dict]:
        where, params = self._where(station, days)
        connector = "AND" if where else "WHERE"
        where += f" {connector} artist = ?"
        params.append(artist)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT title, COUNT(*) as count, MAX(spotify_uri) as spotify_uri "
                f"FROM plays {where} GROUP BY title ORDER BY count DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def recent_plays(self, station: Optional[str] = None, limit: int = 50) -> list[dict]:
        where, params = self._where(station, None)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT station, artist, title, played_at FROM plays {where} "
                f"ORDER BY played_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
