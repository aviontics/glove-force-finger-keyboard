# Sentient Glove

**A hands-free hotkey glove.** Tap your fingertips to fire keyboard keys on your PC — push-to-talk, Enter, macros, anything — with no Bluetooth pairing, sub-10 ms latency and long range.

Built by [Sentient Robotics](https://sentientrobotics.example) on the ESP32-S3.

---

## How it works

```
 ┌──────────────┐   2.4 GHz ESP-NOW    ┌──────────────┐   USB HID    ┌──────┐
 │  GLOVE       │ ───────────────────▶ │  DONGLE      │ ───────────▶ │  PC  │
 │  ESP32-S3    │   long-range mode    │  ESP32-S3    │  (keyboard)  │      │
 │  3 × FSR     │                      │              │ ◀──────────▶ │      │
 └──────────────┘                      └──────────────┘  USB serial  └──────┘
                                                          (config app)
```

- The **glove** carries an ESP32-S3 and three thin-film force sensors on the fingertips. It detects taps, double-taps and long presses and sends them by radio.
- The **dongle** is a second ESP32-S3 plugged into the PC. It appears as a standard wired USB keyboard and turns each gesture into a keystroke. The key mapping lives on the dongle in flash, so remapping never touches the glove.
- The **Sentient Glove Control** desktop app talks to the dongle over USB serial to configure key mappings and show live telemetry, including a range radar.

Because the dongle is a plain USB keyboard, it works on any machine with no drivers and no pairing.

---

## Repository layout

| Path | What it is |
|---|---|
| `firmware/glove_sender_v3.ino` | Glove firmware: sensor reading, gesture engine, heartbeat, LED |
| `firmware/dongle_hid_v3.ino` | Dongle firmware: ESP-NOW receiver, USB HID keyboard, keymap storage, serial protocol |
| `app/sentient_glove_control.py` | PyQt6 desktop configurator |
| `hardware/` | Enclosure CAD (Fusion 360) and bill of materials |

---

## Hardware

### Bill of materials (per glove)

| Qty | Part | Notes |
|---|---|---|
| 1 | Seeed XIAO ESP32S3 Plus | Glove controller. Built-in LiPo charging. |
| 1 | ESP32-S3 board with native USB (XIAO ESP32S3 or S3 mini dev board) | Dongle |
| 3 | Thin-film force-sensitive resistor (FSR 400 type, 20 g–10 kg) | One per fingertip |
| 1 | 3.7 V LiPo, ~500 mAh, JST-PH | Glove power |
| 1 | Mini slide switch | Battery on/off |
| 1 | Thin sports/cycling glove | Wearable base |
| — | 30 AWG silicone wire, heat-shrink, adhesive | Harness |
| — | 3D-printed enclosure (see `hardware/`) | Two-tier case: battery below, board above |

No resistors are required: the sensors are read in **digital mode** using the ESP32's internal pull-ups.

### Wiring the glove

Each sensor connects between **its GPIO and GND**. Nothing connects to 3V3.

| Finger | GPIO | XIAO pin |
|---|---|---|
| 1 | GPIO1 | A0 / D0 |
| 2 | GPIO5 | D4 |
| 3 | GPIO3 | A2 / D2 |

Both GND legs from all three sensors can share one wire back to the board's GND pin.

> **Handling FSRs:** never solder directly to the sensor's film tail — the printed traces delaminate with heat. Use crimp connectors or a slide-on female header.

> **GPIO3 is a strapping pin.** Don't hold finger 3 pressed while powering on or resetting the glove.

Battery: solder the LiPo to the BAT+ / BAT− pads on the underside of the XIAO, with the slide switch in the BAT+ line. Charging happens automatically over the board's USB-C.

### Power-on indicator

The XIAO's user LED (GPIO21) flashes briefly every two seconds while the glove is running. Flip the switch on → LED flashes; off → dark. The orange LED next to it is the charger and lights on its own while charging.

---

## Firmware

Both boards are programmed from the Arduino IDE with the **esp32** board package (3.x) installed via Boards Manager. Use **Arduino IDE 2.x** — on Ubuntu, install it from arduino.cc, not the snap, and add yourself to the `dialout` group.

### Glove — `glove_sender_v3.ino`

Board: your XIAO ESP32S3 / ESP32S3 Dev Module. Default USB settings. Flash normally.

Adding sensors later is a two-line edit at the top of the file:

```cpp
const uint8_t NUM = 3;
const uint8_t fsrPins[NUM]     = {1, 5, 3};
const bool    dtapEnabled[NUM] = {true, true, true};
```

### Dongle — `dongle_hid_v3.ino`

Board settings that matter:

| Setting | Value |
|---|---|
| USB Mode | **USB-OTG (TinyUSB)** |
| USB CDC On Boot | **Enabled** |

**Flashing a board that is already running dongle firmware:** the auto-reset doesn't work in OTG mode, so:

1. Hold **BOOT**, tap **RESET**, release **BOOT** — the board enters download mode and its serial port appears.
2. Upload.
3. Press **RESET** once more to run the new firmware. (Forgetting this leaves the board sitting in the bootloader: no keyboard, and a serial port that never answers.)

After flashing, the dongle shows up as a USB keyboard *and* a USB serial port at the same time.

Both boards are hard-coded to radio channel 6 in long-range mode and must match. They pair automatically — no MAC addresses to enter.

---

## Using the glove

### Gestures

Every finger supports three independent gestures, each mapped to its own key:

| Gesture | How | Default keys (F1 / F2 / F3) |
|---|---|---|
| **Tap** | Press and release within 400 ms | `a` / `b` / `c` |
| **Double tap** | Two taps within 250 ms | `A` / `B` / `C` |
| **Long press** | Hold longer than 400 ms | `F13` / `F14` / `F15` |

Long press behaves like holding a real key: the key goes **down** at the 400 ms mark and comes **up** when you let go. This is how push-to-talk works — map the long press to your PTT key.

F13–F24 are the recommended PTT keys: no application uses them by default, so they never collide with anything. Bind them in Discord, TeamSpeak or your game.

**Latency note:** on a finger with double-tap enabled, a single tap fires ~250 ms after release (the glove waits to see if a second tap is coming). Fingers with double-tap disabled fire instantly. Set `dtapEnabled` per finger accordingly.

### Setup mode (remap without the app)

Hold any sensor for **10 seconds**. The glove requests setup for that finger; if the desktop app is connected, a dialog opens to assign its three keys. Release the sensor, choose the keys, done. Mappings are saved to the dongle's flash immediately and survive power cycles.

> During the 10-second hold the long-press key is held down until the 10 s mark, then released. Click into the app or a harmless window first.

Timing constants (`LONG_MS`, `DOUBLE_GAP_MS`, `SETUP_MS`) are at the top of the glove firmware if you want to tune the feel.

---

## Sentient Glove Control (desktop app)

![Sentient Glove Control](docs/app.png)

### Install

```bash
pip install PyQt6 pyserial
python app/sentient_glove_control.py
```

Runs on Windows, macOS and Linux. On Linux you need read/write access to the dongle's serial port (`dialout` group on Ubuntu).

### Interface

**Dongle Link** — click **SCAN**, choose the dongle's port, click **CONNECT**. The status indicator turns green (`GLOVE ONLINE`) as soon as heartbeats arrive from the glove. `SERIAL ONLY — NO GLOVE` means the dongle is connected but the glove is off or out of range.

**Key Mapping** — a grid of finger × gesture. Each cell is a picker: choose a named key from the dropdown (Enter, Backspace, Tab, Esc, Space, Delete, Home/End, Page Up/Down, arrows, Ctrl/Shift/Alt/Win, F1–F24) or type a single character. Leave a cell blank to unassign that gesture.
- **READ FROM DEVICE** pulls the current map from the dongle.
- **APPLY ALL** writes every cell to the dongle's flash.

**Telemetry** — live log of every gesture received (`finger 2: DOUBLE TAP`), setup requests and command results. Use it to verify sensors and timing.

**Glove Range** — a sweep radar showing link strength (RSSI). The blip drifts outward as signal weakens; the centre shows an estimated distance. Click **CALIBRATE @ 1 m** with the glove one metre from the dongle to anchor the estimate to your hardware. Distance derived from signal strength is indicative only — it's a link-health indicator, not a tape measure. `NO LINK` appears if no heartbeat arrives for 2 seconds.

### Serial protocol

The app is optional — anything that speaks 115200-baud serial can configure the dongle.

| Direction | Message | Meaning |
|---|---|---|
| PC → dongle | `GET` | Request the keymap |
| PC → dongle | `SET,f,slot,code` | Set finger `f` (0–5), slot `t`/`d`/`l` (tap/double/long), to HID keycode `code` (0–255; 0 = none) |
| dongle → PC | `READY` | Booted |
| dongle → PC | `MAP,f,tap,dtap,long` | One line per finger, keycodes as decimals |
| dongle → PC | `EV,f,code` | Gesture received: 1 tap, 2 double, 3 long start, 4 long end, 5 setup |
| dongle → PC | `HB,rssi` | Heartbeat with link RSSI in dBm (every ~400 ms) |
| dongle → PC | `SETUP,f` | Glove requested setup for finger `f` |
| dongle → PC | `OK` / `ERR` | Command result |

Keycodes follow the Arduino keyboard convention: printable characters are their ASCII value; special keys are `0x80`+ (Enter `176`, Backspace `178`, F13 `240`, …).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Nothing types, app opens the port but gets no response | Dongle stuck in bootloader after flashing | Press **RESET** on the dongle |
| Serial port disappears after flashing the dongle | Expected — it's now a keyboard | Enable *USB CDC On Boot*, and use BOOT+RESET to reflash |
| App connects but `NO LINK` | Glove off, out of range, or channel/LR mismatch | Check switch/LED, bring closer, confirm both firmwares use channel 6 + LR |
| A tap fires on two fingers at once | Sensor wires bridged or wrong pins | Continuity-check between finger signal wires; verify GPIO assignments |
| Taps trigger too easily / when gripping things | Thin-film sensors are sensitive | Raise `DEBOUNCE_MS`, mount sensors flat (not under tension), or use firmer press |
| Slow single taps | Double-tap wait | Set `dtapEnabled` to `false` for that finger |
| Glove won't reset/boot | Finger 3 held during power-up | Release finger 3 (GPIO3 is a strapping pin) |

---

## Roadmap

- Battery percentage reported to the app (spare byte in the heartbeat)
- Key combinations / macros per gesture
- Media keys (volume, play/pause)
- Per-finger settings in the app (double-tap enable, timing)

---

## License

MIT — see `LICENSE`.
