# multi-radio

Monitors multiple radio streams simultaneously, identifies songs via Shazam, and adds them to per-station Spotify and/or YouTube playlists. Each station runs in its own thread with an isolated log file.

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

Edit `stations.yaml` with your credentials and station details. The full set of options:

```yaml
shared:
  # Spotify credentials — only required if any station uses spotify_playlist_id.
  # Create an app at https://developer.spotify.com/dashboard and set the redirect URI there.
  spotify_client_id: "your_client_id"
  spotify_client_secret: "your_client_secret"
  spotify_redirect_uri: "http://127.0.0.1:8888/callback"

  # YouTube credentials — only required if any station uses youtube_playlist_id.
  # Create an OAuth 2.0 Desktop app at https://console.cloud.google.com and copy the values below.
  youtube_client_id: "your_youtube_client_id"
  youtube_client_secret: "your_youtube_client_secret"

  sample_duration: 12      # seconds of audio to sample per cycle (default: 12)
  poll_interval: 300       # seconds between cycles (default: 300)
  playlist_max_size: 100   # oldest tracks trimmed when exceeded (default: 100)
  playlist_mode: "normal"  # "normal" = newest on top, "reverse" = newest at bottom
  log_max_bytes: 5242880   # max log file size in bytes (default: 5 MB)
  log_backup_count: 3      # number of rotated log files to keep (default: 3)

  # Dashboard (optional)
  dashboard_enabled: true  # set false to disable the web dashboard entirely (default: true)
  dashboard_port: 3001     # port for the LAN dashboard (default: 3001)

stations:
  - name: "station1"
    stream_url: "https://example.com/stream.m4a"
    spotify_playlist_id: "your_spotify_playlist_id"   # optional
    youtube_playlist_id: "PLxxxxxxxxxxxxxxxxxxxx"      # optional; at least one playlist required
    skip_hours: "mon-fri 07:00-09:30, sat 10:00-14:00"
    analytics: true                 # record plays to the dashboard database (default: true)
    analytics_retention_days: 30   # days of history to keep for this station (default: 30)
```

### Spotify credentials

Create a Spotify app at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Add `http://127.0.0.1:8888/callback` (or your chosen URI) as an allowed redirect URI in the app settings.

### YouTube credentials

Create an **OAuth 2.0 Client ID** of type **Desktop app** at [Google Cloud Console](https://console.cloud.google.com). Enable the **YouTube Data API v3** for your project, then copy the client ID and secret into `stations.yaml`.

Song search uses `yt-dlp` and does not consume YouTube Data API quota.

## First run (OAuth)

### Spotify

On the first run, Spotipy prints an authorization URL. Open it in a browser, authorize the app, and paste the redirected URL back into the terminal. The token is cached in `.spotify_token_cache` for subsequent runs.

### YouTube

On the first run, the app prints an authorization URL. Open it in a browser and authorize the app. Because the Desktop OAuth flow does not redirect automatically, copy the full URL from the browser address bar after authorization and paste it into the terminal. The token is cached in `.youtube_token_cache` for subsequent runs.

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

Per-station `skip_hours` pauses monitoring during talk shows or news blocks. Accepts a comma-separated list of time ranges, each with an optional day prefix.

| Format | Applies to |
|--------|-----------|
| `HH:MM-HH:MM` | Every day |
| `weekdays HH:MM-HH:MM` | Sun–Thu |
| `weekends HH:MM-HH:MM` | Fri–Sat |
| `fri HH:MM-HH:MM` | Single day |
| `mon-fri HH:MM-HH:MM` | Day range |
| `fri-mon HH:MM-HH:MM` | Wrapping day range (Fri → Mon) |

Midnight-crossing time ranges (e.g. `23:00-01:00`) are supported. Multiple entries can be combined with commas:

```yaml
skip_hours: "mon-fri 07:00-09:30, sat 10:00-14:00, 23:00-01:00"
```

## Playlist modes

Controlled by `playlist_mode` in `shared:` (or overridable per station):

- `normal` (default) — new tracks are inserted at the **top**; the oldest track is removed from the bottom when `playlist_max_size` is exceeded.
- `reverse` — new tracks are appended at the **bottom**; the oldest track is removed from the top when `playlist_max_size` is exceeded.

`playlist_max_size` defaults to 100. Set to a higher value or remove the key to allow unlimited growth.

## Dashboard

When at least one station has `analytics: true`, a lightweight web dashboard is available at `http://<host>:3001` (port configurable via `dashboard_port`). It shows:

- **Top Songs** — horizontal bar chart with a Spotify icon per row; green icons are clickable and open the track on Spotify.
- **Top Artists** — horizontal bar chart.
- **Plays by Hour** and **Plays by Day of Week** — bar charts.
- **Recent Plays** — live table of the last 50 plays.

A time-range toolbar lets you filter all charts to the last 7 days, 30 days, or all time. The page refreshes automatically every 5 minutes.

Play history is stored in a local SQLite database (`radio_analytics.db` by default). Each station retains its own history independently according to its `analytics_retention_days` setting — old rows for that station are pruned automatically on each new play. If all stations have `analytics: false`, neither the database nor the dashboard server is started.

## Duplicate handling

If a song is already the most recently added track on a playlist, it is not re-added immediately. The monitor waits at least **120 seconds** before attempting to add the same song again, preventing duplicate entries caused by repeated Shazam matches within a single poll cycle.
