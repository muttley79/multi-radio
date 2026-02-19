import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SkipRange:
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    days: frozenset | None = None  # None = every day; 0=Mon … 6=Sun


@dataclass
class SharedConfig:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    youtube_client_id: str
    youtube_client_secret: str
    sample_duration: int
    poll_interval: int
    playlist_max_size: int
    playlist_mode: str
    log_max_bytes: int
    log_backup_count: int


@dataclass
class StationConfig:
    name: str
    stream_url: str
    spotify_playlist_id: str | None = None
    youtube_playlist_id: str | None = None
    skip_ranges: list[SkipRange] = field(default_factory=list)
    log_file: str = ""

    def __post_init__(self):
        if not self.spotify_playlist_id and not self.youtube_playlist_id:
            raise ValueError(
                f"Station '{self.name}' must have at least one of spotify_playlist_id or youtube_playlist_id"
            )
        if not self.log_file:
            self.log_file = f"{self.name}.log"


@dataclass
class AppConfig:
    shared: SharedConfig
    stations: list[StationConfig]


_DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _parse_days(spec: str) -> frozenset:
    spec = spec.lower()
    if spec == "weekdays":
        return frozenset([6, 0, 1, 2, 3])  # Sun-Thu
    if spec == "weekends":
        return frozenset([4, 5])  # Fri-Sat
    if "-" in spec:
        a, b = spec.split("-", 1)
        start, end = _DAY_MAP[a], _DAY_MAP[b]
        if start <= end:
            return frozenset(range(start, end + 1))
        else:  # wraps: fri-mon → {4,5,6,0}
            return frozenset(list(range(start, 7)) + list(range(0, end + 1)))
    return frozenset([_DAY_MAP[spec]])


def _parse_skip_hours(raw: str) -> list[SkipRange]:
    """Parse comma-separated time ranges, with optional day prefix.

    Formats:
      "07:00-09:30"                   every day (unchanged)
      "weekdays 07:00-09:30"          weekdays only (Sun-Thu)
      "weekends 10:00-12:00"          weekends only (Fri-Sat)
      "mon-fri 07:00-09:30"           day range
      "fri-mon 22:00-08:00"           wrapping day range
      "sat 10:00-14:00"               single day
      "mon-fri 07:00-09:30, sat 10:00-14:00"  multiple entries
    """
    if not raw or not raw.strip():
        return []
    ranges = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part[0].isalpha():
            day_spec, time_part = part.split(" ", 1)
            days = _parse_days(day_spec)
        else:
            day_spec, time_part, days = None, part, None
        start_str, end_str = time_part.strip().split("-")
        sh, sm = (int(x) for x in start_str.strip().split(":"))
        eh, em = (int(x) for x in end_str.strip().split(":"))
        ranges.append(SkipRange(sh, sm, eh, em, days))
    return ranges


def load_config(yaml_path: str = "stations.yaml") -> AppConfig:
    """Load configuration from stations.yaml. Crashes with clear message on errors."""
    path = Path(yaml_path)
    if not path.exists():
        print(f"FATAL: Config file not found: {path.resolve()}", file=sys.stderr)
        sys.exit(1)

    with path.open() as f:
        data = yaml.safe_load(f)

    raw_shared = data.get("shared", {})

    playlist_mode = str(raw_shared.get("playlist_mode", "normal")).lower()
    if playlist_mode not in ("normal", "reverse"):
        print(f"FATAL: playlist_mode must be 'normal' or 'reverse', got '{playlist_mode}'", file=sys.stderr)
        sys.exit(1)

    shared = SharedConfig(
        spotify_client_id=raw_shared.get("spotify_client_id", ""),
        spotify_client_secret=raw_shared.get("spotify_client_secret", ""),
        spotify_redirect_uri=raw_shared.get("spotify_redirect_uri", ""),
        youtube_client_id=raw_shared.get("youtube_client_id", ""),
        youtube_client_secret=raw_shared.get("youtube_client_secret", ""),
        sample_duration=int(raw_shared.get("sample_duration", 12)),
        poll_interval=int(raw_shared.get("poll_interval", 300)),
        playlist_max_size=int(raw_shared.get("playlist_max_size", 100)),
        playlist_mode=playlist_mode,
        log_max_bytes=int(raw_shared.get("log_max_bytes", 5_242_880)),
        log_backup_count=int(raw_shared.get("log_backup_count", 3)),
    )

    stations = []
    for raw_station in data.get("stations", []):
        try:
            station = StationConfig(
                name=raw_station["name"],
                stream_url=raw_station["stream_url"],
                spotify_playlist_id=raw_station.get("spotify_playlist_id"),
                youtube_playlist_id=raw_station.get("youtube_playlist_id"),
                skip_ranges=_parse_skip_hours(raw_station.get("skip_hours", "")),
                log_file=raw_station.get("log_file", ""),
            )
        except ValueError as exc:
            print(f"FATAL: {exc}", file=sys.stderr)
            sys.exit(1)
        stations.append(station)

    if not stations:
        print("FATAL: No stations defined in stations.yaml", file=sys.stderr)
        sys.exit(1)

    return AppConfig(shared=shared, stations=stations)
