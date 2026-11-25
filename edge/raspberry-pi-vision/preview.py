"""Trang xem camera trong LAN: MJPEG có vẽ ROI, danh sách xe trong bãi, nút thử xe vào/ra."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2

PAGE = """<!doctype html><meta charset="utf-8"><title>pi-01 preview</title>
<style>body{font-family:sans-serif;margin:16px;background:#111;color:#eee}img{max-width:100%;cursor:crosshair}
button{font-size:15px;margin:4px 6px 4px 0;padding:6px 12px;cursor:pointer}#cars{font-size:18px;color:#ff6}</style>
<h3>pi-01 camera</h3>
<p>Đưa tay vào khung <b>ENTRY</b> = xe vào, khung <b>EXIT</b> = xe ra. Click vào ảnh để xem tọa độ ROI (0–1).
<a href="/snapshot.jpg" style="color:#8cf">Ảnh gốc</a></p>
<p>Xe trong bãi: <span id="cars">…</span><br>Chờ cho vào: <span id="pin">–</span> · Chờ cho ra: <span id="pout">–</span>
<br><small>Danh sách lấy từ trang Phiên đỗ trên web; chỉ đổi sau khi quản trị bấm Cho vào / Cho ra.</small></p>
<p><button onclick="act('/trigger?lane=ENTRY')">Thử xe VÀO</button><button onclick="act('/trigger?lane=EXIT')">Thử xe RA</button>
<button onclick="act('/background')">Chụp lại nền</button>
</p>
<img id="v" src="/stream"><pre id="o"></pre>
<script>
const fmt = a => (a && a.length) ? a.join(", ") : "–";
const show = d => { cars.textContent = (d.in_lot && d.in_lot.length) ? d.in_lot.join(", ") : "trống"; pin.textContent = fmt(d.pending_entry); pout.textContent = fmt(d.pending_exit); if (d.message) o.textContent = d.message + "\\n" + o.textContent; };
const act = async p => show(await fetch(p, {method: "POST"}).then(r => r.json()));
const poll = async () => { try { show(await fetch("/cars").then(r => r.json())); } catch (e) {} };
poll(); setInterval(poll, 2000);
v.onclick = async e => {
  const x = (e.offsetX / v.clientWidth).toFixed(3), y = (e.offsetY / v.clientHeight).toFixed(3);
  const r = await fetch(`/hsv?x=${x}&y=${y}`).then(r => r.json());
  o.textContent = `x=${x} y=${y}  HSV=${r.hsv}\\n` + o.textContent;
};
</script>"""


class PreviewServer:
    def __init__(self, port, actions=None):
        """actions: {"/đường-dẫn": hàm(query) → dict}; GET /cars và POST các nút trên trang gọi vào đây."""
        self.actions = actions or {}
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
                elif url.path == "/cars" and "/cars" in preview.actions:
                    self._action(url)
                else:
                    self.send_error(404)

            def do_POST(self):
                url = urlparse(self.path)
                if url.path in preview.actions:
                    self._action(url)
                else:
                    self.send_error(404)

            def _action(self, url):
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                body = preview.actions[url.path](q)
                self._send(json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")

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
