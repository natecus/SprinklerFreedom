# SprinklerFreedom

Local, minutes-based web UI to keep your **Blossom sprinkler controller** useful — with optional weather-skip and a friendly weekly scheduler. Runs on a Raspberry Pi (or any Linux/Windows/macOS machine) and talks to your Blossom over your LAN. Save hardware from the landfill ♻️

👉 [Buy me a coffee](https://buymeacoffee.com/natecus)

---

## Why

Blossom’s cloud went away, but the hardware still works. **SprinklerFreedom** gives you:

- Manual zone control (minutes).
- A simple weekly scheduler (days + time → cron under the hood).
- Optional **weather skip** (Open-Meteo precipitation probability).
- LAN-only, no cloud required.
- Works great on a Raspberry Pi as a tiny home server.

---

## Features

- Run any zone for X minutes (with optional Master/PSR valve).
- Add schedules by day/time; auto dedupe + conflict replace modal.
- 7-day precipitation probability display (rotates so **today** is first).
- Quick Blossom auto-discovery for common home subnets.
- Dark mode, tabbed UI:
  - Welcome / Settings  
  - Manual  
  - Schedule  
  - Donate
- All in one file: `SprinklerFreedomv2.py`

---

## Quick Start (any OS)

```bash
# 1) Clone
git clone https://github.com/<your-username>/SprinklerFreedom.git
cd SprinklerFreedom

# 2) (Optional) Create a venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3) Install dependencies
pip install -r requirements.txt

# 4) Run
python SprinklerFreedomv2.py --host 0.0.0.0 --port 5000
