"""주석 파일(feedback.jsonl) 읽기·쓰기 공용 코드.

주석 파일은 '덧붙이기 전용' 기록장이다. 한 줄이 사건 하나이고,
기존 줄은 절대 고치거나 지우지 않는다. 지금 상태는 처음부터 끝까지
읽어서 계산한다.

  {"type":"note", "id":3, "version":"v1.mp4", "time":12.34,
   "pos":{"x":0.42,"y":0.61} 또는 null, "text":"...",
   "image":"feedback_images/3.jpg" 또는 null,
   "created":"2026-11-16T12:00:00+09:00", "sent":null, "done":false}
  {"type":"sent",   "ids":[1,2,3], "at":"..."}
  {"type":"done",   "ids":[1,2],   "at":"...", "fixed_in":"v2.mp4"}
  {"type":"delete", "ids":[4],     "at":"..."}
"""
import json
import os
import threading
from datetime import datetime

FEEDBACK_FILE = "feedback.jsonl"
IMAGE_DIR = "feedback_images"
ROOT = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {"__pycache__", "node_modules"}

_lock = threading.Lock()


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def work_dir(work):
    """작품 이름을 안전하게 폴더 경로로 바꾼다. 바로 아래 하위 폴더만 허용."""
    if not work or work in (".", "..") or "/" in work or "\\" in work or work.startswith("."):
        return None
    if work in SKIP_DIRS:
        return None
    path = os.path.join(ROOT, work)
    return path if os.path.isdir(path) else None


def list_works():
    works = []
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if name.startswith(".") or name in SKIP_DIRS or not os.path.isdir(path):
            continue
        versions = []
        for f in os.listdir(path):
            fp = os.path.join(path, f)
            if f.lower().endswith(".mp4") and os.path.isfile(fp):
                st = os.stat(fp)
                versions.append({"name": f, "mtime": st.st_mtime, "size": st.st_size})
        versions.sort(key=lambda v: v["mtime"], reverse=True)  # 최신 판이 먼저
        works.append({"name": name, "versions": versions})
    return works


def _append(work, event):
    path = os.path.join(work_dir(work), FEEDBACK_FILE)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_notes(work):
    """사건 기록을 처음부터 다시 읽어 주석 목록(번호 순)을 만든다."""
    path = os.path.join(work_dir(work), FEEDBACK_FILE)
    notes = {}
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "note":
                n = dict(ev)
                n.pop("type", None)
                n.setdefault("sent", None)
                n.setdefault("done", False)
                notes[n["id"]] = n
            elif t in ("sent", "done", "delete"):
                for i in ev.get("ids", []):
                    n = notes.get(i)
                    if not n:
                        continue
                    if t == "sent" and not n["sent"]:
                        n["sent"] = ev["at"]
                    elif t == "done":
                        n["done"] = True
                        n["done_at"] = ev["at"]
                        if ev.get("fixed_in"):
                            n["fixed_in"] = ev["fixed_in"]
                    elif t == "delete" and not n["sent"]:
                        n["deleted"] = True
    return [n for _, n in sorted(notes.items()) if not n.get("deleted")]


def _next_id(work):
    path = os.path.join(work_dir(work), FEEDBACK_FILE)
    top = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for raw in f:
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "note":
                    top = max(top, int(ev.get("id", 0)))
    return top + 1


def add_note(work, version, time, pos, text, image_bytes=None):
    with _lock:
        nid = _next_id(work)
        image = None
        if image_bytes:
            img_dir = os.path.join(work_dir(work), IMAGE_DIR)
            os.makedirs(img_dir, exist_ok=True)
            image = f"{IMAGE_DIR}/{nid}.jpg"
            with open(os.path.join(work_dir(work), image), "wb") as f:
                f.write(image_bytes)
        ev = {
            "type": "note", "id": nid, "version": version,
            "time": round(float(time), 3), "pos": pos, "text": text,
            "image": image, "created": now_iso(), "sent": None, "done": False,
        }
        _append(work, ev)
        return nid


def mark(work, kind, ids, **extra):
    with _lock:
        ev = {"type": kind, "ids": list(ids), "at": now_iso()}
        ev.update(extra)
        _append(work, ev)
        return ev
