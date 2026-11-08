// Mẫu. File thật include/secrets.h do infra/aws/provision-devices.sh sinh ra (có cert, KHÔNG commit).
#pragma once
#define WIFI_SSID "TEN_WIFI"
#define WIFI_PASS "MAT_KHAU_WIFI"
#define AWS_IOT_ENDPOINT "xxxxxxxxxxxxxx-ats.iot.ap-southeast-1.amazonaws.com"
#define DEVICE_ID "gate-01"   // hoặc slots-01
static const char AWS_ROOT_CA[] PROGMEM = R"PEM(
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
)PEM";
static const char DEVICE_CERT[] PROGMEM = R"PEM(...)PEM";
static const char DEVICE_KEY[] PROGMEM = R"PEM(...)PEM";
