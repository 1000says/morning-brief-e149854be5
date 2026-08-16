#!/usr/bin/env node
// privacy-guard（CI 側・deploy 前段）
//
// !!! このファイルの guardPatterns_() は relay/src/コード.js と **文字列として同一** に保つこと（CE-05）。
//     relay/test/invariants.test.js の INV-C1/C2/C3 が両者を突合し、片側だけ変更した瞬間に FAIL する。
//
// なぜ grep ではなく node なのか（PLAN-MB-004 v1.1.0 §2.2）:
//   パターンに後読み `(?<!…)` を使う（phone_intl）。POSIX ERE には無いため、
//   grep のままでは中継側とパターンを同一にできない。エンジンを揃えることで
//   「2 つの実装を同期させ続ける」のをやめ、構造的に一致させる。
//
// !!! fail-open の防止（実測された経路）:
//   fs.readFileSync の encoding を落とす／latin1 にすると **address_words（日本語）が例外も出さずに無一致**
//   になり、住所を含む index.html が「guard passed」で通過する。
//   しかも **in-memory の自己テストでは検出できない**ため、自己テストは一時ファイルを実際に読ませる。
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const PATTERN_COUNT = 9;   // リテラルでピン。抽出・定義が壊れたら 0 件ではなく即 FAIL させる

function guardPatterns_() {
  return [
    { name: 'email',           re: /[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/ },
    { name: 'phone_intl',      re: /(?<![0-9.])\+[0-9]{1,3}[-\s][0-9]{1,4}[-\s]?[0-9]{1,4}[-\s]?[0-9]{3,4}(?![0-9])/ },
    { name: 'phone_hyphen',    re: /0[0-9]{1,4}[-\u30FC\uFF70\u2012-\u2015][0-9]{1,4}[-\u30FC\uFF70\u2012-\u2015][0-9]{4}/ },
    { name: 'phone_plain',     re: /0[0-9]{9,10}(?![0-9])/ },
    { name: 'tracking_number', re: /[0-9]{4}-[0-9]{4}-[0-9]{4}/ },
    { name: 'geo_coords',      re: /[0-9]{1,3}\.[0-9]{4,},\s?[0-9]{1,3}\.[0-9]{4,}/ },
    { name: 'map_url',         re: /(maps\.google|goo\.gl\/maps|google\.[a-z.]+\/maps)/i },
    { name: 'address_words',   re: /(丁目|番地|号室|マンション|アパート|〒|\uFF8F\uFF9D\uFF7C\uFF6E\uFF9D|\uFF71\uFF8A\uFF9F\uFF70\uFF84)/ },
    { name: 'digit_run',       re: /[0-9]{3}-?[0-9]{4}/ }
  ];
}

/**
 * guard へ渡す前の正規化（MB-020）。
 * !!! relay/src/コード.js と **文字列として同一** に保つこと（CE-05）。
 */
var GUARD_ENTITIES_ = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', middot: '\u00b7',
  commat: '@', period: '.', num: '#', sol: '/', lowbar: '_', plus: '+', colon: ':',
  hyphen: '-', dash: '-', minus: '-', ndash: '\u2013', mdash: '\u2014',
  // 不可視文字の**名前付き**参照（MB-021）。同じ文字の数値形 `&#8203;` は既に塞いでいたのに
  // 名前付き `&ZeroWidthSpace;` だけ素通りしていた＝同一文字の 3 符号化のうち 1 つだけ穴という
  // 内部不整合だった。ここで文字へ戻せば normalizeForGuard_ (2) の不可視除去がそのまま消す
  // （新しい経路を作らない）。HTML5 の zero-width/invisible 名前付き参照の閉じた集合。
  shy: '\u00AD', SHY: '\u00AD',
  ZeroWidthSpace: '\u200B', NegativeVeryThinSpace: '\u200B', NegativeThinSpace: '\u200B',
  NegativeMediumSpace: '\u200B', NegativeThickSpace: '\u200B',
  zwnj: '\u200C', zwj: '\u200D', NoBreak: '\u2060',
  ApplyFunction: '\u2061', af: '\u2061', InvisibleTimes: '\u2062', it: '\u2062',
  InvisibleComma: '\u2063', ic: '\u2063'
};

function decodeEntitiesOnce_(s) {
  return String(s).replace(/&(#[xX][0-9A-Fa-f]+|#[0-9]+|[A-Za-z][A-Za-z0-9]{1,30});?/g, function (m, b) {
    if (b.charAt(0) === '#') {
      var hex = b.charAt(1) === 'x' || b.charAt(1) === 'X';
      var cp = hex ? parseInt(b.slice(2), 16) : parseInt(b.slice(1), 10);
      if (!isFinite(cp) || cp < 1 || cp > 0x10FFFF) return m;
      if (cp <= 0xFFFF) return String.fromCharCode(cp);
      try { return String.fromCodePoint(cp); } catch (e) { return m; }
    }
    return Object.prototype.hasOwnProperty.call(GUARD_ENTITIES_, b) ? GUARD_ENTITIES_[b] : m;
  });
}

function normalizeForGuard_(s) {
  var t = String(s == null ? '' : s);
  // (1) 実体参照の有界不動点。1 パスだと `&amp;#64;` が素通りするが、Pages が描画する文字列は
  //     `&#64;` で読者はアドレスを完全に復元できる＝それは露出である。
  for (var i = 0; i < 4; i++) {
    var d = decodeEntitiesOnce_(t);
    if (d === t) break;
    t = d;
  }
  // (2) 不可視文字。コピペ由来の ZWSP は `taro@exam<ZWSP>ple.co.jp` を素通りさせる。
  t = t.replace(/[\u200B-\u200D\u2060-\u2064\uFEFF\u00AD]/g, '');
  // (3) 全角 ASCII。U+FF0D はここで '-' になる。
  t = t.replace(/[\uFF01-\uFF5E]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); });
  t = t.replace(/\u3000/g, ' ');
  // (4) 残るハイフン類。!!! U+FF0D を足さないこと（(3) と二重になり、片方を壊しても検出できなくなる）。
  //     !!! U+2012-U+2015 を足さないこと（実測: `会計年度 2026-2027` が digit_run で誤爆する）。
  t = t.replace(/[\u2010\u2011\u2212\uFE58\uFE63]/g, '-');
  return t;
}

/**
 * guard 用のタグ除去（MB-020 / G3 MUST-1）。
 * !!! relay/src/コード.js と **文字列として同一** に保つこと（CE-05）。
 */
function stripTagsForGuard_(html) {
  var t = String(html == null ? '' : html);
  t = t.replace(/<(script|style|svg)\b[\s\S]*?<\/\1>/gi, ' ');
  // ブロック要素は**空白へ**。空文字にすると <td>123</td><td>4567</td> が 1234567 へ
  // 連結して digit_run が誤爆する（実測: 表セル・段落跨ぎ・リスト跨ぎの 3 形）。
  t = t.replace(/<\/?(p|div|section|li|tr|td|th|h[1-6]|br|table|thead|tbody|ul|ol|dl|dt|dd|details|summary|blockquote|hr|figure|figcaption|article|header|footer|nav|main|pre)\b[^>]*>/gi, ' ');
  // 残る**インライン**要素は除去する。<span>/<b>/<wbr> で分断された PII は
  // 生バイト列では一致しない（G3 実測: Pages=PASS / LINE=BLOCK の非対称の正体）。
  t = t.replace(/<[^>]+>/g, '');
  return t;
}

/** ファイルを読んで走査する。**encoding を明示すること**（落とすと日本語が無一致になる）。 */
function scanFile(file) {
  const html = fs.readFileSync(file, { encoding: 'utf8' });
  // encoding を落とすと Buffer が返る。黙って進ませない（fail-closed）。
  if (typeof html !== 'string') throw new Error('scanFile: encoding を明示していない（Buffer が返った）');
  // !!! 一致した**中身を返さない**（MB-020）。配信 repo は Public ＝ Actions のログも
  //     run summary も誰でも閲覧でき 90 日残る。guard が止めた PII を guard 自身が
  //     公開ログへ書いていた。位置と長さがあれば復旧はできる。
  // **2 つの表現で判定する**（G3 MUST-1）。raw だけだとタグで分断された PII を、
  // タグ除去だけだと属性内（mailto:/tel:/maps の href）の PII を取り落とす。
  const reps = [
    { where: 'raw', text: normalizeForGuard_(html) },
    { where: 'text', text: normalizeForGuard_(stripTagsForGuard_(html)) },
  ];
  const hits = [];
  for (const p of guardPatterns_()) {
    for (const r of reps) {
      const m = r.text.match(p.re);
      if (m) { hits.push({ name: p.name, where: r.where, index: m.index, length: String(m[0]).length }); break; }
    }
  }
  return hits;
}

/**
 * 自己テスト（fail-closed）。
 * **一時ファイルへ書いて実際の scanFile() を通す。** in-memory 判定だと encoding のバグを
 * 原理的に観測できないため（守りたい機構が無言で死ぬ）。
 */
function selfTest() {
  const problems = [];
  if (guardPatterns_().length !== PATTERN_COUNT) {
    problems.push('pattern count = ' + guardPatterns_().length + ' (expected ' + PATTERN_COUNT + ')');
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-selftest-'));
  try {
    // 日本語を必ず含める（encoding 落としの検出に不可欠）
    const positives = [
      ['address_words',   '<html><body>中央区1丁目のマンションにて</body></html>'],
      ['email',           '<html><body>連絡は a.b@example.co.jp まで</body></html>'],
      ['digit_run',       '<html><body>郵便番号 1234567</body></html>'],
      ['phone_intl',      '<html><body>国際 +81-3-1234-5678</body></html>'],
      ['geo_coords',      '<html><body>座標 35.6895,139.6917</body></html>'],
      // 正規化を通らないと素通りする形（MB-020）。**実 I/O 経由で確かめる**ので、
      // scanFile から normalizeForGuard_ の呼び出しを外すと selfTest ごと落ちる。
      ['phone_hyphen',    '<html><body>電話 ０３－１２３４－５６７８</body></html>'],
      ['email',           '<html><body>連絡は taro&#64;example.co.jp</body></html>'],
      ['address_words',   '<html><body>受取 ｻﾝﾌﾟﾙﾏﾝｼｮﾝ 3F</body></html>'],
    ];
    // !!! 床（CE-04b ⑧⑨）: positives を空にすると encoding fail-open（latin1 化）まで
    //     不可視になり、日本語住所入り HTML が `guard passed` で exit 0 する（実測された連鎖）。
    if (positives.length < 8) problems.push('self-test fixtures shrunk: ' + positives.length);
    // !!! 総数の床は天井にならない（G3-01）。正規化を**弁別できる**フィクスチャだけを別に数える。
    //     この 3 件が消えると、公開側 guard が生バイト走査へ戻っても selfTest が緑のままになる。
    const NORM_DEPENDENT = ['０３－', 'taro&#64;', 'ｻﾝﾌﾟﾙﾏﾝｼｮﾝ'];
    const normFixtures = positives.filter(([, body]) => NORM_DEPENDENT.some(k => body.indexOf(k) !== -1));
    if (normFixtures.length < 3) {
      problems.push('normalization-discriminating fixtures shrunk: ' + normFixtures.length + ' (expected >= 3)');
    }
    for (const [expected, body] of positives) {
      const f = path.join(dir, 'pos-' + expected + '.html');
      fs.writeFileSync(f, body, { encoding: 'utf8' });
      const hits = scanFile(f).map(h => h.name);
      if (!hits.includes(expected)) {
        problems.push('self-test: ' + expected + ' を検出できなかった (hits=' + JSON.stringify(hits) + ')');
      }
    }
    // 陰性（guard が恒真でないこと）。正規化で**過剰に畳むと落ちる**形を含める（MB-020）:
    // ハイフン集合に U+2012-U+2015 を足すと年度・金額レンジが digit_run で誤爆する。
    const negatives = [
      '<html><body>今日の予定は3件です。天気は晴れ。</body></html>',
      '<html><body>会計年度 2026–2027 の予定</body></html>',
      '<html><body>費用は 100–2000 の範囲</body></html>',
      '<html><body>本日の要点 ①②③④⑤⑥⑦ を確認</body></html>',
    ];
    if (negatives.length < 4) problems.push('self-test negatives shrunk: ' + negatives.length);
    negatives.forEach((body, i) => {
      const negFile = path.join(dir, 'neg-' + i + '.html');
      fs.writeFileSync(negFile, body, { encoding: 'utf8' });
      const negHits = scanFile(negFile);
      if (negHits.length) problems.push('self-test: 無害な入力で発火した #' + i + ' (' + JSON.stringify(negHits) + ')');
    });
  } finally {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* noop */ }
  }
  return problems;
}

function main() {
  const file = process.argv[2] || 'index.html';
  const summary = process.env.GITHUB_STEP_SUMMARY;
  const write = t => { if (summary) { try { fs.appendFileSync(summary, t + '\n'); } catch (_) { /* noop */ } } };

  // 1) 自己テストが通らなければ **走査せずに落とす**（guard が死んでいるのに通すことを防ぐ）
  const problems = selfTest();
  if (problems.length) {
    problems.forEach(p => console.log('::error::privacy-guard self-test FAILED: ' + p));
    write('### 🔴 privacy-guard の自己テストが失敗しました（guard が機能していません）');
    process.exit(1);
  }

  if (!fs.existsSync(file)) {
    console.log('::error::' + file + ' not found');
    process.exit(1);
  }

  // 2) サイズ上限（中継の MAX_BYTES と揃える）。email の後退が O(n^2) 的に劣化するため、
  //    巨大な入力を黙って走査しない（露出ではなく可用性の問題）。
  const bytes = fs.statSync(file).size;
  if (bytes > 512 * 1024) {
    console.log('::error::' + file + ' too large: ' + bytes + ' B (limit 524288)');
    process.exit(1);
  }

  // 3) 本走査
  const hits = scanFile(file);
  if (hits.length) {
    hits.forEach(h => console.log('::error::Forbidden pattern detected in ' + file + ': ' + h.name +
      ' (' + h.where + ' の正規化後 offset ' + h.index + ', length ' + h.length + ' — 内容は公開ログへ出さない)'));
    write('### 🔒 Privacy guard FAILED — deployment blocked');
    write('');
    hits.forEach(h => write('- `' + h.name + '` — ' + h.where + ' の正規化後 offset ' + h.index + ' / length ' + h.length));
    console.log('::error::Privacy guard FAILED — deployment blocked. Fix ' + file + ' and re-push.');
    process.exit(1);
  }
  console.log('Privacy guard passed (' + PATTERN_COUNT + ' patterns, self-test OK).');
  write('### ✅ Privacy guard passed（' + PATTERN_COUNT + ' patterns / 自己テスト込み）');
}

if (require.main === module) main();
module.exports = { guardPatterns_, scanFile, selfTest, PATTERN_COUNT, normalizeForGuard_, decodeEntitiesOnce_, stripTagsForGuard_, GUARD_ENTITIES_ };
