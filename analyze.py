#!/usr/bin/env python3
"""Phân tích thống kê bằng AI (tuỳ chọn). Cần secret ANTHROPIC_API_KEY; không có thì bỏ qua êm.
Chỉ gọi API khi có kỳ mới (so khóa kỳ trong analysis.json) nên tốn rất ít.
Chạy: python3 analyze.py"""
import json, os, sys, time, urllib.request
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "analysis.json")
API = os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")


def load_data():
    s = open(os.path.join(BASE, "data.js"), encoding="utf-8").read()
    return json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))["games"]


def summary(g, info):
    rows = info["rows"]
    last = rows[:60]
    cnt = Counter(n for r in last for n in r["n"])
    gap = {}
    for i, r in enumerate(rows):
        for n in r["n"]:
            gap.setdefault(n, i)
    mx = info["max"]
    cold = sorted(range(1, mx + 1), key=lambda n: -gap.get(n, len(rows)))[:6]
    jr = [r["jv"] for r in rows[:10] if r.get("jv")]
    return ("%s: %d kỳ dữ liệu. Trong 60 kỳ gần nhất, số ra nhiều nhất: %s; ra ít nhất: %s; lâu chưa ra nhất: %s. "
            "Jackpot 10 kỳ gần nhất (tỷ đồng, mới nhất trước): %s." % (
                info["name"], len(rows), cnt.most_common(6),
                sorted(cnt.items(), key=lambda x: x[1])[:6], cold, jr))


def ask(key, text):
    body = json.dumps({"model": MODEL, "max_tokens": 500, "messages": [{"role": "user", "content":
        "Viết nhận xét thống kê ngắn (tối đa 5 gạch đầu dòng, tiếng Việt) cho dữ liệu xổ số sau. "
        "Nhấn mạnh xổ số hoàn toàn ngẫu nhiên, không dự đoán số, không khuyên mua. Dữ liệu:\n" + text}]}).encode()
    req = urllib.request.Request(API, body, {"content-type": "application/json", "x-api-key": key,
                                             "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return "".join(b.get("text", "") for b in json.load(r)["content"]).strip()


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("Không có ANTHROPIC_API_KEY — bỏ qua phân tích AI")
        return 0
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:  # noqa
        old = {}
    new, changed = dict(old), False
    for g, info in load_data().items():
        if not info["rows"]:
            continue
        r0 = info["rows"][0]
        sig = r0["d"] + str(r0.get("h") or "")
        if old.get(g, {}).get("sig") == sig:
            continue
        try:
            new[g] = {"sig": sig, "text": ask(key, summary(g, info))}
            changed = True
        except Exception as e:  # noqa
            print("Lỗi AI", g, e)
    if changed:
        new["updated"] = time.strftime("(cập nhật %d/%m/%Y)", time.gmtime(time.time() + 7 * 3600))
        json.dump(new, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("Đã ghi analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
