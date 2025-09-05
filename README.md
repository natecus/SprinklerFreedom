SprinklerFreedom

Local, minutes-based web UI to keep your Blossom sprinkler controller useful — with optional weather-skip and a friendly weekly scheduler. Runs on a Raspberry Pi (or any Linux/Windows/macOS machine) and talks to your Blossom over your LAN. Save hardware from the landfill ♻️

Buy me a coffee

Why

Blossom’s cloud went away, but the hardware still works. SprinklerFreedom gives you:

Manual zone control (minutes).

A simple weekly scheduler (days + time → cron under the hood).

Optional weather skip (Open-Meteo precipitation probability).

LAN-only, no cloud required.

Works great on a Raspberry Pi as a tiny home server.

Features (current)

Run any zone for X minutes (with optional Master/PSR valve).

Add schedules by day/time; auto dedupe + conflict replace modal.

7-day precip-probability display (rotates so today is first).

Quick Blossom auto-discovery for common home subnets.

Dark mode, tabs: Welcome/Settings • Manual • Schedule • Donate.

All in one file: SprinklerFreedomv2.py.

Screenshots

(Add your screenshots here later—/docs/img/… and link them.)

Quick Start (any OS)
# 1) Clone
git clone https://github.com/<you>/SprinklerFreedom.git
cd SprinklerFreedom

# 2) (Optional) Create a venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3) Install deps
pip install -r requirements.txt

# 4) Run
python SprinklerFreedomv2.py --host 0.0.0.0 --port 5000


Open a browser to: http://<your-pi-or-pc-ip>:5000/

Go to Welcome/Settings tab:

Set your Blossom IP (use Auto-discover if you’re not sure).

(Optional) Turn on Weather skip and adjust threshold.

(Optional) Enable Use Master and set Master Valve # (default 13).

Use Manual to test a zone, then Schedule to automate.
