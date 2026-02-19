import logging
import os
import time
from logging.handlers import RotatingFileHandler

from radio_monitor.config import SharedConfig, StationConfig
from radio_monitor.identifier import identify_song
from radio_monitor.recorder import record_sample
from radio_monitor.scheduler import is_skip_hour
from radio_monitor.spotify_client import SpotifyPlaylistManager
from radio_monitor.youtube_client import YouTubePlaylistManager


def _build_clients(station: StationConfig, shared: SharedConfig) -> list[tuple[str, object]]:
    """Build platform clients for the station. Called once at station startup."""
    clients = []
    if station.spotify_playlist_id:
        clients.append((
            "Spotify",
            SpotifyPlaylistManager(
                client_id=shared.spotify_client_id,
                client_secret=shared.spotify_client_secret,
                redirect_uri=shared.spotify_redirect_uri,
                playlist_id=station.spotify_playlist_id,
                max_size=shared.playlist_max_size,
                mode=shared.playlist_mode,
            ),
        ))
    if station.youtube_playlist_id:
        clients.append((
            "YouTube",
            YouTubePlaylistManager(
                client_id=shared.youtube_client_id,
                client_secret=shared.youtube_client_secret,
                playlist_id=station.youtube_playlist_id,
                max_size=shared.playlist_max_size,
                mode=shared.playlist_mode,
            ),
        ))
    return clients


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

    clients = _build_clients(station, shared)

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

                artist, title = song["artist"], song["title"]
                client_map = dict(clients)
                both = "Spotify" in client_map and "YouTube" in client_map

                if both:
                    # Spotify-led mode: YouTube is only searched when Spotify confirms a new song,
                    # saving 100 quota units per cycle when the song is already in the playlist.
                    spotify = client_map["Spotify"]
                    youtube = client_map["YouTube"]

                    spotify_uri = spotify.search_track(artist, title)
                    if not spotify_uri:
                        logger.warning("Song not found on Spotify: %s - %s", artist, title)
                        time.sleep(shared.poll_interval)
                        continue

                    if spotify_uri == spotify.get_last_track_uri():
                        logger.info("Same song still playing: %s - %s, retrying in 120s", artist, title)
                        time.sleep(120)
                        continue

                    spotify_ok = False
                    try:
                        spotify.add_song(spotify_uri)
                        logger.info("Added to Spotify playlist: %s - %s", artist, title)
                        spotify_ok = True
                    except Exception:
                        logger.exception("Error adding to Spotify for: %s - %s", artist, title)

                    if spotify_ok:
                        youtube_id = youtube.search_track(artist, title)
                        if not youtube_id:
                            logger.warning("Song not found on YouTube: %s - %s", artist, title)
                        else:
                            try:
                                youtube.add_song(youtube_id)
                                logger.info("Added to YouTube playlist: %s - %s", artist, title)
                            except Exception:
                                logger.exception("Error adding to YouTube for: %s - %s", artist, title)

                else:
                    # Single-platform flow
                    platform_ids: dict[str, str | None] = {}
                    for name, client in clients:
                        platform_ids[name] = client.search_track(artist, title)

                    all_same = True
                    for name, client in clients:
                        track_id = platform_ids.get(name)
                        if track_id is None or track_id != client.get_last_track_uri():
                            all_same = False
                            break
                    if all_same and clients:
                        logger.info("Same song still playing: %s - %s, retrying in 120s", artist, title)
                        time.sleep(120)
                        continue

                    for name, client in clients:
                        track_id = platform_ids.get(name)
                        if not track_id:
                            logger.warning("Song not found on %s: %s - %s", name, artist, title)
                            continue
                        try:
                            client.add_song(track_id)
                            logger.info("Added to %s playlist: %s - %s", name, artist, title)
                        except Exception:
                            logger.exception("Error adding to %s for: %s - %s", name, artist, title)

            finally:
                try:
                    os.unlink(audio_file)
                except OSError:
                    pass

        except Exception:
            logger.exception("Unexpected error in station loop")

        time.sleep(shared.poll_interval)
