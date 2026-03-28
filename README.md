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

## How to Run It (Step by Step)

This is the exact sequence to go from a cold start to a live demo.

**Prerequisites:** ESP32 flashed, on the same WiFi network as your laptop, OmniSIG Engine installed or a ZMQ test script ready.

**Step 1 — Start the Flask + Shroud backend**
```bash
cd ~/spectral_shroud
python3 spectral_shroud.py
```
The Spectral Shroud UI will open. The Flask `/nodes` API starts automatically in the background on port 5000.

**Step 2 — Serve the Cesium C2 display**
Open a second terminal:
```bash
cd ~/spectral_shroud
python3 -m http.server 8080
```
Then open your browser to `http://localhost:8080/spectral_shroud_c2.html`. You should see the Bakhmut satellite map load with your nodes plotted and `SHROUD LINK: ACTIVE` in the top center.

**Step 3 — Configure Spectral Shroud**
In the Shroud UI set:
- **ENDPOINT:** `tcp://127.0.0.1:4002`
- **WATCH:** `DJI` (or whatever label your OmniSIG model outputs)
- **ESP32 ENDPOINT:** `http://192.168.1.200` (your node's IP)
- **Enable LED Trigger:** checked
- Hit **[ CONNECT ]**

Hit **[ SAVE CONFIG ]** so these settings persist on next launch.

**Step 4 — Trigger a detection**

*With OmniSIG Engine:* Load a DJI IQ capture file and start inference. When the engine classifies a DJI signal above your confidence threshold, the sequence fires automatically.

*Without OmniSIG (test mode):* Run this in a third terminal:
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

**Step 5 — Watch the kill chain fire**
- Shroud detects the DJI label → stops OmniSIG inference
- HTTP command sent to ESP32 → onboard LED lights up
- NODE-01 flips yellow on the Cesium map → alert banner fires
- After 10 seconds → LED off, OmniSIG restarts, node returns green

**Step 6 — Trigger kinetic (tamper simulation)**
Press the **BOOT button** on the ESP32. NODE-01 flips red on the map. After 30 seconds it goes dark (OFFLINE).

**Step 7 — Reset**
```bash
curl http://127.0.0.1:5000/motion/reset
```
All nodes return to IDLE green.

---

## POC Substitutions — What Stands In For What

This is a proof of concept. Real battlefield hardware is represented by simple analogues to validate the software logic and communication architecture.

| Real Capability | POC Substitute | Notes |
|---|---|---|
| RF Jammer | 🟡 Yellow LED on ESP32 | Indicates jamming would be active. In a real system this triggers an SDR transmitting suppression waveforms on the detected frequency |
| Kinetic self-destruct | 🔴 Red LED on ESP32 | Indicates kinetic effect triggered. In a real system this could be a thermite charge, shaped charge, or data wipe |
| Motion/tamper sensor | BOOT button (GPIO0) | Manually pressed to simulate node being picked up or disturbed. Real system uses MPU-6050 accelerometer or PIR sensor |
| Encrypted mesh radio | WiFi (802.11) | Works on a local network. Real system uses LoRa, private 5G, or Starlink for long-range encrypted comms |
| GPS module | Hardcoded coordinates | Node positions are fixed in firmware. Real system uses a u-blox or similar GPS module reporting live position |
| Solar + battery | USB power | Nodes are powered by laptop USB or power bank. Real system uses LiPo + solar panel with charge controller |
| Ruggedized enclosure | Bare PCB | Real nodes would be potted in epoxy or housed in mil-spec enclosures rated for weather, dust, vibration |
| Multiple nodes | Single ESP32 | Architecture supports N nodes — each needs a unique static IP and node ID in the firmware |

---

## How It Would Work in the Real World

In a real deployment the architecture stays identical — only the hardware at the edge changes.

**Deployment:** Nodes are emplaced manually or air-dropped across a defined area — a perimeter, a chokepoint, a forward operating base. Each node is self-contained: SDR receiver, encrypted radio, GPS, compute, power, and effector (jammer or kinetic charge) in a ruggedized weatherproof housing costing ideally under $5,000 per unit.

**Operation:** The C2 laptop (or a hardened tablet) runs Spectral Shroud and the Cesium display from any location with network access to the mesh. Nodes operate autonomously — if the C2 link goes down, nodes continue executing their last programmed behavior. When a node detects a target signal above threshold, it fires its local effector immediately without waiting for C2 confirmation. The C2 display reflects what happened after the fact.

**Direction Finding:** With enough nodes distributed across an area, the detection pattern itself becomes a DF approximation. If NODE-03 and NODE-07 detect a signal but NODE-01 does not, the signal source is likely in the sector between 03 and 07. No AoA hardware required — the mesh geometry does the work.

**Survivability:** Nodes that go offline (destroyed, captured, battery dead) are simply removed from the display. The remaining nodes continue operating. There is no single point of failure. This is the core architectural advantage over a single high-value jammer or radar system.

**Escalation:** The kinetic anti-tamper function means a captured node destroys itself before it can be exploited for intelligence. The 30-second timer before going OFFLINE gives the C2 operator a window to confirm the event before the node self-destructs.

---

## Background

This project was built as a Dev Days project at [DeepSig](https://deepsig.com), exploring the intersection of AI-native RF sensing (OmniSIG Engine) and autonomous distributed systems concepts drawn from SIGINT and electronic warfare experience.

The convergent evolution happening in defense tech — Anduril, Shield AI, and others — is moving toward exactly this architecture at scale. Spectral Shroud is a one-person proof that the core loop (sense → decide → effect → report) is achievable with commercial hardware and a weekend of engineering.

---

## Disclaimer

This project is a proof of concept for educational and research purposes. RF jamming is regulated and illegal without proper authorization in most jurisdictions. The "jamming" and "kinetic" effects demonstrated here are represented by LEDs only. Always comply with applicable laws and regulations.

---

*"Hundreds of low-cost nodes. Mesh architecture. Loss of nodes does not collapse the system."*
