/* モーニングブリーフの共通の動き（MB-117・DEC-2026-10-12-brief-archive）。
   - 頁の日付が今日（JST）でなければ帯と「最新を読み込む」を出す（自動では再読込しない）
   - ヘッダに「前の日／次の日」（archive/index.json から）と「更新」を足す
   守ること: DOM は createElement と textContent だけで作る（innerHTML を使わない）。日付は形を確かめてから URL に使う。
   7 桁以上の連続した数字を書かない（公開面の guard の digit_run に当たる）。外部参照なし。 */
(function () {
  "use strict";
  var doc = document;
  var YMD = /^\d{4}-\d{2}-\d{2}$/;
  var WD = "日月火水木金土";

  function two(n) { return (n < 10 ? "0" : "") + n; }
  function todayJst() {
    var d = new Date(Date.now() + 9 * 36e5);
    return d.getUTCFullYear() + "-" + two(d.getUTCMonth() + 1) + "-" + two(d.getUTCDate());
  }
  function label(ymd) {
    var p = ymd.split("-");
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return (+p[1]) + "月" + (+p[2]) + "日（" + WD.charAt(d.getUTCDay()) + "）";
  }
  function pageDate() {
    var el = doc.getElementById("tlx-data");
    if (!el) return "";
    try {
      var v = JSON.parse(el.textContent || "").date;
      return typeof v === "string" && YMD.test(v) ? v : "";
    } catch (e) { return ""; }
  }

  var inArchive = /\/archive\/[^\/]*$/.test(location.pathname);
  var root = inArchive ? "../" : "./";
  var pd = pageDate();

  function reloadLatest() { location.replace(root + "?t=" + Date.now()); }

  function navBox() {
    var header = doc.querySelector("header");
    if (!header) return null;
    var nav = header.querySelector(".nav");
    if (!nav) {
      nav = doc.createElement("nav");
      nav.className = "nav";
      header.appendChild(nav);
    }
    nav.setAttribute("aria-label", "ブリーフの移動");
    return nav;
  }

  function link(cls, href, text) {
    var a = doc.createElement("a");
    a.className = cls;
    a.href = href;
    a.textContent = text;
    return a;
  }

  var nav = navBox();
  // 過去頁では「更新」を出さない（「最新」へのリンクと重なる・UIUX レビュー）
  if (nav && !inArchive) {
    var btn = doc.createElement("button");
    btn.type = "button";
    btn.className = "nav-reload";
    btn.textContent = "更新";
    btn.addEventListener("click", reloadLatest);
    nav.appendChild(btn);
  }

  // 本日分でないときの帯（過去頁はビルドが帯を入れるので出さない）
  if (!inArchive && pd && pd !== todayJst()) {
    var header = doc.querySelector("header");
    var bar = doc.createElement("div");
    bar.className = "stale";
    bar.setAttribute("role", "status");
    var msg = doc.createElement("span");
    msg.textContent = label(pd) + "の分を表示しています";
    var b2 = doc.createElement("button");
    b2.type = "button";
    b2.textContent = "今日の分を読み込む";
    b2.addEventListener("click", reloadLatest);
    bar.appendChild(msg);
    bar.appendChild(b2);
    if (header && header.parentNode) header.parentNode.insertBefore(bar, header.nextSibling);
  }

  // 前の日／次の日（一覧が読めたときだけ）
  if (nav && pd && window.fetch) {
    fetch(root + "archive/index.json", { cache: "no-cache" })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (list) {
        if (!Array.isArray(list)) return;
        var dates = list
          .map(function (x) { return x && typeof x.date === "string" && YMD.test(x.date) ? x.date : ""; })
          .filter(Boolean)
          .sort();
        var prev = "", next = "";
        for (var i = 0; i < dates.length; i++) {
          if (dates[i] < pd) prev = dates[i];
          if (dates[i] > pd && !next) next = dates[i];
        }
        var dir = inArchive ? "./" : "archive/";
        var first = nav.firstChild;
        if (prev) nav.insertBefore(link("nav-prev", dir + prev + ".html", "前の日"), first);
        if (inArchive) {
          var a = next ? link("nav-next", dir + next + ".html", "次の日") : link("nav-next", root, "最新");
          nav.appendChild(a);
        }
      })
      .catch(function () { /* 一覧が無くても頁は使える */ });
  }
  // 予定の旗（MB-121）: 列が狭くて名前が切れた予定は、**その予定の箱そのものを横に伸ばして**名前と時刻を出す
  // （同じ位置・同じ高さ・同じ色のまま、空いている側へ必要な長さだけ。タップしなくても全予定が読める・線は使わない）。
  // 伸ばす向きは右 → 左。他の予定の手前で止まる。名前と時刻 → 名前だけの順で入る形を探し、それでも入らなければ
  // 使える幅いっぱいまで伸ばして名前の末尾だけを「…」にする。上下には伸ばさない（別の時刻に見えるため）。
  // 外側の列で伸ばせない予定は、同じ時刻の隣の列の予定と左右を入れ替えてから伸ばす（時刻は変わらない）。
  // 画面の幅が変わったら置き直す。この JS がある頁では :hover で予定を広げる CSS を止める（html.ev-js）
  var grid = doc.querySelector(".grid");
  if (grid && grid.querySelector(".lane .ev")) {
    doc.documentElement.classList.add("ev-js");
    var cssNum = function (e, name, dflt) {
      var v = parseFloat(getComputedStyle(e).getPropertyValue(name));
      return isNaN(v) ? dflt : v;
    };
    var isCut = function (e) {
      var a = e.querySelector(".nm");
      return !!a && a.scrollWidth > a.clientWidth + 1;
    };
    var layoutFlags = function () {
      var old = grid.querySelectorAll(".ldr");
      for (var i = 0; i < old.length; i++) old[i].parentNode.removeChild(old[i]);
      var wr = grid.querySelectorAll(".ev.wrap-t, .ev.stub");
      for (var w0 = 0; w0 < wr.length; w0++) wr[w0].classList.remove("wrap-t", "stub");
      var lanes = grid.querySelectorAll(".lane");
      if (!lanes.length) return;
      // 外側（左のレーンの左の列・右のレーンの右の列）で名前が切れ、同じ時刻の隣の列の予定は切れていないなら、列を入れ替える
      for (var sl = 0; sl < lanes.length; sl++) {
        var se = lanes[sl].querySelectorAll(".ev");
        for (var si = 0; si < se.length; si++) {
          var e1 = se[si];
          if (cssNum(e1, "--n", 1) !== 2 || !isCut(e1)) continue;
          var c1 = cssNum(e1, "--c", 0);
          if (c1 !== (sl === 0 ? 0 : 1)) continue;
          var r1 = e1.getBoundingClientRect();
          for (var sj = 0; sj < se.length; sj++) {
            var e2 = se[sj];
            if (e2 === e1 || isCut(e2) || cssNum(e2, "--c", 0) !== 1 - c1) continue;
            var r2 = e2.getBoundingClientRect();
            if (r2.top >= r1.bottom || r2.bottom <= r1.top) continue;
            e1.style.setProperty("--c", String(1 - c1));
            e2.style.setProperty("--c", String(c1));
            break;
          }
        }
      }
      var g = grid.getBoundingClientRect();
      var x0 = lanes[0].getBoundingClientRect().left - g.left;
      var xMax = lanes[lanes.length - 1].getBoundingClientRect().right - g.left;
      var rects = [], targets = [];
      for (var m = 0; m < lanes.length; m++) {
        var evs = lanes[m].querySelectorAll(".ev");
        for (var n = 0; n < evs.length; n++) {
          var ev = evs[n], nm = ev.querySelector(".nm"), tb = ev.querySelector("b");
          // 長い予定で時刻だけ切れているなら、高さに余裕があれば時刻を折り返して全部出す
          if (tb && tb.scrollWidth > tb.clientWidth + 1 && ev.clientHeight >= 56) ev.classList.add("wrap-t");
          var er = ev.getBoundingClientRect();
          rects.push({ ev: ev, l: er.left - g.left, r: er.right - g.left, t: er.top - g.top, b: er.bottom - g.top });
          var nameCut = isCut(ev);
          // 時刻が切れている・箱の外へ隠れている予定も対象（名前は入っているなら、名前と時刻が丸ごと入るときだけ伸ばす）
          var cut = nameCut || (tb && (tb.scrollWidth > tb.clientWidth + 1 || tb.offsetTop >= ev.clientHeight) && ev.clientHeight < 56);
          // 2 人の予定で、もう片方のレーンに同じ予定が全文で出ているなら伸ばさない
          if (cut && ev.classList.contains("both") && nm && lanes.length > 1) {
            var twins = lanes[m === 0 ? 1 : 0].querySelectorAll(".ev.both .nm");
            for (var tw = 0; tw < twins.length; tw++) {
              if (twins[tw].textContent === nm.textContent && twins[tw].scrollWidth <= twins[tw].clientWidth + 1) { cut = false; break; }
            }
          }
          if (cut) targets.push({ ev: ev, lane: m, timeOnly: !nameCut });
        }
      }
      // 高さ [t, b] の帯で、x から右（dir=1）か左（dir=-1）へ、最初に当たる物の手前まで伸ばせる長さ
      var room = function (self, x, t, b, dir) {
        var lim = dir > 0 ? xMax - 3 : x0 + 3;
        for (var q = 0; q < rects.length; q++) {
          var o = rects[q];
          if (o.ev === self || t >= o.b + 1 || b <= o.t - 1) continue;
          if (dir > 0 && o.l >= x - 0.5) lim = Math.min(lim, o.l - 3);
          if (dir < 0 && o.r <= x + 0.5) lim = Math.max(lim, o.r + 3);
        }
        return Math.max(0, dir > 0 ? lim - x : x - lim);
      };
      targets.sort(function (a, b) { return a.ev.getBoundingClientRect().top - b.ev.getBoundingClientRect().top; });
      targets.forEach(function (t) {
        var ev = t.ev, r = ev.getBoundingClientRect();
        var L = r.left - g.left, R = r.right - g.left, T = r.top - g.top, H = r.height, W = r.width;
        var nm = ev.querySelector(".nm"), tm = ev.querySelector("b");
        var flag = doc.createElement("div");
        flag.className = "ldr " + (t.lane === 0 ? "me" : "yu") + (ev.classList.contains("both") ? " both" : "");
        var a = doc.createElement("span");
        a.className = "ldr-nm";
        a.textContent = nm ? nm.textContent : "";
        var tt = doc.createElement("span");
        tt.className = "ldr-t";
        tt.textContent = tm ? tm.textContent : "";
        flag.appendChild(a);
        flag.appendChild(tt);
        flag.style.left = "0px";
        flag.style.top = T + "px";
        flag.style.height = H + "px";
        flag.style.width = "max-content";
        grid.appendChild(flag);
        var wFull = Math.ceil(flag.getBoundingClientRect().width) + 1;   // 名前＋時刻の 1 行の幅
        tt.style.display = "none";
        var wName = Math.ceil(flag.getBoundingClientRect().width) + 1;   // 名前だけの幅
        tt.style.display = "";
        var er2 = room(ev, R, T, T + H, 1), el2 = room(ev, L, T, T + H, -1);
        if (t.timeOnly) {                              // 時刻を出すためだけなら、自分のレーンの外へは伸ばさない
          var ownR = lanes[t.lane].getBoundingClientRect();
          er2 = Math.min(er2, Math.max(0, ownR.right - g.left - 3 - R));
          el2 = Math.min(el2, Math.max(0, L - (ownR.left - g.left + 3)));
        }
        var put = function (dir, w) {
          w = Math.max(W, Math.min(240, w));
          flag.style.width = w + "px";
          flag.style.left = (dir > 0 ? L : R - w) + "px";
          if (dir < 0) flag.classList.add("to-l");      // 左へ伸びるときは色の帯を元の予定の側（右端）に置く
          ev.classList.add("stub");
          rects.push({ ev: flag, l: dir > 0 ? L : R - w, r: dir > 0 ? L + w : R, t: T, b: T + H });
        };
        var order = [[1, er2], [-1, el2]];
        for (var k1 = 0; k1 < order.length; k1++) { if (W + order[k1][1] >= wFull) return put(order[k1][0], wFull); }
        if (t.timeOnly) { flag.parentNode.removeChild(flag); return; }   // 名前は読めるので、半端には伸ばさない
        for (var k2 = 0; k2 < order.length; k2++) {
          if (W + order[k2][1] >= wName) return put(order[k2][0], Math.min(wFull, W + order[k2][1]));
        }
        var best = er2 >= el2 ? 1 : -1, ext = Math.max(er2, el2);
        if (ext >= 16) {                               // 使える幅いっぱい。文字を少し詰め、それでも入らなければ名前の末尾だけ「…」
          flag.classList.add("tight");
          return put(best, W + ext);
        }
        flag.parentNode.removeChild(flag);            // 伸ばせなければ従来の省略表示のまま
      });
    };
    layoutFlags();
    var lastW = window.innerWidth, timer = 0;
    window.addEventListener("resize", function () {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(layoutFlags, 150);
    });
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(layoutFlags);
  }
})();
