"""클로드가 쓰는 피드백 명령.

  python3 feedback.py 확인
      보냈지만 아직 완료되지 않은 주석을 모든 작품에서 보여 준다.

  python3 feedback.py 완료 <작품> <새 판 파일이름> <번호> [번호 ...]
      그 주석들을 완료로 표시한다. 주석 파일 끝에 한 줄을 덧붙일 뿐,
      기존 내용은 건드리지 않는다.
"""
import os
import sys

import feedback_store as store

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def fmt_time(t):
    t = float(t)
    return f"{int(t // 60)}:{t % 60:05.2f}"


def cmd_check():
    total = 0
    for w in store.list_works():
        notes = [n for n in store.read_notes(w["name"]) if n["sent"] and not n["done"]]
        if not notes:
            continue
        wd = store.work_dir(w["name"])
        latest = w["versions"][0]["name"] if w["versions"] else "(영상 없음)"
        print(f"\n=== 작품: {w['name']}   (지금 최신 판: {latest})")
        for n in notes:
            total += 1
            pos = f"가로 {n['pos']['x']*100:.0f}%, 세로 {n['pos']['y']*100:.0f}%" if n.get("pos") else "위치 없음"
            print(f"[{n['id']}] 판 {n['version']}  {fmt_time(n['time'])} ({n['time']}초)  {pos}")
            print(f"     글: {n['text']}")
            if n.get("image"):
                print(f"     화면 사진: {os.path.join(wd, n['image'])}")
            print(f"     보낸 시각: {n['sent']}")
    if total == 0:
        print("확인할 주석이 없습니다. (보낸 주석이 모두 완료됐거나, 아직 보낸 주석이 없습니다)")
    else:
        print(f"\n모두 {total}개")


def cmd_done(args):
    if len(args) < 3:
        print("사용법: python3 feedback.py 완료 <작품> <새 판 파일이름> <번호> [번호 ...]")
        sys.exit(2)
    work, version, raw_ids = args[0], args[1], args[2:]
    if not store.work_dir(work):
        print(f"없는 작품입니다: {work}")
        sys.exit(1)
    if not os.path.isfile(os.path.join(store.work_dir(work), version)):
        print(f"작품 폴더에 새 판 파일이 없습니다: {version}")
        sys.exit(1)
    notes = {n["id"]: n for n in store.read_notes(work)}
    try:
        ids = sorted({int(x) for x in raw_ids})
    except ValueError:
        print("번호는 숫자로 적어 주세요.")
        sys.exit(2)
    bad = [i for i in ids if i not in notes]
    if bad:
        print(f"없는 주석 번호: {bad}")
        sys.exit(1)
    for i in ids:
        if notes[i]["done"]:
            print(f"[{i}] 은 이미 완료되어 있습니다.")
        elif not notes[i]["sent"]:
            print(f"주의: [{i}] 은 아직 보내지 않은 주석입니다.")
    ids = [i for i in ids if not notes[i]["done"]]
    if ids:
        store.mark(work, "done", ids, fixed_in=version)
        print(f"완료로 표시했습니다: {work} {ids} → {version}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd in ("확인", "check"):
        cmd_check()
    elif cmd in ("완료", "done"):
        cmd_done(args)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
