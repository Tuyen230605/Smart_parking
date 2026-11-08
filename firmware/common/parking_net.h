// Phần dùng chung cho gate-01 và slots-01: Wi-Fi, NTP, MQTT/TLS tới AWS IoT Core,
// envelope message theo docs/mqtt-contract.md (event_id, boot_id, seq, occurred_at).
// Header-only để mỗi project PlatformIO chỉ cần -I../common.
#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include <algorithm>

#include "secrets.h"

#ifndef AWS_IOT_PORT
#define AWS_IOT_PORT 8883  // đặt 443 trong secrets.h nếu mạng chặn 8883
#endif

#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "1.0.0"
#endif

namespace parking {

static const char *SITE = "site-01";
static const uint32_t STATUS_INTERVAL_MS = 30000;

inline String topic(const char *kind, const char *device, const char *leaf) {
  return String("parking/v1/") + SITE + "/" + kind + "/" + device + "/" + leaf;
}

// UUID v4 từ bộ sinh số ngẫu nhiên phần cứng.
inline String uuid4() {
  uint8_t b[16];
  for (int i = 0; i < 16; i += 4) {
    uint32_t r = esp_random();
    memcpy(b + i, &r, 4);
  }
  b[6] = (b[6] & 0x0F) | 0x40;
  b[8] = (b[8] & 0x3F) | 0x80;
  char out[37];
  snprintf(out, sizeof(out), "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x", b[0], b[1],
           b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
  return String(out);
}

inline bool timeValid() { return time(nullptr) > 1700000000; }  // sau 11/2023 = NTP đã đồng bộ

inline String isoNow() {
  time_t t = time(nullptr);
  struct tm tm;
  gmtime_r(&t, &tm);
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
  return String(buf);
}

// "2026-10-05T09:00:07.123Z" → epoch giây UTC; 0 nếu sai định dạng.
inline int64_t parseIso(const char *s) {
  if (!s) return 0;
  int y, mo, d, h, mi, sec;
  if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &sec) != 6) return 0;
  // days_from_civil (Howard Hinnant), không phụ thuộc múi giờ của newlib.
  y -= mo <= 2;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = (unsigned)(y - era * 400);
  const unsigned doy = (153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  const int64_t days = (int64_t)era * 146097 + (int64_t)doe - 719468;
  return days * 86400 + h * 3600 + mi * 60 + sec;
}

class Link {
 public:
  explicit Link(size_t bufferSize = 4096) : mqtt_(bufferSize) {}

  String bootId;
  uint32_t seq = 0;

  void begin(void (*onMessage)(String &, String &)) {
    bootId = uuid4();
    statusTopic_ = topic("devices", DEVICE_ID, "status");
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
    net_.setCACert(AWS_ROOT_CA);
    net_.setCertificate(DEVICE_CERT);
    net_.setPrivateKey(DEVICE_KEY);
#if AWS_IOT_PORT == 443
    static const char *alpn[] = {"x-amzn-mqtt-ca", nullptr};  // MQTT qua 443 cần ALPN
    net_.setAlpnProtocols(alpn);
#endif
    mqtt_.begin(AWS_IOT_ENDPOINT, AWS_IOT_PORT, net_);
    mqtt_.setKeepAlive(30);
    mqtt_.setCleanSession(true);
    mqtt_.setTimeout(5000);
    if (onMessage) mqtt_.onMessage(onMessage);
  }

  // Gọi trong loop(). Trả true khi đang nối MQTT; `justConnected` bật đúng một vòng sau khi nối lại.
  bool loop() {
    justConnected = false;
    if (WiFi.status() != WL_CONNECTED) {
      if (millis() - lastLog_ > 5000) {
        Serial.printf("[net] chờ Wi-Fi %s…\n", WIFI_SSID);
        lastLog_ = millis();
      }
      return false;
    }
    if (!timeValid()) {
      if (millis() - lastLog_ > 3000) {
        Serial.println("[net] chờ đồng bộ NTP…");
        lastLog_ = millis();
      }
      return false;
    }
    if (!mqtt_.connected()) {
      if (millis() - lastTry_ < retryMs_) return false;
      lastTry_ = millis();
      // Last Will: AWS IoT phát OFFLINE nếu mất kết nối đột ngột.
      JsonDocument will;
      envelope(will, "device_status");
      will["state"] = "OFFLINE";
      will["firmware_version"] = FIRMWARE_VERSION;
      serializeJson(will, willBuf_, sizeof(willBuf_));
      mqtt_.setWill(statusTopic_.c_str(), willBuf_, false, 1);
      Serial.printf("[mqtt] kết nối %s với client id %s…\n", AWS_IOT_ENDPOINT, DEVICE_ID);
      if (!mqtt_.connect(DEVICE_ID)) {
        Serial.printf("[mqtt] lỗi %d / rc %d — thử lại sau %lus\n", mqtt_.lastError(), mqtt_.returnCode(),
                      retryMs_ / 1000);
        retryMs_ = std::min<uint32_t>(retryMs_ * 2, 30000);
        return false;
      }
      retryMs_ = 2000;
      Serial.println("[mqtt] ✓ đã kết nối AWS IoT");
      for (auto &t : subs_) mqtt_.subscribe(t.c_str(), 1);
      justConnected = true;
      status();
      lastStatus_ = millis();
    }
    mqtt_.loop();
    if (millis() - lastStatus_ >= STATUS_INTERVAL_MS) {
      lastStatus_ = millis();
      status();
    }
    return mqtt_.connected();
  }

  void subscribe(const String &t) { subs_[nSubs_++] = t; }

  void envelope(JsonDocument &doc, const char *messageType) {
    doc["schema_version"] = 1;
    doc["message_type"] = messageType;
    doc["event_id"] = uuid4();
    doc["device_id"] = DEVICE_ID;
    doc["boot_id"] = bootId;
    doc["seq"] = ++seq;
    doc["occurred_at"] = isoNow();
  }

  bool publish(const String &t, JsonDocument &doc, bool log = true) {
    static char buf[3072];
    size_t n = serializeJson(doc, buf, sizeof(buf));
    if (log) Serial.printf("[pub] %s %s\n", t.c_str() + 19, buf);
    return mqtt_.connected() && mqtt_.publish(t.c_str(), buf, n, false, 1);
  }

  void status(const char *state = nullptr) {
    JsonDocument doc;
    envelope(doc, "device_status");
    doc["state"] = state ? state : (degraded ? "DEGRADED" : "ONLINE");
    doc["firmware_version"] = FIRMWARE_VERSION;
    publish(statusTopic_, doc, false);
  }

  bool connected() { return mqtt_.connected(); }

  bool justConnected = false;
  bool degraded = false;  // phần cứng phụ (OLED/ToF/MCP) lỗi nhưng board vẫn chạy

 private:
  WiFiClientSecure net_;
  MQTTClient mqtt_;
  String statusTopic_;
  String subs_[4];
  int nSubs_ = 0;
  char willBuf_[320];
  uint32_t lastTry_ = 0, retryMs_ = 2000, lastStatus_ = 0, lastLog_ = 0;
};

}  // namespace parking
