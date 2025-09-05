# SprinklerFreedom

Local, minutes-based web UI to keep your **Blossom 8 WiFi sprinkler controller** useful — with optional weather-skip and a friendly weekly scheduler. Runs on a Raspberry Pi (or any Linux/Windows/macOS machine) and talks to your Blossom over your LAN. Save hardware from the landfill 

**Is this project useful?** Maybe you could [Buy me a coffee](https://buymeacoffee.com/natecus)

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
```
## Test it Out
- Open a browser to: http://*your-pi-or-pc-ip*:5000/
- On the Welcome/Settings tab:
  - Set your Blossom IP (use Auto-discover if you’re not sure).
  - (Optional) Turn on Weather skip and adjust threshold.
  - (Optional) Enable Use Master and set Master Valve # (default 13).
  - Use the Manual tab to test a zone, then the Schedule tab to automate.

---
## Caveats & Limitations

- **Always-on requirement**: The app must be running for schedules to trigger.  
  - If you run this on a **PC**, that PC must stay on.  
  - If you run it on a **Raspberry Pi**, the Pi must stay powered and connected to your network.

- **LAN-only**: SprinklerFreedom is designed for **local network use only**. Do not expose it directly to the internet. If you want remote access, use a VPN like Tailscale or WireGuard.

- **Weather skip is “fail-open”**: If weather data is unavailable, the system will **still water** to avoid skipping schedules unnecessarily.

- **Single Blossom device**: Currently supports only one Blossom controller at a time. Multi-device support is a future roadmap item.

- **Manual testing recommended**: After first setup, use the **Manual** tab to test each zone before relying on schedules.
