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

        if me.get("product") != "premium":
            raise RuntimeError(
                "Spotify Premium is required for playlist API access (Feb 2026 restriction). "
                f"Account '{me.get('id')}' has product='{me.get('product')}'."
            )

        playlist_meta = self.sp.playlist(self.playlist_id, fields="id,name,owner.id")
        owner_id = playlist_meta.get("owner", {}).get("id")
        if owner_id != me["id"]:
            logger.warning(
                "Playlist '%s' (%s) is owned by '%s', not the authenticated user '%s'. "
                "Playlist item contents may be restricted (Feb 2026 Spotify API change).",
                playlist_meta.get("name", self.playlist_id),
                self.playlist_id,
                owner_id,
                me["id"],
            )

    def _get_playlist_track_uris(self) -> list[str]:
        """Fetch all track URIs currently in the playlist (needed for trim calculations)."""
        uris = []
        results = self.sp._get(
            f"playlists/{self.playlist_id}/items",
            fields="items.track.uri,next",
            limit=100,
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

        Tries multiple queries in order of strictness, with targeted fallbacks for
        Hebrew titles, multi-artist entries, and transliteration mismatches.
        """
        import re

        HEBREW = r'[\u0590-\u05FF]'
        HEBREW_IN_PARENS = r'\(([^\)]*[\u0590-\u05FF][^\)]*)\)'

        # Hebrew text in title parens: "Title (הכותרת)" → "הכותרת"
        hebrew_match = re.search(HEBREW_IN_PARENS, title)
        hebrew_title = hebrew_match.group(1).strip() if hebrew_match else None

        # If title itself IS Hebrew (no parens), use it directly
        if not hebrew_title and re.search(HEBREW, title):
            hebrew_title = title

        # Hebrew text in artist parens: "Tzlil Mecuvan (צליל מכוון)" → "צליל מכוון"
        hebrew_artist_match = re.search(HEBREW_IN_PARENS, artist)
        hebrew_artist = hebrew_artist_match.group(1).strip() if hebrew_artist_match else None

        # First artist for multi-artist fallback, e.g. "Artist1, Artist2 & Artist3" → "Artist1"
        first_artist = re.split(r'[,&]', artist)[0].strip()

        # Stripped title (last-resort only): remove trailing (parens) or [brackets]
        clean_title = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", title).strip()

        queries = [
            f"artist:{artist} track:{title}",              # 1. exact — full title with Live/Extended
        ]
        if hebrew_title:
            queries += [
                f"artist:{artist} track:{hebrew_title}",   # 2. Hebrew title, strict artist
                f"{artist} {hebrew_title}",                 # 3. Hebrew title, free-text
            ]
        if hebrew_artist:
            queries.append(f"{hebrew_artist} {title}")     # 4. Hebrew artist, transliterated title
            if hebrew_title:
                queries.append(f"{hebrew_artist} {hebrew_title}")  # 5. both Hebrew
        queries.append(f"{artist} {title}")                # 6. free-text, full title (handles Hebrew artist names)
        queries.append(f"{artist} - {title}")              # 7. dash format (matches Spotify UI search style)
        if first_artist != artist:
            queries.append(f"{first_artist} {title}")      # 8. first artist only, full title
            if hebrew_title:
                queries.append(f"{first_artist} {hebrew_title}")  # 9. first artist + Hebrew
        if clean_title != title:
            queries.append(f"artist:{artist} track:{clean_title}")  # 10. stripped title
        if hebrew_title:
            queries.append(f"track:{hebrew_title}")        # 11. last resort: Hebrew title only (no artist)

        for i, query in enumerate(queries):
            results = self.sp.search(q=query, type="track", limit=1, market="IL")
            items = results["tracks"]["items"]
            if items:
                uri = items[0]["uri"]
                logger.info("Spotify match [query=%d]: %s - %s → %s", i + 1, artist, title, uri)
                return uri

        logger.warning("Spotify search found nothing for: %s - %s", artist, title)
        return None

    def get_last_track_uri(self) -> str | None:
        """Get the URI of the most recently added track in the playlist."""
        results = self.sp._get(
            f"playlists/{self.playlist_id}/items",
            fields="items.track.uri",
            limit=1,
        )
        items = results.get("items", [])
        if not items:
            return None
        track = items[0].get("track")
        if track:
            return track.get("uri")
        return None

    def add_song(self, track_uri: str) -> None:
        """Add a track to the playlist, respecting mode and max size.

        No dedup — the caller is responsible for the same-song check via get_last_track_uri().
        Trim removes by exact position so duplicate URIs in the playlist are handled correctly.
        """
        current_uris = self._get_playlist_track_uris()

        if self.mode == "normal":
            # Newest on top: add at position 0, trim the last item(s) if over max
            self.sp._post(
                f"playlists/{self.playlist_id}/items",
                payload={"uris": [track_uri], "position": 0},
            )
            logger.info("Added to top of playlist: %s", track_uri)
            if len(current_uris) + 1 > self.max_size:
                excess_count = len(current_uris) + 1 - self.max_size
                # After the insert at 0, old items shifted by 1: old index i → new position i+1
                items_to_remove = [
                    {"uri": current_uris[self.max_size - 1 + i], "positions": [self.max_size + i]}
                    for i in range(excess_count)
                ]
                self.sp._delete(
                    f"playlists/{self.playlist_id}/items",
                    payload={"items": items_to_remove},
                )
                logger.info("Trimmed %d old track(s) from bottom", excess_count)
        else:
            # Reverse: newest at bottom, trim the first item(s) if over max
            self.sp._post(
                f"playlists/{self.playlist_id}/items",
                payload={"uris": [track_uri]},
            )
            logger.info("Added to bottom of playlist: %s", track_uri)
            if len(current_uris) + 1 > self.max_size:
                excess_count = len(current_uris) + 1 - self.max_size
                # Items at the top were not shifted (add was at end)
                items_to_remove = [
                    {"uri": current_uris[i], "positions": [i]}
                    for i in range(excess_count)
                ]
                self.sp._delete(
                    f"playlists/{self.playlist_id}/items",
                    payload={"items": items_to_remove},
                )
                logger.info("Trimmed %d old track(s) from top", excess_count)
