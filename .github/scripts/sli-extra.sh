#!/usr/bin/env bash
# SLI-5（タイムライン契約・MB-029）・SLI-6（LINE 縮退・MB-040）・SLI-7（縮退モード・MB-043）の判定本体。
#
# **なぜ workflow から出したか（D61・2026-08-25 の実障害）**
#   GitHub Actions は `run:` の値**全体を 1 つの式**として扱い、**21,000 バイト**の上限がある
#   （文字数ではなく UTF-8 バイト数。日本語コメントは 1 文字 3 バイトなので実効枠は約 7,000 文字）。
#   2026-08-25 04:46 の push（a4d4499）で SLI-5/6 を `run:` へ inline した結果 23,081 バイトに達し、
#   GitHub が workflow をパースできず **startup_failure**＝cron も dispatch も起動不能になった。
#   YAML 自体は妥当なので `yaml.safe_load` では検出できない。唯一の権威は `gh workflow run` が返す
#     HTTP 422: failed to parse workflow: (Line: 53, Col: 14): Exceeded max expression length 21000
#   再発防止の天井は relay/test/invariants.test.js の INV-C27（run ブロックのバイト数）。
#
# 判定ロジックを workflow に置かない方針（tlx-check.py / notify-degradation-check.py と同じ）に
# 揃えた結果でもある＝ローカルでも同じコマンドで再現でき、テストが子プロセスで検査できる。
#
# 使い方: [TAG=...] [B_YMD=YYYY-MM-DD] bash .github/scripts/sli-extra.sh [sli5|sli6|sli7|all]
#   TAG    … 「【テスト実行・実障害ではない】」等のラベル（staleness.yml が付ける）
#   B_YMD  … SLI-3 が突合した最新ブリーフの日付。空なら SLI-5 の日付ずれ判定はスキップ。
# 終了コード: 0 = fail 無し / 1 = fail あり（呼び出し側が自分の fail へ畳む）。2 以上は本体の異常。
#
# `-e` は付けない。GitHub Actions の既定シェルは `-e` 付きだが、その下では grep の no-match（exit 1）
# ひとつでゲートが**出力を 1 行も出さずに落ちる**（実測 2026-08-17・run 31997349481＝SLI-4 の事故）。
# fail は明示的に積み、終了コードで返す。
set -uo pipefail

TAG="${TAG:-}"
B_YMD="${B_YMD:-}"
: "${GITHUB_STEP_SUMMARY:=/dev/null}"
fail=0

sli5() {
  # ---------- SLI-5: きょうのタイムライン（MB-029） ----------
  # 生成側はテンプレートを**毎朝作り直す**ため、貼り込んだブロックは静かに落ちる／壊れる。
  # 判定は .github/scripts/tlx-check.py（ローカルでも同じコマンドで再現できる）。
  # データ側（ブロック不在・JSON 破損・日付ずれ）は移行期の方針どおり WARN 止まり＝
  # **無音にはしない**（未導入と故障を受信側が区別できるように）。
  # **SLI-6 と同じ形に揃える**（MB-040 G3 MUST-3・2026-08-25）: 判定器の「不在」と
  #   「動かない」を分ける。SLI-5 も同じ穴を踏んでいた——判定器は SLI-6 と**同じ 1 回の
  #   push で配備される**ため、片方だけ fail-closed にすると「配備し忘れ」の検知が
  #   ゲートによってまちまちになる。不在＝赤（ゲートが存在しない）／実行不能＝黄。
  #   データ側の契約違反は従来どおり warn（移行期の方針は据え置き）。
  if [ ! -f .github/scripts/tlx-check.py ]; then
    tlx_out="ABSENT"
  else
    tlx_out="$(python3 .github/scripts/tlx-check.py index.html 2>/dev/null || echo "BAD runner")"
  fi
  echo "SLI-5 $tlx_out"
  case "$tlx_out" in
    ABSENT)
      echo "::error::${TAG}SLI-5 判定器が配備されていない（.github/scripts/tlx-check.py が repo に無い）。ラベル allowlist を強制できる決定論ゲートはここだけで、不在の間は生名・calendarId が公開面へ出ても検知できない。site/.github/scripts/ 一式を配信 repo へ push する。"
      echo "| タイムライン | 判定器 **未配備** | 🔴 ゲート不在 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
    "BAD runner")
      echo "::warning::${TAG}SLI-5 判定器は在るが実行できない（python3 不在・クラッシュを疑う）。"
      echo "| タイムライン | 判定器 実行不能 | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    MISSING*)
      echo "::warning::${TAG}SLI-5 タイムラインのブロックが無い（tlx-canvas 不在）。生成側の指示文から落ちた疑い。"
      echo "| タイムライン | ブロック不在 | 🟡 未導入/欠落 |" >> "$GITHUB_STEP_SUMMARY" ;;
    NOJSON*)
      echo "::warning::${TAG}SLI-5 ブロックはあるがデータ JSON が無い（何も描画されない）。"
      echo "| タイムライン | JSON 不在 | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    BAD*)
      # cal-label 系は「非表示になる」ではない（ブロックは c を無検証で描画する）。受信側が症状を取り違えないよう分けて書く（MB-036 G3 MUST-1・2026-08-25）。
      echo "::warning::${TAG}SLI-5 タイムラインのデータが契約違反（$tlx_out）。json/date/time 系ならブロックは自動的に非表示。cal-label / allday-cal-label は非表示にならず、allowlist 外のラベル（生のカレンダー名・calendarId・実名）が公開面に描画されている疑い＝生成側タスク本文のラベル表12行を確認する（写しは docs/handoff/cowork/COWORK-TASK-NEXT.md）。"
      echo "| タイムライン | データ不正（${tlx_out#BAD }） | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    OK*)
      t_date="$(echo "$tlx_out" | cut -d' ' -f2)"
      t_ev="$(echo "$tlx_out" | cut -d' ' -f3)"
      t_ad="$(echo "$tlx_out" | cut -d' ' -f4)"
      if [ -n "${B_YMD:-}" ] && [ "$t_date" != "$B_YMD" ]; then
        echo "::warning::${TAG}SLI-5 タイムラインの日付 $t_date がブリーフ日 $B_YMD と一致しない（前日分が残った疑い）。"
        echo "| タイムライン | 日付ずれ $t_date≠$B_YMD | 🟡 |" >> "$GITHUB_STEP_SUMMARY"
      else
        echo "| タイムライン | $t_date・予定 $t_ev 件／終日 $t_ad 件 | 🟢 ok |" >> "$GITHUB_STEP_SUMMARY"
      fi ;;
    *)
      echo "::warning::${TAG}SLI-5 判定不能（出力: $tlx_out）。"
      echo "| タイムライン | 判定不能 | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
  esac
}

sli6() {
  # ---------- SLI-6: LINE 縮退の**判定**（MB-040） ----------
  # 上の「LINE 形式」行（MB-025）は `::warning::` 止まりで **job は緑のまま**だった。
  # 2026-08-25 の `subset-miss` はそのため誰にも届かなかった——中継は理由を
  # notify-state.json へ正直に書いて push しているのに、読む人も鳴らす経路も無い
  # （記録はあるが検出チャネルが死んでいる＝CE-04 gate liveness）。ここで fail へ昇格する。
  # 判定は .github/scripts/notify-degradation-check.py（workflow に条件式を置かない＝
  # ローカルでも同じコマンドで再現でき、relay/test/notify-degradation.test.js が検査できる）。
  # **判定器の「不在」と「動かない」を先に分ける**（MB-040 G3 MUST-3・2026-08-25）。
  #   初版は両方を "BAD runner" に潰して warning 止まりにしていたため、
  #   **配備し忘れると永久に緑**（＝ゲートが存在しないのに毎日 🟡 が出るだけ）になった。
  #   実測: 配信 repo に .github/scripts/ が無く、SLI-4/5/6 のいずれも remote に存在しない。
  #   不在＝**このゲートは存在しない**＝赤／在るのに落ちる＝環境要因なので黄（fail-open）。
  if [ ! -f .github/scripts/notify-degradation-check.py ]; then
    nd_out="ABSENT"
  else
    nd_out="$(python3 .github/scripts/notify-degradation-check.py notify-state.json 2>/dev/null || echo 'BAD runner')"
  fi
  echo "SLI-6 $nd_out"
  case "$nd_out" in
    ABSENT)
      echo "::error::${TAG}SLI-6 判定器が配備されていない（.github/scripts/notify-degradation-check.py が repo に無い）。SLI-6 は存在しないのと同じ＝縮退が起きても誰も気づけない。site/.github/scripts/ 一式を配信 repo へ push する。"
      echo "| LINE 縮退 | 判定器 **未配備** | 🔴 ゲート不在 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
    MISSING)
      # **無音にしない**（未導入と故障を受信側が区別できるように）
      echo "| LINE 縮退 | notify-state.json 未導入 | ⚪ |" >> "$GITHUB_STEP_SUMMARY" ;;
    "SKIP "*)
      echo "| LINE 縮退 | 判定対象外（${nd_out#SKIP }） | ⚪ skip |" >> "$GITHUB_STEP_SUMMARY" ;;
    "OK "*)
      echo "| LINE 縮退 | ${nd_out#OK } で配信 | 🟢 ok |" >> "$GITHUB_STEP_SUMMARY" ;;
    "NG "*)
      echo "::error::${TAG}SLI-6 LINE 通知が縮退している（${nd_out#NG }）。history.json の文字列が当日の公開本文へ verbatim で含まれているかを確認する（生成側の contract＝decisions D59・手順は COWORK-TASK-NEXT.md の『verbatim 自己検査』）。ローカル再現: python -X utf8 scripts/check_notify_degradation.py"
      echo "| LINE 縮退 | ${nd_out#NG } | 🔴 縮退 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
    "BAD runner")
      # 判定器は**在るのに動かない**＝python3 不在・クラッシュ等の環境要因。
      # ここは fail-open（毎日赤くしない）。**不在（ABSENT）とは別事象**として扱う。
      echo "::warning::${TAG}SLI-6 判定器は在るが実行できない（python3 不在・クラッシュを疑う）。"
      echo "| LINE 縮退 | 判定器 実行不能 | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    "BAD "*)
      # state が読めない＝**判定できない**。ここは fail-closed にする（state を書く主体が壊れた日と
      # 正常な日を区別できなくなるため。判定器の不在〔上〕とは別事象）。
      echo "::error::${TAG}SLI-6 notify-state.json が読めない（${nd_out#BAD }）。中継の state 書き込みが壊れた疑い。"
      echo "| LINE 縮退 | state 破損（${nd_out#BAD }） | 🔴 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
    *)
      # 契約外の出力＝判定器と workflow の版がずれている。緑にしない。
      echo "::error::${TAG}SLI-6 判定不能（出力: $nd_out）。判定器と workflow の契約がずれている。"
      echo "| LINE 縮退 | 判定不能（$nd_out） | 🔴 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
  esac
}

sli7() {
  # ---------- SLI-7: ローカル縮退版で出た日（MB-043 / M-3） ----------
  # **フォールバックが成功すると SLI-1 は緑に戻る**＝「生成が止まっている」という本来の異常が
  # 隠れる。戻す対象を作らないために、縮退そのものを数える。判定は
  # .github/scripts/fallback-mode-check.py（git 履歴の index.html から片側マーカーを読む）。
  # しきい値: 1 日だけは notice（生成が 1 日落ちるのは起こりうる）。2 日連続 or 直近 7 日で 3 日以上は warning。
  # 判定器の**不在は赤**（SLI-5/6 と同じ形。配備し忘れを緑で通さない）。
  if [ ! -f .github/scripts/fallback-mode-check.py ]; then
    echo "::error::${TAG}SLI-7 判定器が配備されていない（.github/scripts/fallback-mode-check.py が repo に無い）。フォールバックが常態化しても SLI-1 は緑のままで、生成停止が検知できない。site/.github/scripts/ 一式を配信 repo へ push する。"
    echo "| 縮退モード | 判定器 **未配備** | 🔴 ゲート不在 |" >> "$GITHUB_STEP_SUMMARY"
    fail=1
    return
  fi
  fb_out="$(python3 .github/scripts/fallback-mode-check.py 2>/dev/null || echo "BAD runner")"
  echo "SLI-7 $fb_out"
  case "$fb_out" in
    "OK consecutive=0"*)
      echo "| 縮退モード | 直近の publish はすべて通常生成 | 🟢 |" >> "$GITHUB_STEP_SUMMARY" ;;
    OK*)
      # 1 日だけの縮退。鳴らさずに残す（アラート疲れを避ける）が、無音にはしない。
      echo "::notice::${TAG}SLI-7 直近の publish が ローカル縮退版（${fb_out#OK }）。1 日だけなら想定内。"
      echo "| 縮退モード | ${fb_out#OK } | 🟡 1 日 |" >> "$GITHUB_STEP_SUMMARY" ;;
    WARN*)
      echo "::warning::${TAG}SLI-7 縮退が続いている（${fb_out#WARN }）。claude.ai の生成が繰り返し落ちている＝週次上限の常態化を疑う。SLI-1 は緑に見えるが、届いているのは機械生成の縮退版。"
      echo "| 縮退モード | ${fb_out#WARN } | 🟡 常態化 |" >> "$GITHUB_STEP_SUMMARY" ;;
    "BAD no-publish-commits")
      # publish が 1 件も無いのは SLI-1 の担当。ここで二重に鳴らさない。
      echo "::notice::${TAG}SLI-7 publish commit が無く判定できない（SLI-1 側で扱う）。"
      echo "| 縮退モード | publish 無し（SLI-1 参照） | ⚪ |" >> "$GITHUB_STEP_SUMMARY" ;;
    "BAD runner")
      echo "::warning::${TAG}SLI-7 判定器は在るが実行できない（python3 不在・クラッシュを疑う）。"
      echo "| 縮退モード | 判定器 実行不能 | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    BAD*)
      echo "::warning::${TAG}SLI-7 判定できない（${fb_out#BAD }）。git 履歴が浅い（fetch-depth）等を疑う。"
      echo "| 縮退モード | 判定不能（${fb_out#BAD }） | 🟡 |" >> "$GITHUB_STEP_SUMMARY" ;;
    *)
      echo "::error::${TAG}SLI-7 判定不能（出力: $fb_out）。判定器と workflow の契約がずれている。"
      echo "| 縮退モード | 判定不能（$fb_out） | 🔴 |" >> "$GITHUB_STEP_SUMMARY"
      fail=1 ;;
  esac
}

case "${1:-all}" in
  sli5) sli5 ;;
  sli6) sli6 ;;
  sli7) sli7 ;;
  all)  sli5; sli6; sli7 ;;
  *)
    # 契約外の引数＝呼び出し側と本体の版がずれている。黙って何もしないと**ゲートが消える**。
    echo "::error::sli-extra.sh: 不明な引数 '${1}'（sli5|sli6|sli7|all）。workflow と判定本体の契約がずれている。"
    exit 2 ;;
esac
exit "$fail"
