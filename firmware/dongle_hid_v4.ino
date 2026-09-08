// ============================================================
// SENTIENT GLOVE - DONGLE v4  (USB receiver side)
// Board: ESP32-S3. Tools -> USB Mode: "USB-OTG (TinyUSB)",
//                  USB CDC On Boot: Enabled
//
// Each gesture slot is a BINDING: modifier set + key.
//   mods bitmask: bit0 Ctrl, bit1 Shift, bit2 Alt, bit3 Win/GUI
//   code: HID keycode (ASCII for printable, KEY_* for specials, 0 = none)
// Long press = binding held down until the finger releases (true PTT).
// Modifiers are reference-counted so a tap on one finger never
// releases a modifier another finger is still holding.
//
// Serial protocol (115200, newline-terminated):
//   PC -> dongle:  GET
//                  SET,f,slot,mods,code      slot t/d/l
//   dongle -> PC:  READY
//                  MAP,f,tm,tk,dm,dk,lm,lk   per finger: mods,key for tap/double/long
//                  EV,f,code                 1 tap 2 dtap 3 long-start 4 long-end 5 setup
//                  HB,rssi
//                  SETUP,f
//                  OK / ERR
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

enum { MOD_CTRL = 1, MOD_SHIFT = 2, MOD_ALT = 4, MOD_GUI = 8 };
const uint8_t modKey[4] = {KEY_LEFT_CTRL, KEY_LEFT_SHIFT, KEY_LEFT_ALT, KEY_LEFT_GUI};
uint8_t modCount[4] = {0, 0, 0, 0};

struct KeyBind { uint8_t mods; uint8_t code; };
KeyBind bind[MAX_F][3];                       // [finger][0 tap, 1 dtap, 2 long]

const KeyBind defBind[MAX_F][3] = {
  {{0, 'a'},                {0, 'A'}, {MOD_CTRL | MOD_ALT, 'r'}},   // F1: long = Ctrl+Alt+R (PTT)
  {{MOD_CTRL | MOD_ALT, 'j'}, {0, 'B'}, {0, KEY_F14}},              // F2: tap = Ctrl+Alt+J
  {{0, KEY_RETURN},         {0, 'C'}, {0, KEY_F15}},                // F3: tap = Enter
  {{0, 'd'},                {0, 'D'}, {0, KEY_F16}},
  {{0, 'e'},                {0, 'E'}, {0, KEY_F17}},
  {{0, 'f'},                {0, 'F'}, {0, KEY_F18}},
};
const char slotChar[3] = {'t', 'd', 'l'};

// ---------- modifier reference counting ----------
void modsDown(uint8_t m) {
  for (int i = 0; i < 4; i++)
    if (m & (1 << i)) { if (modCount[i]++ == 0) Keyboard.press(modKey[i]); }
}
void modsUp(uint8_t m) {
  for (int i = 0; i < 4; i++)
    if (m & (1 << i)) { if (modCount[i] > 0 && --modCount[i] == 0) Keyboard.release(modKey[i]); }
}

void tapBind(const KeyBind& b) {
  if (!b.code && !b.mods) return;
  modsDown(b.mods);
  if (b.code) { Keyboard.press(b.code); delay(8); Keyboard.release(b.code); }
  else        { delay(8); }                   // modifier-only tap
  modsUp(b.mods);
}
void holdBind(const KeyBind& b) {
  modsDown(b.mods);
  if (b.code) Keyboard.press(b.code);
}
void releaseBind(const KeyBind& b) {
  if (b.code) Keyboard.release(b.code);
  modsUp(b.mods);
}

// ---------- radio queue ----------
volatile uint8_t qF[32], qE[32];
volatile int8_t  qR[32];
volatile uint8_t qHead = 0, qTail = 0;

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len != sizeof(TapEvent)) return;
  TapEvent e;
  memcpy(&e, data, len);
  int8_t rssi = (info && info->rx_ctrl) ? info->rx_ctrl->rssi : 0;
  uint8_t next = (qHead + 1) & 31;
  if (next != qTail) { qF[qHead] = e.finger; qE[qHead] = e.event; qR[qHead] = rssi; qHead = next; }
}

// ---------- persistence ----------
void prefKey(char* k, uint8_t f, uint8_t slot) { k[0] = "TDL"[slot]; k[1] = '0' + f; k[2] = 0; }

void saveBind(uint8_t f, uint8_t slot, KeyBind b) {
  char k[3]; prefKey(k, f, slot);
  prefs.putUShort(k, ((uint16_t)b.mods << 8) | b.code);
  bind[f][slot] = b;
}
void loadBinds() {
  for (uint8_t f = 0; f < MAX_F; f++)
    for (uint8_t s = 0; s < 3; s++) {
      char k[3]; prefKey(k, f, s);
      uint16_t d = ((uint16_t)defBind[f][s].mods << 8) | defBind[f][s].code;
      uint16_t v = prefs.getUShort(k, d);
      bind[f][s] = { (uint8_t)(v >> 8), (uint8_t)(v & 0xFF) };
    }
}

void printMap() {
  for (uint8_t f = 0; f < MAX_F; f++)
    Serial.printf("MAP,%u,%u,%u,%u,%u,%u,%u\n", f,
                  bind[f][0].mods, bind[f][0].code,
                  bind[f][1].mods, bind[f][1].code,
                  bind[f][2].mods, bind[f][2].code);
  Serial.println("OK");
}

// ---------- serial commands ----------
void handleLine(String s) {
  s.trim();
  if (s.length() == 0) return;
  if (s == "GET") { printMap(); return; }
  if (s.startsWith("SET,")) {
    // SET,f,slot,mods,code
    int tok[4]; String rest = s.substring(4); int n = 0; char slot = 0;
    while (n < 4 && rest.length()) {
      int c = rest.indexOf(','); String part = (c < 0) ? rest : rest.substring(0, c);
      if (n == 1) slot = part.charAt(0); else tok[n] = part.toInt();
      rest = (c < 0) ? "" : rest.substring(c + 1); n++;
    }
    int f = tok[0], mods = tok[2], code = tok[3];
    int si = (slot == 't') ? 0 : (slot == 'd') ? 1 : (slot == 'l') ? 2 : -1;
    if (n == 4 && f >= 0 && f < MAX_F && si >= 0 && mods >= 0 && mods <= 15 && code >= 0 && code <= 255) {
      saveBind((uint8_t)f, (uint8_t)si, { (uint8_t)mods, (uint8_t)code });
      Serial.println("OK");
      return;
    }
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

  prefs.begin("keymap4");
  loadBinds();
  Serial.println("READY");
  printMap();
}

String rxLine;

void loop() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') { if (rxLine.length()) { handleLine(rxLine); rxLine = ""; } }
    else if (rxLine.length() < 64) rxLine += ch;
  }

  while (qTail != qHead) {
    uint8_t f = qF[qTail], ev = qE[qTail]; int8_t r = qR[qTail];
    qTail = (qTail + 1) & 31;

    if (f == HB_FINGER) { Serial.printf("HB,%d\n", r); continue; }
    if (f >= MAX_F) continue;

    Serial.printf("EV,%u,%u\n", f, ev);
    switch (ev) {
      case EV_TAP:        tapBind(bind[f][0]);     break;
      case EV_DTAP:       tapBind(bind[f][1]);     break;
      case EV_LONG_START: holdBind(bind[f][2]);    break;   // down while finger held
      case EV_LONG_END:   releaseBind(bind[f][2]); break;   // up when finger lifts
      case EV_SETUP:      Serial.printf("SETUP,%u\n", f); break;
    }
  }
}
