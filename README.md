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

## Initial Setup of Blossom Controller

The Blossom 8 sprinkler controller was originally tied to a discontinued cloud app. Instead of tossing it, we figured out how to get it online locally and control it ourselves. Here’s the step-by-step:

### 1. Power up the Blossom
- Plug in the Blossom 8.  
- After a minute, it broadcasts a Wi-Fi setup network.

### 2. Connect to the Blossom’s setup Wi-Fi
- On your phone or pc (it works best on pc), look for an SSID named **Blossom_XXXX** (the last digits vary by device).  
- Connect to that network using the default password: 12flowers

### 3. Configure your home Wi-Fi
- Once connected, use ipconfig to find your default gateway, this will be the IP of the Blossom
  - On mine it was `http://192.168.4.1` but I don't know if that is default.  
- Pick your home Wi-Fi network (SSID) from the list.  
- Enter your home Wi-Fi password.  
- Save settings. The Blossom will reboot and join your home Wi-Fi.  

### 4. Find the Blossom on your LAN
Now the Blossom is part of your home network. To get its IP address:  

1. **Check your router’s device list** – it usually shows up as “Blossom.”  
2. **Use SprinklerFreedom’s “Auto-Discover” button** – it scans your subnet for devices serving `/bloom.js`.  
3. **Use a network scan tool** (e.g. `nmap` or Fing).  

---

## Quick Start (any OS)

```bash
# 1) Clone
git clone https://github.com/natecus/SprinklerFreedom.git
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
