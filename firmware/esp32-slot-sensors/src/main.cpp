// ESP32 slots-01 — 18 nút bấm nối thẳng vào GPIO, mỗi nút một ô. Nhấn = đảo trạng thái ô (trống ↔ có xe).
// Hợp đồng: docs/mqtt-contract.md §4, ánh xạ ô: docs/parking-layout.md.
//
// Đấu nối (ESP32 thường, esp32dev): mỗi nút một chân vào GPIO bên dưới, chân kia vào GND.
// Dùng pull-up trong chip → không cần điện trở; nhả = HIGH, nhấn = LOW.
// Chân chưa cắm nút luôn đọc HIGH nên coi như "chưa nhấn" — cắm thêm nút lúc nào cũng được.
//
//   F1-A1 → 25   F1-A2 → 26   F1-A3 → 27
//   F1-B1 → 32   F1-B2 → 33   F1-B3 → 4
//   F1-C1 → 13   F1-C2 → 14   F1-C3 → 16
//   F2-A1 → 17   F2-A2 → 18   F2-A3 → 19
//   F2-B1 → 21   F2-B2 → 22   F2-B3 → 23
//   F2-C1 → 5    F2-C2 → 15   F2-C3 → 12
//
// Tránh: GPIO0/2 (nút BOOT, LED), 1/3 (UART nạp code), 6–11 (flash), 34–39 (không có pull-up trong).
// GPIO12 và 15 là chân strapping: chỉ cần KHÔNG giữ nút F2-C3 / F2-C2 lúc cấp nguồn là được
// (nhấn kéo xuống LOW — đúng mức an toàn khi boot, nên kể cả lỡ giữ cũng không hỏng).
#include <Preferences.h>

// WiFi/WiFiClientSecure include ở đây để PlatformIO LDF nhận ra thư viện framework.
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "parking_net.h"

using namespace parking;

static const int N_SLOTS = 18;
static const char *SLOT_IDS[N_SLOTS] = {"F1-A1", "F1-A2", "F1-A3", "F1-B1", "F1-B2", "F1-B3",
                                        "F1-C1", "F1-C2", "F1-C3", "F2-A1", "F2-A2", "F2-A3",
                                        "F2-B1", "F2-B2", "F2-B3", "F2-C1", "F2-C2", "F2-C3"};
static const int SLOT_PINS[N_SLOTS] = {25, 26, 27, 32, 33, 4,  13, 14, 16,
                                       17, 18, 19, 21, 22, 23, 5,  15, 12};

static const uint32_t DEBOUNCE_MS = 50;
static const uint32_t SNAPSHOT_MS = 30000;

Preferences nvs;
Link net;
const String T_STATE = topic("slots", "slots-01", "state");

bool occupied[N_SLOTS] = {false};  // khởi đầu: tất cả trống

struct Button {
  bool raw = true, stable = true;  // HIGH = nhả (pull-up)
  uint32_t changedAt = 0;
} buttons[N_SLOTS];

uint32_t lastSnapshot = 0;

// Lưu trạng thái 18 ô vào NVS để mất điện/khởi động lại không mất (giống SIM-05).
// Namespace mới "slotbtn" → lần đầu nạp bản này mọi ô bắt đầu TRỐNG, bỏ dữ liệu của firmware cũ.
void saveNvs() {
  uint32_t bits = 0;
  for (int i = 0; i < N_SLOTS; i++)
    if (occupied[i]) bits |= 1UL << i;
  nvs.putUInt("bits", bits);
}

void loadNvs() {
  uint32_t bits = nvs.getUInt("bits", 0);
  for (int i = 0; i < N_SLOTS; i++) occupied[i] = bits & (1UL << i);
}

void publishChanged(int i) {
  JsonDocument doc;
  net.envelope(doc, "slot_changed");
  doc["slot_id"] = SLOT_IDS[i];
  doc["occupied"] = occupied[i];
  doc["source"] = "BUTTON";
  net.publish(T_STATE, doc);  // offline: snapshot sau khi nối lại sẽ đồng bộ
}

void publishSnapshot() {
  JsonDocument doc;
  net.envelope(doc, "slots_snapshot");
  JsonArray arr = doc["slots"].to<JsonArray>();
  int count = 0;
  for (int i = 0; i < N_SLOTS; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["slot_id"] = SLOT_IDS[i];
    o["occupied"] = occupied[i];
    o["source"] = "BUTTON";
    count += occupied[i];
  }
  if (net.publish(T_STATE, doc, false)) Serial.printf("[pub] snapshot 18 ô (%d có xe)\n", count);
  lastSnapshot = millis();
}

void toggleSlot(int i) {
  occupied[i] = !occupied[i];
  Serial.printf("[slot] %s (GPIO%d) → %s\n", SLOT_IDS[i], SLOT_PINS[i], occupied[i] ? "CO XE" : "trong");
  saveNvs();
  publishChanged(i);
}

void readButtons() {
  uint32_t now = millis();
  for (int i = 0; i < N_SLOTS; i++) {
    bool level = digitalRead(SLOT_PINS[i]);
    Button &b = buttons[i];
    if (level != b.raw) {
      b.raw = level;
      b.changedAt = now;
    }
    if (b.raw != b.stable && now - b.changedAt >= DEBOUNCE_MS) {
      b.stable = b.raw;
      if (!b.stable) toggleSlot(i);  // mỗi lần NHẤN (HIGH → LOW) đảo trạng thái
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n=== slots-01 firmware %s (18 nút GPIO) ===\n", FIRMWARE_VERSION);
  nvs.begin("slotbtn", false);
  loadNvs();
  for (int i = 0; i < N_SLOTS; i++) pinMode(SLOT_PINS[i], INPUT_PULLUP);
  delay(10);
  // Đọc mức ban đầu để nút đang bị giữ lúc khởi động không bị tính là một lần nhấn.
  for (int i = 0; i < N_SLOTS; i++) buttons[i].raw = buttons[i].stable = digitalRead(SLOT_PINS[i]);
  int count = 0;
  for (int i = 0; i < N_SLOTS; i++) count += occupied[i];
  Serial.printf("[slot] khởi động: %d/18 ô có xe\n", count);
  net.begin(nullptr);
}

void loop() {
  net.loop();
  if (net.justConnected) publishSnapshot();  // đủ 18 ô lúc boot/nối lại
  readButtons();
  if (net.connected() && millis() - lastSnapshot >= SNAPSHOT_MS) publishSnapshot();
  delay(5);
}
