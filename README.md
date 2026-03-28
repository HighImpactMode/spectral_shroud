# ▓▒░ SPECTRAL SHROUD ░▒▓
### Distributed RF Mitigation System — Proof of Concept

> *"What would I want if I was out there?"*

Spectral Shroud is a proof-of-concept distributed RF detection and mitigation system inspired by the evolution of drone warfare — particularly the lessons being written in real time on the battlefields of Ukraine. It is a personal R&D project built to explore how far a single engineer can get toward a battlefield-relevant autonomous sensor mesh using commercial off-the-shelf hardware and modern AI-driven RF sensing.

---

## The Problem

Modern battlefields are increasingly dominated by small, cheap, commercially available drones — DJI quadcopters, FPV kamikaze drones, ISR platforms. Counter-drone systems exist, but they tend to be large, expensive, high-value, and easily targeted. What's needed is something different: a distributed, low-cost, expendable mesh of autonomous nodes that can sense, communicate, respond, and survive the loss of individual units without collapsing the system.

---

## The Holy Grail

The ideal system would have:

1. **RF Sensing** — ML-driven signal classification and direction finding
2. **Private Communications** — LoRa, private 5G, Starlink mesh
3. **Jamming / Electronic Effects** — frequency-targeted RF suppression
4. **Kinetic Self-Destruction** — anti-tamper denial capability
5. **GPS Location Reporting** — real-time geospatial awareness
6. **Sustainable Energy** — solar or energy harvesting
7. **Mobility** — drone-like repositioning capability
8. **Centralized C2** — managed but capable of autonomous operation

Deployed as hundreds of low-cost nodes across a battlefield — emplaced manually or air-dropped — forming a resilient mesh where the loss of individual nodes does not collapse the system.

---

## What Spectral Shroud Actually Is

A proof of concept. One engineer, spare time, commercial hardware. The goal was to see how far down the holy grail checklist a single person could get.

| Capability | Holy Grail | Spectral Shroud POC |
|---|---|---|
| RF Sensing (ML) | ✅ | ✅ via OmniSIG Engine |
| Direction Finding | ✅ | ⚠️ Heatmap approximation (multi-node detection clustering) |
| Communications | ✅ | ✅ WiFi (802.11) |
| Jamming | ✅ | 🟡 Represented by LED (yellow) |
| Kinetic Effect | ✅ | 🟡 Represented by LED (red) + motion trigger |
| GPS Reporting | ✅ | ✅ Hardcoded coordinates, Cesium geospatial display |
| Sustainable Energy | ✅ | ❌ Battery only |
| Mobility | ✅ | ❌ Static nodes |
| C2 | ✅ | ✅ Laptop + Cesium globe |
| Autonomous Operation | ✅ | ✅ State machine, no human in loop after trigger |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        C2 LAPTOP                            │
│                                                             │
│  ┌─────────────┐    ZMQ PUB     ┌──────────────────────┐   │
│  │   OmniSIG   │ ─────────────► │   Spectral Shroud    │   │
│  │   Engine    │   (port 4002)  │   (Python/tkinter)   │   │
│  │  (AI RF ID) │                │                      │   │
│  └─────────────┘                │  - ZMQ subscriber    │   │
│                                 │  - Label filter      │   │
│  ┌─────────────┐                │  - State machine     │   │
│  │   Cesium    │ ◄── HTTP ───── │  - Flask /nodes API  │   │
│  │  C2 Display │   (port 5000)  │  - OmniSIG control   │   │
│  │  (Browser)  │                └──────────┬───────────┘   │
│  └─────────────┘                           │               │
└───────────────────────────────────────────┼───────────────┘
                                            │ HTTP
                                            │ (WiFi)
                              ┌─────────────▼──────────────┐
                              │        ESP32 NODE(S)        │
                              │                             │
                              │  - AsyncWebServer           │
                              │  - /jam  → Yellow LED       │
                              │  - /status → JSON           │
                              │  - BOOT btn → POST /motion  │
                              │  - FreeRTOS task timer      │
                              └─────────────────────────────┘
```

---

## Node State Machine

Each sensor node operates on a simple state machine reflected both physically (LED color) and geospatially (Cesium map marker color):

```
🟢 IDLE      — Node online, heartbeating, monitoring
🟡 JAMMING   — Target detected, RF suppression active (10s)
🔴 KINETIC   — Tamper/motion detected, node compromised
⚫ OFFLINE   — Node dark (30s after kinetic, or connection lost)
```

---

## Demo Sequence

1. **Start OmniSIG Engine** — begin publishing SigMF metadata on ZMQ
2. **Start Spectral Shroud** — connect to ZMQ, set watchlist to `DJI`
3. **Open Cesium C2 Display** — nodes appear on Bakhmut, Ukraine satellite imagery, green heartbeat pulsing
4. **DJI signal detected** — Shroud filters metadata, matches label
5. **Jam sequence fires** — OmniSIG inference stops, HTTP command sent to ESP32, onboard LED lights yellow, NODE-01 flips yellow on Cesium map, alert banner fires
6. **10 seconds elapse** — LED off, OmniSIG restarts, node returns to green
7. **Rescan** — no signal (drone is down)
8. **BOOT button pressed** — kinetic tamper trigger, node flips red on map
9. **30 seconds elapse** — node goes dark (OFFLINE), LED off

---

## Hardware

| Component | Purpose |
|---|---|
| Laptop (Ubuntu 24) | C2 node, runs OmniSIG + Spectral Shroud |
| USRP SDR | RF capture and transmission |
| ESP32 DOIT DevKit V1 | Sensor node (WiFi, LED, tamper button) |
| Onboard LED (GPIO2) | Visual state indicator |
| BOOT Button (GPIO0) | Tamper/kinetic trigger |

---

## Software Stack

| Component | Technology |
|---|---|
| RF Classification | OmniSIG Engine (DeepSig) — AI-native signal ID |
| Metadata Transport | ZMQ PUB/SUB, SigMF |
| C2 Application | Python, tkinter, Flask, flask-cors |
| Node Firmware | Arduino (ESP32), ESPAsyncWebServer, HTTPClient |
| Geospatial Display | CesiumJS, Cesium Ion |
| Data Format | SigMF, JSON |

---

## Getting Started

### Prerequisites

```bash
pip3 install pyzmq requests flask flask-cors --break-system-packages
```

ESP32 Arduino libraries:
- `ESPAsyncWebServer` (me-no-dev)
- `AsyncTCP` (me-no-dev)

### Configuration

Edit `spectral_shroud_esp32.ino`:
```cpp
const char* SSID     = "YOUR_WIFI_SSID";      // Must be 2.4GHz
const char* PASSWORD = "YOUR_WIFI_PASSWORD";
IPAddress LOCAL_IP(192, 168, 1, 200);          // Static IP for the node
```

Edit `spectral_shroud_c2.html`:
```javascript
Cesium.Ion.defaultAccessToken = 'YOUR_CESIUM_ION_TOKEN';
const SHROUD_STATUS_URL = 'http://127.0.0.1:5000/nodes';
```

### Running

**1. Flash the ESP32:**
Open `spectral_shroud_esp32/spectral_shroud_esp32.ino` in Arduino IDE and upload to your ESP32 Dev Module.

**2. Start Spectral Shroud:**
```bash
python3 spectral_shroud.py
```

**3. Serve the Cesium display:**
```bash
python3 -m http.server 8080
# Open http://localhost:8080/spectral_shroud_c2.html
```

**4. Configure Spectral Shroud UI:**
- ENDPOINT: `tcp://127.0.0.1:4002` (OmniSIG ZMQ output)
- WATCH: `DJI` (or your target label)
- ESP32 ENDPOINT: `http://192.168.1.200`
- Enable LED Trigger: ✅
- Hit CONNECT

**5. Test without OmniSIG:**
```bash
python3 -c "
import zmq, json, time
ctx = zmq.Context()
sock = ctx.socket(zmq.PUB)
sock.bind('tcp://127.0.0.1:4002')
time.sleep(2)
msg = {'annotations': [{'core:label': 'DJI', 'confidence': 0.95, 'rssi': -60}]}
for i in range(5):
    sock.send_json(msg)
    time.sleep(1)
"
```

---

## Project Structure

```
spectral_shroud/
├── spectral_shroud.py              # Main C2 application
├── spectral_shroud_c2.html         # Cesium geospatial display
├── config.json                     # Persistent UI configuration
└── spectral_shroud_esp32/
    └── spectral_shroud_esp32.ino   # ESP32 node firmware
```

---

## Roadmap

- [ ] Multi-node fan-out (broadcast commands to N nodes simultaneously)
- [ ] Node identity + named coordinates (true geospatial DF approximation)
- [ ] Real motion sensor (MPU-6050 accelerometer)
- [ ] OmniSIG Engine end-to-end test with DJI IQ capture file
- [ ] Colored LEDs (yellow/red/green physical state match)
- [ ] LoRa radio backup communications
- [ ] Solar power budget analysis
- [ ] Anti-tamper logic hardening

---

## Background

This project was built as a personal Dev Days project at [DeepSig](https://deepsig.com), exploring the intersection of AI-native RF sensing (OmniSIG Engine) and autonomous distributed systems concepts drawn from SIGINT and electronic warfare experience.

The convergent evolution happening in defense tech — Anduril, Shield AI, and others — is moving toward exactly this architecture at scale. Spectral Shroud is a one-person proof that the core loop (sense → decide → effect → report) is achievable with commercial hardware and a weekend of engineering.

---

## Disclaimer

This project is a proof of concept for educational and research purposes. RF jamming is regulated and illegal without proper authorization in most jurisdictions. The "jamming" and "kinetic" effects demonstrated here are represented by LEDs only. Always comply with applicable laws and regulations.

---

*Built by Morgan — USAF SIGINT veteran, RF engineer, DeepSig Field Support Representative*

*"Hundreds of low-cost nodes. Mesh architecture. Loss of nodes does not collapse the system."*
