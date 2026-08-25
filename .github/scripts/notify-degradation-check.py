#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLI-6: `notify-state.json` を読み、LINE 通知の**縮退**を判定する（MB-040）。

中継は縮退の理由を `notify-state.json` に**正直に書いて配信 repo へ push している**。
それでも 2026-08-25 の `subset-miss` は誰にも届かなかった——`staleness.yml` の「LINE 形式」行が
`::warning::` 止まりで、**job が緑のまま**だったからである（記録はあるが検出チャネルが死んでいる＝
CE-04 gate liveness）。本判定器はそこを **fail** へ昇格させるために置く。

判定ロジックは workflow の中ではなく**ここ**にある（ローカルでも同じコマンドで再現でき、
`relay/test/notify-degradation.test.js` が子プロセスで検査できる）。

## ローカル日次ゲート（`scripts/check_notify_degradation.py`）との関係（G3 SHOULD-2）

**2 実装は別契約**である。判定表が違うのは移植漏れではなく分担の結果:

| | 本判定器（配信 repo の CI） | ローカル日次ゲート |
|---|---|---|
| 入力 | ワークツリーのファイル（取得は無い） | 公開 raw URL（取得が失敗しうる） |
| `ymd` の鮮度 | **見ない**——`staleness.yml` の **SLI-3** が同じ repo で毎日見ており、
  ここでも見ると同じ事象で 2 本鳴る（アラート疲れ） | 見る（ローカルには SLI-3 が無い） |
| `enabled=false` | 無条件 SKIP（同上・SLI-3 が「更新が止まった」を塞ぐ） | 3 日床つき SKIP |
| 取得不能 | 概念として無い | 404/410 は NG・その他は 3 日床つき SKIP |

**この分担を変えるときは両方の docstring を同時に直す**（片側更新の禁止＝CE-05）。

使い方: python3 .github/scripts/notify-degradation-check.py notify-state.json [--expect-format flex]

標準出力（1 行・staleness.yml が case で分岐する）:
  MISSING              … notify-state.json が無い（MB-014 未導入）
  BAD <理由>           … JSON が読めない／オブジェクトでない（state を書く主体が壊れた疑い）
  SKIP disabled        … 通知が無効（enabled=false）。鮮度は SLI-3 が別途見る
  SKIP no-format       … format 未記録（MB-025 未配備の古い state）
  NG degraded <reason> … 縮退している（subset-miss / guard / too-large / no-history 等）
  NG format <fmt>      … 形式が期待と違う（reason が空のまま text へ落ちた日）
  NG send-failed <code>… 送信自体が失敗（ok=false）
  OK <format>          … 正常

終了コードは常に 0（判定は呼び出し側が行う＝判定器の実行失敗と判定結果を混同しない）。
"""
import json
import os
import sys

DEFAULT_EXPECT_FORMAT = "flex"


def judge(state, expect_format=DEFAULT_EXPECT_FORMAT):
    """`(line,)` の 1 行を返す。**この関数が唯一の判定**（workflow 側に条件式を置かない）。"""
    if not isinstance(state, dict):
        return "BAD not-an-object"
    if state.get("enabled") is not True:
        # 無効時の鮮度は SLI-3 が既に見ている。ここで二重に鳴らさない（アラート疲れ）。
        return "SKIP disabled"
    if state.get("ok") is not True:
        return "NG send-failed %s" % (state.get("code"),)
    rsn = state.get("reason")
    if isinstance(rsn, str) and rsn.strip():
        # **縮退の一次シグナル**。format が flex のままでも reason があれば鳴らす。
        return "NG degraded %s" % rsn.strip()
    if state.get("degraded") is True:
        return "NG degraded link-only"
    fmt = state.get("format")
    if not isinstance(fmt, str) or not fmt:
        # MB-025 以前の state（format を書かない中継）。**無音にはしない**が fail にもしない。
        return "SKIP no-format"
    if fmt != expect_format:
        # reason が空でも形式だけ落ちている日がある。format 検査を落とすとその日が素通りする。
        return "NG format %s" % fmt
    return "OK %s" % fmt


def main(argv):
    path = argv[1] if len(argv) > 1 else "notify-state.json"
    expect = DEFAULT_EXPECT_FORMAT
    if "--expect-format" in argv:
        expect = argv[argv.index("--expect-format") + 1]
    if not os.path.exists(path):
        print("MISSING")
        return 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            state = json.load(f)
    except OSError:
        print("BAD read-error")
        return 0
    except ValueError:
        print("BAD json-parse")
        return 0
    print(judge(state, expect))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
