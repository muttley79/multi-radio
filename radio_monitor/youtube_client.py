import json
import logging
import os
import urllib.parse

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/youtube"]
_TOKEN_CACHE = ".youtube_token_cache.json"


def _get_credentials(client_id: str, client_secret: str) -> Credentials:
    """Load cached credentials or run OAuth flow."""
    creds = None
    if os.path.exists(_TOKEN_CACHE):
        with open(_TOKEN_CACHE) as f:
            creds = Credentials.from_authorized_user_info(json.load(f), _SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
        flow.redirect_uri = "http://localhost"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("\nYouTube authorization required.")
        print("Visit this URL on any device (phone/laptop):\n")
        print(f"  {auth_url}\n")
        print("After approving, your browser will redirect to http://localhost/... and fail to load.")
        print("That's expected — copy the full URL from the address bar and paste it below.\n")
        redirected = input("Paste the full redirect URL: ").strip()
        code = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query).get("code", [None])[0]
        if not code:
            raise ValueError("No authorization code found in the URL you pasted.")
        flow.fetch_token(code=code)
        creds = flow.credentials

    with open(_TOKEN_CACHE, "w") as f:
        f.write(creds.to_json())

    return creds


class YouTubePlaylistManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        playlist_id: str,
        max_size: int = 100,
        mode: str = "normal",
    ):
        self.playlist_id = playlist_id
        self.max_size = max_size
        self.mode = mode
        creds = _get_credentials(client_id, client_secret)
        self._yt = build("youtube", "v3", credentials=creds)

    def verify_auth(self) -> None:
        """Force an API call to trigger OAuth login if needed. Call at startup."""
        resp = self._yt.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        name = items[0]["snippet"]["title"] if items else "(unknown)"
        logger.info("Authenticated as YouTube user: %s", name)

    def search_track(self, artist: str, title: str) -> str | None:
        """Search YouTube for an official music video. Returns videoId or None."""
        query = f"{artist} {title} official music video"
        resp = (
            self._yt.search()
            .list(part="id", q=query, type="video", maxResults=1)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            logger.warning("YouTube search found nothing for: %s - %s", artist, title)
            return None
        video_id = items[0]["id"]["videoId"]
        logger.info("YouTube match: %s - %s → %s", artist, title, video_id)
        return video_id

    def _get_playlist_items(self) -> list[dict]:
        """Fetch all playlist items as raw API dicts (id + snippet)."""
        items = []
        page_token = None
        while True:
            kwargs = {
                "part": "id,snippet",
                "playlistId": self.playlist_id,
                "maxResults": 50,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._yt.playlistItems().list(**kwargs).execute()
            items.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    def get_last_track_uri(self) -> str | None:
        """Return the videoId at position 0 (most recently added in normal mode)."""
        items = self._get_playlist_items()
        if not items:
            return None
        return items[0]["snippet"]["resourceId"]["videoId"]

    def add_song(self, video_id: str) -> None:
        """Add a video to the playlist, respecting mode and max size.

        No dedup — the caller is responsible for the same-song check via get_last_track_uri().
        Trim removes by playlist item ID so duplicate videos in the playlist are handled correctly.
        """
        current_items = self._get_playlist_items()

        if self.mode == "normal":
            # Newest on top (position 0)
            self._yt.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": self.playlist_id,
                        "position": 0,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            logger.info("Added to top of YouTube playlist: %s", video_id)
            # Trim from bottom if over max
            if len(current_items) + 1 > self.max_size:
                excess = current_items[self.max_size - 1 :]
                for item in excess:
                    self._yt.playlistItems().delete(id=item["id"]).execute()
                logger.info("Trimmed %d old item(s) from YouTube playlist", len(excess))
        else:
            # Reverse: newest at bottom (no position = appends)
            self._yt.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": self.playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            logger.info("Added to bottom of YouTube playlist: %s", video_id)
            # Trim from top if over max
            if len(current_items) + 1 > self.max_size:
                excess = current_items[: len(current_items) + 1 - self.max_size]
                for item in excess:
                    self._yt.playlistItems().delete(id=item["id"]).execute()
                logger.info("Trimmed %d old item(s) from YouTube playlist", len(excess))
