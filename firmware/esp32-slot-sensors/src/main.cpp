#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <MQTT.h>                       // 256dpi/MQTT, hỗ trợ publish QoS 1
#include <ArduinoJson.h>
#include <Preferences.h>
#include <Adafruit_MCP23X17.h>
#include <Adafruit_VL53L0X.h>
#include <time.h>
#include "config.h"
#include "secrets.h"

static Adafruit_MCP23X17 mcp[2];
static bool mcpOk[2];
static Adafruit_VL53L0X tof;
static bool tofOk = false;

static WiFiClientSecure net;
static MQTTClient mqtt(2048);           // snapshot 18 ô ~1.5 KB
static Preferences prefs;

static bool occ[SLOT_COUNT];            // trạng thái thật của nút / ToF
static bool btnRaw[BTN_COUNT], btnStable[BTN_COUNT];
static uint32_t btnT[BTN_COUNT];

static bool tofRaw, tofStable;
static uint32_t tofT, tofLastOkMs, tofRetryAt;
static uint16_t tofBuf[TOF_SAMPLES];
static uint8_t tofN = 0, tofIdx = 0;

static char bootId[37];
static uint32_t seqNo = 0;              // seq đầu tiên = 0, tăng theo thứ tự publish
static bool pending[SLOT_COUNT];        // ô đã đổi, chưa gửi slot_changed
static bool snapshotDue = true, statusDue = true;
static bool savePending = false;
static uint32_t saveAt, lastScan, lastNet, wifiTry, lastSnap, lastStatus;
static char willBuf[420];

static bool timeSynced() { return time(nullptr) > 1700000000; }
static void markChanged(int s) { pending[s] = true; }

// Giá trị gửi lên: ToF lỗi thì theo TOF_FAULT_OCCUPIED
static bool reported(int i) { return (i == TOF_SLOT && !tofOk) ? TOF_FAULT_OCCUPIED : occ[i]; }
static const char* sourceOf(int i) { return i == TOF_SLOT ? "SENSOR" : "BUTTON"; }

// ---------- UUID v4 và thời gian ISO-8601 ----------
static void uuid4(char out[37]) {
  uint8_t b[16];
  for (int i = 0; i < 16; i += 4) { uint32_t r = esp_random(); memcpy(b + i, &r, 4); }
  b[6] = (b[6] & 0x0F) | 0x40;          // version 4
  b[8] = (b[8] & 0x3F) | 0x80;          // variant
  snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7],
           b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

static void isoNow(char out[24]) {
  time_t t = time(nullptr); struct tm tmv; gmtime_r(&t, &tmv);
  strftime(out, 24, "%Y-%m-%dT%H:%M:%SZ", &tmv);       // luôn có hậu tố Z
}

// ---------- Nút bấm ----------
static void readButtons(bool out[BTN_COUNT]) {
  uint16_t v[2] = {0xFFFF, 0xFFFF};
  for (int c = 0; c < 2; c++) if (mcpOk[c]) v[c] = mcp[c].readGPIOAB();   // A = byte thấp, B = byte cao
  for (int i = 0; i < BTN_COUNT; i++) {
    const BtnMap& m = BTN_MAP[i];
    out[i] = mcpOk[m.chip] && !((v[m.chip] >> m.pin) & 1);               // active-low
  }
}

static void scanButtons(uint32_t now) {
  bool cur[BTN_COUNT];
  readButtons(cur);
  for (int i = 0; i < BTN_COUNT; i++) {
    if (cur[i] != btnRaw[i]) { btnRaw[i] = cur[i]; btnT[i] = now; }
    else if (cur[i] != btnStable[i] && now - btnT[i] >= DEBOUNCE_MS) {
      btnStable[i] = cur[i];
      if (btnStable[i]) {                                                 // cạnh nhấn => đảo trạng thái ô
        uint8_t s = BTN_MAP[i].slot;
        occ[s] = !occ[s];
        markChanged(s);
        savePending = true; saveAt = now + NVS_SAVE_DELAY_MS;
      }
    }
  }
}

// ---------- ToF ----------
static uint16_t median(uint16_t* a, uint8_t n) {
  uint16_t t[TOF_SAMPLES];
  memcpy(t, a, n * sizeof(uint16_t));
  for (uint8_t i = 1; i < n; i++) {
    uint16_t k = t[i]; int j = i - 1;
    while (j >= 0 && t[j] > k) { t[j + 1] = t[j]; j--; }
    t[j + 1] = k;
  }
  return t[n / 2];
}

static bool initTof() {
  if (!tof.begin(TOF_ADDR, false, &Wire)) return false;
  VL53L0X_RangingMeasurementData_t m;
  tof.rangingTest(&m, false);
  bool o = (m.RangeStatus != 4) && (m.RangeMilliMeter <= TOF_ON_MM);
  tofRaw = tofStable = o; occ[TOF_SLOT] = o;
  tofN = tofIdx = 0;
  tof.startRangeContinuous(TOF_PERIOD_MS);
  tofLastOkMs = millis();
  return true;
}

static void updateTof(uint32_t now) {
  if (!tofOk) {
    if (now >= tofRetryAt) {
      tofRetryAt = now + TOF_RETRY_MS;
      if (initTof()) { tofOk = true; markChanged(TOF_SLOT); statusDue = true; }
    }
    return;
  }
  if (tof.isRangeComplete()) {
    uint16_t mm = tof.readRange();
    tofLastOkMs = now;
    if (mm == 0 || mm > 8000) mm = 8190;                                  // ngoài tầm => coi là xa
    tofBuf[tofIdx] = mm; tofIdx = (tofIdx + 1) % TOF_SAMPLES;
    if (tofN < TOF_SAMPLES) tofN++;
    if (tofN < TOF_SAMPLES) return;
    uint16_t med = median(tofBuf, TOF_SAMPLES);
#ifdef TOF_DEBUG
    Serial.printf("tof raw=%u median=%u\n", mm, med);
#endif
    bool raw = tofRaw;
    if (med <= TOF_ON_MM) raw = true;
    else if (med >= TOF_OFF_MM) raw = false;
    if (raw != tofRaw) { tofRaw = raw; tofT = now; }
    if (tofRaw != tofStable && now - tofT >= TOF_DEBOUNCE_MS) {
      tofStable = tofRaw; occ[TOF_SLOT] = tofStable; markChanged(TOF_SLOT);
    }
  } else if (now - tofLastOkMs > TOF_TIMEOUT_MS) {
    tofOk = false; tofRetryAt = now + TOF_RETRY_MS;
    markChanged(TOF_SLOT); statusDue = true;                              // DEGRADED + F1-A1 theo TOF_FAULT_OCCUPIED
  }
}

// ---------- NVS ----------
static void saveMask() {
  uint32_t m = 0;
  for (int s = 1; s < SLOT_COUNT; s++) if (occ[s]) m |= (1u << s);        // bỏ bit 0 (ToF luôn đọc thật)
  prefs.putUInt("mask", m);
}

// ---------- MQTT ----------
static void fillHeader(JsonDocument& d, const char* type) {
  char id[37], ts[24]; uuid4(id); isoNow(ts);
  d["schema_version"] = SCHEMA_VERSION;
  d["message_type"]   = type;
  d["event_id"]       = id;
  d["device_id"]      = DEVICE_ID;
  d["boot_id"]        = bootId;
  d["seq"]            = seqNo++;
  d["occurred_at"]    = ts;
}

static bool sendDoc(const char* topic, JsonDocument& d) {
  static char buf[2048];
  size_t n = serializeJson(d, buf, sizeof buf);
  if (n == 0 || n >= sizeof buf) return false;
  return mqtt.publish(topic, buf, false, 1);                              // retain=false, QoS 1
}

static bool publishSlotChanged(int i) {
  JsonDocument d; fillHeader(d, "slot_changed");
  d["slot_id"] = SLOT_IDS[i]; d["occupied"] = reported(i); d["source"] = sourceOf(i);
  return sendDoc(TOPIC_STATE, d);
}

static bool publishSnapshot() {
  JsonDocument d; fillHeader(d, "slots_snapshot");
  JsonArray a = d["slots"].to<JsonArray>();                               // đủ 18 ID, mỗi ID đúng một lần
  for (int i = 0; i < SLOT_COUNT; i++) {
    JsonObject o = a.add<JsonObject>();
    o["slot_id"] = SLOT_IDS[i]; o["occupied"] = reported(i); o["source"] = sourceOf(i);
  }
  return sendDoc(TOPIC_STATE, d);
}

static bool publishStatus() {
  JsonDocument d; fillHeader(d, "device_status");
  bool healthy = tofOk && mcpOk[0] && mcpOk[1];
  d["state"] = healthy ? "ONLINE" : "DEGRADED";
  d["firmware_version"] = FW_VERSION;
  return sendDoc(TOPIC_STATUS, d);
}

static void buildWill() {                                                 // Last Will cũng phải đủ phần đầu
  char id[37], ts[24]; uuid4(id); isoNow(ts);
  snprintf(willBuf, sizeof willBuf,
    "{\"schema_version\":%d,\"message_type\":\"device_status\",\"event_id\":\"%s\","
    "\"device_id\":\"%s\",\"boot_id\":\"%s\",\"seq\":0,\"occurred_at\":\"%s\","
    "\"state\":\"OFFLINE\",\"firmware_version\":\"%s\"}",
    SCHEMA_VERSION, id, DEVICE_ID, bootId, ts, FW_VERSION);
}

static void ensureNet(uint32_t now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (now - wifiTry > 10000) { wifiTry = now; WiFi.begin(WIFI_SSID, WIFI_PASS); }
    return;
  }
  if (!mqtt.connected() && timeSynced() && now - lastNet > 3000) {        // cần giờ thật cho occurred_at
    lastNet = now;
    buildWill();
    mqtt.setWill(TOPIC_STATUS, willBuf, false, 1);
    if (mqtt.connect(DEVICE_ID)) { snapshotDue = true; statusDue = true; } // reconnect: snapshot ngay, giữ boot_id và seq
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  uuid4(bootId);                                                          // boot_id mới mỗi lần khởi động
  Wire.begin(PIN_SDA, PIN_SCL, I2C_HZ);

  const uint8_t addr[2] = {MCP_ADDR_0, MCP_ADDR_1};
  for (int c = 0; c < 2; c++) {
    mcpOk[c] = mcp[c].begin_I2C(addr[c], &Wire);
    if (!mcpOk[c]) { Serial.printf("MCP23017 0x%02X not found!\n", addr[c]); continue; }
    for (int p = 0; p < 16; p++) mcp[c].pinMode(p, INPUT_PULLUP);
  }

  prefs.begin("slots", false);
  uint32_t m = prefs.getUInt("mask", 0);                                  // khôi phục "xe ảo" của các nút
  for (int s = 1; s < SLOT_COUNT; s++) occ[s] = (m >> s) & 1;

  readButtons(btnRaw);                                                    // nút đang bị giữ lúc khởi động
  memcpy(btnStable, btnRaw, sizeof btnStable);                            // không tính là một lần nhấn

  tofOk = initTof();
  if (!tofOk) Serial.println("VL53L0X not found! F1-A1 => theo TOF_FAULT_OCCUPIED");

  net.setCACert(AWS_CA); net.setCertificate(AWS_CERT); net.setPrivateKey(AWS_KEY);
  mqtt.begin(AWS_ENDPOINT, 8883, net);
  mqtt.setKeepAlive(30);
  mqtt.setTimeout(5000);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  configTime(0, 0, "pool.ntp.org", "time.google.com");                    // NTP bắt buộc cho occurred_at
}

void loop() {
  uint32_t now = millis();
  ensureNet(now);
  mqtt.loop();

  if (now - lastScan >= SCAN_MS) {
    lastScan = now; scanButtons(now); updateTof(now);
  }
  if (savePending && (int32_t)(now - saveAt) >= 0) { saveMask(); savePending = false; }

  if (mqtt.connected() && timeSynced()) {
    if (snapshotDue || now - lastSnap >= SNAPSHOT_PERIOD_MS) {
      if (publishSnapshot()) {
        snapshotDue = false; lastSnap = now;
        memset(pending, 0, sizeof pending);                               // snapshot đã gồm mọi thay đổi
      }
    } else {
      for (int i = 0; i < SLOT_COUNT; i++)
        if (pending[i] && publishSlotChanged(i)) pending[i] = false;      // phát ngay khi đổi
    }
    if (statusDue || now - lastStatus >= STATUS_PERIOD_MS) {
      if (publishStatus()) { statusDue = false; lastStatus = now; }
    }
  }
  digitalWrite(PIN_LED, mqtt.connected());
  delay(1);
}