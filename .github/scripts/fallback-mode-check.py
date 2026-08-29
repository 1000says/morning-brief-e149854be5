#!/usr/bin/env python3
"""SLI-7 の判定器: 公開ブリーフが「ローカル縮退版」で出た日を数える（MB-043 / M-3）。

**なぜ要るか**
  生成フォールバックが成功すると、`SLI-1`（配信鮮度）は緑に戻る。つまり
  「claude.ai が週次上限に達して生成が止まっている」という**本来の異常が、
  フォールバックによって隠れる**。戻す対象を作らないために、縮退そのものを数える。

**どう数えるか**
  中継のコミットメッセージは生成主体によらず `brief: YYYY-MM-DD (generated HH:MM JST)` で同じ。
  区別できるのは `index.html` の中の片側マーカーだけ:
      <meta name="brief-mode" content="fallback-local">
  正常日（Cowork 生成）はこの行を**出さない**＝無い日を primary とみなす（片側検出）。
  「正常日にも primary と書かせる」設計にしなかったのは、生成側の指示文に 1 行足す必要があり、
  貼り忘れが縮退の見逃しに直結するため（書き忘れとフォールバックが区別できなくなる）。

**しきい値（アラート疲れを避ける）**
  1 日だけの縮退は notice（生成が 1 日落ちるのは起こりうる）。
  **2 日連続**、または **直近 7 日で 3 日以上**なら warning＝上限が常態化している。

使い方: python3 .github/scripts/fallback-mode-check.py [--json] [--limit N]
出力（1 行・契約）: OK consecutive=<n> last7=<n> scanned=<n>
                    / WARN consecutive=<n> last7=<n> scanned=<n>
                    / BAD <理由>
終了コード: 0 = 判定できた（OK/WARN とも）/ 2 = 判定できない（BAD）
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

MARKER = re.compile(r'<meta\s+name="brief-mode"\s+content="fallback-local"\s*/?>')
BRIEF_MSG = re.compile(r"^brief: (\d{4}-\d{2}-\d{2}) ")
JST = timezone(timedelta(hours=9))


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:200] or "git failed")
    return r.stdout


def publishes(limit: int):
    """index.html を触った `brief: ` コミットを新しい順に返す。

    `brief: ` に限るのは SLI-1 と同じ理由——doc 修正や検証用 commit を数えると、
    「縮退していない日」を水増しして連続日数を過小評価する。
    """
    out = git("log", f"-{limit * 4}", "--first-parent", "--format=%H%x09%cI%x09%s", "--", "index.html")
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, iso, subject = parts
        m = BRIEF_MSG.match(subject)
        if not m:
            continue
        rows.append({"sha": sha, "iso": iso, "ymd": m.group(1)})
        if len(rows) >= limit:
            break
    return rows


def is_fallback(sha: str) -> bool:
    return bool(MARKER.search(git("show", f"{sha}:index.html")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()

    try:
        rows = publishes(a.limit)
    except Exception as e:  # noqa: BLE001
        print(f"BAD git ({e})")
        return 2

    if not rows:
        # 「publish が 1 件も無い」は SLI-1 の担当。ここで赤にすると同じ事象を二重に鳴らす。
        print("BAD no-publish-commits")
        return 2

    # 1 日に複数回 publish されることがある（遅延して本物が届いた日など）。
    # **その日の最後の publish**＝実際に読者が見た版で日を代表させる。
    by_day: dict[str, dict] = {}
    for r in rows:
        by_day.setdefault(r["ymd"], r)   # rows は新しい順なので最初に来たものが最後の publish

    days = sorted(by_day.keys(), reverse=True)
    try:
        flags = [(d, is_fallback(by_day[d]["sha"])) for d in days]
    except Exception as e:  # noqa: BLE001
        print(f"BAD show ({e})")
        return 2

    consecutive = 0
    for _d, f in flags:
        if not f:
            break
        consecutive += 1

    cutoff = (datetime.now(JST) - timedelta(days=7)).strftime("%Y-%m-%d")
    last7 = sum(1 for d, f in flags if f and d >= cutoff)

    warn = consecutive >= 2 or last7 >= 3
    body = f"consecutive={consecutive} last7={last7} scanned={len(flags)}"

    if a.json:
        print(json.dumps({
            "status": "WARN" if warn else "OK",
            "consecutive": consecutive, "last7": last7, "scanned": len(flags),
            "days": [{"ymd": d, "fallback": f} for d, f in flags],
        }, ensure_ascii=False))
    else:
        print(("WARN " if warn else "OK ") + body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
