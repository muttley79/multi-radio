# multi-radio

Monitors multiple radio streams simultaneously, identifies songs via Shazam, and adds them to per-station Spotify playlists. Each station runs in its own thread with an isolated log file.

## Requirements

- Python 3.12+
- `ffmpeg` installed and on PATH

## Installation

### With uv (recommended)

```bash
uv venv .venv
uv pip install -r requirements.txt
```

### With pip

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuration

```bash
cp stations.yaml.example stations.yaml
```

Edit `stations.yaml` with your Spotify credentials and station details. See the example file for all available options.

To create a Spotify app and get credentials, visit the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).

## First run (OAuth)

On the first run, Spotipy will print an authorization URL. Open it in a browser, authorize the app, and paste the redirected URL back into the terminal. The token is cached in `.spotify_token_cache` for subsequent runs.

## Running

```bash
./start.sh   # starts in background, writes PID to radio-monitor.pid
./stop.sh    # stops the background process
```

Logs are written to `{station-name}.log` in this directory.

## Systemd service

```bash
sudo cp radio-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radio-monitor
```

## Skip hours

Per-station `skip_hours` pauses monitoring during talk shows or news blocks. Accepts comma-separated `HH:MM-HH:MM` ranges. Midnight-crossing ranges (e.g. `23:00-01:00`) are supported.
