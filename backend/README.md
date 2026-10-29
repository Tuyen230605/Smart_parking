# Backend nghiệp vụ

AWS Lambda nhận sự kiện IoT Core và API web, quản lý phiên/ô, tạo QR token, gán ô bằng ghi có điều kiện, tính phí mô phỏng, phát lệnh cần và gọi Amazon SES. Dữ liệu ở DynamoDB. Xem [kiến trúc](../docs/architecture.md), [use case](../docs/use-cases.md), [API](../docs/api-contract.md).

Backend là nơi duy nhất phát lệnh servo, không coi ACK mở cần là xác nhận xe qua cổng. Email chỉ thuộc lượt hiện tại; không lập bảng liên kết biển số→email lâu dài. Mọi sự kiện/lệnh/API mutation xử lý retry an toàn bằng ID.

Python 3.12, chỉ dùng boto3 có sẵn trong runtime Lambda. Hạ tầng và cách deploy: [infra/aws](../infra/aws/README.md).

## Chạy test

```bash
cd backend
uv sync              # tạo .venv với boto3, moto, pytest, paho-mqtt
uv run pytest        # DynamoDB giả bằng moto, không cần tài khoản AWS
```

## Chạy local cho web và mock thiết bị (không cần AWS)

[`local/dev_server.py`](local/dev_server.py) chạy cùng code Lambda với DynamoDB giả trong RAM. Mọi request được coi như đã đăng nhập nhóm `ADMIN` và `KIOSK`; email chỉ in ra màn hình.

```bash
cd backend
uv run python local/dev_server.py --fake-slots          # API http://localhost:3001/v1, slots-01 giả
```

Web: đặt `VITE_API_BASE_URL=http://localhost:3001/v1` trong `web/.env.local`. Giả thiết bị bằng HTTP:

```bash
curl -X POST localhost:3001/dev/slots/F1-A2 -d '{"occupied": true}'   # ô có xe
curl -X POST localhost:3001/dev/mqtt -d @event.json                   # message MQTT v1 kèm "mqtt_topic"
curl -X POST localhost:3001/dev/jobs/expire_reservations              # chạy job ngay
```

Nối với mock thiết bị thật qua Mosquitto (lệnh cổng/OLED được phát lại lên broker):

```bash
docker run --rm -p 1883:1883 eclipse-mosquitto:2.0.21 mosquitto -c /mosquitto-no-auth.conf
uv run python local/dev_server.py --mqtt localhost:1883 --fake-slots
python ../edge/raspberry-pi-vision/mock_pi.py entry-ok                # từ thư mục có config.toml của Pi
```

Bỏ `--fake-slots` khi `mock_slots.py` của người 3 đã chạy, để hai nguồn không ghi đè nhau.

## Cấu trúc `src/parking/`

| File | Vai trò |
|---|---|
| `ingest.py` | Lambda nhận MQTT qua IoT Rule: xe vào/ra, trạng thái ô, ACK cổng/OLED, trạng thái thiết bị |
| `api.py` | Lambda HTTP API: định tuyến, `/public/*`, `/kiosk/active-claims`, `/admin/dashboard` |
| `admin.py` | Endpoint quản trị còn lại: phiên, xử lý OCR, QR, thu phí, cổng ra, thiết bị, bảng giá |
| `jobs.py` | Lambda theo lịch: hết hạn giữ ô (mỗi phút), xóa dữ liệu định danh (mỗi giờ) |
| `flows.py` | Giữ ô và khóa phí ra, dùng chung cho sự kiện thiết bị và thao tác quản trị |
| `rest.py` | Đọc event API Gateway, lỗi chuẩn, kiểm nhóm Cognito, Idempotency-Key |
| `contract.py` | Kiểm message MQTT v1 và tạo `gate_command`/`display_command` |
| `store.py` | DynamoDB: chuyển kiểu, ghi có điều kiện, transaction, phân trang |
| `state.py` | Trạng thái ô/thiết bị suy ra lúc đọc |
| `claims.py` | Token QR ký HMAC, cache khóa từ SSM |
| `layout.py`, `pricing.py`, `plates.py` | 18 ô và lộ trình, bảng giá, chuẩn hóa biển số |
| `app.py`, `config.py` | Ghép boto3/IoT/SES và đọc biến môi trường |

`local/` không đóng gói vào Lambda: `dev_server.py` (API local) và `schema.py` (bảng DynamoDB cho test và chạy local).

## Trạng thái phiên

```text
RESERVED → ENTRY_GATE_OPEN → PARKED → EXIT_REQUESTED (0 ₫) ─────────────┐
   │        (ACK cần vào)   (ô báo xe) ↘ PAYMENT_PENDING → (thu tiền) → EXIT_REQUESTED
   └───────────────────────────────────┘                                   ↓ open-exit + ACK
                                                                    EXIT_GATE_OPEN → confirm-passage → CLOSED
MANUAL_REVIEW → RESOLVED (cho vào: phiên RESERVED mới; cho ra: khóa phí phiên đang đỗ) | DISMISSED
RESERVED / ENTRY_GATE_OPEN ── 5 phút ô không báo xe ──→ EXPIRED (bỏ giữ ô nếu ô vẫn trống, bỏ khóa biển số và QR)
```

## Job theo lịch

- **`expire_reservations` mỗi phút** (UC-05, SIM-13): phiên giữ ô quá 5 phút chưa đỗ → `EXPIRED`. Ô đang báo có xe thì không giải phóng, lần chạy sau xét lại. Dashboard báo số lượt hết hạn trong 1 giờ qua.
- **`purge_identity` mỗi giờ** (UC-10, SIM-16): phiên tới `purge_due_at` (9 ngày 23 giờ) bị xóa biển số, email, QR và khóa `ActivePlates`; giữ phí, thời gian, audit. Phiên còn mở cũng bị xóa đúng hạn; dashboard cảnh báo trước 24 giờ để quản trị đóng phiên.
- Cả hai idempotent; job lỗi thì Lambda báo lỗi và alarm gửi email.

## Endpoint quản trị

Tất cả cần nhóm `ADMIN`. Thao tác thay đổi cần header `Idempotency-Key`; gửi lại cùng key trả kết quả hiện tại mà không làm lại. Mỗi thao tác thêm một mục `audit` (`action`, `at`, `actor_id`, `actor`, `reason`, `detail`) vào phiên, không chứa biển số/email.

| Endpoint | Body | Kết quả |
|---|---|---|
| `GET /admin/sessions?status=&limit=&cursor=` | | `{sessions: [...], next_cursor}`, mới nhất trước, `limit` 1–100 |
| `GET /admin/sessions/{id}` | | Chi tiết, `audit`; biển số/email là `null` khi quá hạn 10 ngày |
| `POST .../resolve-plate` | `{action: ENTRY\|EXIT\|DISMISS, plate_text, reason}` | `{review, session, commands_sent}`; `EXIT` khóa phí ở lúc xe tới cổng ra |
| `POST .../renew-claim` | `{reason?}` | Như một phần tử của `/kiosk/active-claims`; QR cũ trả 410 |
| `POST .../payment` | `{payment_status: PAID_CASH\|WAIVED, amount_vnd, note}` | Chi tiết phiên; `PAID_CASH` phải đúng `fee_vnd`, `WAIVED` bắt buộc `note` |
| `POST .../open-exit` | `{reason?}` | `202 {command_id, session}`; `503 DEVICE_OFFLINE` nếu gate-01 offline hoặc không gửi được lệnh |
| `POST .../confirm-passage` | `{reason?}` | Phiên `CLOSED`; bỏ khóa biển số và giữ ô, xóa email |
| `GET /admin/devices` | | `{devices: [...]}` gồm `online`, trạng thái hai cần, OLED, snapshot ô |
| `GET /admin/pricing`, `PUT /admin/pricing` | `{free_minutes, first_block_minutes, first_block_vnd, extra_hour_vnd, reason?}` | Bảng giá kèm `version`; phiên đang mở giữ giá lúc check-in |

## Quyết định thiết kế

- **Gán ô nguyên tử:** một `TransactWriteItems` gồm dấu sự kiện (hoặc phiên chờ xử lý), khóa biển số trong `ActivePlates`, kiểm snapshot ô còn mới, giữ ô `occupied=false`, tạo phiên và ghi `command_id`. Ô vừa bị lượt khác giữ thì thử ô kế tiếp. Lệnh MQTT chỉ phát sau khi transaction thành công; retry gặp `DUPLICATE` nên không mở cần lần hai.
- **Trạng thái suy ra lúc đọc:** ô `UNKNOWN` khi `slots-01` không gửi snapshot quá 90 giây, thiết bị `OFFLINE` khi quá 90 giây không có tin. Không cần job định kỳ cho hai việc này.
- **Thứ tự tin ô:** `slot_changed` bị bỏ nếu cũ hơn ô đó hoặc cũ hơn snapshot đã nhận (cùng `boot_id`), vì snapshot không ghi lại ô không đổi. Snapshot ghi các ô trước rồi mới đánh dấu đã nhận, nên Lambda retry sau lỗi giữa chừng vẫn ghi đủ. Ô được gán báo có xe thì phiên sang `PARKED`, kể cả ở lần retry; job hết hạn cũng sửa phiên còn kẹt.
- **Không mở cần khi không chắc:** sai làn, không đọc được biển số, confidence < 0,85, biển số đang có phiên, ô không có dữ liệu mới, hoặc sự kiện Pi cũ hơn 60 giây đều tạo phiên `MANUAL_REVIEW` và hiện `CHO NHAN VIEN` trên OLED.
- **Xe ra:** khóa `charge_end_at` và `fee_vnd` ngay khi Pi báo thẻ đỏ. Mở cần ra là thao tác quản trị (G3 chưa chốt), chỉ khi gate-01 online.
- **Idempotency:** thao tác chỉ thành công được một lần (email, xử lý OCR, thu phí, xác nhận xe qua) lưu key ngay trên phiên trong cùng lần ghi có điều kiện. Thao tác lặp lại được (`open-exit`, `renew-claim`, `PUT /admin/pricing`) ghi dấu `idem#…` vào `ProcessedMessages` cùng transaction, nhớ 24 giờ, nên key cũ gửi lại sau key mới vẫn không chạy lần hai. Không giữ bản sao response nên không lưu dữ liệu định danh ngoài phiên, không có trạng thái "đang xử lý" bị kẹt. `open-exit` gửi lệnh lỗi thì xóa dấu để bấm lại được.
- **Publish IoT:** dùng endpoint dữ liệu riêng của tài khoản (`iot:DescribeEndpoint`, lấy một lần mỗi container), không dùng endpoint chung của boto3. `tests/test_template.py` kiểm quyền IAM của từng Lambda so với thao tác code dùng, vì moto không kiểm IAM.
- **QR:** token `session_id.nonce.hạn.chữ_ký`, không lưu trong DB. Kiosk ký lại URL từ dữ liệu phiên. Khóa ở SSM SecureString, cache 5 phút; đổi khóa bằng giá trị `khóa_mới,khóa_cũ`.
- **Email:** một lần mỗi phiên bằng conditional update; SES lỗi chỉ ghi `FAILED`, không ảnh hưởng phiên. Email bị xóa khi đóng phiên; nhập email luôn đưa phiên vào lịch purge (cả khi biển số đã bị purge trước đó).
- **Dữ liệu định danh:** phiên có `identity_expires_at` (10 ngày) và `purge_due_at` (sớm hơn 1 giờ) trên index thưa `purge_due`. API quản trị ẩn biển số/email quá hạn kể cả khi purge chưa chạy. Log không chứa biển số, email, token.

## Khác hoặc bổ sung so với hợp đồng hiện tại

Cần đưa vào PR hợp đồng v1.1 để nhóm duyệt:

1. `GET /kiosk/active-claims` thêm `route_steps`, `created_at`; sắp phiên mới nhất trước.
2. Lỗi 500 trả body chuẩn với mã mới `INTERNAL_ERROR`.
3. Thêm `payment_status=PENDING`. Phiên 0 ₫ sang `EXIT_REQUESTED`, có phí sang `PAYMENT_PENDING`, thu tiền xong về `EXIT_REQUESTED`.
4. `review_reason` của `MANUAL_REVIEW`: `WRONG_LANE`, `STALE_EVENT`, `UNREADABLE_PLATE`, `LOW_CONFIDENCE`, `PLATE_ALREADY_ACTIVE`, `SLOTS_UNKNOWN`, `NO_ACTIVE_SESSION`, `SESSION_NOT_PARKED`.
5. `gate_telemetry`/`display_telemetry` phải có phần đầu chung `schema_version`, `message_type`, `event_id`, `device_id`, `occurred_at`; `boot_id`/`seq` không bắt buộc.
6. `GET /public/layout`: `updated_at` là `null` nếu ô chưa từng có dữ liệu.
7. Mọi mutation (email khách và quản trị) bắt buộc header `Idempotency-Key` (8–64 ký tự `A-Z a-z 0-9 _ -`).
8. Sự kiện Pi cũ hơn 60 giây hoặc lệch giờ quá 30 giây không mở cần.
9. Trạng thái mới `RESOLVED`, `DISMISSED` cho phiên chờ xử lý; không dùng `DETECTED` và `EXIT_CONFIRMED` (xác nhận xe qua chuyển thẳng `CLOSED`).
10. Request/response của endpoint quản trị như bảng trên, gồm phân trang `limit`/`cursor`/`next_cursor` và `resolve-plate` có thêm `DISMISS`.

## Chưa làm

- Gửi lại email (`resend`) và đánh dấu ô `OUT_OF_SERVICE` chưa có endpoint.
- Phần web của người 4: `web/src/auth.ts` (Cognito) và trang `/admin` dùng các endpoint trên.
- PR hợp đồng v1.1 cho 10 điểm khác ở trên.
- Deploy lên AWS thật và chạy SIM-01 → SIM-16 với thiết bị (người 4 tự deploy theo [infra/aws](../infra/aws/README.md)).
