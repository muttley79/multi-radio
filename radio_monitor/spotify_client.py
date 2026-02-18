import logging

import spotipy
from spotipy.oauth2 import SpotifyOAuth

logger = logging.getLogger(__name__)


class SpotifyPlaylistManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        playlist_id: str,
        max_size: int = 100,
        mode: str = "normal",
    ):
        self.playlist_id = playlist_id
        self.max_size = max_size
        self.mode = mode
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="playlist-modify-public playlist-modify-private",
                cache_path=".spotify_token_cache",
                open_browser=False,
            )
        )

    def verify_auth(self) -> None:
        """Force an API call to trigger OAuth login if needed. Call at startup."""
        me = self.sp.current_user()
        logger.info("Authenticated as Spotify user: %s", me.get("display_name") or me["id"])

    def get_playlist_track_uris(self) -> list[str]:
        """Fetch all track URIs currently in the playlist."""
        uris = []
        results = self.sp.playlist_items(
            self.playlist_id, fields="items.track.uri,next", additional_types=["track"]
        )
        while True:
            for item in results["items"]:
                track = item.get("track")
                if track and track.get("uri"):
                    uris.append(track["uri"])
            if results.get("next"):
                results = self.sp.next(results)
            else:
                break
        return uris

    def search_track(self, artist: str, title: str) -> str | None:
        """Search Spotify for a track by artist and title. Returns URI or None.

        Tries multiple queries in order of strictness, always keeping artist strict.
        """
        import re
        clean_title = re.sub(r"\s*\(.*?\)\s*$", "", title).strip()

        queries = [
            f"artist:{artist} track:{clean_title}",
            f"artist:{artist} track:{title}",
            f"artist:{artist} {clean_title}",
        ]

        for query in queries:
            results = self.sp.search(q=query, type="track", limit=1)
            items = results["tracks"]["items"]
            if items:
                uri = items[0]["uri"]
                logger.info("Spotify match: %s - %s → %s", artist, title, uri)
                return uri

        logger.warning("Spotify search found nothing for: %s - %s", artist, title)
        return None

    def get_last_track_uri(self) -> str | None:
        """Get the URI of the most recently added track in the playlist."""
        results = self.sp.playlist_items(
            self.playlist_id, fields="items.track.uri", additional_types=["track"], limit=1
        )
        items = results.get("items", [])
        if not items:
            return None
        track = items[0].get("track")
        if track:
            return track.get("uri")
        return None

    def add_song(self, track_uri: str) -> bool:
        """Add a track to the playlist, respecting mode and max size.

        Returns True if added, False if duplicate.
        """
        current_uris = self.get_playlist_track_uris()

        if track_uri in current_uris:
            logger.info("Already in playlist: %s", track_uri)
            return False

        if self.mode == "normal":
            # Newest on top
            self.sp.playlist_add_items(self.playlist_id, [track_uri], position=0)
            logger.info("Added to top of playlist: %s", track_uri)
            # Trim from bottom if over max
            if len(current_uris) + 1 > self.max_size:
                excess = current_uris[self.max_size - 1 :]
                self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, excess)
                logger.info("Trimmed %d old track(s) from bottom", len(excess))
        else:
            # Reverse: newest at bottom
            self.sp.playlist_add_items(self.playlist_id, [track_uri])
            logger.info("Added to bottom of playlist: %s", track_uri)
            # Trim from top if over max
            if len(current_uris) + 1 > self.max_size:
                excess = current_uris[: len(current_uris) + 1 - self.max_size]
                self.sp.playlist_remove_all_occurrences_of_items(self.playlist_id, excess)
                logger.info("Trimmed %d old track(s) from top", len(excess))

        return True
