#!/usr/bin/env python3
"""配信 repo の git 履歴から「これまでのブリーフ」（過去 14 日分の頁と一覧）を作る（PLAN-MB-117 §2）。

使い方: python3 .github/scripts/build-archive.py <出力先 _site>
  配信 repo のルート（index.html と .git がある所）で実行する。標準ライブラリ + git + node だけ。

何をするか
  1. `git log -- index.html` のうち件名が `brief: YYYY-MM-DD` で始まるコミットだけを使う。
     日付ごとに最も新しいコミットを 1 つ取る（件名に日付が無いコミットは使わない）。
  2. 最新の日付（＝いま公開中の頁）は除く。残りのうち最新の日付から暦日で 14 日以内だけ。
     `.github/archive-exclude.txt`（1 行 1 日付・`#` 以降はコメント）の日付と、
     予備が作った頁（`<meta name="brief-mode" content="fallback-local">`）は除く。
  3. 頁を加工する（details.arch の削除・リンクの書き換え・noindex・帯）。
  4. 一時ディレクトリに全部作り、全ファイルに `node .github/guard.js` を掛ける。
     落ちた頁は除く。一覧が落ちたら（または何か例外が出たら）archive を出さない。
  5. すべて通ったら `<出力先>/archive` へ移す。

標準出力は 1 行の要約だけ: `archive: pages=N excluded=M guard_failed=K`
  excluded = 窓の中で除外リスト・予備の頁・壊れた頁（details の閉じ無し・head か body が無い）として落としたもの。
終了コード: 0 = archive を出せた／頁 0 件で出さなかった。1 = 想定外の例外（archive は出さない）。2 = 使い方の誤り。
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SUBJECT = re.compile(r"^brief: (\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WINDOW_DAYS = 14
WEEK = "月火水木金土日"
GUARD = ".github/guard.js"
EXCLUDE = ".github/archive-exclude.txt"

ROBOTS_META = '<meta name="robots" content="noindex, nofollow">'
# 過去頁の帯（暗色にも対応・押す場所は 44px＝UIUX レビュー）。旧版の頁にも入るので自前の <style> を持つ。
BANNER_CSS = ("<style>#tlx-warn{display:none!important}"   # 旧版の「本日分ではありません」は帯と重複・暗色で読めない
              ".arch-banner{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0;"
              "padding:10px max(16px,calc((100% - 720px) / 2 + 16px));background:#E7F1EA;color:#22211D;font-size:14px;font-weight:600;"
              "font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP','Segoe UI',sans-serif}"
              ".arch-banner a{margin-left:auto;display:inline-flex;align-items:center;min-height:44px;padding:0 16px;"
              "border-radius:999px;background:#2F6B4F;color:#FFFFFF;text-decoration:none}"
              ".arch-banner a:focus-visible{outline:2px solid #2F6B4F;outline-offset:2px}"
              "@media (prefers-color-scheme: dark){.arch-banner{background:#1E2C24;color:#ECEAE3}"
              ".arch-banner a{background:#7CC49C;color:#151513}}</style>")

TAG_DETAILS = re.compile(r"<(/?)details\b[^>]*>", re.I)


def to_date(s):
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None


def label_of(d):
    return "%d月%d日（%s）" % (d.month, d.day, WEEK[d.weekday()])


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s failed" % args[0])
    return r.stdout


def brief_commits():
    """{date: (sha, コミット時刻の ISO)}。日付ごとに最も新しいコミット（git log は新しい順）。"""
    out = git("log", "--format=%H%x09%cI%x09%s", "--", "index.html").decode("utf-8", errors="replace")
    found = {}
    for line in out.splitlines():
        sha, _, rest = line.partition("\t")
        ctime, _, subject = rest.partition("\t")
        m = SUBJECT.match(subject)
        if not m:
            continue
        d = to_date(m.group(1))
        if d is None:
            continue
        found.setdefault(d, (sha, ctime))
    return found


def load_excludes():
    p = Path(EXCLUDE)
    if not p.is_file():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        d = to_date(line.split("#", 1)[0].strip())
        if d is not None:
            out.add(d)
    return out


def get_attr(tag, name):
    m = re.search(r"(?<![\w-])" + name + r"""\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag, re.I)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def meta_tags(s):
    return re.findall(r"<meta\b[^>]*>", s, re.I)


def tlx_date(s):
    """頁の tlx-data の date（読めなければ None）。"""
    m = re.search(r'<script\b[^>]*\bid=["\']tlx-data["\'][^>]*>(.*?)</script>', s, re.S | re.I)
    if not m:
        return None
    try:
        v = json.loads(m.group(1)).get("date")
    except Exception:
        return None
    return to_date(v) if isinstance(v, str) else None


def committed_late(ctime, d):
    """コミットが件名の日付の翌日 12:00（JST）より後＝後から押された頁（Fable 条件・差し替えの検出）。"""
    try:
        t = datetime.datetime.fromisoformat(ctime.replace("Z", "+00:00"))
    except ValueError:
        return True
    jst = datetime.timezone(datetime.timedelta(hours=9))
    limit = datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time(12, 0), tzinfo=jst)
    return t > limit


def is_fallback(s):
    for tag in meta_tags(s):
        if (get_attr(tag, "name") or "").strip().lower() == "brief-mode" \
                and (get_attr(tag, "content") or "").strip().lower() == "fallback-local":
            return True
    return False


def has_robots(s):
    """robots の meta があり、その content が noindex を含む（content を見ないと index を許す meta で素通りする・G3 P2）。"""
    return any((get_attr(t, "name") or "").strip().lower() == "robots"
               and "noindex" in (get_attr(t, "content") or "").lower() for t in meta_tags(s))


def strip_arch(s):
    """<details>…</details> を class に関わらずすべて削る（G3 P0: 旧版には class なし・arc・arch-day の
    3 通りの過去分の折りたたみがあり、class="arch" だけを消すと 14 日より前の過去分が再公開された）。
    Grok 版の頁は details を持たない。閉じタグが無い壊れた形は None。"""
    out = []
    pos = 0
    while True:
        start = None
        for m in TAG_DETAILS.finditer(s, pos):
            if not m.group(1):
                start = m
                break
        if start is None:
            out.append(s[pos:])
            return "".join(out)
        depth = 1
        end = None
        for m in TAG_DETAILS.finditer(s, start.end()):
            depth += -1 if m.group(1) else 1
            if depth == 0:
                end = m.end()
                break
        if end is None:
            return None
        out.append(s[pos:start.start()])
        pos = end


def transform(s, d):
    """頁を過去頁に加工する。作れない形（壊れた details・head/body 無し）は None。"""
    s = strip_arch(s)
    if s is None:
        return None
    # 折りたたみを消した後に見出しだけ残る「これまでのブリーフ」の節を削る（旧版・予備の頁）
    s = re.sub(r"<section\b[^>]*>\s*<h2\b[^>]*>\s*これまでのブリーフ\s*</h2>\s*</section>\s*", "", s)
    s = re.sub(r"""(href\s*=\s*)(["'])archive/""", r"\1\2./", s)
    s = re.sub(r"""(href\s*=\s*)(["'])assets/""", r"\1\2../assets/", s)
    s = re.sub(r"""(src\s*=\s*)(["'])assets/""", r"\1\2../assets/", s)
    body = re.search(r"<body\b[^>]*>", s, re.I)
    if body is None:
        return None
    banner = BANNER_CSS + ('<div class="arch-banner"><span>%sのブリーフです</span>'
                           '<a href="../">最新を見る</a></div>') % label_of(d)
    s = s[:body.end()] + banner + s[body.end():]
    if not has_robots(s):
        head = re.search(r"<head\b[^>]*>", s, re.I)
        if head is None:
            return None
        s = s[:head.end()] + ROBOTS_META + s[head.end():]
    return s


LIST_CSS = """
:root{color-scheme:light dark;--bg:#F6F5F1;--card:#FFFFFF;--ink:#22211D;--soft:#5F5D55;--line:#E3E1D9;
  --brand:#2F6B4F;--brand-soft:#E7F1EA;--sun:#9A3B2E;--sat:#2F5E8C}
@media (prefers-color-scheme: dark){:root{--bg:#151513;--card:#1F1F1C;--ink:#ECEAE3;--soft:#B5B2A7;
  --line:#34332E;--brand:#7CC49C;--brand-soft:#1E2C24;--sun:#F08A7A;--sat:#8DB8E6}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.6;
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Segoe UI",sans-serif}
.page{max-width:720px;margin:0 auto;padding:28px 16px 56px}
.kicker{font-size:13px;font-weight:700;color:var(--brand);margin:0}
h1{font-size:24px;line-height:1.3;margin:4px 0 0}
.days{list-style:none;margin:20px 0 0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:8px}
.days a{display:flex;align-items:baseline;gap:12px;padding:12px 16px;min-height:48px;background:var(--card);
  border:1px solid var(--line);border-radius:12px;color:var(--ink);text-decoration:none}
.days a:hover{border-color:var(--brand)}
.days a:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.days .d{font-weight:700;white-space:nowrap}
.days .wkend{color:var(--sun)}
.days .p{flex:1 1 auto;color:var(--soft);font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.days .sat{color:var(--sat)}
.note{color:var(--soft);font-size:13px;margin:16px 0 0}
"""


def preview_of(s):
    """一覧に添える一言。Grok 版の「今日いちばん大事なこと」の 1 つめ（旧版・無ければ空）。"""
    m = re.search(r'<section class="card focus">.*?<li>(.*?)</li>', s, re.S)
    if not m:
        # 予備の頁は件数だけの定型文（名前が入らない）
        if is_fallback(s):
            m = re.search(r'<p class="head">(予定 \d+ 件[^<]*)</p>', s)
    if not m:
        # 旧 Claude（Cowork）版の見出しの一文には利用者の名前が入る＝一覧に集めない（UIUX レビュー・D7）
        return ""
    t = re.sub(r"<[^>]+>", "", m.group(1))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:40]


def list_html(entries, previews=None):
    previews = previews or {}
    rows = []
    for d in entries:
        wk = ' sat' if d.weekday() == 5 else (' wkend' if d.weekday() == 6 else '')
        pv = previews.get(d, "")
        pv = pv.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append('<li><a href="%s.html"><span class="d%s">%s</span><span class="p">%s</span></a></li>'
                    % (d.isoformat(), wk, label_of(d), pv))
    return (
        '<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        + ROBOTS_META + '\n<title>これまでのブリーフ</title>\n<style>' + LIST_CSS + '</style>\n'
        '<link rel="stylesheet" href="../assets/brief.css">\n</head>\n<body>\n<div class="page">\n'
        '<header>\n<p class="kicker">朝のブリーフ</p>\n<h1>これまでのブリーフ</h1>\n'
        '<nav class="nav" aria-label="ブリーフの移動"><a class="nav-next" href="../">最新のブリーフ</a></nav>\n</header>\n'
        '<ul class="days">\n' + "\n".join(rows) + '\n</ul>\n'
        '<p class="note">直近 2 週間ぶんを置いています。</p>\n</div>\n</body>\n</html>\n'
    )


def run_guard(path):
    if not os.path.isfile(GUARD):
        raise RuntimeError("%s not found" % GUARD)
    r = subprocess.run(["node", GUARD, str(path)], capture_output=True, timeout=120)
    return r.returncode == 0


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(out_dir, tmp):
    commits = brief_commits()
    dates = sorted(commits, reverse=True)
    pages = excluded = guard_failed = 0
    kept = []
    previews = {}
    if dates:
        latest = dates[0]
        excl = load_excludes()
        arch = tmp / "archive"
        arch.mkdir()
        for d in dates[1:]:
            if (latest - d).days > WINDOW_DAYS:
                continue
            if d in excl:
                excluded += 1
                continue
            sha, ctime = commits[d]
            if committed_late(ctime, d):
                excluded += 1
                print("build-archive: late commit date=%s" % d.isoformat(), file=sys.stderr)
                continue
            try:
                s = git("show", "%s:index.html" % sha).decode("utf-8")
            except UnicodeDecodeError:
                excluded += 1
                continue
            # 頁の日付と件名の日付が違う頁は載せない。予備の頁（MB-043）は日付が読めなければ除く（fail-closed）。
            # 予備の頁は利用者の決定（2026-10-12）で載せる＝その日に実際に公開された頁（予定名は collect.js で一般化済み）。
            td = tlx_date(s)
            if (td is not None and td != d) or (td is None and is_fallback(s)):
                excluded += 1
                continue
            t = transform(s, d)
            if t is None:
                excluded += 1
                continue
            f = arch / ("%s.html" % d.isoformat())
            write_text(f, t)
            if run_guard(f):
                kept.append(d)
                previews[d] = preview_of(s)
            else:
                f.unlink()
                guard_failed += 1
                print("build-archive: guard failed date=%s" % d.isoformat(), file=sys.stderr)
        if kept:
            idx = arch / "index.html"
            write_text(idx, list_html(kept, previews))
            write_text(arch / "index.json", json.dumps(
                [{"date": d.isoformat(), "label": label_of(d)} for d in kept],
                ensure_ascii=False))
            if not run_guard(idx):
                raise RuntimeError("archive/index.html failed guard")
            partial = out_dir / ".archive.partial"
            final = out_dir / "archive"
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                if partial.exists():
                    shutil.rmtree(partial)
                shutil.copytree(arch, partial)
                if final.exists():
                    shutil.rmtree(final)
                os.replace(partial, final)
            finally:
                if partial.exists():
                    shutil.rmtree(partial, ignore_errors=True)
            pages = len(kept)
    print("archive: pages=%d excluded=%d guard_failed=%d" % (pages, excluded, guard_failed))


def main(argv):
    if len(argv) != 2:
        print("usage: build-archive.py <output _site dir>", file=sys.stderr)
        return 2
    out_dir = Path(argv[1])
    tmp = Path(tempfile.mkdtemp(prefix="build-archive-"))
    try:
        build(out_dir, tmp)
        return 0
    except Exception as e:  # noqa: BLE001
        print("build-archive: error: %s: %s" % (type(e).__name__, str(e)[:200]), file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
