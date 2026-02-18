import asyncio
import logging

from shazamio import Shazam

logger = logging.getLogger(__name__)


async def _identify(audio_file: str) -> dict | None:
    shazam = Shazam()
    result = await shazam.recognize(audio_file)

    matches = result.get("matches", [])
    if not matches:
        return None

    track = result.get("track")
    if not track:
        return None

    title = track.get("title", "")
    artist = track.get("subtitle", "")

    if title and artist:
        logger.info("Identified: %s - %s", artist, title)
        return {"artist": artist, "title": title}

    return None


def identify_song(audio_file: str) -> dict | None:
    """Identify a song from an audio file using Shazam.

    Returns {'artist': ..., 'title': ...} or None if unrecognized.
    """
    try:
        return asyncio.run(_identify(audio_file))
    except Exception as e:
        logger.error("Shazam identification error: %s", e)
        return None
