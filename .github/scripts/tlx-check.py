#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLI-5: 公開ページの「きょうのタイムライン」ブロックを検査する（MB-029）。

生成側（Cowork）はテンプレートを毎朝作り直すため、貼り込んだブロックは**静かに落ちる／壊れる**。
SLI-4（brief-sources マーカー）と同型の「無音にしない」検査を置く。

使い方: python3 .github/scripts/tlx-check.py index.html
標準出力（1 行・staleness.yml が case で分岐する）:
  MISSING                     … ブロックが無い（tlx-canvas 不在）
  NOJSON                      … ブロックはあるがデータ JSON が無い
  BAD <理由>                  … JSON が壊れている／契約違反（描画されない・誤表示になる）
                                 うち `cal-label` / `allday-cal-label` は **公開安全**の違反
                                 （allowlist 外のラベル＝生のカレンダー名・calendarId・実名が
                                 公開面に描画されている疑い。ブロック側は無検証なので描画される）
  OK <date> <events> <allday> … 正常
終了コードは常に 0（判定は呼び出し側が行う＝ジョブを落とさない）。
"""
import json
import re
import sys

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# 帰属カレンダーラベル `c` の allowlist（PLAN-MB-036 §2.3・decisions D58）。
# !!! ここが **唯一の機械防御**である。ブロック（timeline-block.html）は `cl.textContent=label` で
#     無検証に描画し、guard.js はメール書式しか止めず、しかも発火は push の**後**（露出は防げない）。
#     生成側（claude.ai）の指示文は「お願い」でしかないため、allowlist 外が来たら**ここで鳴らす**。
# 生成側の 12 行表のうち `c` に書いてよいのは 10 語だけ:
#   1. my予定(primary) … `c` に書かない（**省略＝my予定** の意味・M3）
#   7. Todoist         … 表示しない
# よって「省略」または下の 10 語、それ以外は fail-closed で NG（未知は通さない）。
CAL_LABELS = frozenset([
    "ファミリー", "家族(1)", "家族(2)", "子の予定", "祝日",
    "England", "Japan", "Spain", "Manchester City", "Barcelona",
])


def bad_cal(v):
    """ラベルが契約違反なら True。

    「省略」の判定は **描画の意味論に合わせる**（欠落と空文字はどちらもラベルが出ない＝同値）。
    それ以外は str かつ allowlist 内であることを要求する（`c` が数値・辞書・リストなら NG）。
    """
    if v is None or v == "":
        return False
    return not (isinstance(v, str) and v in CAL_LABELS)


def main(path):
    try:
        s = open(path, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        print("BAD read-error")
        return 0
    if "tlx-canvas" not in s:
        print("MISSING")
        return 0
    m = re.search(r'id="tlx-data"\s*>\s*(\{.*?\})\s*</script>', s, re.S)
    if not m:
        print("NOJSON")
        return 0
    try:
        d = json.loads(m.group(1))
    except Exception:
        print("BAD json-parse")
        return 0
    date = d.get("date")
    if not isinstance(date, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("BAD date")
        return 0
    ev = d.get("events")
    ad = d.get("allday")
    if not isinstance(ev, list) or not isinstance(ad, list):
        print("BAD shape")
        return 0
    for it in ev:
        if not isinstance(it, dict):
            print("BAD event-type")
            return 0
        s0, e0, t0 = it.get("s"), it.get("e"), it.get("t")
        if not (isinstance(s0, str) and HHMM.match(s0)):
            print("BAD event-start")
            return 0
        if not (isinstance(e0, str) and HHMM.match(e0)):
            print("BAD event-end")
            return 0
        if not isinstance(t0, str) or not t0.strip():
            print("BAD event-title")
            return 0
        if bad_cal(it.get("c")):
            print("BAD cal-label")
            return 0
    for it in ad:
        # 終日は文字列でもよい（`c` を持てない形＝省略と同値）。辞書のときだけラベルを見る。
        if isinstance(it, dict) and bad_cal(it.get("c")):
            print("BAD allday-cal-label")
            return 0
    print("OK %s %d %d" % (date, len(ev), len(ad)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "index.html"))
