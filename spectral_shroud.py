import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import requests

import zmq
from flask import Flask, jsonify, request
from flask_cors import CORS

node_states = {
    'NODE-01': 'IDLE',
    'NODE-02': 'IDLE',
    'NODE-03': 'IDLE',
}

kinetic_timers = {}  # node_id -> active threading.Timer

flask_app = Flask(__name__)
CORS(flask_app)


@flask_app.route('/nodes', methods=['GET'])
def get_nodes():
    return jsonify(node_states)


def _kinetic_expire(node_id):
    node_states[node_id] = 'OFFLINE'
    kinetic_timers.pop(node_id, None)


@flask_app.route('/motion', methods=['POST'])
def post_motion():
    data = request.get_json(silent=True) or {}
    node_id = data.get('node_id')
    if node_id not in node_states:
        return jsonify({'error': f'unknown node_id: {node_id}'}), 400

    # Cancel any existing timer for this node before starting a fresh one
    existing = kinetic_timers.pop(node_id, None)
    if existing is not None:
        existing.cancel()

    node_states[node_id] = 'KINETIC'
    timer = threading.Timer(30, _kinetic_expire, args=(node_id,))
    timer.daemon = True
    timer.start()
    kinetic_timers[node_id] = timer

    return jsonify({'node_id': node_id, 'state': 'KINETIC'})


@flask_app.route('/motion/reset', methods=['GET'])
def get_motion_reset():
    for key in node_states:
        node_states[key] = 'IDLE'
    return jsonify(node_states)


def start_flask():
    flask_app.run(host='0.0.0.0', port=5000, use_reloader=False)


CONFIG_FILE = "config.json"

# Hacker/Matrix-inspired color palette - Black & Green
COLORS = {
    'bg': '#000000',           # Pure black background
    'bg_secondary': '#0a0e0a', # Very dark green-black
    'bg_accent': '#0d1b0d',    # Dark green accent background
    'fg': '#00ff41',           # Bright matrix green text
    'fg_secondary': '#00b830', # Muted green
    'accent': '#00ff41',       # Bright green accent
    'accent_hover': '#00d936', # Slightly darker green
    'success': '#00ff41',      # Bright green for success
    'warning': '#39ff14',      # Neon green for warnings
    'error': '#ff0000',        # Red for errors
    'alert': '#39ff14',        # Neon green alert
    'border': '#1a3a1a',       # Dark green border
    'glow': '#00ff41',         # Glow effect color
}


def safe_json_loads(raw: bytes):
    """
    Accepts bytes from ZMQ and attempts to parse JSON.
    Supports:
      - raw JSON object
      - JSON lines (first line is JSON)
    """
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    # If it's JSONL or has prefixes, try to find the first JSON object.
    # Simple heuristic: find first '{' and last '}'.
    if text[0] != "{":
        l = text.find("{")
        r = text.rfind("}")
        if l != -1 and r != -1 and r > l:
            text = text[l : r + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_signal_type(msg: dict):
    """
    Extract a 'signal type' from a SigMF-meta-like JSON message.
    You MUST adapt this to your stream.

    Handles common patterns:
      1) Annotation events: msg["annotations"][*]["core:label"] / ["label"] / ["type"]
      2) Single annotation: msg["annotation"]["core:label"] / etc.
      3) Your custom classifier: msg["detection"]["type"] or msg["signal_type"]

    Returns a list[str] of detected types in this message.
    """
    found = []

    # Custom/common shortcuts
    for key in ("signal_type", "signalType", "detected_type", "type"):
        if isinstance(msg.get(key), str):
            found.append(msg[key])

    # Classifier nested
    det = msg.get("detection") or msg.get("classifier") or {}
    if isinstance(det, dict):
        for key in ("type", "label", "core:label", "name"):
            if isinstance(det.get(key), str):
                found.append(det[key])

    # SigMF-ish: annotations list
    ann_list = msg.get("annotations")
    if isinstance(ann_list, list):
        for ann in ann_list:
            if not isinstance(ann, dict):
                continue
            for key in ("core:label", "label", "type", "name"):
                if isinstance(ann.get(key), str):
                    found.append(ann[key])

    # SigMF-ish: single annotation dict
    ann = msg.get("annotation")
    if isinstance(ann, dict):
        for key in ("core:label", "label", "type", "name"):
            if isinstance(ann.get(key), str):
                found.append(ann[key])

    # Dedup, preserve order
    out = []
    seen = set()
    for s in found:
        s2 = s.strip()
        if s2 and s2 not in seen:
            seen.add(s2)
            out.append(s2)
    return out


def extract_confidence(msg: dict):
    """Extract confidence value from SigMF message. Returns None if not found."""
    # Try common confidence field names
    for key in ("confidence", "core:confidence", "conf"):
        if key in msg and isinstance(msg[key], (int, float)):
            return float(msg[key])

    # Check in annotations
    ann_list = msg.get("annotations")
    if isinstance(ann_list, list) and len(ann_list) > 0:
        ann = ann_list[0]
        for key in ("confidence", "core:confidence", "conf"):
            if key in ann and isinstance(ann[key], (int, float)):
                return float(ann[key])

    # Check in single annotation
    ann = msg.get("annotation")
    if isinstance(ann, dict):
        for key in ("confidence", "core:confidence", "conf"):
            if key in ann and isinstance(ann[key], (int, float)):
                return float(ann[key])

    return None


def extract_rssi(msg: dict):
    """Extract RSSI value from SigMF message. Returns None if not found."""
    # Try common RSSI field names
    for key in ("rssi", "core:rssi", "power", "signal_power"):
        if key in msg and isinstance(msg[key], (int, float)):
            return float(msg[key])

    # Check in annotations
    ann_list = msg.get("annotations")
    if isinstance(ann_list, list) and len(ann_list) > 0:
        ann = ann_list[0]
        for key in ("rssi", "core:rssi", "power", "signal_power"):
            if key in ann and isinstance(ann[key], (int, float)):
                return float(ann[key])

    # Check in single annotation
    ann = msg.get("annotation")
    if isinstance(ann, dict):
        for key in ("rssi", "core:rssi", "power", "signal_power"):
            if key in ann and isinstance(ann[key], (int, float)):
                return float(ann[key])

    return None


class OmniSIGAPIClient:
    """Client for OmniSIG Engine API (REQ/REP pattern)"""
    def __init__(self, api_endpoint="tcp://127.0.0.1:4003"):
        self.api_endpoint = api_endpoint
        self.ctx = zmq.Context.instance()
        self.sock = None

    def connect(self):
        """Connect to OmniSIG API"""
        if self.sock is None:
            self.sock = self.ctx.socket(zmq.REQ)
            self.sock.setsockopt(zmq.RCVTIMEO, 5000)  # 5 second timeout
            self.sock.setsockopt(zmq.LINGER, 0)
            self.sock.connect(self.api_endpoint)

    def send_command(self, command):
        """Send a command to OmniSIG API and return response"""
        try:
            self.connect()
            self.sock.send_string(command)
            response = self.sock.recv_string()
            return response
        except Exception as e:
            return f"Error: {e}"

    def stop_inference(self):
        """Stop OmniSIG inference"""
        return self.send_command("inference.stop")

    def start_inference(self):
        """Start OmniSIG inference"""
        return self.send_command("inference.start")

    def close(self):
        """Close the socket"""
        if self.sock:
            self.sock.close()
            self.sock = None


class ZmqSubscriberThread(threading.Thread):
    def __init__(self, endpoint: str, topic: str, out_q: queue.Queue, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.endpoint = endpoint
        self.topic = topic
        self.out_q = out_q
        self.stop_evt = stop_evt

        self.ctx = None
        self.sock = None

    def run(self):
        try:
            self.ctx = zmq.Context.instance()
            self.sock = self.ctx.socket(zmq.SUB)
            # Keep it responsive so stop works quickly
            self.sock.setsockopt(zmq.RCVTIMEO, 250)
            self.sock.setsockopt(zmq.LINGER, 0)

            # Subscribe
            if self.topic:
                self.sock.setsockopt(zmq.SUBSCRIBE, self.topic.encode("utf-8"))
            else:
                self.sock.setsockopt(zmq.SUBSCRIBE, b"")

            self.sock.connect(self.endpoint)
            self.out_q.put(("status", f"Connected to {self.endpoint} (topic='{self.topic}')"))

            while not self.stop_evt.is_set():
                try:
                    raw = self.sock.recv()
                except zmq.error.Again:
                    continue  # timeout, loop again
                except Exception as e:
                    self.out_q.put(("error", f"ZMQ recv error: {e}"))
                    break

                # If publisher sends multipart [topic, payload], handle that too
                # (If we received a single frame, raw is bytes; if multipart, we'd use recv_multipart)
                # For simplicity: detect topic prefix "topic {json...}" too.
                msg = safe_json_loads(raw)
                if msg is None:
                    # Try multipart fallback: non-blocking peek not trivial; just log raw
                    snippet = raw[:200].decode("utf-8", errors="replace")
                    self.out_q.put(("raw", f"Non-JSON payload (first 200 chars): {snippet}"))
                    continue

                self.out_q.put(("json", msg))

        finally:
            try:
                if self.sock is not None:
                    self.sock.close()
            except Exception:
                pass
            self.out_q.put(("status", "Disconnected"))


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title("Spectral Shroud - SigMF Alert Monitor")

        # Apply dark theme first
        self._apply_dark_theme()

        self.pack(fill="both", expand=True)

        self.msg_q = queue.Queue()
        self.stop_evt = threading.Event()
        self.sub_thread = None

        self.alert_count = tk.IntVar(value=0)
        self.connected = tk.BooleanVar(value=False)

        # OmniSIG API client
        self.omnisig_api = None

        # LED trigger state
        self.led_active = False
        self.last_trigger_time = 0
        self.trigger_cooldown = 10  # seconds

        self._build_ui()
        self._load_config()
        self._poll_queue()

    def _apply_dark_theme(self):
        """Apply custom dark theme styling"""
        style = ttk.Style()

        # Configure root window
        self.master.configure(bg=COLORS['bg'])

        # Frame styles
        style.configure('TFrame', background=COLORS['bg'])
        style.configure('TLabelframe', background=COLORS['bg'],
                       foreground=COLORS['accent'], bordercolor=COLORS['accent'],
                       borderwidth=2)
        style.configure('TLabelframe.Label', background=COLORS['bg'],
                       foreground=COLORS['accent'], font=('Courier New', 10, 'bold'))

        # Label styles
        style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['fg'])
        style.configure('Status.TLabel', background=COLORS['bg'],
                       foreground=COLORS['fg_secondary'], font=('Segoe UI', 9))
        style.configure('Alert.TLabel', background=COLORS['bg'],
                       foreground=COLORS['alert'], font=('Segoe UI', 14, 'bold'))

        # Button styles
        style.configure('TButton',
                       background=COLORS['bg_accent'],
                       foreground=COLORS['fg'],
                       bordercolor=COLORS['accent'],
                       focuscolor=COLORS['accent'],
                       lightcolor=COLORS['accent'],
                       darkcolor=COLORS['bg_accent'])
        style.map('TButton',
                 background=[('active', COLORS['accent_hover']), ('pressed', COLORS['bg_accent'])],
                 foreground=[('active', COLORS['fg'])])

        style.configure('Connect.TButton', foreground=COLORS['success'])
        style.configure('Disconnect.TButton', foreground=COLORS['error'])
        style.configure('Action.TButton', foreground=COLORS['accent'])

        # Entry styles
        style.configure('TEntry',
                       fieldbackground=COLORS['bg_secondary'],
                       background=COLORS['bg_secondary'],
                       foreground=COLORS['fg'],
                       bordercolor=COLORS['border'],
                       insertcolor=COLORS['accent'])

        # Checkbutton styles
        style.configure('TCheckbutton',
                       background=COLORS['bg'],
                       foreground=COLORS['fg'])
        style.map('TCheckbutton',
                 background=[('active', COLORS['bg'])],
                 foreground=[('active', COLORS['accent'])])

    def _build_ui(self):
        root = self.master
        root.geometry("1200x800")

        # Configure grid weights for responsive design
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header with title - Hacker style
        header = tk.Frame(self, bg=COLORS['bg'], height=70,
                         highlightthickness=2, highlightbackground=COLORS['accent'])
        header.pack(fill="x", padx=0, pady=0)
        title = tk.Label(header, text="▓▒░ SPECTRAL SHROUD ░▒▓",
                        font=('Courier New', 20, 'bold'),
                        bg=COLORS['bg'], fg=COLORS['accent'])
        title.pack(pady=18)
        subtitle = tk.Label(header, text="[ SigMF Meta Alert System ]",
                           font=('Courier New', 9),
                           bg=COLORS['bg'], fg=COLORS['fg_secondary'])
        subtitle.pack(pady=(0, 8))

        # Top connection bar
        conn = ttk.LabelFrame(self, text=">>> CONNECTION SETTINGS")
        conn.pack(fill="x", padx=15, pady=15)

        self.endpoint_var = tk.StringVar(value="tcp://127.0.0.1:4002")
        self.topic_var = tk.StringVar(value="")  # empty = all
        self.watch_var = tk.StringVar(value="LTE,NR,WiFi,Bluetooth,Starlink")  # comma-separated
        self.case_sensitive = tk.BooleanVar(value=False)
        self.beep = tk.BooleanVar(value=True)

        # New fields for LED control
        self.min_confidence_var = tk.StringVar(value="0.7")
        self.min_rssi_var = tk.StringVar(value="-80")
        self.omnisig_api_var = tk.StringVar(value="tcp://127.0.0.1:4003")
        self.esp32_endpoint_var = tk.StringVar(value="http://192.168.1.100")
        self.enable_led_trigger = tk.BooleanVar(value=False)

        # Connection row
        conn_row = ttk.Frame(conn)
        conn_row.pack(fill="x", padx=10, pady=12)

        ttk.Label(conn_row, text="ENDPOINT:", font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        endpoint_entry = tk.Entry(conn_row, textvariable=self.endpoint_var, width=30,
                                 bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                                 insertbackground=COLORS['accent'],
                                 relief='flat', font=('Courier New', 10),
                                 highlightthickness=2, highlightbackground=COLORS['border'],
                                 highlightcolor=COLORS['glow'])
        endpoint_entry.pack(side="left", padx=(0, 20))

        ttk.Label(conn_row, text="TOPIC:", font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        topic_entry = tk.Entry(conn_row, textvariable=self.topic_var, width=18,
                              bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                              insertbackground=COLORS['accent'],
                              relief='flat', font=('Courier New', 10),
                              highlightthickness=2, highlightbackground=COLORS['border'],
                              highlightcolor=COLORS['glow'])
        topic_entry.pack(side="left", padx=(0, 8))
        ttk.Label(conn_row, text="[empty = all]", font=('Courier New', 8)).pack(side="left", padx=(0, 20))

        # Buttons
        self.connect_btn = tk.Button(conn_row, text="[ CONNECT ]", command=self.on_connect,
                                     bg=COLORS['bg'], fg=COLORS['success'],
                                     font=('Courier New', 9, 'bold'), relief='solid',
                                     borderwidth=2, padx=15, pady=6, cursor='hand2',
                                     activebackground=COLORS['success'],
                                     activeforeground=COLORS['bg'],
                                     highlightbackground=COLORS['success'],
                                     highlightcolor=COLORS['success'])
        self.connect_btn.pack(side="left", padx=4)

        self.disconnect_btn = tk.Button(conn_row, text="[ DISCONNECT ]", command=self.on_disconnect,
                                        bg=COLORS['bg'], fg=COLORS['error'],
                                        font=('Courier New', 9, 'bold'), relief='solid',
                                        borderwidth=2, padx=15, pady=6, cursor='hand2', state="disabled",
                                        activebackground=COLORS['error'],
                                        activeforeground=COLORS['bg'],
                                        highlightbackground=COLORS['error'],
                                        highlightcolor=COLORS['error'])
        self.disconnect_btn.pack(side="left", padx=4)

        # Rules bar
        rules = ttk.LabelFrame(self, text=">>> ALERT RULES")
        rules.pack(fill="x", padx=15, pady=(0, 15))

        rules_row = ttk.Frame(rules)
        rules_row.pack(fill="x", padx=10, pady=12)

        ttk.Label(rules_row, text="WATCH:",
                 font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        watch_entry = tk.Entry(rules_row, textvariable=self.watch_var, width=50,
                              bg=COLORS['bg_secondary'], fg=COLORS['alert'],
                              insertbackground=COLORS['alert'],
                              relief='flat', font=('Courier New', 10, 'bold'),
                              highlightthickness=2, highlightbackground=COLORS['border'],
                              highlightcolor=COLORS['glow'])
        watch_entry.pack(side="left", padx=(0, 15))

        ttk.Checkbutton(rules_row, text="[CASE-SENS]",
                       variable=self.case_sensitive).pack(side="left", padx=8)
        ttk.Checkbutton(rules_row, text="[BEEP]",
                       variable=self.beep).pack(side="left", padx=8)

        # Alert counter display - Matrix style
        alert_frame = tk.Frame(rules_row, bg=COLORS['bg'],
                              highlightthickness=2, highlightbackground=COLORS['alert'])
        alert_frame.pack(side="right", padx=(15, 0))
        tk.Label(alert_frame, text=">> ALERTS:",
                font=('Courier New', 9, 'bold'),
                bg=COLORS['bg'], fg=COLORS['fg_secondary']).pack(side="left", padx=(10, 5), pady=6)
        self.alert_label = tk.Label(alert_frame, textvariable=self.alert_count,
                                    font=('Courier New', 18, 'bold'),
                                    bg=COLORS['bg'], fg=COLORS['alert'],
                                    width=8)
        self.alert_label.pack(side="left", padx=(0, 10), pady=6)

        # LED Trigger Configuration
        led_config = ttk.LabelFrame(self, text=">>> LED TRIGGER CONFIGURATION")
        led_config.pack(fill="x", padx=15, pady=(0, 15))

        # Row 1: Enable and thresholds
        led_row1 = ttk.Frame(led_config)
        led_row1.pack(fill="x", padx=10, pady=(12, 6))

        self.led_toggle_btn = tk.Button(
            led_row1, text="[ ] ENABLE LED TRIGGER",
            command=self._toggle_led_trigger,
            bg=COLORS['bg'], fg=COLORS['fg_secondary'],
            font=('Courier New', 9, 'bold'), relief='flat',
            borderwidth=0, padx=0, pady=0, cursor='hand2',
            activebackground=COLORS['bg'], activeforeground=COLORS['accent'],
            highlightthickness=0)
        self.led_toggle_btn.pack(side="left", padx=(0, 20))
        self.enable_led_trigger.trace_add('write', lambda *_: self._update_led_toggle_btn())

        ttk.Label(led_row1, text="MIN CONFIDENCE:",
                 font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        conf_entry = tk.Entry(led_row1, textvariable=self.min_confidence_var, width=8,
                             bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                             insertbackground=COLORS['accent'],
                             relief='flat', font=('Courier New', 10),
                             highlightthickness=2, highlightbackground=COLORS['border'],
                             highlightcolor=COLORS['glow'])
        conf_entry.pack(side="left", padx=(0, 20))

        ttk.Label(led_row1, text="MIN RSSI (dBm):",
                 font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        rssi_entry = tk.Entry(led_row1, textvariable=self.min_rssi_var, width=8,
                             bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                             insertbackground=COLORS['accent'],
                             relief='flat', font=('Courier New', 10),
                             highlightthickness=2, highlightbackground=COLORS['border'],
                             highlightcolor=COLORS['glow'])
        rssi_entry.pack(side="left", padx=(0, 8))

        # Row 2: Endpoints
        led_row2 = ttk.Frame(led_config)
        led_row2.pack(fill="x", padx=10, pady=(6, 12))

        ttk.Label(led_row2, text="OMNISIG API:",
                 font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        api_entry = tk.Entry(led_row2, textvariable=self.omnisig_api_var, width=25,
                            bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                            insertbackground=COLORS['accent'],
                            relief='flat', font=('Courier New', 10),
                            highlightthickness=2, highlightbackground=COLORS['border'],
                            highlightcolor=COLORS['glow'])
        api_entry.pack(side="left", padx=(0, 20))

        ttk.Label(led_row2, text="ESP32 ENDPOINT:",
                 font=('Courier New', 9, 'bold')).pack(side="left", padx=(0, 8))
        esp32_entry = tk.Entry(led_row2, textvariable=self.esp32_endpoint_var, width=25,
                              bg=COLORS['bg_secondary'], fg=COLORS['accent'],
                              insertbackground=COLORS['accent'],
                              relief='flat', font=('Courier New', 10),
                              highlightthickness=2, highlightbackground=COLORS['border'],
                              highlightcolor=COLORS['glow'])
        esp32_entry.pack(side="left", padx=(0, 8))

        # Bottom controls — packed before the log so expand=True on the log
        # doesn't steal the space needed by the button row.
        bottom = tk.Frame(self, bg=COLORS['bg'])
        bottom.pack(side="bottom", fill="x", padx=15, pady=(0, 15))

        # Control buttons - Terminal style
        btn_style = {'relief': 'solid', 'font': ('Courier New', 9), 'cursor': 'hand2',
                    'padx': 12, 'pady': 6, 'borderwidth': 2}

        clear_btn = tk.Button(bottom, text="[ CLEAR LOG ]", command=self.clear_log,
                             bg=COLORS['bg'], fg=COLORS['warning'],
                             activebackground=COLORS['warning'], activeforeground=COLORS['bg'],
                             **btn_style)
        clear_btn.pack(side="left", padx=(0, 8))

        reset_btn = tk.Button(bottom, text="[ RESET ALERTS ]",
                             command=lambda: self.alert_count.set(0),
                             bg=COLORS['bg'], fg=COLORS['accent'],
                             activebackground=COLORS['accent'], activeforeground=COLORS['bg'],
                             **btn_style)
        reset_btn.pack(side="left", padx=(0, 8))

        test_btn = tk.Button(bottom, text="[ TEST ALERT ]",
                            command=lambda: self._trigger_alert("TEST"),
                            bg=COLORS['bg'], fg=COLORS['alert'],
                            activebackground=COLORS['alert'], activeforeground=COLORS['bg'],
                            **btn_style)
        test_btn.pack(side="left", padx=(0, 8))

        save_btn = tk.Button(bottom, text="[ SAVE CONFIG ]",
                             command=self._save_config,
                             bg=COLORS['bg'], fg=COLORS['fg_secondary'],
                             activebackground=COLORS['fg_secondary'], activeforeground=COLORS['bg'],
                             **btn_style)
        save_btn.pack(side="left")

        # Status indicator - Terminal style
        status_frame = tk.Frame(bottom, bg=COLORS['bg'],
                               highlightthickness=2, highlightbackground=COLORS['accent'])
        status_frame.pack(side="right")

        tk.Label(status_frame, text=">> STATUS:",
                font=('Courier New', 9, 'bold'),
                bg=COLORS['bg'], fg=COLORS['fg_secondary']).pack(side="left", padx=(10, 5), pady=6)

        self.status_lbl = tk.Label(status_frame, text="IDLE",
                                   font=('Courier New', 10, 'bold'),
                                   bg=COLORS['bg'], fg=COLORS['fg_secondary'])
        self.status_lbl.pack(side="left", padx=(0, 10), pady=6)

        # Log area - Terminal style
        logf = ttk.LabelFrame(self, text=">>> SYSTEM LOG")
        logf.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # Text widget with terminal theme
        log_frame = tk.Frame(logf, bg=COLORS['bg'])
        log_frame.pack(fill="both", expand=True, padx=8, pady=8)

        # Scrollbar
        scrollbar = tk.Scrollbar(log_frame, bg=COLORS['bg_secondary'],
                                troughcolor=COLORS['bg'],
                                activebackground=COLORS['accent'])
        scrollbar.pack(side="right", fill="y")

        self.log = tk.Text(log_frame, height=8, wrap="none",
                          bg=COLORS['bg'], fg=COLORS['fg'],
                          insertbackground=COLORS['accent'],
                          selectbackground=COLORS['bg_accent'],
                          selectforeground=COLORS['alert'],
                          font=('Courier New', 10),
                          relief='flat',
                          yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log.yview)

        # Configure text tags for colored output - Matrix style
        self.log.tag_configure('alert', foreground=COLORS['alert'], font=('Courier New', 10, 'bold'))
        self.log.tag_configure('success', foreground=COLORS['success'], font=('Courier New', 10, 'bold'))
        self.log.tag_configure('warning', foreground=COLORS['warning'])
        self.log.tag_configure('info', foreground=COLORS['accent'])
        self.log.tag_configure('error', foreground=COLORS['error'], font=('Courier New', 10, 'bold'))
        self.log.tag_configure('timestamp', foreground=COLORS['fg_secondary'])

    def _toggle_led_trigger(self):
        self.enable_led_trigger.set(not self.enable_led_trigger.get())

    def _update_led_toggle_btn(self):
        if self.enable_led_trigger.get():
            self.led_toggle_btn.configure(text="[X] ENABLE LED TRIGGER", fg=COLORS['accent'])
        else:
            self.led_toggle_btn.configure(text="[ ] ENABLE LED TRIGGER", fg=COLORS['fg_secondary'])

    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.endpoint_var.set(cfg.get("endpoint", self.endpoint_var.get()))
        self.topic_var.set(cfg.get("topic", self.topic_var.get()))
        self.watch_var.set(cfg.get("watch_var", self.watch_var.get()))
        self.min_confidence_var.set(cfg.get("min_confidence", self.min_confidence_var.get()))
        self.min_rssi_var.set(cfg.get("min_rssi", self.min_rssi_var.get()))
        self.omnisig_api_var.set(cfg.get("omnisig_api", self.omnisig_api_var.get()))
        self.esp32_endpoint_var.set(cfg.get("esp32_endpoint", self.esp32_endpoint_var.get()))
        self.enable_led_trigger.set(cfg.get("enable_led_trigger", self.enable_led_trigger.get()))
        self.case_sensitive.set(cfg.get("case_sensitive", self.case_sensitive.get()))
        self.beep.set(cfg.get("beep", self.beep.get()))

    def _save_config(self):
        cfg = {
            "endpoint": self.endpoint_var.get(),
            "topic": self.topic_var.get(),
            "watch_var": self.watch_var.get(),
            "min_confidence": self.min_confidence_var.get(),
            "min_rssi": self.min_rssi_var.get(),
            "omnisig_api": self.omnisig_api_var.get(),
            "esp32_endpoint": self.esp32_endpoint_var.get(),
            "enable_led_trigger": self.enable_led_trigger.get(),
            "case_sensitive": self.case_sensitive.get(),
            "beep": self.beep.get(),
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
            self.log_line(">> Config saved to config.json", 'success')
        except Exception as e:
            self.log_line(f">> ERROR saving config: {e}", 'error')

    def log_line(self, s: str, tag=None):
        ts = time.strftime("%H:%M:%S")
        # Insert timestamp with muted color
        self.log.insert("end", f"[{ts}] ", 'timestamp')
        # Insert message with optional tag
        if tag:
            self.log.insert("end", f"{s}\n", tag)
        else:
            self.log.insert("end", f"{s}\n")
        self.log.see("end")

    def clear_log(self):
        self.log.delete("1.0", "end")

    def on_connect(self):
        if self.sub_thread and self.sub_thread.is_alive():
            return

        endpoint = self.endpoint_var.get().strip()
        if not endpoint:
            messagebox.showerror("Missing endpoint", "Please enter a ZMQ endpoint like tcp://127.0.0.1:4002")
            return

        topic = self.topic_var.get().strip()
        self.stop_evt.clear()
        self.sub_thread = ZmqSubscriberThread(endpoint, topic, self.msg_q, self.stop_evt)
        self.sub_thread.start()

        self.connect_btn.configure(state="disabled", bg=COLORS['bg_secondary'])
        self.disconnect_btn.configure(state="normal", bg=COLORS['bg'])
        self.status_lbl.configure(text="[CONNECTING...]", fg=COLORS['warning'])

    def on_disconnect(self):
        self.stop_evt.set()
        self.connect_btn.configure(state="normal", bg=COLORS['bg'])
        self.disconnect_btn.configure(state="disabled", bg=COLORS['bg_secondary'])
        self.status_lbl.configure(text="[DISCONNECTING...]", fg=COLORS['warning'])

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "status":
                    if "Connected" in payload:
                        self.status_lbl.configure(text="[CONNECTED]", fg=COLORS['success'])
                    elif "Disconnected" in payload:
                        self.status_lbl.configure(text="[DISCONNECTED]", fg=COLORS['fg_secondary'])
                    else:
                        self.status_lbl.configure(text="[CONNECTING...]", fg=COLORS['warning'])
                    self.log_line(payload, 'success' if "Connected" in payload else 'info')
                elif kind == "error":
                    self.status_lbl.configure(text="[ERROR]", fg=COLORS['error'])
                    self.log_line(payload, 'error')
                elif kind == "raw":
                    self.log_line(payload, 'warning')
                elif kind == "json":
                    self._handle_json(payload)
        except queue.Empty:
            pass
        self.after(75, self._poll_queue)

    def _watchlist(self):
        raw = self.watch_var.get()
        items = [x.strip() for x in raw.split(",") if x.strip()]
        if not self.case_sensitive.get():
            items = [x.lower() for x in items]
        return set(items)

    def _handle_json(self, msg: dict):
        types = extract_signal_type(msg)
        if not types:
            # Uncomment if you want noisy logs:
            # self.log_line("JSON received (no type found)")
            return

        # Extract confidence and RSSI
        confidence = extract_confidence(msg)
        rssi = extract_rssi(msg)

        watch = self._watchlist()
        matched = []

        for t in types:
            key = t if self.case_sensitive.get() else t.lower()
            if key in watch:
                matched.append(t)

        if matched:
            # Check if LED trigger conditions are met
            if self.enable_led_trigger.get() and not self.led_active:
                # Check cooldown
                time_since_last = time.time() - self.last_trigger_time
                if time_since_last < self.trigger_cooldown:
                    self.log_line(f">> DETECTED: {', '.join(matched)} (confidence={confidence}, rssi={rssi}) - COOLDOWN ACTIVE", 'warning')
                    return

                # Check thresholds
                try:
                    min_conf = float(self.min_confidence_var.get())
                    min_rssi = float(self.min_rssi_var.get())

                    meets_confidence = confidence is None or confidence >= min_conf
                    meets_rssi = rssi is None or rssi >= min_rssi

                    if meets_confidence and meets_rssi:
                        self.log_line(f">> LED TRIGGER: {', '.join(matched)} (conf={confidence}, rssi={rssi})", 'success')
                        self._trigger_led_sequence(", ".join(matched), confidence, rssi)
                    else:
                        self.log_line(f">> DETECTED: {', '.join(matched)} (conf={confidence}, rssi={rssi}) - BELOW THRESHOLD", 'warning')
                except ValueError:
                    self.log_line(">> ERROR: Invalid confidence or RSSI threshold values", 'error')
                    self._trigger_alert(", ".join(matched), msg=msg)
            else:
                self._trigger_alert(", ".join(matched), msg=msg)
        else:
            self.log_line(f">> DETECTED: {', '.join(types)}", 'info')

    def _trigger_alert(self, signal_type: str, msg=None):
        self.alert_count.set(self.alert_count.get() + 1)

        # Flash the alert counter
        self._flash_alert_counter()

        # Log with alert styling - Terminal/Matrix style
        self.log_line("▓" * 70, 'alert')
        self.log_line(f">>> ALERT TRIGGERED :: WATCHED SIGNAL DETECTED <<<", 'alert')
        self.log_line(f">>> SIGNAL TYPE: {signal_type}", 'alert')
        self.log_line("▓" * 70, 'alert')

        if self.beep.get():
            try:
                self.master.bell()
                # Multiple beeps for emphasis
                self.after(100, self.master.bell)
                self.after(200, self.master.bell)
            except Exception:
                pass

        # Update status
        self.status_lbl.configure(text=f"[ALERT: {signal_type[:15]}]", fg=COLORS['alert'])

        # If you want to log details:
        # if msg is not None:
        #     self.log_line("Raw JSON: " + json.dumps(msg)[:400] + ("..." if len(json.dumps(msg)) > 400 else ""))

    def _flash_alert_counter(self):
        """Flash the alert counter for visual feedback"""
        original_bg = COLORS['bg']
        flash_bg = COLORS['bg_accent']

        def flash(times=0):
            if times < 6:  # Flash 3 times (6 color changes)
                current_bg = self.alert_label.cget('bg')
                new_bg = flash_bg if current_bg == original_bg else original_bg
                self.alert_label.configure(bg=new_bg)
                self.after(150, lambda: flash(times + 1))
            else:
                self.alert_label.configure(bg=original_bg)

        flash()

    def _trigger_led_sequence(self, signal_type, confidence, rssi):
        """Execute the LED trigger sequence in a background thread"""
        if self.led_active:
            return

        # Run the sequence in a separate thread to avoid blocking the UI
        thread = threading.Thread(target=self._led_sequence_worker,
                                  args=(signal_type, confidence, rssi),
                                  daemon=True)
        thread.start()

    def _led_sequence_worker(self, signal_type, confidence, rssi):
        """Worker thread for LED sequence"""
        try:
            self.led_active = True
            omnisig_api_endpoint = self.omnisig_api_var.get()
            esp32_endpoint = self.esp32_endpoint_var.get()

            # Step 1: Stop OmniSIG inference
            self.msg_q.put(("status", "Stopping OmniSIG inference..."))
            api_client = OmniSIGAPIClient(omnisig_api_endpoint)
            response = api_client.stop_inference()
            self.msg_q.put(("status", f"OmniSIG stopped: {response}"))

            # Step 2: Trigger JAM sequence on ESP32 (self-timed, 10 seconds)
            node_states['NODE-01'] = 'JAMMING'
            self.msg_q.put(("status", "Triggering JAM sequence on ESP32..."))
            try:
                resp = requests.get(f"{esp32_endpoint}/jam", timeout=3)
                self.msg_q.put(("status", f"JAM triggered: {resp.status_code}"))
            except Exception as e:
                self.msg_q.put(("error", f"ESP32 JAM failed: {e}"))

            # Trigger alert visuals/sound
            self._trigger_alert(signal_type, msg=None)

            # Step 3: Wait for jam duration to complete
            time.sleep(10)

            # Step 5: Restart OmniSIG inference
            self.msg_q.put(("status", "Restarting OmniSIG inference..."))
            response = api_client.start_inference()
            self.msg_q.put(("status", f"OmniSIG restarted: {response}"))
            api_client.close()
            node_states['NODE-01'] = 'IDLE'

            # Step 6: Set cooldown timer
            self.last_trigger_time = time.time()
            self.msg_q.put(("status", f"LED sequence complete. Cooldown: {self.trigger_cooldown}s"))

        except Exception as e:
            self.msg_q.put(("error", f"LED sequence error: {e}"))
        finally:
            self.led_active = False


def main():
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    root = tk.Tk()

    # Set window icon behavior (optional, helps with taskbar)
    try:
        root.iconbitmap('')  # This prevents default tk icon
    except Exception:
        pass

    app = App(root)

    def on_close():
        app.stop_evt.set()
        if app.omnisig_api:
            app.omnisig_api.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
