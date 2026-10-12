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
})();
