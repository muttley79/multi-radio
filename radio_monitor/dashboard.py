import json
import logging
import threading

from flask import Flask, Response, jsonify, request

from radio_monitor.database import RadioDatabase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded HTML template.
# %%STATION%%  is replaced with the JSON-encoded station name (null or "name")
# %%STATIONS%% is replaced with the JSON-encoded list of all station names
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radio Monitor Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f0f2f5; color: #222; }
header {
  background: #1a1a2e; color: #eee;
  padding: 0.8rem 1.5rem;
  display: flex; align-items: center; gap: 2rem; flex-wrap: wrap;
}
header h1 { font-size: 1.15rem; white-space: nowrap; }
nav a {
  color: #adf; text-decoration: none;
  padding: 0.25rem 0.75rem; border-radius: 4px;
  transition: background 0.15s;
}
nav a.active, nav a:hover { background: rgba(255,255,255,0.2); color: white; }
.toolbar {
  padding: 0.5rem 1.5rem; background: white; border-bottom: 1px solid #ddd;
  display: flex; gap: 0.5rem; align-items: center;
}
.toolbar label { font-size: 0.85rem; color: #666; margin-right: 0.2rem; }
button.range {
  padding: 0.2rem 0.75rem; border: 1px solid #ccc; background: white;
  border-radius: 4px; cursor: pointer; font-size: 0.85rem; transition: all 0.15s;
}
button.range.active, button.range:hover {
  background: #1a1a2e; color: white; border-color: #1a1a2e;
}
.charts {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1rem; padding: 1rem 1.5rem;
}
@media (max-width: 800px) { .charts { grid-template-columns: 1fr; } }
.card {
  background: white; border-radius: 8px; padding: 1.2rem;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.card h2 {
  font-size: 0.8rem; color: #888; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 0.8rem;
}
.chart-wrap { position: relative; }
.chart-wrap-hbar { height: 540px; }
.chart-wrap-bar  { height: 260px; }
.recent {
  margin: 0 1.5rem 1.5rem; background: white; border-radius: 8px;
  padding: 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,0.08); overflow-x: auto;
}
.recent-hdr {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.8rem;
}
.recent-hdr h2 {
  font-size: 0.8rem; color: #888; text-transform: uppercase; letter-spacing: 0.06em;
}
#lastUpdate { font-size: 0.75rem; color: #aaa; }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th {
  text-align: left; padding: 0.35rem 0.6rem; border-bottom: 2px solid #eee;
  color: #888; font-size: 0.78rem; text-transform: uppercase; font-weight: 600;
}
td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #f0f0f0; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafbfc; }
.empty { text-align: center; padding: 2rem; color: #bbb; font-size: 0.9rem; }
#statusBar { padding: 0.3rem 1.5rem 1rem; font-size: 0.75rem; color: #aaa; min-height: 1.4rem; }
</style>
</head>
<body>
<header>
  <h1>&#128251; Radio Monitor</h1>
  <nav id="stationNav"></nav>
</header>
<div class="toolbar">
  <label>Time range:</label>
  <button class="range" data-days="7">7 days</button>
  <button class="range" data-days="30">30 days</button>
  <button class="range active" data-days="">All time</button>
</div>
<div class="charts">
  <div class="card">
    <h2>Top Songs</h2>
    <div class="chart-wrap chart-wrap-hbar"><canvas id="topSongs"></canvas></div>
  </div>
  <div class="card">
    <h2>Top Artists</h2>
    <div class="chart-wrap chart-wrap-hbar"><canvas id="topArtists"></canvas></div>
  </div>
  <div class="card">
    <h2>Plays by Hour of Day (UTC)</h2>
    <div class="chart-wrap chart-wrap-bar"><canvas id="hourChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Plays by Day of Week</h2>
    <div class="chart-wrap chart-wrap-bar"><canvas id="dowChart"></canvas></div>
  </div>
</div>
<div class="recent">
  <div class="recent-hdr">
    <h2>Recent Plays</h2>
    <span id="lastUpdate"></span>
  </div>
  <table>
    <thead>
      <tr><th>Time (UTC)</th><th>Station</th><th>Artist</th><th>Title</th></tr>
    </thead>
    <tbody id="recentBody">
      <tr><td colspan="4" class="empty">Loading&hellip;</td></tr>
    </tbody>
  </table>
</div>
<div id="statusBar"></div>
<script>
const STATION  = %%STATION%%;
const STATIONS = %%STATIONS%%;
const charts   = {};

// --- Nav ---
const nav = document.getElementById('stationNav');
[{name: null, label: 'All'}, ...STATIONS.map(s => ({name: s, label: s}))].forEach(item => {
  const a = document.createElement('a');
  a.href = item.name ? '/' + item.name : '/';
  a.textContent = item.label;
  if ((item.name === null && STATION === null) || item.name === STATION) a.className = 'active';
  nav.appendChild(a);
});

// --- Time range ---
let currentDays = null;
document.querySelectorAll('.range').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = btn.dataset.days || null;
    loadAll();
  });
});

function buildUrl(path, extra) {
  const p = new URLSearchParams();
  if (STATION)     p.set('station', STATION);
  if (currentDays) p.set('days',    currentDays);
  if (extra) Object.entries(extra).forEach(([k, v]) => p.set(k, v));
  const qs = p.toString();
  return qs ? path + '?' + qs : path;
}

// --- Spotify helpers ---
function spotifyUrl(uri) {
  return 'https://open.spotify.com/track/' + uri.replace('spotify:track:', '');
}

function makeSvgImg(fill) {
  const svg = '<svg viewBox="0 0 168 168" xmlns="http://www.w3.org/2000/svg">'
    + '<circle cx="84" cy="84" r="84" fill="' + fill + '"/>'
    + '<path fill="white" d="M120.6 115.5c-1.5 2.5-4.8 3.3-7.3 1.8-19.9-12.2-45.1-15'
    + '-74.7-8.2-2.9.7-5.8-1.1-6.4-4-.7-2.9 1.1-5.8 4-6.4 32.4-7.4 60.2-4.2 82.7 9.5'
    + ' 2.5 1.5 3.3 4.8 1.8 7.3zm9.8-21.9c-1.9 3.1-6 4.1-9.1 2.2-22.8-14-57.5-18.1'
    + '-84.5-9.9-3.5 1.1-7.2-.9-8.3-4.4-1.1-3.5.9-7.2 4.4-8.3 30.8-9.3 69.1-4.8 95.3'
    + ' 11.3 3.1 1.9 4.1 6 2.2 9.1zm.8-22.8C103.7 53.2 62 51.7 38.7 59.1c-4.2 1.3'
    + '-8.6-1-9.9-5.2-1.3-4.2 1-8.6 5.2-9.9 26.9-8.2 71.6-6.6 99.8 11 3.8 2.3 5 7.2'
    + ' 2.7 11-.2.3-.4.6-.6.8-2.3 3.6-7.2 4.7-10.7 2.4z"/></svg>';
  const img = new Image(14, 14);
  img.src = 'data:image/svg+xml;base64,' + btoa(svg);
  return img;
}
const SP_GREEN = makeSvgImg('#1DB954');
const SP_GRAY  = makeSvgImg('#bbbbbb');

// --- Charts ---
function destroyChart(id) {
  if (charts[id]) {
    const canvas = charts[id].canvas;
    if (canvas._spClick) canvas.removeEventListener('click', canvas._spClick);
    if (canvas._spMove) canvas.removeEventListener('mousemove', canvas._spMove);
    charts[id].destroy();
    delete charts[id];
  }
}

function makeHBar(id, labels, data, color) {
  destroyChart(id);
  if (!labels.length) return;
  const ctx = document.getElementById(id).getContext('2d');
  charts[id] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color, borderRadius: 3 }] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

function makeSongHBar(id, songs, color) {
  destroyChart(id);
  if (!songs.length) return;
  const labels = songs.map(s => s.artist + ' \u2014 ' + s.title).reverse();
  const counts = songs.map(s => s.count).reverse();
  const uris   = songs.map(s => s.spotify_uri || null).reverse();
  const canvas  = document.getElementById(id);
  const ctx     = canvas.getContext('2d');

  const spPlugin = {
    id: 'spIcons',
    afterDraw(chart) {
      const ctx2 = chart.ctx;
      chart.data.datasets[0].data.forEach((count, i) => {
        const meta = chart.getDatasetMeta(0);
        const bar  = meta.data[i];
        const x    = chart.scales.x.getPixelForValue(count) + 4;
        const y    = bar.y - 7;
        ctx2.drawImage(uris[i] ? SP_GREEN : SP_GRAY, x, y, 14, 14);
      });
    }
  };

  charts[id] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data: counts, backgroundColor: color, borderRadius: 3 }] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 22 } },
      plugins: { legend: { display: false } },
      scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
    },
    plugins: [spPlugin],
  });

  // Icon hit-test helper: returns uri if click/move is over a green icon, else null
  function iconUri(e) {
    if (!charts[id]) return null;
    const chart = charts[id];
    const rect  = canvas.getBoundingClientRect();
    const cx    = e.clientX - rect.left;
    const cy    = e.clientY - rect.top;
    const meta  = chart.getDatasetMeta(0);
    for (let i = 0; i < counts.length; i++) {
      if (!uris[i]) continue;
      const bar = meta.data[i];
      const ix  = chart.scales.x.getPixelForValue(counts[i]) + 4;
      const iy  = bar.y - 7;
      if (cx >= ix && cx <= ix + 14 && cy >= iy && cy <= iy + 14) return uris[i];
    }
    return null;
  }

  canvas._spClick = function(e) {
    const uri = iconUri(e);
    if (uri) window.open(spotifyUrl(uri), '_blank');
  };
  canvas._spMove = function(e) {
    canvas.style.cursor = iconUri(e) ? 'pointer' : 'default';
  };
  canvas.addEventListener('click', canvas._spClick);
  canvas.addEventListener('mousemove', canvas._spMove);
}

function makeBar(id, labels, data, color) {
  destroyChart(id);
  const ctx = document.getElementById(id).getContext('2d');
  charts[id] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color, borderRadius: 3 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

// --- Data loading ---
async function loadStats() {
  document.getElementById('statusBar').textContent = 'Loading\u2026';
  try {
    const res  = await fetch(buildUrl('/api/stats'));
    if (!res.ok) throw new Error(res.statusText);
    const d    = await res.json();

    makeSongHBar('topSongs', d.top_songs, '#4a6fa5');

    const artistLabels = d.top_artists.map(a => a.artist).reverse();
    const artistCounts = d.top_artists.map(a => a.count).reverse();
    makeHBar('topArtists', artistLabels, artistCounts, '#e07b39');

    makeBar('hourChart',
      d.plays_by_hour.map(h => h.hour + ':00'),
      d.plays_by_hour.map(h => h.count),
      '#5ab4ac');

    makeBar('dowChart',
      d.plays_by_dow.map(item => item.label),
      d.plays_by_dow.map(item => item.count),
      '#8b7bb1');

    document.getElementById('statusBar').textContent = '';
  } catch (e) {
    document.getElementById('statusBar').textContent = 'Error loading stats: ' + e.message;
  }
}

async function loadRecent() {
  try {
    const res  = await fetch(buildUrl('/api/recent', {limit: 50}));
    if (!res.ok) throw new Error(res.statusText);
    const rows = await res.json();
    const tbody = document.getElementById('recentBody');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">No plays recorded yet.</td></tr>';
    } else {
      tbody.innerHTML = rows.map(r => {
        const t = r.played_at.replace('T', ' ');
        return '<tr><td>' + t + '</td><td>' + r.station + '</td><td>' + r.artist + '</td><td>' + r.title + '</td></tr>';
      }).join('');
    }
    document.getElementById('lastUpdate').textContent =
      'updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error('Recent plays error:', e);
  }
}

function loadAll() { loadStats(); loadRecent(); }
loadAll();
setInterval(loadAll, 5 * 60 * 1000);
</script>
</body>
</html>
"""


class DashboardServer:
    def __init__(self, db: RadioDatabase, host: str, port: int, station_names: list[str]):
        self._db = db
        self._host = host
        self._port = port
        self._station_names = station_names
        self._app = self._build_app()

    def _render(self, station) -> str:
        return (
            _HTML_TEMPLATE
            .replace("%%STATION%%",  json.dumps(station))
            .replace("%%STATIONS%%", json.dumps(self._station_names))
        )

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        db = self._db

        @app.route("/")
        def index():
            return Response(self._render(None), mimetype="text/html")

        for sname in self._station_names:
            def _make_view(name):
                def view():
                    return Response(self._render(name), mimetype="text/html")
                view.__name__ = f"station_{name}"
                return view
            app.add_url_rule(f"/{sname}", endpoint=f"station_{sname}", view_func=_make_view(sname))

        @app.route("/api/stats")
        def api_stats():
            station  = request.args.get("station") or None
            days_raw = request.args.get("days", "")
            days     = int(days_raw) if days_raw.isdigit() else None
            return jsonify({
                "top_songs":    db.top_songs(station=station, days=days),
                "top_artists":  db.top_artists(station=station, days=days),
                "plays_by_hour": db.plays_by_hour(station=station, days=days),
                "plays_by_dow": db.plays_by_dow(station=station, days=days),
            })

        @app.route("/api/recent")
        def api_recent():
            station   = request.args.get("station") or None
            limit_raw = request.args.get("limit", "50")
            limit     = int(limit_raw) if limit_raw.isdigit() else 50
            return jsonify(db.recent_plays(station=station, limit=limit))

        return app

    def start(self) -> None:
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.WARNING)

        thread = threading.Thread(
            target=lambda: self._app.run(
                host=self._host,
                port=self._port,
                threaded=True,
                use_reloader=False,
                debug=False,
            ),
            name="dashboard",
            daemon=True,
        )
        thread.start()
        logger.info("Dashboard running on http://%s:%d", self._host, self._port)
