import logging
import threading

from radio_monitor.config import load_config
from radio_monitor.spotify_client import SpotifyPlaylistManager
from radio_monitor.youtube_client import YouTubePlaylistManager
from radio_monitor.worker import run_station

logger = logging.getLogger(__name__)


def main() -> None:
    app_config = load_config()
    shared = app_config.shared

    # Verify Spotify OAuth once if any station uses it
    if any(s.spotify_playlist_id for s in app_config.stations):
        station = next(s for s in app_config.stations if s.spotify_playlist_id)
        SpotifyPlaylistManager(
            client_id=shared.spotify_client_id,
            client_secret=shared.spotify_client_secret,
            redirect_uri=shared.spotify_redirect_uri,
            playlist_id=station.spotify_playlist_id,
            max_size=shared.playlist_max_size,
            mode=shared.playlist_mode,
        ).verify_auth()

    # Verify YouTube OAuth once if any station uses it
    if any(s.youtube_playlist_id for s in app_config.stations):
        station = next(s for s in app_config.stations if s.youtube_playlist_id)
        YouTubePlaylistManager(
            client_id=shared.youtube_client_id,
            client_secret=shared.youtube_client_secret,
            playlist_id=station.youtube_playlist_id,
            max_size=shared.playlist_max_size,
            mode=shared.playlist_mode,
        ).verify_auth()

    # Analytics database (created even if dashboard is off, so workers can record)
    db = None
    any_analytics = any(s.analytics_enabled for s in app_config.stations)
    if any_analytics:
        from radio_monitor.database import RadioDatabase
        db = RadioDatabase(db_path=shared.analytics_db)

    # Dashboard web server
    if shared.dashboard_enabled and any_analytics and db is not None:
        try:
            from radio_monitor.dashboard import DashboardServer
            station_names = [s.name for s in app_config.stations]
            DashboardServer(db, shared.dashboard_host, shared.dashboard_port, station_names).start()
        except ImportError:
            logger.warning("Flask not installed — dashboard disabled. Run: pip install flask")

    threads = []
    for station in app_config.stations:
        t = threading.Thread(
            target=run_station,
            args=(station, shared, db),
            name=station.name,
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
