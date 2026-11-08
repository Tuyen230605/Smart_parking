// ESP32 gate-01 — 2 servo cần chắn (ENTRY/EXIT) + OLED SSD1306 128x64.
// Hợp đồng: docs/mqtt-contract.md §5–§7. Hai handler riêng cho gate_command và display_command.
//
// Đấu nối mặc định (đổi ở khối PIN bên dưới):
//   Servo cần VÀO  tín hiệu → GPIO18     Servo cần RA tín hiệu → GPIO19
//   Servo VCC → nguồn 5V RIÊNG (≥2A), GND servo nối chung GND ESP32
//   OLED SDA → GPIO21, SCL → GPIO22, VCC 3V3, GND
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
static const int PIN_SERVO_ENTRY = 18;
static const int PIN_SERVO_EXIT = 19;
static const int ANGLE_CLOSED = 0;   // chỉnh theo cơ khí sa bàn
static const int ANGLE_OPEN = 90;
static const uint32_t SERVO_MOVE_MS = 700;   // thời gian servo quay hết hành trình
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

struct Gate {
  Gate(const char *n, int p) : name(n), pin(p) {}
  const char *name;
  int pin;
  Servo servo;
  GateState state = CLOSED;
  uint32_t since = 0;
  String commandId;
};
Gate gates[2] = {{"ENTRY", PIN_SERVO_ENTRY}, {"EXIT", PIN_SERVO_EXIT}};

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
  if (s == OPENING) g.servo.write(ANGLE_OPEN);
  if (s == CLOSING) g.servo.write(ANGLE_CLOSED);
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
  for (auto &g : gates) {
    g.servo.setPeriodHertz(50);
    g.servo.attach(g.pin, 500, 2400);
    g.servo.write(ANGLE_CLOSED);  // khởi động luôn đóng cần
  }
  Wire.begin(21, 22);
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
