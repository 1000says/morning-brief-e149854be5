#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLI-4 の Grok 版の判定（DEC-2026-10-12-sli4-grok）。

使い方: python3 grok-check.py index.html <ブリーフ日 YYYY-MM-DD> <期待カレンダー数>
出力（1 行）:
  NOTGROK ext=0            … Grok 版ではない（呼び出し側が従来の brief-sources 検査を続ける）
  OK date=… cal=… ok=… ev=… me=… yu=… both=…
  WARN <理由,…> | <値>      … 配信は続けてよいが無音にしない（部分失敗・共有予定の数の不一致・予定 0 件）
  BAD <理由,…> | <値>       … FAIL（テンプレート逸脱・日付ずれ・件数の増減・許可外の要素）

なぜ要るか:
  Grok 版は固定テンプレートを埋めるだけで、旧 SLI-4 の前提（tlx の予定 JSON・Cowork の印）を持たない。
  「brief-mode=grok なら検査を飛ばす」形にすると、grok の印 1 語で SLI-4 を素通りできる（G2 P0）。
  そこで Grok 版にも決定論の契約を置く: 構造の印・日付＝ブリーフ日・タグ/属性/クラスの許可リスト・
  レーンの予定数の上限・brief-sources（件数）。外部参照の禁止は**全モード**に掛ける。

出力に外から来た文字列をそのまま載せない（理由は固定語・タグ名などは [a-z0-9-] に削る）。
"""
import hashlib
import json
import re
import sys
from html.parser import HTMLParser

EV_MAX = 20  # 1 レーンの予定の上限（実測は最大 6 件/日。超えたら範囲が広がった疑い）

ALLOWED_TAGS = {
    "html", "head", "meta", "title", "style", "script", "body", "div", "header", "footer",
    "section", "h1", "h2", "p", "small", "b", "span", "ol", "ul", "li",
}
ALLOWED_ATTRS = {"charset", "class", "content", "id", "name", "lang", "style", "type"}
# テンプレート・指示・実出力（2026-10-11）に現れるクラスの和。増やすときはテンプレートと同時に。
ALLOWED_CLASSES = {
    "allday", "card", "focus", "cell", "chip", "me", "yu", "both", "count", "ev", "long", "short",
    "grid", "hours", "kicker", "lane", "lane-name", "lanes-head", "lbl", "legend", "list",
    "tomorrow", "nm", "none", "page", "tag", "due", "over", "who", "empty", "sub",
}
# テンプレートの <style> 本体の sha256（改行は LF にそろえる）。テンプレートの CSS を変えたらここも同時に直す。
STYLE_SHA256 = {"3c829fc4a8c77ba47bcd4247ca18c86c532c6f906eb68bd6c534590f2b56da2d"}  # 2026-10-10 版
ALLOWED_META_NAMES = {"viewport", "color-scheme", "brief-mode", "brief-sources"}
STYLE_ATTR_RE = re.compile(r"^\s*(--[a-z]+\s*:\s*-?[0-9.]+\s*;?\s*)+$")
# CSS・属性値に出てはいけない外部参照・実行の形（全モード共通）
EXT_RE = re.compile(r"url\s*\(|@import|@font-face|expression\s*\(|javascript:|https?://|(?<![:\w])//[a-z0-9]",
                    re.I)


def safe(s):
    return re.sub(r"[^a-z0-9-]", "", str(s).lower())[:20] or "?"


class Walker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bad = set()
        self.metas = []          # (name, content)
        self.scripts = []        # attrs dict
        self.tlx_text = None
        self.styles = []
        self.stack = []          # (tag, lane or None)
        self.lane_counts = {}    # 'me'/'yu' -> {'ev':n, 'both':n}
        self.lanes = []
        self.ids = {}
        self.classes = {}
        self._in_tlx = False
        self._in_style = False
        self._in_body = False
        self._buf = []

    def _lane(self):
        for _, ln in reversed(self.stack):
            if ln:
                return ln
        return None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag not in ALLOWED_TAGS:
            self.bad.add("tag:" + safe(tag))
        for k in a:
            if k not in ALLOWED_ATTRS:
                self.bad.add("attr:" + safe(k))
        for v in a.values():
            if EXT_RE.search(v):
                self.bad.add("ext-attr")
        if "style" in a and not STYLE_ATTR_RE.match(a["style"]):
            self.bad.add("style-attr")
        cls = a.get("class", "").split()
        for c in cls:
            if c not in ALLOWED_CLASSES:
                self.bad.add("class:" + safe(c))
        joined = " ".join(cls)
        self.classes[joined] = self.classes.get(joined, 0) + 1
        if "id" in a:
            self.ids[a["id"]] = self.ids.get(a["id"], 0) + 1
        lane = None
        if tag == "div" and cls[:1] == ["lane"] and len(cls) == 2 and cls[1] in ("me", "yu"):
            lane = cls[1]
            self.lanes.append(lane)
            self.lane_counts.setdefault(lane, {"ev": 0, "both": 0})
        cur = self._lane()
        if cur and "ev" in cls:
            self.lane_counts[cur]["ev"] += 1
            if "both" in cls:
                self.lane_counts[cur]["both"] += 1
        if tag == "body":
            self._in_body = True
        if tag == "meta":
            if self._in_body:
                self.bad.add("meta-in-body")
            if "charset" not in a:
                nm = a.get("name", "")
                if nm not in ALLOWED_META_NAMES:
                    self.bad.add("meta:" + safe(nm))
                self.metas.append((nm, a.get("content", "")))
        if tag == "script":
            self.scripts.append(a)
            if a.get("id") == "tlx-data":
                self._in_tlx = True
                self._buf = []
        if tag == "style":
            self._in_style = True
            self._buf = []
        if tag not in ("meta",):
            self.stack.append((tag, lane))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "script" and self._in_tlx:
            self.tlx_text = "".join(self._buf)
            self._in_tlx = False
        if tag == "style" and self._in_style:
            self.styles.append("".join(self._buf))
            self._in_style = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_tlx or self._in_style:
            self._buf.append(data)


def mode_of(html):
    """brief-mode の値を属性順に依らず読む（複数あれば 'multi'）。"""
    vals = []
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if re.search(r"""name\s*=\s*["']brief-mode["']""", tag, re.I):
            m = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
            vals.append(m.group(1).strip().lower() if m else "")
    if len(vals) > 1:
        return "multi"
    return vals[0] if vals else ""


def parse_sources(content):
    out = {}
    for k in ("cal", "ok", "ev"):
        m = re.search(r"\b" + k + r"=([^;\s]*)", content)
        out[k] = m.group(1) if m else None
    return out


def main(argv):
    if len(argv) < 4:
        print("BAD usage")
        return 0
    path, b_ymd, expect = argv[1], argv[2].strip(), argv[3].strip()
    try:
        html = open(path, encoding="utf-8").read()
    except Exception:
        print("BAD unreadable")
        return 0
    nocomment = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    mode = mode_of(nocomment)

    # 全モード共通: CSS の外部参照・meta refresh
    ext = 0
    for css in re.findall(r"<style\b[^>]*>(.*?)</style>", nocomment, re.S | re.I):
        if EXT_RE.search(css):
            ext += 1
    if re.search(r"""http-equiv\s*=\s*["']?refresh""", nocomment, re.I):
        ext += 1
    if re.search(r"""\s(?:src|href|srcset|action|formaction)\s*=\s*["']?\s*(?:https?:|//|data:|javascript:)""",
                 nocomment, re.I):
        ext += 1

    if mode != "grok" and mode != "multi":
        print(("BAD ext | ext=%d" % ext) if ext else "NOTGROK ext=0")
        return 0

    bad, warn = [], []
    if mode == "multi":
        bad.append("mode-multi")
    if ext:
        bad.append("ext")
    w = Walker()
    try:
        w.feed(nocomment)
        w.close()
    except Exception:
        bad.append("parse")
    bad.extend(sorted(w.bad))

    # 構造の印（テンプレート準拠）
    if w.ids.get("tlx-data", 0) != 1:
        bad.append("tlx-data")
    if w.classes.get("lanes-head", 0) != 1:
        bad.append("lanes-head")
    if sorted(w.lanes) != ["me", "yu"]:
        bad.append("lanes")
    # script は tlx-data の JSON 1 本だけ
    if len(w.scripts) != 1 or w.scripts[0].get("id") != "tlx-data" or \
            w.scripts[0].get("type", "").lower() != "application/json":
        bad.append("script")

    # <style> はテンプレートと 1 文字も違わない（見た目・非表示の仕込みを差し替えさせない）
    if len(w.styles) != 1 or hashlib.sha256(w.styles[0].replace("\r\n", "\n").encode("utf-8")).hexdigest() not in STYLE_SHA256:
        bad.append("style")

    # 日付＝ブリーフ日
    date = ""
    try:
        date = str(json.loads(w.tlx_text or "").get("date", ""))
    except Exception:
        bad.append("tlx-json")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        bad.append("date")
    elif not b_ymd:
        bad.append("no-brief-date")
    elif date != b_ymd:
        bad.append("date-drift")

    # 件数（brief-sources）。Grok 版でも必須＝指示の喪失と範囲の拡大を自己申告でも拾う
    src = [c for n, c in w.metas if n == "brief-sources"]
    cal = ok = evn = None
    if len(src) != 1:
        bad.append("sources" if not src else "sources-multi")
    else:
        p = parse_sources(src[0])
        if not all(p[k] is not None and p[k].isdigit() for k in ("cal", "ok", "ev")):
            bad.append("sources-format")
        else:
            cal, ok, evn = int(p["cal"]), int(p["ok"]), int(p["ev"])
            if not expect.isdigit():
                bad.append("expect")
            elif cal < int(expect):
                bad.append("cal-shrink")
            elif cal > int(expect):
                bad.append("cal-grow")
            elif ok < cal:
                warn.append("partial")
            elif ok > cal:
                bad.append("ok-gt-cal")

    me = w.lane_counts.get("me", {"ev": 0, "both": 0})
    yu = w.lane_counts.get("yu", {"ev": 0, "both": 0})
    if me["ev"] > EV_MAX or yu["ev"] > EV_MAX:
        bad.append("ev-max")
    if me["both"] != yu["both"]:
        warn.append("both-mismatch")
    if me["ev"] + yu["ev"] == 0:
        warn.append("lanes-empty")

    vals = "date=%s cal=%s ok=%s ev=%s me=%d yu=%d both=%d" % (
        date or "-", cal if cal is not None else "-", ok if ok is not None else "-",
        evn if evn is not None else "-", me["ev"], yu["ev"], me["both"])
    if bad:
        print("BAD %s | %s" % (",".join(dict.fromkeys(bad)), vals))
    elif warn:
        print("WARN %s | %s" % (",".join(warn), vals))
    else:
        print("OK " + vals)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
