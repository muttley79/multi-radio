import threading

from radio_monitor.config import load_config
from radio_monitor.spotify_client import SpotifyPlaylistManager
from radio_monitor.worker import run_station


def main() -> None:
    app_config = load_config()
    shared = app_config.shared

    # Verify OAuth sequentially before spawning threads to avoid interleaved prompts
    for station in app_config.stations:
        spotify = SpotifyPlaylistManager(
            client_id=shared.spotify_client_id,
            client_secret=shared.spotify_client_secret,
            redirect_uri=shared.spotify_redirect_uri,
            playlist_id=station.spotify_playlist_id,
            max_size=shared.playlist_max_size,
            mode=shared.playlist_mode,
        )
        spotify.verify_auth()

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
