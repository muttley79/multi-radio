import logging
import os
import time
from logging.handlers import RotatingFileHandler

from radio_monitor.config import SharedConfig, StationConfig
from radio_monitor.identifier import identify_song
from radio_monitor.recorder import record_sample
from radio_monitor.scheduler import is_skip_hour
from radio_monitor.spotify_client import SpotifyPlaylistManager


def run_station(station: StationConfig, shared: SharedConfig) -> None:
    """Per-station monitoring loop. Intended to run in a dedicated thread."""
    logger = logging.getLogger(f"station.{station.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    fh = RotatingFileHandler(station.log_file, maxBytes=shared.log_max_bytes, backupCount=shared.log_backup_count)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Starting station %s — stream: %s, interval: %ds", station.name, station.stream_url, shared.poll_interval)

    spotify = SpotifyPlaylistManager(
        client_id=shared.spotify_client_id,
        client_secret=shared.spotify_client_secret,
        redirect_uri=shared.spotify_redirect_uri,
        playlist_id=station.spotify_playlist_id,
        max_size=shared.playlist_max_size,
        mode=shared.playlist_mode,
    )

    in_skip = False
    while True:
        try:
            if is_skip_hour(station.skip_ranges):
                if not in_skip:
                    logger.info("Entered skip hours — pausing until window ends")
                    in_skip = True
                time.sleep(shared.poll_interval)
                continue

            if in_skip:
                logger.info("Ended skip hours — resuming")
                in_skip = False

            audio_file = record_sample(station.stream_url, shared.sample_duration)
            if not audio_file:
                logger.warning("Failed to record sample, retrying next cycle")
                time.sleep(shared.poll_interval)
                continue

            try:
                song = identify_song(audio_file)
                if not song:
                    logger.info("Could not identify song (jingle/ad/talk?)")
                    time.sleep(shared.poll_interval)
                    continue

                uri = spotify.search_track(song["artist"], song["title"])
                if not uri:
                    logger.warning("Song not found on Spotify: %s - %s", song["artist"], song["title"])
                    time.sleep(shared.poll_interval)
                    continue

                last_uri = spotify.get_last_track_uri()
                if uri == last_uri:
                    logger.info("Same song still playing: %s - %s, retrying in 120s", song["artist"], song["title"])
                    time.sleep(120)
                    continue

                added = spotify.add_song(uri)
                if added:
                    logger.info("Added to playlist: %s - %s", song["artist"], song["title"])
                else:
                    logger.info("Already in playlist: %s - %s", song["artist"], song["title"])

            finally:
                try:
                    os.unlink(audio_file)
                except OSError:
                    pass

        except Exception:
            logger.exception("Unexpected error in station loop")

        time.sleep(shared.poll_interval)
