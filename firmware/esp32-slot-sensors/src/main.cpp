// ESP32 slots-01 — VL53L0X thật ở F1-A1 + 17 nút giả lập qua 2 MCP23017.
// Hợp đồng: docs/mqtt-contract.md §4, ánh xạ ô: docs/parking-layout.md.
//
// Đấu nối (bus I²C chung 3,3V): SDA → GPIO21, SCL → GPIO22
//   MCP23017 #1 địa chỉ 0x20 (A0=A1=A2=GND): GPA0..GPB7 = nút B1..B16
//   MCP23017 #2 địa chỉ 0x21 (A0=VCC):       GPA0       = nút B17
//   Mỗi nút: một chân vào MCP, chân kia GND (dùng pull-up trong MCP, nhấn = LOW). RESET MCP nối 3V3.
//   VL53L0X địa chỉ 0x29, đặt nhìn xuống ô F1-A1.
#include <Adafruit_MCP23X17.h>
#include <Preferences.h>
#include <VL53L0X.h>
#include <Wire.h>

// WiFi/WiFiClientSecure include ở đây để PlatformIO LDF nhận ra thư viện framework.
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "parking_net.h"

using namespace parking;

static const char *SLOT_IDS[18] = {"F1-A1", "F1-A2", "F1-A3", "F1-B1", "F1-B2", "F1-B3",
                                   "F1-C1", "F1-C2", "F1-C3", "F2-A1", "F2-A2", "F2-A3",
                                   "F2-B1", "F2-B2", "F2-B3", "F2-C1", "F2-C2", "F2-C3"};

// ── hiệu chỉnh ToF trên sa bàn (đo bằng Serial monitor: dòng "[tof] mm=…") ──
static const uint16_t TOF_OCCUPIED_MM = 60;  // gần hơn → có xe
static const uint16_t TOF_FREE_MM = 90;      // xa hơn → trống (khoảng giữa = trễ, giữ trạng thái cũ)
static const int TOF_CONFIRM_SAMPLES = 5;    // số mẫu liên tiếp trước khi đổi trạng thái
static const uint32_t TOF_PERIOD_MS = 100;
static const uint32_t DEBOUNCE_MS = 50;
static const uint32_t SNAPSHOT_MS = 30000;

Adafruit_MCP23X17 mcp1, mcp2;
bool mcp1Ok = false, mcp2Ok = false, tofOk = false;
VL53L0X tof;
Preferences nvs;
Link net;
const String T_STATE = topic("slots", "slots-01", "state");

bool occupied[18] = {false};

// Nút: i = 1..17 ứng với SLOT_IDS[i]. Trạng thái debounce riêng mỗi nút.
struct Button {
  bool raw = true, stable = true;  // HIGH = nhả (pull-up)
  uint32_t changedAt = 0;
} buttons[18];

int tofVotes = 0;
uint32_t lastTof = 0, lastSnapshot = 0, lastTofLog = 0;
bool pendingChange[18] = {false};

const char *sourceOf(int i) { return i == 0 ? "SENSOR" : "BUTTON"; }

void saveNvs() {
  uint32_t bits = 0;
  for (int i = 1; i < 18; i++)
    if (occupied[i]) bits |= 1UL << i;
  nvs.putUInt("bits", bits);  // chỉ lưu 17 ô nút; F1-A1 luôn đọc lại từ cảm biến
}

void loadNvs() {
  uint32_t bits = nvs.getUInt("bits", 0);
  for (int i = 1; i < 18; i++) occupied[i] = bits & (1UL << i);
}

void publishChanged(int i) {
  JsonDocument doc;
  net.envelope(doc, "slot_changed");
  doc["slot_id"] = SLOT_IDS[i];
  doc["occupied"] = occupied[i];
  doc["source"] = sourceOf(i);
  if (!net.publish(T_STATE, doc)) pendingChange[i] = true;  // offline: snapshot sau reconnect sẽ đồng bộ
}

void publishSnapshot() {
  JsonDocument doc;
  net.envelope(doc, "slots_snapshot");
  JsonArray arr = doc["slots"].to<JsonArray>();
  int count = 0;
  for (int i = 0; i < 18; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["slot_id"] = SLOT_IDS[i];
    o["occupied"] = occupied[i];
    o["source"] = sourceOf(i);
    count += occupied[i];
  }
  if (net.publish(T_STATE, doc, false)) {
    Serial.printf("[pub] snapshot 18 ô (%d có xe)\n", count);
    memset(pendingChange, 0, sizeof(pendingChange));
  }
  lastSnapshot = millis();
}

void setSlot(int i, bool value) {
  if (occupied[i] == value) return;
  occupied[i] = value;
  Serial.printf("[slot] %s → %s (%s)\n", SLOT_IDS[i], value ? "CO XE" : "trong", sourceOf(i));
  if (i > 0) saveNvs();
  publishChanged(i);
}

void readButtons() {
  uint16_t a = mcp1Ok ? mcp1.readGPIOAB() : 0xFFFF;
  uint16_t b = mcp2Ok ? mcp2.readGPIOAB() : 0xFFFF;
  uint32_t now = millis();
  for (int i = 1; i < 18; i++) {
    bool level = i <= 16 ? (a >> (i - 1)) & 1 : (b >> (i - 17)) & 1;
    Button &btn = buttons[i];
    if (level != btn.raw) {
      btn.raw = level;
      btn.changedAt = now;
    }
    if (btn.raw != btn.stable && now - btn.changedAt >= DEBOUNCE_MS) {
      btn.stable = btn.raw;
      if (!btn.stable) setSlot(i, !occupied[i]);  // mỗi lần NHẤN đảo trạng thái
    }
  }
}

void readTof() {
  if (!tofOk || millis() - lastTof < TOF_PERIOD_MS) return;
  lastTof = millis();
  uint16_t mm = tof.readRangeContinuousMillimeters();
  if (tof.timeoutOccurred() || mm >= 8000) return;  // 8190 = ngoài tầm
  if (millis() - lastTofLog > 2000) {
    Serial.printf("[tof] mm=%u (co xe <%u, trong >%u)\n", mm, TOF_OCCUPIED_MM, TOF_FREE_MM);
    lastTofLog = millis();
  }
  bool want = occupied[0];
  if (mm < TOF_OCCUPIED_MM) want = true;
  else if (mm > TOF_FREE_MM) want = false;
  if (want != occupied[0]) {
    if (++tofVotes >= TOF_CONFIRM_SAMPLES) {
      tofVotes = 0;
      setSlot(0, want);
    }
  } else {
    tofVotes = 0;
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n=== slots-01 firmware %s ===\n", FIRMWARE_VERSION);
  nvs.begin("slots", false);
  loadNvs();
  Wire.begin(21, 22);
  Wire.setClock(400000);

  mcp1Ok = mcp1.begin_I2C(0x20);
  mcp2Ok = mcp2.begin_I2C(0x21);
  for (int p = 0; p < 16; p++) {
    if (mcp1Ok) mcp1.pinMode(p, INPUT_PULLUP);
    if (mcp2Ok && p == 0) mcp2.pinMode(p, INPUT_PULLUP);
  }
  if (!mcp1Ok) Serial.println("[hw] ✗ không thấy MCP23017 0x20 (nút B1..B16)");
  if (!mcp2Ok) Serial.println("[hw] ✗ không thấy MCP23017 0x21 (nút B17)");

  tof.setTimeout(200);
  tofOk = tof.init();
  if (tofOk) {
    tof.startContinuous(50);
  } else {
    Serial.println("[hw] ✗ không thấy VL53L0X 0x29 (F1-A1)");
  }
  net.degraded = !(mcp1Ok && mcp2Ok && tofOk);
  // Đọc mức nút ban đầu để không coi nút đang giữ lúc khởi động là một lần nhấn.
  uint16_t a = mcp1Ok ? mcp1.readGPIOAB() : 0xFFFF, b = mcp2Ok ? mcp2.readGPIOAB() : 0xFFFF;
  for (int i = 1; i < 18; i++) buttons[i].raw = buttons[i].stable = i <= 16 ? (a >> (i - 1)) & 1 : (b >> (i - 17)) & 1;

  net.begin(nullptr);
}

void loop() {
  net.loop();
  if (net.justConnected) publishSnapshot();  // đủ 18 ô lúc boot/reconnect
  readButtons();
  readTof();
  if (net.connected() && millis() - lastSnapshot >= SNAPSHOT_MS) publishSnapshot();
  delay(5);
}
