#pragma once
#include <Arduino.h>

#define FW_VERSION      "1.3.0"          // <= 32 ký tự
#define SCHEMA_VERSION  1
#define SITE_ID         "site-01"
#define DEVICE_ID       "slots-01"       // cũng là MQTT client ID và tên Thing

// ---- I2C ----
#define PIN_SDA     21
#define PIN_SCL     22
#define I2C_HZ      400000
#define MCP_ADDR_0  0x20                 // A0=A1=A2=GND
#define MCP_ADDR_1  0x21                 // A0=3V3
#define TOF_ADDR    0x29
#define PIN_LED     2                    // sáng khi MQTT đã kết nối

// ---- Ô đỗ: thứ tự này khớp parking-layout.md ----
#define SLOT_COUNT 18
#define BTN_COUNT  17
#define TOF_SLOT   0                     // F1-A1 dùng ToF thật
static const char* const SLOT_IDS[SLOT_COUNT] = {
  "F1-A1","F1-A2","F1-A3","F1-B1","F1-B2","F1-B3","F1-C1","F1-C2","F1-C3",
  "F2-A1","F2-A2","F2-A3","F2-B1","F2-B2","F2-B3","F2-C1","F2-C2","F2-C3"};

// Map cố định nút -> (chip MCP, chân 0..15, chỉ số ô). Chân 0-7 = GPA0-7, 8-15 = GPB0-7.
struct BtnMap { uint8_t chip; uint8_t pin; uint8_t slot; };
static const BtnMap BTN_MAP[BTN_COUNT] = {
  {0, 0, 1},  {0, 1, 2},  {0, 2, 3},  {0, 3, 4},  {0, 4, 5},  {0, 5, 6},    // B1..B6   -> F1-A2..F1-C1
  {0, 6, 7},  {0, 7, 8},                                                    // B7,B8    -> F1-C2,F1-C3
  {0, 8, 9},  {0, 9, 10}, {0, 10, 11},{0, 11, 12},{0, 12, 13},{0, 13, 14}, // B9..B14  -> F2-A1..F2-B3
  {0, 14, 15},{0, 15, 16},                                                  // B15,B16  -> F2-C1,F2-C2
  {1, 0, 17}                                                                // B17      -> F2-C3 (MCP #2)
};

// ---- Thời gian (ms) ----
#define SCAN_MS               5
#define DEBOUNCE_MS           40
#define NVS_SAVE_DELAY_MS     2000
#define SNAPSHOT_PERIOD_MS    30000
#define STATUS_PERIOD_MS      30000

// ---- ToF VL53L0X ----
#define TOF_ON_MM             100        // <= : có xe
#define TOF_OFF_MM            140        // >= : trống (giữa hai ngưỡng: giữ nguyên)
#define TOF_DEBOUNCE_MS       300
#define TOF_PERIOD_MS         50
#define TOF_TIMEOUT_MS        2000       // không có số đo trong 2 s => lỗi
#define TOF_RETRY_MS          10000
#define TOF_SAMPLES           5          // trung vị 5 mẫu
// ToF lỗi: F1-A1 báo "có xe" để backend không xếp xe vào (cần người 4 xác nhận)
#define TOF_FAULT_OCCUPIED    true

// ---- Topic MQTT v1 ----
#define TOPIC_STATE   "parking/v1/" SITE_ID "/slots/" DEVICE_ID "/state"
#define TOPIC_STATUS  "parking/v1/" SITE_ID "/devices/" DEVICE_ID "/status"