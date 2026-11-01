#!/usr/bin/env python3
"""
Vietlott 6/45 & 6/55 - server tự động cập nhật kết quả.

  python3 server.py                -> chạy web (http://localhost:8000) + tự cập nhật
  python3 server.py --sync-once    -> kiểm tra & cập nhật 1 lần rồi thoát (dùng cho cron / Task Scheduler)
  python3 server.py --build        -> chỉ tạo lại data.js từ 2 file .ods

Chỉ dùng thư viện chuẩn của Python (>= 3.8), không cần cài thêm gì.
"""
import argparse
import html as htmllib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dtime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
# file .ods nằm trong thư mục data/ (nếu có), không thì nằm cùng thư mục với server.py
DATA_DIR = os.path.join(BASE, "data") if os.path.isdir(os.path.join(BASE, "data")) else BASE

try:
    from zoneinfo import ZoneInfo
    VN = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # Windows thiếu tzdata, Python cũ...
    VN = timezone(timedelta(hours=7))

DRAW_HOUR = 18  # Vietlott quay lúc 18:00

# weekday(): Thứ 2 = 0 ... Chủ nhật = 6
def _src(env, kq, mn):
    # nguồn chính (ketquadientoan) + nguồn dự phòng/đối chiếu (minhngoc)
    return [("ketquadientoan", os.environ.get(env, kq), "kqdt"), ("minhngoc", mn, "mn")]


GAMES = {
    "655": dict(
        name="Power 6/55", file="655.ods", maxn=55, main=6, bonus=True,
        days=(1, 3, 5),  # Thứ 3, 5, 7
        sources=_src("VIETLOTT_URL_655",
                     "https://www.ketquadientoan.com/tat-ca-ky-xo-so-power-655.html",
                     "https://www.minhngoc.net.vn/ket-qua-xo-so/dien-toan-vietlott/power-6x55.html"),
    ),
    "645": dict(
        name="Mega 6/45", file="645.ods", maxn=45, main=6, bonus=False,
        days=(2, 4, 6),  # Thứ 4, 6, Chủ nhật
        sources=_src("VIETLOTT_URL_645",
                     "https://www.ketquadientoan.com/tat-ca-ky-xo-so-mega-6-45.html",
                     "https://www.minhngoc.net.vn/ket-qua-xo-so/dien-toan-vietlott/mega-6x45.html"),
    ),
}
WD = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

T_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
LOCK = threading.RLock()
STATUS = {g: dict(last_check=None, last_ok=None, error=None, new_at=None, last_added=0) for g in GAMES}
LAST_TRY = {g: 0.0 for g in GAMES}
LAST_MANUAL = 0.0


def now_vn():
    return datetime.now(VN)


def log(msg):
    line = "[%s] %s" % (now_vn().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(DATA_DIR, "sync.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ───────────────────────── ODS đọc / ghi ─────────────────────────

def ods_path(g):
    return os.path.join(DATA_DIR, GAMES[g]["file"])


def read_ods(g):
    """Trả về list dict, MỚI NHẤT Ở ĐẦU (đúng thứ tự trong file)."""
    cfg = GAMES[g]
    need = cfg["main"] + (1 if cfg["bonus"] else 0)
    with zipfile.ZipFile(ods_path(g)) as z:
        root = ET.fromstring(z.read("content.xml"))
    rows = []
    for tr in root.iter("{%s}table-row" % T_NS):
        cells = tr.findall("{%s}table-cell" % T_NS)[:3]
        if len(cells) < 2:
            continue
        texts = ["".join(c.itertext()).strip() for c in cells]
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texts[0])
        ns = re.findall(r"\d{1,2}", texts[1])
        if not m or len(ns) != need:
            continue
        ns = [int(x) for x in ns]
        rows.append(dict(
            d="%s-%s-%s" % (m.group(3), m.group(2), m.group(1)),
            n=ns[:cfg["main"]],
            b=ns[cfg["main"]] if cfg["bonus"] else None,
            j=texts[2] if len(texts) > 2 else "",
            jv=jack_val(texts[2] if len(texts) > 2 else ""),
        ))
    return rows


def jack_val(s):
    """'≈ 188.8 Tỷ' -> 188.8 (để vẽ biểu đồ); không đọc được -> 0."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*Tỷ", s or "")
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def prepend_ods(g, row):
    """Chèn 1 kỳ mới lên HÀNG ĐẦU của file .ods (giữ nguyên định dạng của hàng đầu hiện có)."""
    cfg = GAMES[g]
    path = ods_path(g)
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)  # sao lưu bản gốc 1 lần

    with zipfile.ZipFile(path) as zin:
        content = zin.read("content.xml").decode("utf-8")
        m = re.search(r"<table:table-row\b.*?</table:table-row>", content, re.S)
        if not m:
            raise RuntimeError("Không tìm thấy hàng mẫu trong %s" % path)
        tmpl = m.group(0)
        ps = list(re.finditer(r"<text:p>.*?</text:p>", tmpl, re.S))
        if len(ps) != 3:
            raise RuntimeError("Hàng mẫu không có đúng 3 ô (%d)" % len(ps))

        d = date.fromisoformat(row["d"])
        label = "%s, %s" % (WD[d.weekday()], d.strftime("%d/%m/%Y"))

        num_tmpl = ps[1].group(0)
        sep = re.search(r'<text:span text:style-name="([^"]+)"> </text:span>', num_tmpl)
        bon = re.search(r'<text:span text:style-name="([^"]+)">\d\d</text:span>', num_tmpl)
        mains = ["%02d" % x for x in row["n"]]
        if sep:
            sp = '<text:span text:style-name="%s"> </text:span>' % sep.group(1)
            body = sp.join(mains)
            if cfg["bonus"]:
                bs = bon.group(1) if bon else sep.group(1)
                body += sp + '<text:span text:style-name="%s">%02d</text:span>' % (bs, row["b"])
        else:
            body = " ".join(mains + (["%02d" % row["b"]] if cfg["bonus"] else []))
        new_p = ["<text:p>%s</text:p>" % _esc(label), "<text:p>%s</text:p>" % body,
                 "<text:p>%s</text:p>" % _esc(row["j"] or "")]

        new_row = tmpl
        for mm, rep in reversed(list(zip(ps, new_p))):
            new_row = new_row[:mm.start()] + rep + new_row[mm.end():]
        new_content = content[:m.start()] + new_row + content[m.start():]

        fd, tmp = tempfile.mkstemp(suffix=".ods", dir=DATA_DIR)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as zout:
                for item in zin.infolist():  # mimetype vẫn là mục đầu, không nén
                    data = new_content.encode("utf-8") if item.filename == "content.xml" else zin.read(item.filename)
                    zout.writestr(item, data, compress_type=item.compress_type)
        except Exception:
            os.remove(tmp)
            raise
    os.replace(tmp, path)


def update_ods_jackpot(g, iso_date, jack):
    """Điền/sửa ô jackpot (cột 3) của kỳ `iso_date` đã có trong .ods. True nếu đã sửa."""
    path = ods_path(g)
    d = date.fromisoformat(iso_date)
    needle = d.strftime("%d/%m/%Y")
    with zipfile.ZipFile(path) as zin:
        content = zin.read("content.xml").decode("utf-8")
        for m in re.finditer(r"<table:table-row\b.*?</table:table-row>", content, re.S):
            row = m.group(0)
            ps = list(re.finditer(r"<text:p>.*?</text:p>", row, re.S))
            if len(ps) != 3 or needle not in re.sub(r"<[^>]+>", "", ps[0].group(0)):
                continue
            if re.sub(r"<[^>]+>", "", ps[2].group(0)).strip() == jack:
                return False
            new_row = row[:ps[2].start()] + "<text:p>%s</text:p>" % _esc(jack) + row[ps[2].end():]
            new_content = content[:m.start()] + new_row + content[m.end():]
            fd, tmp = tempfile.mkstemp(suffix=".ods", dir=DATA_DIR)
            os.close(fd)
            try:
                with zipfile.ZipFile(tmp, "w") as zout:
                    for item in zin.infolist():
                        data = new_content.encode("utf-8") if item.filename == "content.xml" else zin.read(item.filename)
                        zout.writestr(item, data, compress_type=item.compress_type)
            except Exception:
                os.remove(tmp)
                raise
            zin.close()
            os.replace(tmp, path)
            return True
    return False


def backfill_jackpots(g, res):
    """Kết quả thường có trước, tiền jackpot các trang nguồn cập nhật chậm hơn:
    điền bổ sung jackpot cho vài kỳ gần nhất đang để trống."""
    fixed = 0
    for r in read_ods(g)[:5]:
        if r["j"]:
            continue
        j = next((s[r["d"]]["j"] for s in res.values() if r["d"] in s and s[r["d"]].get("j")), "")
        if j and update_ods_jackpot(g, r["d"], j):
            fixed += 1
            log("%s: điền jackpot kỳ %s = %s" % (GAMES[g]["name"], r["d"], j))
    return fixed


# ───────────────────────── Lấy dữ liệu từ web ─────────────────────────

ROW_RE = re.compile(
    r"(T[2-7]|CN)\s*,\s*(\d{2})/(\d{2})/(\d{4})(.*?)(?=(?:T[2-7]|CN)\s*,\s*\d{2}/\d{2}/\d{4}|\Z)", re.S)


def parse_source(html_text, g):
    """Bóc các kỳ quay từ HTML của ketquadientoan.com. Chịu được nhiều kiểu markup (td/span/...)."""
    cfg = GAMES[g]
    need = cfg["main"] + (1 if cfg["bonus"] else 0)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html_text)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    num_re = re.compile(r"\s*((?:\d{2}\s+){%d}\d{2})(?![\d.,])" % (need - 1))
    out, seen = [], set()
    for m in ROW_RE.finditer(t):
        iso = "%s-%s-%s" % (m.group(4), m.group(3), m.group(2))
        if iso in seen:
            continue
        seg = m.group(5)
        mm = num_re.match(seg)
        if not mm:
            continue
        ns = [int(x) for x in mm.group(1).split()]
        main = ns[:cfg["main"]]
        if len(set(main)) != cfg["main"] or any(not 1 <= x <= cfg["maxn"] for x in ns):
            continue
        rest = seg[mm.end():]
        jm = re.search(r"≈\s*[\d.,]+\s*Tỷ", rest)
        if jm:
            jack = re.sub(r"\s+", " ", jm.group(0))
        else:
            fm = re.search(r"\d{1,3}(?:\.\d{3}){2,}", rest)
            if fm:
                v = round(int(fm.group(0).replace(".", "")) / 1e9, 1)
                jack = "≈ %s Tỷ" % (("%d" % v) if v == int(v) else ("%.1f" % v))
            else:
                jack = ""
        seen.add(iso)
        out.append(dict(d=iso, n=main, b=ns[cfg["main"]] if cfg["bonus"] else None, j=jack))
    return out


MN_DATE = re.compile(r"Ngày quay thưởng\s*(\d{2})/(\d{2})/(\d{4})")


def jack_fmt(v):
    v = round(v / 1e9, 1)
    return "≈ %s Tỷ" % (("%d" % v) if v == int(v) else ("%.1f" % v))


def parse_minhngoc(html_text, g):
    """Bóc các kỳ quay từ minhngoc.net.vn (nguồn dự phòng)."""
    cfg = GAMES[g]
    need = cfg["main"] + (1 if cfg["bonus"] else 0)
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html_text)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t).replace("\xa0", " ")
    num_re = re.compile(r"(?<![\d/.,#])((?:\d{2}\s+){%d}\d{2})(?![\d/.,])" % (need - 1))
    ms = list(MN_DATE.finditer(t))
    out, seen = [], set()
    for i, m in enumerate(ms):
        iso = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
        seg = t[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(t)]
        nm = num_re.search(seg[:500])
        if iso in seen or not nm:
            continue
        ns = [int(x) for x in nm.group(1).split()]
        main = ns[:cfg["main"]]
        if len(set(main)) != cfg["main"] or any(not 1 <= x <= cfg["maxn"] for x in ns):
            continue
        jm = re.search(r"Jackpot(?:\s*1)?\b.{0,60}?(\d{1,3}(?:[.,]\d{3}){2,})", seg[nm.end():], re.S)
        jack = jack_fmt(int(re.sub(r"\D", "", jm.group(1)))) if jm else ""
        seen.add(iso)
        out.append(dict(d=iso, n=main, b=ns[cfg["main"]] if cfg["bonus"] else None, j=jack))
    return out


PARSERS = {"kqdt": parse_source, "mn": parse_minhngoc}


def fetch_url(url):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "vi,en;q=0.8",
    })
    with urlopen(req, timeout=30) as r:
        raw = r.read()
    return raw.decode("utf-8", errors="replace")


def gather(g):
    """Lấy tất cả nguồn. Trả về ({tên_nguồn: {ngày: kỳ}}, [lỗi])."""
    res, errs = {}, []
    for name, url, pk in GAMES[g]["sources"]:
        try:
            rows = PARSERS[pk](fetch_url(url), g)
            if rows:
                res[name] = {r["d"]: r for r in rows}
            else:
                errs.append("%s: không đọc được kết quả nào (trang có thể đã đổi cấu trúc)" % name)
        except Exception as e:  # noqa
            errs.append("%s: %s: %s" % (name, type(e).__name__, e))
    return res, errs


def sync(g):
    """Lấy từ nhiều nguồn, đối chiếu chéo rồi mới ghi kỳ mới vào .ods. Trả về số kỳ đã thêm.
    Ghi ngay khi >=2 nguồn khớp nhau; nếu mới có 1 nguồn thì chờ 45 phút sau giờ quay rồi mới tin.
    Nếu các nguồn lệch nhau thì KHÔNG ghi và báo lỗi."""
    with LOCK:
        st = STATUS[g]
        LAST_TRY[g] = time.time()
        st["last_check"] = now_vn().isoformat(timespec="seconds")
        try:
            local = read_ods(g)
            latest = local[0]["d"] if local else "0000-00-00"
            known = {r["d"] for r in local}
            res, errs = gather(g)
            if not res:
                raise RuntimeError("Tất cả nguồn đều lỗi: " + "; ".join(errs))
            for e in errs:
                log("%s: nguồn phụ lỗi - %s" % (GAMES[g]["name"], e))
            now = now_vn()
            today = now.date().isoformat()
            cands = sorted({d for s in res.values() for d in s if d > latest and d not in known and d <= today})
            added, problem = 0, None
            for d in cands:  # cũ → mới, để kỳ mới nhất nằm trên cùng
                vs = [s[d] for s in res.values() if d in s]
                if len({(tuple(v["n"]), v["b"]) for v in vs}) > 1:
                    problem = "Các nguồn lệch nhau ở kỳ %s - tạm không ghi" % d
                    break
                row = dict(vs[0])
                row["j"] = next((v["j"] for v in vs if v["j"]), "")
                due = datetime.combine(date.fromisoformat(d), dtime(DRAW_HOUR, 0), tzinfo=VN) + timedelta(minutes=45)
                if len(vs) < 2 and now < due:
                    log("%s: kỳ %s mới có 1 nguồn, chờ nguồn thứ 2 xác nhận" % (GAMES[g]["name"], d))
                    break
                if len(vs) < 2:
                    log("%s: cảnh báo - kỳ %s chỉ có 1 nguồn xác nhận" % (GAMES[g]["name"], d))
                prepend_ods(g, row)
                added += 1
                log("%s: thêm kỳ %s  %s%s  %s  (%d nguồn)" % (
                    GAMES[g]["name"], row["d"], " ".join("%02d" % x for x in row["n"]),
                    (" + %02d" % row["b"]) if row["b"] else "", row["j"], len(vs)))
            fixed = backfill_jackpots(g, res)
            if problem:
                if fixed:
                    build_data()
                raise RuntimeError(problem)
            st["error"] = None
            st["last_ok"] = st["last_check"]
            st["last_added"] = added
            if added:
                st["new_at"] = st["last_check"]
            if added or fixed:
                build_data()
            return added
        except Exception as e:  # noqa
            st["error"] = "%s: %s" % (type(e).__name__, e)
            log("%s: LỖI %s" % (GAMES[g]["name"], st["error"]))
            return 0


# ───────────────────────── Dữ liệu cho web ─────────────────────────

_cache = {}


def load_games():
    out = {}
    for g, cfg in GAMES.items():
        p = ods_path(g)
        mt = os.path.getmtime(p)
        c = _cache.get(g)
        if not c or c[0] != mt:
            c = (mt, read_ods(g))
            _cache[g] = c
        out[g] = dict(name=cfg["name"], max=cfg["maxn"], bonus=cfg["bonus"], days=list(cfg["days"]), rows=c[1])
    return out


def build_data():
    """Tạo data.js. Chỉ ghi lại file khi dữ liệu kỳ quay thật sự thay đổi
    (tránh bot commit + dựng lại web liên tục chỉ vì dấu thời gian)."""
    with LOCK:
        games = load_games()
        path = os.path.join(BASE, "data.js")
        try:
            with open(path, encoding="utf-8") as f:
                old = json.loads(f.read().strip()[len("window.LOTTO_DATA="):].rstrip(";"))
            if old.get("games") == games:
                return False
        except Exception:  # noqa  (chưa có file / file hỏng -> ghi mới)
            pass
        data = dict(games=games, generated=now_vn().isoformat(timespec="seconds"))
        tmp = os.path.join(BASE, "data.js.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("window.LOTTO_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
        os.replace(tmp, path)
        return True


def api_payload():
    with LOCK:
        return dict(games=load_games(), status=STATUS, server_time=now_vn().isoformat(timespec="seconds"))


# ───────────────────────── Lịch tự động ─────────────────────────

def scheduler():
    while True:
        try:
            now = now_vn()
            today = now.date().isoformat()
            t18 = now.replace(hour=DRAW_HOUR, minute=0, second=0, microsecond=0)
            for g, cfg in GAMES.items():
                rows = read_ods(g)
                latest = rows[0]["d"] if rows else ""
                waiting = now.weekday() in cfg["days"] and now >= t18 and latest < today
                if waiting:
                    # sau 18h ngày quay: hỏi mỗi 60s trong 2 giờ đầu, sau đó mỗi 10 phút
                    interval = 60 if now < t18 + timedelta(hours=2) else 600
                else:
                    interval = 6 * 3600  # các lúc khác: kiểm tra bù mỗi 6 tiếng
                if time.time() - LAST_TRY[g] >= interval:
                    sync(g)
        except Exception as e:  # noqa
            log("scheduler lỗi: %r" % e)
        time.sleep(15)


# ───────────────────────── HTTP ─────────────────────────

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/data.js": ("data.js", "application/javascript; charset=utf-8")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/data":
            return self._send(200, json.dumps(api_payload(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
        if path in STATIC:
            fn, ct = STATIC[path]
            try:
                with open(os.path.join(BASE, fn), "rb") as f:
                    return self._send(200, f.read(), ct)
            except OSError:
                return self._send(404, b"not found", "text/plain")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        global LAST_MANUAL
        if self.path.split("?")[0] == "/api/sync":
            if time.time() - LAST_MANUAL < 20:  # chống bấm/gọi dồn dập
                added = {g: 0 for g in GAMES}
            else:
                LAST_MANUAL = time.time()
                added = {g: sync(g) for g in GAMES}
            body = dict(added=added, **api_payload())
            return self._send(200, json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="mặc định 127.0.0.1; dùng 0.0.0.0 để máy khác trong mạng truy cập")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--sync-once", action="store_true")
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()

    if a.build:
        build_data()
        print("Đã tạo data.js")
        return
    if a.sync_once:
        n = {g: sync(g) for g in GAMES}
        build_data()
        print("Đã thêm:", n)
        sys.exit(1 if any(STATUS[g]["error"] for g in GAMES) else 0)

    build_data()
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    log("Mở http://%s:%d  (Ctrl+C để dừng)" % ("localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
