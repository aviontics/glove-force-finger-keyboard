// ============================================================
// SENTIENT GLOVE - SENDER v3  (glove side)
// Board: ESP32-S3 (XIAO ESP32S3 Plus or dev module)
// Sensors: thin-film FSRs in DIGITAL mode -> each between GPIO and GND
// Gestures: TAP / DOUBLE_TAP / LONG_START+END / 10s hold -> SETUP
// Adds: 400 ms heartbeat so the dongle can report link RSSI
// ============================================================
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

const uint8_t NUM = 3;
const uint8_t fsrPins[NUM]     = {1, 5, 3};        // finger 1, 2, 3
const bool    dtapEnabled[NUM] = {true, true, true};

const uint32_t DEBOUNCE_MS   = 20;
const uint32_t LONG_MS       = 400;
const uint32_t DOUBLE_GAP_MS = 250;
const uint32_t SETUP_MS      = 10000;
const uint32_t HEARTBEAT_MS  = 400;                // link/RSSI beacon

enum EvCode : uint8_t { EV_TAP = 1, EV_DTAP, EV_LONG_START, EV_LONG_END, EV_SETUP };
const uint8_t HB_FINGER = 0xFF;                    // heartbeat marker

struct TapEvent { uint8_t finger; uint8_t event; };
uint8_t bcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

enum GState : uint8_t { IDLE, PRESSED, LONG_ACTIVE, WAIT_SECOND, PRESSED2, WAIT_RELEASE };
GState   gs[NUM];
bool     lastRaw[NUM], stable[NUM];
uint32_t lastChange[NUM], tPress[NUM], tRelease[NUM];

void sendEv(uint8_t f, uint8_t ev) {
  TapEvent e = {f, ev};
  esp_now_send(bcast, (uint8_t*)&e, sizeof(e));
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(6, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_LR);
  esp_now_init();
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, bcast, 6);
  peer.channel = 6;
  esp_now_add_peer(&peer);
  for (int i = 0; i < NUM; i++) {
    pinMode(fsrPins[i], INPUT_PULLUP);
    gs[i] = IDLE;
    lastRaw[i] = stable[i] = false;
  }
}

void loop() {
  uint32_t now = millis();

  // ---- heartbeat for link monitoring ----
  static uint32_t lastHB = 0;
  if (now - lastHB >= HEARTBEAT_MS) {
    lastHB = now;
    sendEv(HB_FINGER, 0);
  }

  for (int i = 0; i < NUM; i++) {
    bool raw = (digitalRead(fsrPins[i]) == LOW);
    if (raw != lastRaw[i]) { lastRaw[i] = raw; lastChange[i] = now; }
    bool changed = false;
    if ((now - lastChange[i]) >= DEBOUNCE_MS && raw != stable[i]) {
      stable[i] = raw;
      changed = true;
    }
    bool pressed = stable[i];

    switch (gs[i]) {
      case IDLE:
        if (changed && pressed) { tPress[i] = now; gs[i] = PRESSED; }
        break;
      case PRESSED:
        if (pressed && (now - tPress[i]) >= LONG_MS) {
          sendEv(i, EV_LONG_START);
          gs[i] = LONG_ACTIVE;
        } else if (changed && !pressed) {
          if (dtapEnabled[i]) { tRelease[i] = now; gs[i] = WAIT_SECOND; }
          else { sendEv(i, EV_TAP); gs[i] = IDLE; }
        }
        break;
      case LONG_ACTIVE:
        if (pressed && (now - tPress[i]) >= SETUP_MS) {
          sendEv(i, EV_LONG_END);              // lift held key first
          sendEv(i, EV_SETUP);                 // then request setup
          gs[i] = WAIT_RELEASE;
        } else if (changed && !pressed) {
          sendEv(i, EV_LONG_END);
          gs[i] = IDLE;
        }
        break;
      case WAIT_SECOND:
        if (changed && pressed) { sendEv(i, EV_DTAP); gs[i] = PRESSED2; }
        else if ((now - tRelease[i]) >= DOUBLE_GAP_MS) { sendEv(i, EV_TAP); gs[i] = IDLE; }
        break;
      case PRESSED2:
        if (changed && !pressed) gs[i] = IDLE;
        break;
      case WAIT_RELEASE:
        if (changed && !pressed) gs[i] = IDLE;
        break;
    }
  }
  delay(1);
}
