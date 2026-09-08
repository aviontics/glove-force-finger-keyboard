// ============================================================
// SENTIENT GLOVE - DONGLE v3  (USB receiver side)
// Board: ESP32-S3. Tools -> USB Mode: "USB-OTG (TinyUSB)",
//                  USB CDC On Boot: Enabled
// USB HID keyboard + CDC serial protocol for the desktop app.
//
// Serial protocol (115200, newline-terminated):
//   PC -> dongle:  GET               request current keymap
//                  SET,f,slot,c      f=finger 0-5, slot t/d/l, c=character
//   dongle -> PC:  READY             on boot
//                  MAP,f,tap,dtap,long   (x6, after GET or boot)
//                  EV,f,code         gesture received (code 1-5)
//                  HB,rssi           heartbeat with link RSSI in dBm
//                  SETUP,f           glove requested setup for finger f
//                  OK / ERR          command results
// ============================================================
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "USB.h"
#include "USBHIDKeyboard.h"
#include <Preferences.h>

USBHIDKeyboard Keyboard;
Preferences prefs;

const uint8_t MAX_F = 6;
enum EvCode : uint8_t { EV_TAP = 1, EV_DTAP, EV_LONG_START, EV_LONG_END, EV_SETUP };
const uint8_t HB_FINGER = 0xFF;
struct TapEvent { uint8_t finger; uint8_t event; };

char keyTap[MAX_F], keyDtap[MAX_F], keyLong[MAX_F];
const char defTap[MAX_F]  = {'a', 'b', 'c', 'd', 'e', 'f'};
const char defDtap[MAX_F] = {'A', 'B', 'C', 'D', 'E', 'F'};
const char defLong[MAX_F] = {'1', '2', '3', '4', '5', '6'};

// small lock-free queue filled by the radio callback, drained in loop()
volatile uint8_t qF[32], qE[32];
volatile int8_t  qR[32];
volatile uint8_t qHead = 0, qTail = 0;

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len != sizeof(TapEvent)) return;
  TapEvent e;
  memcpy(&e, data, len);
  int8_t rssi = (info && info->rx_ctrl) ? info->rx_ctrl->rssi : 0;
  uint8_t next = (qHead + 1) & 31;
  if (next != qTail) {
    qF[qHead] = e.finger;
    qE[qHead] = e.event;
    qR[qHead] = rssi;
    qHead = next;
  }
}

void saveKey(uint8_t f, char slot, char c) {
  char k[3] = {slot, (char)('0' + f), 0};
  prefs.putUChar(k, (uint8_t)c);
  if (slot == 't')      keyTap[f]  = c;
  else if (slot == 'd') keyDtap[f] = c;
  else                  keyLong[f] = c;
}

void printMap() {
  for (uint8_t f = 0; f < MAX_F; f++)
    Serial.printf("MAP,%u,%c,%c,%c\n", f, keyTap[f], keyDtap[f], keyLong[f]);
  Serial.println("OK");
}

void handleLine(String s) {
  s.trim();
  if (s.length() == 0) return;
  if (s == "GET") { printMap(); return; }
  if (s.startsWith("SET,")) {
    int a = s.indexOf(',', 4);
    int b = (a > 0) ? s.indexOf(',', a + 1) : -1;
    if (a > 0 && b > 0 && b + 1 < (int)s.length()) {
      int  f    = s.substring(4, a).toInt();
      char slot = s.charAt(a + 1);
      char c    = s.charAt(b + 1);
      if (f >= 0 && f < MAX_F && (slot == 't' || slot == 'd' || slot == 'l')) {
        saveKey((uint8_t)f, slot, c);
        Serial.println("OK");
        return;
      }
    }
    Serial.println("ERR");
    return;
  }
  Serial.println("ERR");
}

void setup() {
  Serial.begin(115200);
  Keyboard.begin();
  USB.begin();

  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(6, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_LR);
  esp_now_init();
  esp_now_register_recv_cb(onRecv);

  prefs.begin("keymap");
  for (uint8_t f = 0; f < MAX_F; f++) {
    char k[3] = {'t', (char)('0' + f), 0};
    keyTap[f]  = (char)prefs.getUChar(k, defTap[f]);
    k[0] = 'd';
    keyDtap[f] = (char)prefs.getUChar(k, defDtap[f]);
    k[0] = 'l';
    keyLong[f] = (char)prefs.getUChar(k, defLong[f]);
  }
  Serial.println("READY");
  printMap();
}

String rxLine;

void loop() {
  // ---- serial commands from the desktop app ----
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (rxLine.length()) { handleLine(rxLine); rxLine = ""; }
    } else if (rxLine.length() < 64) {
      rxLine += ch;
    }
  }

  // ---- radio events ----
  while (qTail != qHead) {
    uint8_t f  = qF[qTail];
    uint8_t ev = qE[qTail];
    int8_t  r  = qR[qTail];
    qTail = (qTail + 1) & 31;

    if (f == HB_FINGER) {               // heartbeat -> link telemetry
      Serial.printf("HB,%d\n", r);
      continue;
    }
    if (f >= MAX_F) continue;

    Serial.printf("EV,%u,%u\n", f, ev);

    switch (ev) {
      case EV_TAP:        Keyboard.write(keyTap[f]);    break;
      case EV_DTAP:       Keyboard.write(keyDtap[f]);   break;
      case EV_LONG_START: Keyboard.press(keyLong[f]);   break;
      case EV_LONG_END:   Keyboard.release(keyLong[f]); break;
      case EV_SETUP:      Serial.printf("SETUP,%u\n", f); break;
    }
  }
}
