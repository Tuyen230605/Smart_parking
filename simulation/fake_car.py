"""Giả làm camera của Pi: báo có một xe ở làn vào hoặc làn ra (dùng khi chưa có Pi).

    python simulation/fake_car.py vao 51A-12345   # xe ở làn vào -> phiên "Chờ cho vào" trên /admin/sessions
    python simulation/fake_car.py ra  51A-12345   # xe ở làn ra  -> phiên "Chờ cho ra", hiện số tiền

Cần mở cổng thì vẫn phải bấm Cho vào / Cho ra trên trang quản trị.
"""
import argparse
import logging
import sys
import time

from devices import Device, setup_logging, topic


def main():
    p = argparse.ArgumentParser()
    p.add_argument("lane", choices=["vao", "ra"])
    p.add_argument("plate", help="biển số, ví dụ 51A-12345")
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--wrong-card", action="store_true", help="dùng sai màu thẻ (thử MANUAL_REVIEW)")
    args = p.parse_args()
    setup_logging()
    logging.getLogger("mock").setLevel(logging.WARNING)

    entry = args.lane == "vao"
    color = ("GREEN" if entry else "RED") if not args.wrong_card else ("RED" if entry else "GREEN")
    pi = Device("pi-01").start()
    if not pi.connected.wait(45):
        sys.exit("✗ pi-01 chưa kết nối được AWS IoT — kiểm tra mạng, thử IOT_PORT=443")
    pi.publish(topic("vision", "pi-01", "events"), pi.envelope("vehicle_detected") | {
        "lane_id": "ENTRY" if entry else "EXIT", "card_color": color,
        "plate_text": args.plate, "plate_confidence": args.confidence}, quiet=True)
    time.sleep(2)  # chờ QoS1 gửi xong
    pi.stop()
    print(f"✓ Đã gửi: xe {args.plate} quẹt thẻ {'XANH' if color == 'GREEN' else 'ĐỎ'} ở làn {'VÀO' if entry else 'RA'}")
    print("  Xem: /kiosk (QR), /admin → Phiên đỗ, cửa sổ mock_gate (cần + OLED)")


if __name__ == "__main__":
    main()
