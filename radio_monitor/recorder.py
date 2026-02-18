import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT_EXTRA = 15  # extra seconds beyond sample duration before killing ffmpeg


def record_sample(stream_url: str, duration: int) -> str | None:
    """Record audio from stream URL using ffmpeg. Returns path to temp MP3 file, or None on failure."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-re",
        "-i", stream_url,
        "-t", str(duration),
        "-acodec", "libmp3lame",
        "-ar", "44100",
        "-ac", "1",
        "-loglevel", "error",
        tmp.name,
    ]

    timeout = duration + FFMPEG_TIMEOUT_EXTRA
    try:
        subprocess.run(cmd, timeout=timeout, check=True, capture_output=True)
        logger.info("Recorded %ds sample to %s", duration, tmp.name)
        return tmp.name
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out after %ds", timeout)
        return None
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg failed: %s", e.stderr.decode(errors="replace").strip())
        return None
    except FileNotFoundError:
        logger.error("ffmpeg not found — install it with: apt install ffmpeg")
        return None
