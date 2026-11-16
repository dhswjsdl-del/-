"""영상 피드백 페이지 서버.  실행:  python3 server.py   (윈도우: python server.py)

- 이 폴더 바로 아래의 하위 폴더 하나 = 작품 하나, 그 안의 mp4 = 판.
- 같은 와이파이의 폰에서도 열 수 있도록 모든 네트워크 주소에서 받는다.
- 기본 번호(8765)를 다른 프로그램이 쓰고 있으면 다음 빈 번호로 연다.
  번호를 정하려면:  python3 server.py 9000
"""
import base64
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import feedback_store as store

DEFAULT_PORT = 8765
PAGE = os.path.join(store.ROOT, "page.html")


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # 실제로 보내지는 않음
            return s.getsockname()[0]
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoFeedback/1.0"

    def log_message(self, fmt, *args):
        pass  # 조용히

    # ---------- 응답 도우미 ----------
    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, msg, code=400):
        self.send_json({"오류": msg}, code)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 50 * 1024 * 1024:
            raise ValueError("너무 큰 요청")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def send_file(self, path, ctype):
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        partial = False
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a == "":
                    start = max(0, size - int(b))
                else:
                    start = int(a)
                    if b:
                        end = min(int(b), size - 1)
                partial = True
            except ValueError:
                pass
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-cache")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- GET ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        if not parts:
            return self.send_file(PAGE, "text/html; charset=utf-8")
        if parts == ["api", "works"]:
            works = store.list_works()
            for w in works:
                notes = store.read_notes(w["name"])
                w["unsent"] = sum(1 for n in notes if not n["sent"])
                w["open"] = sum(1 for n in notes if n["sent"] and not n["done"])
            return self.send_json({"works": works})
        if parts == ["api", "notes"]:
            work = parse_qs(url.query).get("work", [""])[0]
            if not store.work_dir(work):
                return self.fail("없는 작품입니다", 404)
            return self.send_json({"notes": store.read_notes(work)})
        # /media/<작품>/<파일>  또는  /media/<작품>/feedback_images/<파일>
        if parts[0] == "media" and len(parts) in (3, 4):
            wd = store.work_dir(parts[1])
            rest = parts[2:]
            if wd and all(p not in ("", ".", "..") and "/" not in p and "\\" not in p for p in rest):
                if len(rest) == 1 and rest[0].lower().endswith(".mp4"):
                    fp = os.path.join(wd, rest[0])
                    if os.path.isfile(fp):
                        return self.send_file(fp, "video/mp4")
                if len(rest) == 2 and rest[0] == store.IMAGE_DIR and rest[1].lower().endswith(".jpg"):
                    fp = os.path.join(wd, *rest)
                    if os.path.isfile(fp):
                        return self.send_file(fp, "image/jpeg")
        self.fail("찾을 수 없습니다", 404)

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            return self.fail("요청을 읽을 수 없습니다")

        if path == "/api/notes":
            work = data.get("work", "")
            if not store.work_dir(work):
                return self.fail("없는 작품입니다", 404)
            text = str(data.get("text", "")).strip()
            if not text:
                return self.fail("내용이 비어 있습니다")
            pos = data.get("pos")
            if pos is not None:
                pos = {"x": round(float(pos["x"]), 4), "y": round(float(pos["y"]), 4)}
            img = None
            if pos is not None and data.get("image"):
                b64 = data["image"].split(",", 1)[-1]
                img = base64.b64decode(b64)
            nid = store.add_note(work, str(data.get("version", "")), data.get("time", 0), pos, text, img)
            return self.send_json({"id": nid})

        if path == "/api/send":
            sent = []
            for w in store.list_works():
                ids = [n["id"] for n in store.read_notes(w["name"]) if not n["sent"]]
                if ids:
                    ev = store.mark(w["name"], "sent", ids)
                    sent.append({"work": w["name"], "ids": ids, "at": ev["at"]})
            return self.send_json({"sent": sent})

        if path == "/api/delete":
            work = data.get("work", "")
            if not store.work_dir(work):
                return self.fail("없는 작품입니다", 404)
            nid = int(data.get("id", 0))
            note = next((n for n in store.read_notes(work) if n["id"] == nid), None)
            if not note:
                return self.fail("없는 주석입니다", 404)
            if note["sent"]:
                return self.fail("이미 보낸 주석은 지울 수 없습니다")
            store.mark(work, "delete", [nid])
            return self.send_json({"ok": True})

        self.fail("찾을 수 없습니다", 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    httpd = None
    for p in range(port, port + 50):
        if port_in_use(p):
            continue
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", p), Handler)
            break
        except OSError:
            continue
    if not httpd:
        print("빈 번호를 찾지 못했습니다.")
        sys.exit(1)
    p = httpd.server_address[1]
    if p != port:
        print(f"{port}번은 다른 프로그램이 쓰고 있어서 {p}번으로 열었습니다.")
    print("영상 피드백 페이지가 켜졌습니다.")
    print(f"  이 컴퓨터에서:      http://localhost:{p}")
    ip = lan_ip()
    if ip:
        print(f"  같은 와이파이 폰에서: http://{ip}:{p}")
    print("끄려면 Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n껐습니다.")


if __name__ == "__main__":
    main()
