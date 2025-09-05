#!/usr/bin/env python3
"""
SprinklerFreedom - Blossom local control UI (minutes-based)
- Friendly scheduler (time picker + day checkboxes), Sun–Sat calendar.
- Weather skip via Open-Meteo. Shows next 7 days precip probability.
- Two-row / seven-column forecast (Weekday above, M-D + % below), starting at TODAY.
- Simple LAN discovery of Blossom (no external deps).
- Works on Windows/macOS/Linux; same file runs on Raspberry Pi.

Dependencies:
    pip install flask apscheduler requests
"""

from flask import Flask, request, render_template_string, redirect, url_for, jsonify
import requests, json, time, threading, ipaddress, socket, argparse, os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, date  # for nice forecast labels & rotation

DEFAULT_HOST = "127.0.0.1"   # use 0.0.0.0 to allow LAN access
DEFAULT_PORT = 5000          # on Pi you can use 80 with systemd/root

CONF_FILE  = "config.json"
SCHED_FILE = "schedules.json"

app   = Flask(__name__)
sched = BackgroundScheduler(daemon=True)

# ---------------------------- Config helpers ----------------------------

def load_conf():
    if not os.path.exists(CONF_FILE):
        # Defaults use Rexburg, ID
        return {
            "blossom_ip": "",
            "use_master": False,
            "master_valve": 13,     # NEW: configurable master valve number
            "zones": list(range(1, 9)),
            # weather skip defaults
            "enable_weather_skip": True,
            "rain_prob_threshold": 50,  # percent
            "latitude": 43.8260,        # Rexburg
            "longitude": -111.7897
        }
    with open(CONF_FILE, "r") as f:
        return json.load(f)

def save_conf(cfg):
    with open(CONF_FILE, "w") as f:
        json.dump(cfg, f)

def load_sched():
    if not os.path.exists(SCHED_FILE):
        return []
    with open(SCHED_FILE, "r") as f:
        return json.load(f)

def save_sched(s):
    with open(SCHED_FILE, "w") as f:
        json.dump(s, f)

# ---------------------------- Blossom API ----------------------------

def blossom_url(path: str) -> str:
    ip = load_conf().get("blossom_ip", "").strip()
    if not ip:
        raise RuntimeError("Blossom IP not set (open Settings first).")
    return f"http://{ip}{path}"

def blossom_post(path: str, payload: dict) -> bool:
    try:
        requests.post(blossom_url(path), json=payload, timeout=3)
        return True
    except Exception:
        return False

def all_off():
    # valve 0 + inverter 0 = turn everything off
    blossom_post("/bloom/valve", {"valve": 0, "inverter": 0})

def run_zone(zone: int, seconds: int, use_master: bool | None = None):
    cfg = load_conf()
    if use_master is None:
        use_master = cfg.get("use_master", False)
    if use_master:
        mv = int(cfg.get("master_valve", 13))
        if mv > 0:
            blossom_post("/bloom/valve", {"valve": mv, "inverter": 1})  # PSR/Master
    blossom_post("/bloom/valve", {"valve": int(zone), "inverter": 1})
    time.sleep(max(1, int(seconds)))
    all_off()

# ---------------------------- Weather (Open-Meteo) ----------------------------

def fetch_rain_probs(lat: float, lon: float):
    """
    Returns (dates, probs) for the next 7 days (ISO date string, % probability).
    If unavailable, returns ([], []).
    """
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=precipitation_probability_max"
            "&forecast_days=7"
            "&timezone=auto"
        )
        headers = {"User-Agent": "SprinklerFreedom/1.0 (+local)"}
        r = requests.get(url, timeout=10, headers=headers)
        r.raise_for_status()
        js = r.json()
        probs = js.get("daily", {}).get("precipitation_probability_max", []) or []
        dates = js.get("daily", {}).get("time", []) or []
        n = min(7, len(dates), len(probs))
        return dates[:n], probs[:n]
    except Exception as e:
        print(f"[weather] fetch failed: {e}")
        return [], []

def should_skip_today_by_weather():
    cfg = load_conf()
    if not cfg.get("enable_weather_skip", False):
        return (False, "weather skip disabled")
    lat = cfg.get("latitude"); lon = cfg.get("longitude")
    thr = int(cfg.get("rain_prob_threshold", 50))
    dates, probs = fetch_rain_probs(lat, lon)
    if not probs:
        # Fail open: if weather API fails, don't skip watering
        return (False, "weather data unavailable")
    prob = int(probs[0])  # today's probability
    if prob >= thr:
        return (True, f"rain prob {prob}% ≥ {thr}%")
    return (False, f"rain prob {prob}% < {thr}%")

# ---------------------------- Discovery (stdlib) ----------------------------

def get_local_ip_guess() -> str:
    """Get our primary LAN IP by opening a UDP socket (no traffic sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.100"

def guess_subnets():
    """Return a few /24s to scan quickly (our /24 + common home LANs)."""
    ip = get_local_ip_guess()
    nets = set()
    try:
        ipaddress.IPv4Address(ip)
        nets.add(str(ipaddress.IPv4Network(f"{ip}/255.255.255.0", strict=False)))
    except Exception:
        pass
    for n in ("192.168.0.0/24", "192.168.1.0/24", "10.0.0.0/24"):
        nets.add(n)
    return [ipaddress.IPv4Network(n) for n in nets]

def is_blossom(ip: str) -> bool:
    try:
        r = requests.get(f"http://{ip}/bloom.js", timeout=0.5)
        return r.status_code == 200
    except Exception:
        return False

def discover_blossom():
    hits = []
    for net in guess_subnets():
        for host in net.hosts():
            s = str(host)
            if s.endswith(".0") or s.endswith(".255"):
                continue
            if is_blossom(s):
                hits.append(s)
        if hits:
            break
    return hits

# ---------------------------- Scheduler ----------------------------

def install_jobs():
    """Install cron-triggered jobs, each guarded by the weather check."""
    sched.remove_all_jobs()
    for i, sch in enumerate(load_sched()):
        minutes = float(sch["minutes"]) if isinstance(sch["minutes"], (int, float, str)) else 0
        seconds = int(float(minutes) * 60)
        zone = int(sch["zone"])
        trig = CronTrigger.from_crontab(sch["cron"])  # may raise, which is OK

        def make_guarded(z=zone, secs=seconds, mins=minutes):
            def _job():
                skip, reason = should_skip_today_by_weather()
                if skip:
                    print(f"[weather-skip] Z{z} skipped: {reason}")
                    return
                print(f"[run] Z{z} for {secs}s ({mins} min). Weather OK: {reason}")
                run_zone(z, secs, None)
            return _job

        sched.add_job(make_guarded(), trigger=trig, id=f"job{i}")

# ---------------------------- UI Template ----------------------------

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SprinklerFreedom</title>
<style>
:root{
  --bg:#f7f8fa; --card:#ffffff; --ink:#0f172a; --muted:#64748b; --ring:#e5e7eb;
  --accent:#22c55e; --chip:#f1f5f9;
}
.dark{ --bg:#0b1220; --card:#0f172a; --ink:#e2e8f0; --muted:#94a3b8; --ring:#162235; --accent:#22c55e; --chip:#0b1628; }
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink);margin:0}

/* Header */
.header{position:sticky;top:0;z-index:10;background:linear-gradient(180deg,rgba(34,197,94,.08),transparent 90%),var(--bg);border-bottom:1px solid var(--ring);backdrop-filter:blur(6px)}
.header-inner{max-width:1000px;margin:0 auto;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;color:white;background:radial-gradient(80% 90% at 20% 15%,#86efac,#22c55e);box-shadow:0 6px 20px rgba(34,197,94,.35),inset 0 0 12px rgba(255,255,255,.18);font-weight:700}
.brand h1{font-size:18px;margin:0}
.small{color:var(--muted);font-size:.92rem}

/* Tabs */
.container{max-width:1000px;margin:0 auto;padding:16px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.tab-btn{
  appearance:none;border:1px solid var(--ring);background:var(--card);color:var(--ink);
  padding:10px 14px;border-radius:12px;cursor:pointer;font-weight:600;
}
.tab-btn.active{background:var(--accent);color:#062a1e;border-color:transparent;box-shadow:0 6px 16px rgba(34,197,94,.3)}
.panel{background:var(--card);border:1px solid var(--ring);border-radius:16px;padding:16px;box-shadow:0 10px 25px rgba(2,6,23,.08);display:none}
.panel.active{display:block}

/* Forms */
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
label{display:flex;flex-direction:column;gap:6px;font-size:.92rem}
input,select,button{
  font:inherit;border:1px solid var(--ring);background:#fff;color:var(--ink);padding:10px 12px;border-radius:10px
}
.dark input,.dark select{background:#0b1628;border-color:#1f2b40;color:var(--ink)}
input[type="number"]{width:8em} input[type="time"]{width:10em}
.btn{background:var(--accent);color:#062a1e;font-weight:700;border:none;cursor:pointer;padding:10px 14px;border-radius:10px;box-shadow:0 6px 16px rgba(34,197,94,.35)}
.btn.secondary{background:transparent;color:var(--ink);border:1px solid var(--ring);box-shadow:none}
.btn.danger{background:#ef4444;color:white;box-shadow:0 6px 16px rgba(239,68,68,.35)}
.pill{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--chip);border:1px solid var(--ring);padding:8px 10px;border-radius:12px}

/* Forecast */
.forecast7{display:grid;grid-template-rows:auto auto;gap:8px;margin-top:8px}
.forecast7 .row{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}
.forecast7 .cell{background:var(--chip);border:1px solid var(--ring);border-radius:12px;padding:10px;text-align:center}
.forecast7 .dow{font-weight:700}
.forecast7 .md{font-variant-numeric:tabular-nums;font-weight:600}
.forecast7 .pct{font-size:.9rem;color:var(--muted)}

/* Schedule calendar */
.sched-grid{display:grid;grid-template-columns:140px repeat(7,1fr);grid-auto-rows:minmax(72px,auto);gap:8px;margin-top:14px}
.sched-grid .head{font-weight:700;border-bottom:1px solid var(--ring);padding:8px}
.sched-grid .zcell{background:var(--chip);border:1px solid var(--ring);border-radius:12px;padding:10px;font-weight:700;display:flex;flex-direction:column;gap:8px;align-items:center;justify-content:center}
.sched-grid .ztools{display:flex;gap:8px}
.sched-grid .cell{background:var(--card);border:1px solid var(--ring);border-radius:12px;padding:10px;min-height:64px}
.sched-grid .entry{display:flex;gap:8px;align-items:center;justify-content:flex-start;background:var(--chip);border:1px solid var(--ring);border-radius:10px;padding:6px 8px;margin:6px 0}
.sched-grid .entry .label{font-size:.92rem}
.sched-grid .entry form{margin:0}
.sched-grid .entry button{padding:4px 8px;border-radius:8px}
.sched-grid .head{font-weight:700;border-bottom:1px solid var(--ring);padding:8px}
.sched-grid .zcell{background:var(--chip);border:1px solid var(--ring);border-radius:12px;padding:10px;font-weight:700;display:flex;align-items:center;justify-content:center}
.sched-grid .cell{background:var(--card);border:1px solid var(--ring);border-radius:12px;padding:10px;min-height:64px}
.sched-grid .entry{display:flex;gap:8px;align-items:center;justify-content:space-between;background:var(--chip);border:1px solid var(--ring);border-radius:10px;padding:6px 8px;margin:6px 0}
.sched-grid .entry .label{font-size:.92rem}
.sched-grid .entry form{margin:0}
.sched-grid .entry button{padding:4px 8px;border-radius:8px}

/* Footer note */
.note{color:var(--muted);font-size:.9rem;margin-top:10px}

/* Toggle */
.toggle{display:flex;align-items:center;gap:8px}
.switch{width:44px;height:26px;border-radius:20px;background:#d1fae5;position:relative;transition:.2s;border:1px solid #a7f3d0}
.switch::after{content:"";position:absolute;top:2px;left:2px;width:22px;height:22px;border-radius:50%;background:#10b981;transition:.2s;box-shadow:0 1px 6px rgba(0,0,0,.25)}
.switch.on{background:#1f2937;border-color:#0b1220}
.switch.on::after{left:20px;background:#111827}
/* Modal */
.modal{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(2,6,23,.5);z-index:50}
.modal.hidden{display:none}
.modal .card{background:var(--card);border:1px solid var(--ring);border-radius:16px;box-shadow:0 20px 50px rgba(2,6,23,.25);max-width:520px;width:92%;padding:16px}
.modal .card h4{margin:0 0 8px 0}
.modal .row{margin-top:10px;display:flex;justify-content:center;align-items:center;gap:12px}
</style>
</head>
<body>
  <div class="header">
    <div class="header-inner">
      <div class="brand">
        <div class="logo">SF</div>
        <div>
          <h1>SprinklerFreedom</h1>
          <div class="small">Local Blossom control • minutes-based • weather-aware</div>
        </div>
      </div>
      <div class="toggle">
        <span class="small">Dark</span>
        <div id="themeSwitch" class="switch" role="switch" aria-checked="false" tabindex="0"></div>
      </div>
    </div>
  </div>

  <div class="container">
    <!-- TAB HEADERS -->
    <nav class="tabs" role="tablist">
      <button class="tab-btn" data-tab="welcome" role="tab" aria-controls="panel-welcome">Welcome / Settings</button>
      <button class="tab-btn" data-tab="manual"  role="tab" aria-controls="panel-manual">Manual</button>
      <button class="tab-btn" data-tab="schedule" role="tab" aria-controls="panel-schedule">Schedule</button>
      <button class="tab-btn" data-tab="donate"  role="tab" aria-controls="panel-donate">Donate</button>
    </nav>

    <!-- WELCOME / SETTINGS -->
    <section id="panel-welcome" class="panel" role="tabpanel">
      <h3>Welcome</h3>
      <p class="small">How it works: set your Blossom IP, (optional) enable weather-skip using a % chance of rain, then use the Manual tab to test a zone or the Schedule tab to automate. Durations are in minutes (decimals allowed).</p>

      <h3 style="margin-top:14px">Settings</h3>
      <form method="POST" action="{{ url_for('save_settings') }}" class="row">
        <label>Blossom IP<input name="blossom_ip" value="{{ cfg.blossom_ip }}" placeholder="e.g. 192.168.1.132"></label>
        <label>Use Master
          <select name="use_master">
            <option value="false" {% if not cfg.use_master %}selected{% endif %}>No</option>
            <option value="true"  {% if cfg.use_master %}selected{% endif %}>Yes</option>
          </select>
        </label>
        <label>Master Valve #
          <input name="master_valve" type="number" min="-1" max="31" step="1" value="{{ cfg.master_valve }}">
        </label>
        <label>Weather skip
          <select name="enable_weather_skip">
            <option value="true"  {% if cfg.enable_weather_skip %}selected{% endif %}>On</option>
            <option value="false" {% if not cfg.enable_weather_skip %}selected{% endif %}>Off</option>
          </select>
        </label>
        <label>Rain prob ≥ (%)<input name="rain_prob_threshold" type="number" min="0" max="100" step="1" value="{{ cfg.rain_prob_threshold }}"></label>
        <label>Lat<input name="latitude" type="number" step="0.0001" value="{{ cfg.latitude }}"></label>
        <label>Lon<input name="longitude" type="number" step="0.0001" value="{{ cfg.longitude }}"></label>
        <button class="btn" type="submit">Save</button>
        <button class="btn secondary" formaction="{{ url_for('discover') }}" formmethod="POST">Auto-discover</button>
        <!-- Weather test button removed from UI (use /weathercheck route) -->
      </form>

      {% if discovered %}<p>Found:
        {% for ip in discovered %}<span class="pill"><strong>{{ip}}</strong></span>{% endfor %}
      </p>{% endif %}

      {% if weather_status %}<p class="small">{{ weather_status }}</p>{% endif %}

      {% if forecast_fmt and forecast_fmt|length > 0 %}
        <h4 style="margin-top:10px">7-day precipitation chance</h4>
        <div class="forecast7">
          <div class="row">
            {% for f in forecast_fmt %}
              <div class="cell"><div class="dow">{{ f.dow }}</div></div>
            {% endfor %}
          </div>
          <div class="row">
            {% for f in forecast_fmt %}
              <div class="cell">
                <div class="md">{{ f.md }}</div>
                <div class="pct">{{ f.pct }}%</div>
              </div>
            {% endfor %}
          </div>
        </div>
      {% else %}
        <p class="small">No forecast data available right now.</p>
      {% endif %}
      <p class="note">Tip: reserve static DHCP leases for the Blossom and this server, so the IPs don’t change.</p>
    </section>

    <!-- MANUAL -->
    <section id="panel-manual" class="panel" role="tabpanel">
      <h3>Manual Control</h3>
      <form method="POST" action="{{ url_for('manual') }}" class="row">
        <label>Zone
          <select name="zone">
            {% for z in zones %}<option value="{{z}}">Zone {{z}}</option>{% endfor %}
          </select>
        </label>
        <label>Minutes<input name="minutes" type="number" value="1.0" min="0.1" step="0.1"></label>
        <button class="btn" type="submit">Start</button>
        <button class="btn danger" formaction="{{ url_for('alloff_route') }}" formmethod="POST">All OFF</button>
      </form>
    </section>

    <!-- SCHEDULE -->
    <section id="panel-schedule" class="panel" role="tabpanel">
      <h3>Schedules</h3>
      <p class="small">Pick days + time. We’ll build the cron automatically.</p>

      <form id="addForm" method="POST" action="{{ url_for('add_schedule') }}" class="row" onsubmit="return buildCron();">
        <label>Zone
          <select name="zone">
            {% for z in zones %}<option value="{{z}}">Zone {{z}}</option>{% endfor %}
          </select>
        </label>
        <label>Minutes<input name="minutes" id="minutes" type="number" value="5.0" min="0.1" step="0.1"></label>
        <label>Start Time<input id="tod" type="time" value="06:00" step="60"></label>

        <div style="display:flex;flex-direction:column;gap:6px">
          <span class="small">Days</span>
          <div class="row">
            <label><input type="checkbox" class="dow" value="0">Sun</label>
            <label><input type="checkbox" class="dow" value="1" checked>Mon</label>
            <label><input type="checkbox" class="dow" value="2" checked>Tue</label>
            <label><input type="checkbox" class="dow" value="3" checked>Wed</label>
            <label><input type="checkbox" class="dow" value="4" checked>Thu</label>
            <label><input type="checkbox" class="dow" value="5" checked>Fri</label>
            <label><input type="checkbox" class="dow" value="6">Sat</label>
          </div>
        </div>

        <input type="hidden" name="cron" id="cron">
        <input type="hidden" name="override" id="overrideFlag" value="0">
        <button class="btn" type="submit">Add</button>
      </form>

      <div id="schedGrid"></div>

      <!-- Conflict modal -->
      <div id="conflictModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="conflictTitle">
        <div class="card">
          <h4 id="conflictTitle">Schedule conflict</h4>
          <p class="small">A schedule for this zone already exists at the same time on at least one selected day. Do you want to replace the existing entry/entries?</p>
          <div class="row">
            <label style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="dontAsk"> Don't ask again (always replace)</label>
          </div>
          <div class="row" style="display:flex;gap:8px;justify-content:flex-end">
            <button class="btn secondary" type="button" id="modalCancel">Cancel</button>
            <button class="btn" type="button" id="modalConfirm">Replace</button>
          </div>
        </div>
      </div>
    </section>

    <!-- DONATE -->
    <section id="panel-donate" class="panel" role="tabpanel">
      <h3>Support This Project</h3>
      <p class="small">If this tool saved your Blossom from e-waste, consider buying me a coffee</p>
      <p>
        <!-- Replace the href with your link -->
        <a class="btn" href="https://www.buymeacoffee.com/" target="_blank" rel="noopener">Buy me a coffee</a>
        <button class="btn secondary" onclick="navigator.clipboard.writeText(window.location.href);alert('URL copied!')">Share this page</button>
      </p>
      <p class="note">Open-source spirit: keep your hardware useful.</p>
    </section>

    <p class="note">Posts to <code>/bloom/valve</code> on your Blossom. Keep both devices on the same LAN (DHCP reservation recommended).</p>
  </div>

<script>
// Theme toggle
const savedTheme = localStorage.getItem("sf-theme");
if(savedTheme==="dark") document.body.classList.add("dark");
const sw = document.getElementById("themeSwitch");
function syncSwitch(){ sw.classList.toggle("on", document.body.classList.contains("dark")); sw.setAttribute("aria-checked", document.body.classList.contains("dark")); }
syncSwitch();
sw.onclick = ()=>{ document.body.classList.toggle("dark"); localStorage.setItem("sf-theme", document.body.classList.contains("dark")?"dark":"light"); syncSwitch(); };
sw.onkeydown = (e)=>{ if(e.key===" "||e.key==="Enter"){ e.preventDefault(); sw.click(); }};

// Tabs
const tabs = Array.from(document.querySelectorAll(".tab-btn"));
const panels = {
  welcome: document.getElementById("panel-welcome"),
  manual:  document.getElementById("panel-manual"),
  schedule:document.getElementById("panel-schedule"),
  donate:  document.getElementById("panel-donate"),
};
function showTab(name){
  tabs.forEach(t=>t.classList.toggle("active", t.dataset.tab===name));
  Object.entries(panels).forEach(([k,el])=>el.classList.toggle("active", k===name));
  localStorage.setItem("sf-tab", name);
  // focus first heading for a11y
  const h = panels[name].querySelector("h3"); if(h) h.focus?.();
}
tabs.forEach(t=>t.addEventListener("click", ()=>showTab(t.dataset.tab)));
const startTab = localStorage.getItem("sf-tab") || "welcome";
showTab(startTab);

// Build cron from day checkboxes + time input
function getSelectedDows(){
  return Array.from(document.querySelectorAll('.dow')).filter(b => b.checked).map(b => parseInt(b.value,10));
}
function buildCron(){
  const form = document.getElementById('addForm');
  const tod = document.getElementById('tod').value || '06:00';
  const [hh, mm] = tod.split(':').map(x => parseInt(x,10));
  if (isNaN(hh) || isNaN(mm)) { alert('Please enter a valid start time.'); return false; }
  const picked = getSelectedDows();
  let dow='*'; if (picked.length>0 && picked.length<7) dow = picked.join(',');
  document.getElementById('cron').value = `${mm} ${hh} * * ${dow}`;

  // conflict detection (zone + same time + overlapping days)
  const autoOverride = localStorage.getItem('sf-override-auto') === '1';
  const zoneSel = form.querySelector('select[name="zone"]');
  const zone = parseInt(zoneSel.value,10);
  const overlap = SCHEDULES.some(s=>{
    if (parseInt(s.zone,10)!==zone) return false;
    const p = parseCron(s.cron); if(!p) return false;
    if (p.hh!==hh || p.mm!==mm) return false;
    const dset = new Set(p.dows);
    return picked.some(d=>dset.has(d));
  });
  if (overlap && !autoOverride){
    // show modal
    window._pendingSchedule = {submit: true};
    const modal = document.getElementById('conflictModal');
    modal.classList.remove('hidden');
    return false; // pause submit
  }
  document.getElementById('overrideFlag').value = overlap ? '1' : '0';
  return true;
}
// Modal handlers
(function(){
  const modal = document.getElementById('conflictModal');
  if(!modal) return;
  document.getElementById('modalCancel').onclick = ()=>{ modal.classList.add('hidden'); };
  document.getElementById('modalConfirm').onclick = ()=>{
    const dontAsk = document.getElementById('dontAsk').checked;
    if(dontAsk) localStorage.setItem('sf-override-auto','1');
    document.getElementById('overrideFlag').value = '1';
    modal.classList.add('hidden');
    document.getElementById('addForm').submit();
  };
})();

// Inject schedules (index, zone, minutes, cron) from Jinja into JS:
const SCHEDULES = [
  {% for i,sch in schedules -%}
  { idx: {{i}}, zone: {{sch.zone}}, minutes: {{sch.minutes}}, cron: "{{sch.cron}}" }{{ "," if not loop.last }}
  {%- endfor %}
];
// Inject zones in order for grid rows
const ZONES = [ {% for z in zones %} {{z}}{{ "," if not loop.last }} {% endfor %} ];

// Parse cron "M H * * DOW" -> {mm, hh, dows[]}
function parseCron(cron){
  try{
    const p = cron.trim().split(/\s+/);
    const mm = parseInt(p[0],10), hh = parseInt(p[1],10);
    const dowRaw = p[4] || '*';
    let dows=[];
    if (dowRaw==='*'||dowRaw==='*/1'){ dows=[0,1,2,3,4,5,6]; }
    else{
      dowRaw.split(',').forEach(tok=>{
        if(tok.includes('-')){ const [a,b]=tok.split('-').map(x=>parseInt(x,10)); for(let d=a;d<=b;d++) dows.push(d); }
        else { const v=parseInt(tok,10); if(!isNaN(v)) dows.push(v); }
      });
      dows = Array.from(new Set(dows)).filter(d=>d>=0&&d<=6).sort((a,b)=>a-b);
    }
    return {mm,hh,dows};
  }catch(e){ return null; }
}

// Format "6:05 AM"
function fmtTime(hh,mm){
  const ampm = hh>=12?'PM':'AM';
  const h=((hh+11)%12)+1;
  const m=String(mm).padStart(2,'0');
  return `${h}:${m} ${ampm}`;
}

// Build map: zone -> [ [entries for Sun], ... Sat ]
function buildZoneDayMap(){
  const map = new Map();
  ZONES.forEach(z=>{ map.set(z, Array.from({length:7}, ()=>[])); });
  SCHEDULES.forEach(s=>{
    const parsed = parseCron(s.cron); if(!parsed) return;
    parsed.dows.forEach(d=>{
      const arr = map.get(s.zone) || map.get(Number(s.zone));
      if(!arr) return;
      arr[d].push({ idx: s.idx, minutes: Number(s.minutes), hh: parsed.hh, mm: parsed.mm });
    });
  });
  // sort each day by time
  for(const arr of map.values()){
    for(let d=0; d<7; d++) arr[d].sort((a,b)=> (a.hh*60+a.mm)-(b.hh*60+b.mm));
  }
  return map;
}

function renderScheduleGrid(){
  const grid = document.getElementById('schedGrid');
  grid.className = 'sched-grid';
  grid.innerHTML = '';
  const dayNames = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  // header row
  const headZone = document.createElement('div'); headZone.className='head'; headZone.textContent='Zone'; grid.appendChild(headZone);
  for(const dn of dayNames){ const h=document.createElement('div'); h.className='head'; h.textContent=dn; grid.appendChild(h); }

  const map = buildZoneDayMap();
  ZONES.forEach(z=>{
    const zc = document.createElement('div'); zc.className='zcell';
    zc.innerHTML = `<div>Zone ${z}</div>`;
    const tools = document.createElement('div'); tools.className='ztools';
    const form = document.createElement('form'); form.method='POST'; form.action = `{{ url_for('clear_zone', zone=0) }}`.replace('0', z);
    const btn = document.createElement('button'); btn.type='submit'; btn.textContent='Clear zone'; btn.className='btn secondary';
    form.appendChild(btn); tools.appendChild(form); zc.appendChild(tools);
    grid.appendChild(zc);

    const days = map.get(z) || Array.from({length:7}, ()=>[]);
    for(let d=0; d<7; d++){
      const cell = document.createElement('div'); cell.className='cell';
      days[d].forEach(ent=>{
        const row = document.createElement('div'); row.className='entry';
        const label = document.createElement('span'); label.className='label'; label.textContent = `${ent.minutes} min @ ${fmtTime(ent.hh, ent.mm)}`;
        row.appendChild(label);
        cell.appendChild(row);
      });
      grid.appendChild(cell);
    }
  });
}
renderScheduleGrid();
</script>
</body>
</html>
"""


# ---------------------------- Routes ----------------------------

def make_page_context(extra=None):
    cfg = load_conf()
    dates, probs = fetch_rain_probs(cfg.get("latitude"), cfg.get("longitude"))
    forecast = list(zip(dates, probs)) if dates and probs else []

    # status line so it's always visible
    if probs:
        today_prob = int(probs[0])
        thr = int(cfg.get("rain_prob_threshold", 50))
        if cfg.get("enable_weather_skip", False):
            weather_status = f"Weather skip ON • Today rain prob: {today_prob}% (threshold {thr}%)"
        else:
            weather_status = f"Weather skip OFF • Today rain prob: {today_prob}%"
    else:
        weather_status = "Weather data unavailable (showing no forecast)."

    # Build formatted forecast with weekday + M-D, and rotate so first col is TODAY
    weekday_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]  # datetime.weekday(): Mon=0
    forecast_fmt = []
    dt_list = []
    for d, p in forecast:
        try:
            dt = datetime.fromisoformat(d)
            dow = weekday_names[dt.weekday()]
            md  = f"{dt.month}-{dt.day}"
            pct = int(p)
            dt_list.append(dt.date())
        except Exception:
            dow, md, pct = d, d, p
        forecast_fmt.append({"dow": dow, "md": md, "pct": pct})

    # Rotate by the DATE difference from the first forecast date to today (0..6)
    if dt_list:
        try:
            offset = (date.today() - dt_list[0]).days
            if 0 <= offset <= 6:
                forecast_fmt = forecast_fmt[offset:] + forecast_fmt[:offset]
        except Exception:
            pass

    ctx = {
        "cfg": cfg,
        "zones": cfg.get("zones", list(range(1, 9))),
        "schedules": list(enumerate(load_sched())),
        "discovered": None,
        "forecast": forecast,
        "forecast_fmt": forecast_fmt,
        "weather_status": weather_status,
    }
    if extra:
        ctx.update(extra)
    return ctx

@app.route("/", methods=["GET"])
def index():
    return render_template_string(TEMPLATE, **make_page_context())

@app.route("/settings", methods=["POST"])
def save_settings():
    cfg = load_conf()
    cfg["blossom_ip"] = request.form.get("blossom_ip", "").strip()
    cfg["use_master"] = request.form.get("use_master", "false") == "true"
    try:
        cfg["master_valve"] = int(request.form.get("master_valve", str(cfg.get("master_valve", 13))))
    except Exception:
        cfg["master_valve"] = 13
    cfg["enable_weather_skip"] = request.form.get("enable_weather_skip", "true") == "true"
    try:
        cfg["rain_prob_threshold"] = int(request.form.get("rain_prob_threshold", "50"))
    except Exception:
        cfg["rain_prob_threshold"] = 50
    try:
        cfg["latitude"]  = float(request.form.get("latitude",  str(cfg.get("latitude", 43.8260))))
        cfg["longitude"] = float(request.form.get("longitude", str(cfg.get("longitude",-111.7897))))
    except Exception:
        pass
    save_conf(cfg)
    return redirect(url_for("index"))

@app.route("/discover", methods=["POST"])
def discover():
    ips = discover_blossom()
    ctx = make_page_context({"discovered": ips})
    return render_template_string(TEMPLATE, **ctx)

# Hidden-but-available weather check endpoint (not linked in UI)
@app.route("/weathercheck", methods=["GET"])
def weathercheck():
    cfg = load_conf()
    dates, probs = fetch_rain_probs(cfg.get("latitude"), cfg.get("longitude"))
    skip, reason = should_skip_today_by_weather()
    data = {
        "enable_weather_skip": cfg.get("enable_weather_skip", False),
        "rain_prob_threshold": int(cfg.get("rain_prob_threshold", 50)),
        "today_prob": int(probs[0]) if probs else None,
        "skip_today": bool(skip),
        "skip_reason": reason,
        "forecast": [{"date": d, "precip_prob": int(p)} for d, p in zip(dates or [], probs or [])]
    }
    # If client asks for JSON explicitly, return JSON; else show simple HTML
    if request.headers.get('Accept', '').lower().startswith('application/json') or request.args.get('format') == 'json':
        return jsonify(data)
    # simple HTML for quick human debugging
    lines = [
        "<h3>Weather Check</h3>",
        f"<p>Weather skip: {'ON' if data['enable_weather_skip'] else 'OFF'}; threshold ≥ {data['rain_prob_threshold']}%</p>",
        f"<p>Today: {data['today_prob']}% → skip_today={data['skip_today']} ({data['skip_reason']})</p>",
        "<pre>" + "\n".join(f"{row['date']}: {row['precip_prob']}%" for row in data['forecast']) + "</pre>",
        '<p><a href="/">Back</a></p>'
    ]
    return "\n".join(lines)

@app.route("/manual", methods=["POST"])
def manual():
    z = int(request.form.get("zone", "1"))
    m = float(request.form.get("minutes", "1.0"))
    seconds = int(m * 60)
    threading.Thread(target=run_zone, args=(z, seconds, None), daemon=True).start()
    return redirect(url_for("index"))

@app.route("/alloff", methods=["POST"])
def alloff_route():
    all_off()
    return redirect(url_for("index"))

@app.route("/schedule/add", methods=["POST"])
def add_schedule():
    z = int(request.form.get("zone", "1"))
    m = float(request.form.get("minutes", "5.0"))
    c = request.form.get("cron", "0 6 * * *")
    override = request.form.get("override", "0") == "1"

    def parse_cron_mm_hh_dows(cron: str):
        try:
            p = cron.strip().split()
            mm, hh = int(p[0]), int(p[1])
            dow_raw = p[4] if len(p) > 4 else '*'
            if dow_raw in ('*', '*/1'):
                dows = set(range(7))
            else:
                dows = set()
                for tok in dow_raw.split(','):
                    if '-' in tok:
                        a,b = tok.split('-')
                        a,b = int(a), int(b)
                        for d in range(a, b+1):
                            if 0 <= d <= 6: dows.add(d)
                    else:
                        v = int(tok)
                        if 0 <= v <= 6: dows.add(v)
            return mm, hh, dows
        except Exception:
            return None

    mm_hh_dows = parse_cron_mm_hh_dows(c)
    data = load_sched()

    # If override: remove entries with same zone & same time & overlapping days
    if mm_hh_dows and override:
        mm, hh, new_dows = mm_hh_dows
        filtered = []
        for sch in data:
            try:
                if int(sch.get('zone')) != z:
                    filtered.append(sch); continue
                parsed2 = parse_cron_mm_hh_dows(sch.get('cron',''))
                if not parsed2:
                    filtered.append(sch); continue
                mm2, hh2, dows2 = parsed2
                if mm2 == mm and hh2 == hh and (new_dows & dows2):
                    # drop it (replacing)
                    continue
                filtered.append(sch)
            except Exception:
                filtered.append(sch)
        data = filtered

    # Prevent exact duplicates even without override
    if any( int(s.get('zone'))==z and float(s.get('minutes'))==m and s.get('cron')==c for s in data ):
        save_sched(data)
        install_jobs()
        return redirect(url_for("index"))

    data.append({"zone": z, "minutes": m, "cron": c})
    save_sched(data)
    install_jobs()
    return redirect(url_for("index"))

@app.route("/schedule/del/<int:idx>", methods=["POST"])
def del_schedule(idx):
    data = load_sched()
    if 0 <= idx < len(data):
        data.pop(idx)
        save_sched(data)
        install_jobs()
    return redirect(url_for("index"))

@app.route("/schedule/clear_zone/<int:zone>", methods=["POST"])
def clear_zone(zone):
    data = [sch for sch in load_sched() if int(sch.get('zone')) != int(zone)]
    save_sched(data)
    install_jobs()
    return redirect(url_for("index"))

# ---------------------------- Entrypoint ----------------------------

def main():
    parser = argparse.ArgumentParser(description="SprinklerFreedom")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Bind port (default 5000)")
    args = parser.parse_args()

    if not os.path.exists(CONF_FILE):
        save_conf(load_conf())
    if not os.path.exists(SCHED_FILE):
        save_sched([])

    install_jobs()
    sched.start()
    app.run(host=args.host, port=args.port)

if __name__ == "__main__":
    main()
