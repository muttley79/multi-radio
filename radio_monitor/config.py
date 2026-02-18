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


@dataclass
class SharedConfig:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
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
    spotify_playlist_id: str
    skip_ranges: list[SkipRange] = field(default_factory=list)
    log_file: str = ""

    def __post_init__(self):
        if not self.log_file:
            self.log_file = f"{self.name}.log"


@dataclass
class AppConfig:
    shared: SharedConfig
    stations: list[StationConfig]


def _parse_skip_hours(raw: str) -> list[SkipRange]:
    """Parse comma-separated time ranges like '02:00-06:00,23:00-01:00'."""
    if not raw or not raw.strip():
        return []
    ranges = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        start_str, end_str = part.split("-")
        sh, sm = (int(x) for x in start_str.strip().split(":"))
        eh, em = (int(x) for x in end_str.strip().split(":"))
        ranges.append(SkipRange(sh, sm, eh, em))
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
        spotify_client_id=raw_shared["spotify_client_id"],
        spotify_client_secret=raw_shared["spotify_client_secret"],
        spotify_redirect_uri=raw_shared["spotify_redirect_uri"],
        sample_duration=int(raw_shared.get("sample_duration", 12)),
        poll_interval=int(raw_shared.get("poll_interval", 300)),
        playlist_max_size=int(raw_shared.get("playlist_max_size", 100)),
        playlist_mode=playlist_mode,
        log_max_bytes=int(raw_shared.get("log_max_bytes", 5_242_880)),
        log_backup_count=int(raw_shared.get("log_backup_count", 3)),
    )

    stations = []
    for raw_station in data.get("stations", []):
        station = StationConfig(
            name=raw_station["name"],
            stream_url=raw_station["stream_url"],
            spotify_playlist_id=raw_station["spotify_playlist_id"],
            skip_ranges=_parse_skip_hours(raw_station.get("skip_hours", "")),
            log_file=raw_station.get("log_file", ""),
        )
        stations.append(station)

    if not stations:
        print("FATAL: No stations defined in stations.yaml", file=sys.stderr)
        sys.exit(1)

    return AppConfig(shared=shared, stations=stations)
