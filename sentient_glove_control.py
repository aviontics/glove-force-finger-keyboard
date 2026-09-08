#!/usr/bin/env python3
"""
SENTIENT GLOVE CONTROL
Desktop configurator for the Sentient Robotics hands-free hotkey glove.

Requires:  pip install PyQt6 pyserial
Firmware:  dongle_hid_v2.ino on the dongle, glove_sender_v2.ino on the glove.
Run:       python sentient_glove_control.py
"""

import math
import sys
import time

import serial
from serial.tools import list_ports
from PyQt6 import QtCore, QtGui, QtWidgets

FINGERS = 3          # rows shown in the mapper (firmware supports up to 6)
BAUD = 115200
EV_NAMES = {1: "TAP", 2: "DOUBLE TAP", 3: "LONG PRESS \u25bc", 4: "LONG PRESS \u25b2", 5: "SETUP REQUEST"}
SLOTS = [("t", "Tap"), ("d", "Double tap"), ("l", "Long press")]

# HID keycodes as used by the ESP32 USBHIDKeyboard library (Arduino Keyboard convention).
# Printable keys are their ASCII value; specials live at 0x80+. 0 = unassigned.
SPECIAL_KEYS = [
    ("Enter", 0xB0), ("Backspace", 0xB2), ("Tab", 0xB3), ("Esc", 0xB1), ("Space", 0x20),
    ("Delete", 0xD4), ("Insert", 0xD1), ("Home", 0xD2), ("End", 0xD5),
    ("Page Up", 0xD3), ("Page Down", 0xD6),
    ("Up", 0xDA), ("Down", 0xD9), ("Left", 0xD8), ("Right", 0xD7),
    ("Left Ctrl", 0x80), ("Left Shift", 0x81), ("Left Alt", 0x82), ("Left GUI/Win", 0x83),
    ("Right Ctrl", 0x84), ("Right Shift", 0x85), ("Right Alt", 0x86), ("Right GUI/Win", 0x87),
    ("Caps Lock", 0xC1), ("Print Screen", 0xCE), ("Scroll Lock", 0xCF), ("Pause", 0xD0),
] + [(f"F{n}", 0xC2 + n - 1) for n in range(1, 13)] \
  + [(f"F{n}", 0xF0 + n - 13) for n in range(13, 25)]
NAME_TO_CODE = {name.lower(): code for name, code in SPECIAL_KEYS}
CODE_TO_NAME = {code: name for name, code in SPECIAL_KEYS}


def code_to_label(code: int) -> str:
    if code == 0:
        return ""
    if code in CODE_TO_NAME:
        return CODE_TO_NAME[code]
    if 33 <= code <= 126:
        return chr(code)
    return f"#{code}"


def label_to_code(text: str):
    """Returns a keycode, 0 for blank/none, or None if unrecognised."""
    t = text.strip()
    if t == "" or t.lower() in ("none", "-", "--"):
        return 0
    if t.lower() in NAME_TO_CODE:
        return NAME_TO_CODE[t.lower()]
    if len(t) == 1 and 33 <= ord(t) <= 126:
        return ord(t)
    if t.startswith("#") and t[1:].isdigit() and 0 <= int(t[1:]) <= 255:
        return int(t[1:])
    return None


class KeyPicker(QtWidgets.QComboBox):
    """Editable combo: pick a named special key, or type a single character."""

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.addItem("")
        for name, _ in SPECIAL_KEYS:
            self.addItem(name)
        self.setFixedWidth(118)
        self.lineEdit().setObjectName("keycap")
        self.setToolTip("Type one character, or choose a special key")

    def set_code(self, code: int):
        self.setCurrentText(code_to_label(code))

    def code(self):
        return label_to_code(self.currentText())

ACCENT = "#00e5ff"
ACCENT2 = "#1de9b6"
WARN = "#ff5370"
BG = "#070c11"
PANEL = "#0d151d"
TEXT = "#cfe8e6"

QSS = f"""
* {{ font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QGroupBox {{
    background: {PANEL};
    border: 1px solid #16323d;
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 14px; padding: 0 6px;
    color: {ACCENT}; letter-spacing: 3px; font-size: 11px; font-weight: 600;
}}
QPushButton {{
    background: #0f2530; color: {ACCENT};
    border: 1px solid #1a4a5a; border-radius: 6px;
    padding: 6px 14px; letter-spacing: 1px;
}}
QPushButton:hover {{ background: #143544; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #0a1c26; }}
QPushButton:disabled {{ color: #3a5560; border-color: #14303a; }}
QPushButton#danger {{ color: {WARN}; border-color: #5a1a2a; }}
QComboBox, QLineEdit {{
    background: #091018; border: 1px solid #1a4a5a; border-radius: 6px;
    padding: 5px 8px; color: {TEXT}; selection-background-color: #145a6e;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit#keycap {{
    font-family: 'Consolas', 'DejaVu Sans Mono', monospace;
    font-size: 14px; font-weight: 700; color: {ACCENT2};
    qproperty-alignment: AlignCenter;
    border: none; background: transparent;
}}
QComboBox QAbstractItemView {{
    background: #091018; color: {TEXT}; selection-background-color: #145a6e;
    border: 1px solid #1a4a5a;
}}
QPlainTextEdit {{
    background: #050a0f; border: 1px solid #16323d; border-radius: 8px;
    font-family: 'Consolas', 'DejaVu Sans Mono', monospace; font-size: 12px;
    color: #8fd8c8;
}}
QLabel#title {{
    color: {ACCENT}; font-size: 22px; font-weight: 300; letter-spacing: 8px;
}}
QLabel#subtitle {{ color: #4d7a86; font-size: 10px; letter-spacing: 4px; }}
QLabel#status_ok {{ color: {ACCENT2}; letter-spacing: 2px; }}
QLabel#status_bad {{ color: {WARN}; letter-spacing: 2px; }}
QLabel#colhead {{ color: #4d7a86; font-size: 10px; letter-spacing: 2px; }}
"""


# ----------------------------------------------------------------------
class SerialWorker(QtCore.QThread):
    """Owns the serial port; emits every incoming line."""
    line = QtCore.pyqtSignal(str)
    closed = QtCore.pyqtSignal(str)

    def __init__(self, port: str):
        super().__init__()
        self._port_name = port
        self._ser = None
        self._run = True
        self._lock = QtCore.QMutex()

    def run(self):
        try:
            self._ser = serial.Serial(self._port_name, BAUD, timeout=0.2)
        except Exception as e:                                    # noqa: BLE001
            self.closed.emit(f"open failed: {e}")
            return
        buf = b""
        while self._run:
            try:
                chunk = self._ser.read(64)
            except Exception as e:                                # noqa: BLE001
                self.closed.emit(f"link lost: {e}")
                break
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    text = raw.decode(errors="replace").strip()
                    if text:
                        self.line.emit(text)
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:                                         # noqa: BLE001
            pass

    def send(self, text: str):
        with QtCore.QMutexLocker(self._lock):
            if self._ser and self._ser.is_open:
                try:
                    self._ser.write((text + "\n").encode())
                except Exception:                                 # noqa: BLE001
                    pass

    def stop(self):
        self._run = False
        self.wait(1000)


# ----------------------------------------------------------------------
class RangeRadar(QtWidgets.QWidget):
    """Futuristic sweep radar showing link RSSI and an estimated range."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 260)
        self.rssi = None          # smoothed dBm
        self.linked = False
        self.dist = None          # metres, estimated
        self._sweep = 0.0
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)

    def _tick(self):
        self._sweep = (self._sweep + 2.4) % 360.0
        self.update()

    def set_link(self, rssi, dist, linked):
        self.rssi, self.dist, self.linked = rssi, dist, linked

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 12

        p.fillRect(self.rect(), QtGui.QColor(BG))

        grid = QtGui.QPen(QtGui.QColor(20, 60, 72), 1)
        p.setPen(grid)
        for frac in (1.0, 0.72, 0.45, 0.2):
            p.drawEllipse(QtCore.QPointF(cx, cy), r * frac, r * frac)
        p.drawLine(QtCore.QPointF(cx - r, cy), QtCore.QPointF(cx + r, cy))
        p.drawLine(QtCore.QPointF(cx, cy - r), QtCore.QPointF(cx, cy + r))

        if self.linked:
            # sweep wedge
            grad = QtGui.QConicalGradient(cx, cy, -self._sweep)
            grad.setColorAt(0.0, QtGui.QColor(0, 229, 255, 120))
            grad.setColorAt(0.12, QtGui.QColor(0, 229, 255, 0))
            grad.setColorAt(1.0, QtGui.QColor(0, 229, 255, 0))
            p.setBrush(QtGui.QBrush(grad))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.drawEllipse(QtCore.QPointF(cx, cy), r, r)

            # strength arc: map RSSI -95..-30 dBm -> 0..1
            if self.rssi is not None:
                pct = max(0.0, min(1.0, (self.rssi + 95.0) / 65.0))
                pen = QtGui.QPen(QtGui.QColor(ACCENT2), 5)
                pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                rect = QtCore.QRectF(cx - r + 4, cy - r + 4, 2 * r - 8, 2 * r - 8)
                p.drawArc(rect, 90 * 16, -int(360 * 16 * pct))

            # glove blip at radius proportional to (1 - strength)
            if self.rssi is not None:
                pct = max(0.0, min(1.0, (self.rssi + 95.0) / 65.0))
                blip_r = r * (0.15 + 0.75 * (1.0 - pct))
                ang = math.radians(self._sweep)
                bx = cx + blip_r * math.cos(ang)
                by = cy - blip_r * math.sin(ang)
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(QtGui.QColor(ACCENT))
                p.drawEllipse(QtCore.QPointF(bx, by), 4, 4)

        # centre text
        p.setPen(QtGui.QColor(ACCENT if self.linked else WARN))
        f = p.font()
        f.setPointSize(17)
        f.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(f)
        if not self.linked:
            centre = "NO LINK"
        elif self.dist is None:
            centre = "--"
        else:
            centre = f"\u2248 {self.dist:.1f} m"
        p.drawText(self.rect().adjusted(0, -10, 0, -10),
                   QtCore.Qt.AlignmentFlag.AlignCenter, centre)

        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QtGui.QColor("#4d7a86"))
        sub = f"RSSI {self.rssi:.0f} dBm" if (self.linked and self.rssi is not None) else "awaiting heartbeat"
        p.drawText(self.rect().adjusted(0, 34, 0, 0),
                   QtCore.Qt.AlignmentFlag.AlignCenter, sub)
        p.end()


# ----------------------------------------------------------------------
class SetupDialog(QtWidgets.QDialog):
    """Shown when the glove requests setup (10 s hold on a sensor)."""

    def __init__(self, finger: int, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure finger {finger + 1}")
        self.setStyleSheet(QSS)
        lay = QtWidgets.QFormLayout(self)
        head = QtWidgets.QLabel(f"SETUP MODE \u2014 FINGER {finger + 1}")
        head.setObjectName("status_ok")
        lay.addRow(head)
        self.edits = {}
        for slot, label in SLOTS:
            e = KeyPicker()
            e.set_code(current.get(slot, 0))
            self.edits[slot] = e
            lay.addRow(label, e)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def values(self):
        out = {}
        for slot, e in self.edits.items():
            c = e.code()
            if c is not None:
                out[slot] = c
        return out


# ----------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sentient Glove Control")
        self.resize(980, 640)
        self.setStyleSheet(QSS)

        self.worker = None
        self.rssi_ema = None
        self.rssi_at_1m = -50.0       # calibratable
        self.path_exp = 2.4
        self.last_hb = 0.0

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)

        # ---------- header ----------
        head = QtWidgets.QHBoxLayout()
        tcol = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("SENTIENT GLOVE CONTROL")
        title.setObjectName("title")
        sub = QtWidgets.QLabel("SENTIENT ROBOTICS \u2022 HANDS-FREE HOTKEY SYSTEM")
        sub.setObjectName("subtitle")
        tcol.addWidget(title)
        tcol.addWidget(sub)
        head.addLayout(tcol)
        head.addStretch(1)
        self.status = QtWidgets.QLabel("\u25cf OFFLINE")
        self.status.setObjectName("status_bad")
        head.addWidget(self.status)
        root.addLayout(head)

        body = QtWidgets.QHBoxLayout()
        root.addLayout(body, 1)
        left = QtWidgets.QVBoxLayout()
        right = QtWidgets.QVBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)

        # ---------- connection ----------
        conn = QtWidgets.QGroupBox("DONGLE LINK")
        cl = QtWidgets.QHBoxLayout(conn)
        self.port_box = QtWidgets.QComboBox()
        self.btn_refresh = QtWidgets.QPushButton("SCAN")
        self.btn_conn = QtWidgets.QPushButton("CONNECT")
        cl.addWidget(self.port_box, 1)
        cl.addWidget(self.btn_refresh)
        cl.addWidget(self.btn_conn)
        left.addWidget(conn)

        # ---------- keymap ----------
        km = QtWidgets.QGroupBox("KEY MAPPING")
        grid = QtWidgets.QGridLayout(km)
        grid.setHorizontalSpacing(14)
        for col, name in enumerate(["FINGER", "TAP", "DOUBLE TAP", "LONG PRESS"]):
            lbl = QtWidgets.QLabel(name)
            lbl.setObjectName("colhead")
            grid.addWidget(lbl, 0, col, QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.key_edits = []           # [finger][slot] -> QLineEdit
        for f in range(FINGERS):
            grid.addWidget(QtWidgets.QLabel(f"F{f + 1}"), f + 1, 0,
                           QtCore.Qt.AlignmentFlag.AlignHCenter)
            row = {}
            for col, (slot, _label) in enumerate(SLOTS, start=1):
                e = KeyPicker()
                grid.addWidget(e, f + 1, col, QtCore.Qt.AlignmentFlag.AlignHCenter)
                row[slot] = e
            self.key_edits.append(row)
        btns = QtWidgets.QHBoxLayout()
        self.btn_read = QtWidgets.QPushButton("READ FROM DEVICE")
        self.btn_apply = QtWidgets.QPushButton("APPLY ALL")
        btns.addWidget(self.btn_read)
        btns.addWidget(self.btn_apply)
        btns.addStretch(1)
        grid.addLayout(btns, FINGERS + 1, 0, 1, 4)
        left.addWidget(km)

        # ---------- event log ----------
        lg = QtWidgets.QGroupBox("TELEMETRY")
        ll = QtWidgets.QVBoxLayout(lg)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        ll.addWidget(self.log)
        left.addWidget(lg, 1)

        # ---------- radar ----------
        rg = QtWidgets.QGroupBox("GLOVE RANGE  (RSSI ESTIMATE)")
        rl = QtWidgets.QVBoxLayout(rg)
        self.radar = RangeRadar()
        rl.addWidget(self.radar, 1)
        cal = QtWidgets.QHBoxLayout()
        self.btn_cal = QtWidgets.QPushButton("CALIBRATE @ 1 m")
        self.cal_lbl = QtWidgets.QLabel("ref \u2212 50 dBm")
        self.cal_lbl.setObjectName("colhead")
        cal.addWidget(self.btn_cal)
        cal.addWidget(self.cal_lbl)
        cal.addStretch(1)
        rl.addLayout(cal)
        note = QtWidgets.QLabel("Range is inferred from signal strength \u2014 indicative only.")
        note.setObjectName("colhead")
        note.setWordWrap(True)
        rl.addWidget(note)
        right.addWidget(rg, 1)

        # ---------- wiring ----------
        self.btn_refresh.clicked.connect(self.scan_ports)
        self.btn_conn.clicked.connect(self.toggle_conn)
        self.btn_read.clicked.connect(lambda: self._send("GET"))
        self.btn_apply.clicked.connect(self.apply_all)
        self.btn_cal.clicked.connect(self.calibrate)

        self.watchdog = QtCore.QTimer(self)
        self.watchdog.timeout.connect(self._check_link)
        self.watchdog.start(500)

        self.scan_ports()
        self._set_online(False)

    # ---------------- serial plumbing ----------------
    def scan_ports(self):
        self.port_box.clear()
        for p in list_ports.comports():
            self.port_box.addItem(f"{p.device}  \u2014  {p.description}", p.device)

    def toggle_conn(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
            self._set_online(False)
            self._log("link closed")
            self.btn_conn.setText("CONNECT")
            return
        if self.port_box.currentIndex() < 0:
            self._log("no port selected")
            return
        port = self.port_box.currentData()
        self.worker = SerialWorker(port)
        self.worker.line.connect(self.on_line)
        self.worker.closed.connect(self.on_closed)
        self.worker.start()
        self.btn_conn.setText("DISCONNECT")
        self._log(f"opening {port} \u2026")
        QtCore.QTimer.singleShot(800, lambda: self._send("GET"))

    def on_closed(self, why: str):
        self._log(why)
        self.worker = None
        self.btn_conn.setText("CONNECT")
        self._set_online(False)

    def _send(self, text: str):
        if self.worker:
            self.worker.send(text)

    # ---------------- protocol ----------------
    def on_line(self, s: str):
        self.last_hb_seen = True
        if s.startswith("HB,"):
            try:
                r = float(s[3:])
            except ValueError:
                return
            self.last_hb = time.monotonic()
            self.rssi_ema = r if self.rssi_ema is None else (0.8 * self.rssi_ema + 0.2 * r)
            d = 10 ** ((self.rssi_at_1m - self.rssi_ema) / (10 * self.path_exp))
            d = max(0.1, min(300.0, d))
            self.radar.set_link(self.rssi_ema, d, True)
            self._set_online(True)
            return
        if s.startswith("MAP,"):
            parts = s.split(",")
            if len(parts) == 5:
                try:
                    f = int(parts[1])
                except ValueError:
                    return
                if 0 <= f < FINGERS:
                    for (slot, _), val in zip(SLOTS, parts[2:5]):
                        if val.isdigit():
                            self.key_edits[f][slot].set_code(int(val))
            return
        if s.startswith("EV,"):
            parts = s.split(",")
            if len(parts) == 3:
                name = EV_NAMES.get(int(parts[2]) if parts[2].isdigit() else 0, "?")
                self._log(f"finger {int(parts[1]) + 1}: {name}")
            return
        if s.startswith("SETUP,"):
            try:
                f = int(s.split(",")[1])
            except (ValueError, IndexError):
                return
            self._log(f"finger {f + 1}: SETUP MODE requested")
            if f < FINGERS:
                self.run_setup(f)
            return
        if s in ("READY", "OK", "ERR"):
            self._log(s.lower())
            return
        self._log(s)

    def run_setup(self, f: int):
        current = {slot: (self.key_edits[f][slot].code() or 0) for slot, _ in SLOTS}
        dlg = SetupDialog(f, current, self)
        if dlg.exec():
            for slot, code in dlg.values().items():
                self._send(f"SET,{f},{slot},{code}")
                self.key_edits[f][slot].set_code(code)
            self._log(f"finger {f + 1}: mapping saved")

    def apply_all(self):
        if not self.worker:
            self._log("not connected")
            return
        n, bad = 0, []
        for f in range(FINGERS):
            for slot, _ in SLOTS:
                code = self.key_edits[f][slot].code()
                if code is None:
                    bad.append(f"F{f + 1} {dict(SLOTS)[slot].lower()}")
                    continue
                self._send(f"SET,{f},{slot},{code}")
                n += 1
        self._log(f"sent {n} mapping(s)" + (f"; unrecognised: {', '.join(bad)}" if bad else ""))

    def calibrate(self):
        if self.rssi_ema is None:
            self._log("no signal to calibrate against")
            return
        self.rssi_at_1m = self.rssi_ema
        self.cal_lbl.setText(f"ref {self.rssi_at_1m:.0f} dBm")
        self._log(f"calibrated: {self.rssi_at_1m:.0f} dBm = 1 m")

    # ---------------- housekeeping ----------------
    def _check_link(self):
        if self.worker and (time.monotonic() - self.last_hb) > 2.0:
            self.radar.set_link(None, None, False)
            self._set_online(False, keep_serial=True)

    def _set_online(self, ok: bool, keep_serial: bool = False):
        if ok:
            self.status.setObjectName("status_ok")
            self.status.setText("\u25cf GLOVE ONLINE")
        else:
            self.status.setObjectName("status_bad")
            self.status.setText("\u25cf SERIAL ONLY \u2014 NO GLOVE" if (self.worker and keep_serial)
                                else "\u25cf OFFLINE")
            if not keep_serial:
                self.radar.set_link(None, None, False)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{ts}] {msg}")

    def closeEvent(self, ev):
        if self.worker:
            self.worker.stop()
        super().closeEvent(ev)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
