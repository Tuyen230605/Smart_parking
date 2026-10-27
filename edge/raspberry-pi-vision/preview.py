"""Trang xem camera trong LAN: MJPEG có vẽ ROI, click để lấy tọa độ tỉ lệ và HSV khi hiệu chỉnh."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

PAGE = """<!doctype html><meta charset="utf-8"><title>pi-01 preview</title>
<style>body{font-family:sans-serif;margin:16px;background:#111;color:#eee}img{max-width:100%;cursor:crosshair}</style>
<h3>pi-01 camera</h3><p>Click vào ảnh để xem tọa độ ROI (0–1) và HSV. <a href="/snapshot.jpg" style="color:#8cf">Ảnh gốc</a></p>
<img id="v" src="/stream"><pre id="o"></pre>
<script>
v.onclick = async e => {
  const x = (e.offsetX / v.clientWidth).toFixed(3), y = (e.offsetY / v.clientHeight).toFixed(3);
  const r = await fetch(`/hsv?x=${x}&y=${y}`).then(r => r.json());
  o.textContent = `x=${x} y=${y}  HSV=${r.hsv}  (vùng 9x9 quanh điểm)\\n` + o.textContent;
};
</script>"""


class PreviewServer:
    def __init__(self, port):
        self.lock = threading.Condition()
        self.jpeg = None
        self.raw = None
        server = ThreadingHTTPServer(("0.0.0.0", port), self._handler())
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def update(self, raw, annotated, width):
        scale = width / annotated.shape[1]
        small = cv2.resize(annotated, None, fx=scale, fy=scale)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with self.lock:
            self.raw = raw
            self.jpeg = buf.tobytes() if ok else self.jpeg
            self.lock.notify_all()

    def _handler(self):
        preview = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, body, ctype):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    self._send(PAGE.encode(), "text/html; charset=utf-8")
                elif url.path == "/stream":
                    self._stream()
                elif url.path == "/snapshot.jpg":
                    with preview.lock:
                        raw = preview.raw
                    if raw is None:
                        return self.send_error(503)
                    self._send(cv2.imencode(".jpg", raw)[1].tobytes(), "image/jpeg")
                elif url.path == "/hsv":
                    self._hsv(parse_qs(url.query))
                else:
                    self.send_error(404)

            def _hsv(self, q):
                with preview.lock:
                    raw = preview.raw
                if raw is None:
                    return self.send_error(503)
                h, w = raw.shape[:2]
                x = min(max(int(float(q["x"][0]) * w), 4), w - 5)
                y = min(max(int(float(q["y"][0]) * h), 4), h - 5)
                patch = cv2.cvtColor(raw[y - 4:y + 5, x - 4:x + 5], cv2.COLOR_BGR2HSV)
                hsv = [int(v) for v in patch.reshape(-1, 3).mean(axis=0)]
                self._send(json.dumps({"hsv": hsv}).encode(), "application/json")

            def _stream(self):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        with preview.lock:
                            preview.lock.wait(timeout=2)
                            jpeg = preview.jpeg
                        if jpeg:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler
