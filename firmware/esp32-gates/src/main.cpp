// ESP32-S3 gate-01 — MỘT servo SG90 làm cần chắn dùng chung cho làn VÀO và RA + OLED SSD1306 (tuỳ chọn).
// Hợp đồng: docs/mqtt-contract.md §5–§7. Hai handler riêng cho gate_command và display_command.
//
// Cần chắn 1 servo, 3 vị trí:
//   đóng (CLOSED)        → cần chỉ thẳng   (ANGLE_CENTER = 90°)
//   mở cho xe VÀO (ENTRY) → quay TRÁI 90°   (ANGLE_ENTRY_OPEN)
//   mở cho xe RA  (EXIT)  → quay PHẢI 90°   (ANGLE_EXIT_OPEN)
// Backend vẫn gửi lệnh ENTRY/EXIT như hai cần; firmware ánh xạ cả hai vào một servo.
// Lệnh mở làn này khi làn kia đang mở → làn kia báo CLOSED, cần quay sang hướng mới.
//
// Đấu nối (đổi ở khối PIN bên dưới):
//   Servo dây cam/vàng (tín hiệu) → GPIO18
//   Servo dây đỏ (VCC) → 5V (nguồn riêng ≥1A tốt nhất; 1 SG90 không tải có thể lấy chân 5V/VBUS của board)
//   Servo dây nâu (GND) → GND ESP32 (BẮT BUỘC chung mass)
//   OLED (nếu có) ESP32-S3: SDA → GPIO8, SCL → GPIO9 · ESP32 thường: SDA → GPIO21, SCL → GPIO22
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include <Wire.h>

// WiFi/WiFiClientSecure include ở đây để PlatformIO LDF nhận ra thư viện framework.
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "parking_net.h"

using namespace parking;

// ── cấu hình phần cứng ─────────────────────────────────────────────────────
static const int PIN_SERVO = 18;
#if CONFIG_IDF_TARGET_ESP32S3
static const int PIN_SDA = 8, PIN_SCL = 9;
#else
static const int PIN_SDA = 21, PIN_SCL = 22;
#endif
// Góc servo. Nếu lắp xong thấy quay ngược chiều (VÀO lại quay phải) thì đổi chỗ 180 ↔ 0.
// Nếu cần không thẳng khi đóng, chỉnh ANGLE_CENTER (ví dụ 85 hoặc 95) cho khớp cơ khí.
static const int ANGLE_CENTER = 90;
static const int ANGLE_ENTRY_OPEN = 180;  // trái 90°
static const int ANGLE_EXIT_OPEN = 0;     // phải 90°
static const uint32_t SERVO_MOVE_MS = 700;   // thời gian servo quay 90° (quay 180° từ trái sang phải cũng kịp)
static const uint32_t GATE_HOLD_MS = 5000;   // giữ mở rồi tự đóng
static const uint32_t DISPLAY_HOLD_MS = 3000; // màn ưu tiên cao được giữ tối thiểu
static const uint32_t IDLE_AFTER_MS = 20000;  // không có lệnh mới → về màn chờ

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
bool oledOk = false;
Link net;

const String T_GATE_CMD = topic("gates", "gate-01", "commands");
const String T_DISP_CMD = topic("displays", "gate-01", "commands");
const String T_GATE_TEL = topic("gates", "gate-01", "telemetry");
const String T_DISP_TEL = topic("displays", "gate-01", "telemetry");

// ── chống lệnh trùng: nhớ 20 command_id gần nhất ───────────────────────────
String seenIds[20];
int seenPos = 0;
bool seen(const String &id) {
  for (auto &s : seenIds)
    if (s == id) return true;
  return false;
}
void remember(const String &id) {
  seenIds[seenPos] = id;
  seenPos = (seenPos + 1) % 20;
}

// ── hàng đợi message: callback MQTT chỉ chép vào đây, xử lý trong loop() ───
struct Inbox {
  String topic, payload;
  bool used = false;
};
Inbox inbox[6];
void onMessage(String &t, String &p) {
  for (auto &m : inbox)
    if (!m.used) {
      m.topic = t;
      m.payload = p;
      m.used = true;
      return;
    }
  Serial.println("[mqtt] inbox đầy, bỏ message");
}

// ── cần chắn: máy trạng thái không chặn ────────────────────────────────────
enum GateState { CLOSED, OPENING, OPEN_, CLOSING, ERROR_ };
const char *STATE_NAMES[] = {"CLOSED", "OPENING", "OPEN", "CLOSING", "ERROR"};

// Hai "cần logic" ENTRY/EXIT (để báo trạng thái đúng hợp đồng) dùng chung một servo vật lý.
struct Gate {
  Gate(const char *n, int a) : name(n), openAngle(a) {}
  const char *name;
  int openAngle;
  GateState state = CLOSED;
  uint32_t since = 0;
  String commandId;
};
Gate gates[2] = {{"ENTRY", ANGLE_ENTRY_OPEN}, {"EXIT", ANGLE_EXIT_OPEN}};
Servo arm;
int armAngle = -1;

bool isOpen(const Gate &g) { return g.state == OPENING || g.state == OPEN_; }

// Đặt servo theo trạng thái hai cần logic: làn nào đang mở thì quay về hướng đó, còn lại chỉ thẳng.
void updateArm() {
  int target = ANGLE_CENTER;
  for (auto &g : gates)
    if (isOpen(g)) target = g.openAngle;
  if (target != armAngle) {
    arm.write(target);
    armAngle = target;
    Serial.printf("[servo] → %d°\n", target);
  }
}

void telemetry(const char *gate, const char *state, const String &commandId, const char *errorCode = nullptr) {
  JsonDocument doc;
  net.envelope(doc, "gate_telemetry");
  doc["command_id"] = commandId.length() ? commandId.c_str() : nullptr;
  doc["gate"] = gate;
  doc["state"] = state;
  if (errorCode)
    doc["error_code"] = errorCode;
  else
    doc["error_code"] = nullptr;
  net.publish(T_GATE_TEL, doc);
}

void setGate(Gate &g, GateState s) {
  g.state = s;
  g.since = millis();
  updateArm();
  Serial.printf("[gate] %s → %s\n", g.name, STATE_NAMES[s]);
  telemetry(g.name, STATE_NAMES[s], g.commandId);
}

void tickGates() {
  for (auto &g : gates) {
    uint32_t dt = millis() - g.since;
    if (g.state == OPENING && dt >= SERVO_MOVE_MS) setGate(g, OPEN_);
    else if (g.state == OPEN_ && dt >= GATE_HOLD_MS) setGate(g, CLOSING);
    else if (g.state == CLOSING && dt >= SERVO_MOVE_MS) setGate(g, CLOSED);
  }
}

// Kiểm tra chung cho cả hai loại lệnh. Trả mã lỗi hoặc nullptr nếu hợp lệ.
const char *validate(JsonDocument &doc, const char *messageType) {
  if ((doc["schema_version"] | 0) != 1 || strcmp(doc["message_type"] | "", messageType) != 0)
    return "SCHEMA_UNSUPPORTED";
  if (strcmp(doc["target_device_id"] | "", DEVICE_ID) != 0) return "WRONG_TARGET";
  String id = doc["command_id"] | "";
  if (!id.length()) return "SCHEMA_UNSUPPORTED";
  if (seen(id)) return "DUPLICATE_COMMAND";
  int64_t expires = parseIso(doc["expires_at"] | "");
  if (!expires || (int64_t)time(nullptr) > expires) return "COMMAND_EXPIRED";
  return nullptr;
}

void handleGate(JsonDocument &doc) {
  String id = doc["command_id"] | "";
  const char *gateName = doc["gate"] | "";
  const char *action = doc["action"] | "";
  const char *err = validate(doc, "gate_command");
  Gate *g = nullptr;
  for (auto &x : gates)
    if (strcmp(x.name, gateName) == 0) g = &x;
  if (!err && (!g || (strcmp(action, "OPEN") != 0 && strcmp(action, "CLOSE") != 0))) err = "SCHEMA_UNSUPPORTED";
  if (err) {
    Serial.printf("[gate] bỏ lệnh %s: %s\n", id.c_str(), err);
    telemetry(g ? g->name : nullptr, "ERROR", id, err);
    return;
  }
  remember(id);
  g->commandId = id;
  if (strcmp(action, "OPEN") == 0) {
    // Chỉ một cần vật lý: làn kia đang mở thì nhường (báo CLOSED) trước khi quay sang hướng mới.
    for (auto &other : gates)
      if (&other != g && other.state != CLOSED) setGate(other, CLOSED);
    if (g->state == OPEN_) g->since = millis();  // đang mở: gia hạn thời gian giữ
    else setGate(*g, OPENING);
  } else if (g->state != CLOSED) {
    setGate(*g, CLOSING);
  } else {
    telemetry(g->name, "CLOSED", id);
  }
}

// ── OLED ───────────────────────────────────────────────────────────────────
int priority(const String &screen) {
  if (screen == "ERROR" || screen == "LOT_FULL") return 3;
  if (screen == "EXIT_FEE") return 2;
  if (screen == "ENTRY_ROUTE") return 1;
  return 0;
}

struct Screen {
  String name = "IDLE";
  String lines[3];
  String commandId;
  uint32_t at = 0;
} current, pending;
bool hasPending = false;
bool showingOffline = false;

void draw(const String &l0, const String &l1, const String &l2) {
  if (!oledOk) return;
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  // Dòng đầu chữ lớn nếu ≤10 ký tự (ví dụ "VAO: F1-A1"), còn lại chữ nhỏ 20 ký tự.
  oled.setTextSize(l0.length() <= 10 ? 2 : 1);
  oled.setCursor(0, 0);
  oled.println(l0);
  oled.setTextSize(1);
  oled.setCursor(0, 28);
  oled.println(l1);
  oled.setCursor(0, 44);
  oled.println(l2);
  oled.display();
}

void show(Screen &s) {
  current = s;
  current.at = millis();
  draw(s.lines[0], s.lines[1], s.lines[2]);
  Serial.printf("[oled] %s | %s | %s | %s\n", s.name.c_str(), s.lines[0].c_str(), s.lines[1].c_str(),
                s.lines[2].c_str());
  if (s.commandId.length()) {
    JsonDocument doc;
    net.envelope(doc, "display_telemetry");
    doc["command_id"] = s.commandId;
    doc["state"] = "SHOWN";
    doc["screen"] = s.name;
    net.publish(T_DISP_TEL, doc, false);
  }
}

void handleDisplay(JsonDocument &doc) {
  String id = doc["command_id"] | "";
  const char *err = validate(doc, "display_command");
  if (err) {
    Serial.printf("[oled] bỏ lệnh %s: %s\n", id.c_str(), err);
    JsonDocument ack;
    net.envelope(ack, "display_telemetry");
    ack["command_id"] = id;
    ack["state"] = "ERROR";
    ack["error_code"] = err;
    net.publish(T_DISP_TEL, ack);
    return;
  }
  remember(id);
  Screen s;
  s.name = doc["screen"] | "IDLE";
  s.commandId = id;
  JsonArray lines = doc["lines"].as<JsonArray>();
  for (int i = 0; i < 3; i++) s.lines[i] = i < (int)lines.size() ? String(lines[i] | "").substring(0, 20) : "";
  bool held = millis() - current.at < DISPLAY_HOLD_MS;
  if (held && priority(s.name) < priority(current.name)) {
    pending = s;  // ERROR > EXIT_FEE > ENTRY_ROUTE: chờ màn hiện tại hết thời gian giữ
    hasPending = true;
  } else {
    show(s);
  }
}

void tickDisplay(bool online) {
  if (!online) {
    if (!showingOffline) draw("MAT KET NOI", "Khong nhan lenh moi", "Nhan vien kiem tra");
    showingOffline = true;
    return;
  }
  if (showingOffline) {
    showingOffline = false;
    draw(current.lines[0], current.lines[1], current.lines[2]);
  }
  if (hasPending && millis() - current.at >= DISPLAY_HOLD_MS) {
    hasPending = false;
    show(pending);
  }
  if (current.name != "IDLE" && millis() - current.at >= IDLE_AFTER_MS) {
    Screen idle;
    idle.lines[0] = "SAN SANG";
    idle.lines[1] = "Smart Parking";
    idle.lines[2] = "Quet the o lan vao";
    show(idle);
  }
}

// ── setup / loop ───────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n=== gate-01 firmware %s ===\n", FIRMWARE_VERSION);
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  arm.setPeriodHertz(50);
  int ch = arm.attach(PIN_SERVO, 500, 2400);  // SG90: 500 µs = 0°, 2400 µs = 180°
  Serial.printf("[servo] attach GPIO%d → kênh %d, attached=%d\n", PIN_SERVO, ch, arm.attached());
  // Tự kiểm tra khi khởi động: quay qua lại để nhìn là biết servo có nhận tín hiệu/nguồn hay không.
  for (int a : {90, 150, 30, 90}) {
    arm.write(a);
    Serial.printf("[servo] tự kiểm tra → %d°\n", a);
    delay(600);
  }
  updateArm();                       // khởi động luôn đóng cần (chỉ thẳng)
  Wire.begin(PIN_SDA, PIN_SCL);
  oledOk = oled.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (!oledOk) {
    Serial.println("[oled] không tìm thấy SSD1306 ở 0x3C (thử 0x3D?) — chạy tiếp không màn hình");
    net.degraded = true;
  }
  current.lines[0] = "KHOI DONG";
  current.lines[1] = "Dang noi Wi-Fi/AWS";
  draw(current.lines[0], current.lines[1], "");
  net.subscribe(T_GATE_CMD);
  net.subscribe(T_DISP_CMD);
  net.begin(onMessage);
}

void loop() {
  bool online = net.loop();
  if (net.justConnected) {
    // Báo trạng thái thật của hai cần sau khi nối lại; không chạy lại lệnh cũ (đã hết hạn).
    for (auto &g : gates) telemetry(g.name, STATE_NAMES[g.state], "");
    current.at = 0;
    current.name = "BOOT";
  }
  for (auto &m : inbox) {
    if (!m.used) continue;
    JsonDocument doc;
    if (deserializeJson(doc, m.payload)) {
      Serial.println("[mqtt] JSON lỗi");
    } else if (m.topic == T_GATE_CMD) {
      handleGate(doc);
    } else if (m.topic == T_DISP_CMD) {
      handleDisplay(doc);
    }
    m.used = false;
  }
  tickGates();
  tickDisplay(online);
  delay(5);
}
