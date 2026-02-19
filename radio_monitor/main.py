import threading

from radio_monitor.config import load_config
from radio_monitor.spotify_client import SpotifyPlaylistManager
from radio_monitor.youtube_client import YouTubePlaylistManager
from radio_monitor.worker import run_station


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

    threads = []
    for station in app_config.stations:
        t = threading.Thread(
            target=run_station,
            args=(station, shared),
            name=station.name,
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
