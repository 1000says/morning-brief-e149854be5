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
    { name: 'phone_hyphen',    re: /0[0-9]{1,4}-[0-9]{1,4}-[0-9]{4}/ },
    { name: 'phone_plain',     re: /0[0-9]{9,10}(?![0-9])/ },
    { name: 'tracking_number', re: /[0-9]{4}-[0-9]{4}-[0-9]{4}/ },
    { name: 'geo_coords',      re: /[0-9]{1,3}\.[0-9]{4,},\s?[0-9]{1,3}\.[0-9]{4,}/ },
    { name: 'map_url',         re: /(maps\.google|goo\.gl\/maps|google\.[a-z.]+\/maps)/i },
    { name: 'address_words',   re: /(丁目|番地|号室|マンション|アパート|〒)/ },
    { name: 'digit_run',       re: /[0-9]{3}-?[0-9]{4}/ }
  ];
}

/** ファイルを読んで走査する。**encoding を明示すること**（落とすと日本語が無一致になる）。 */
function scanFile(file) {
  const html = fs.readFileSync(file, { encoding: 'utf8' });
  // encoding を落とすと Buffer が返る。黙って進ませない（fail-closed）。
  if (typeof html !== 'string') throw new Error('scanFile: encoding を明示していない（Buffer が返った）');
  const hits = [];
  for (const p of guardPatterns_()) {
    const m = html.match(p.re);
    if (m) hits.push({ name: p.name, sample: String(m[0]).slice(0, 24) });
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
    ];
    // !!! 床（CE-04b ⑧⑨）: positives を空にすると encoding fail-open（latin1 化）まで
    //     不可視になり、日本語住所入り HTML が `guard passed` で exit 0 する（実測された連鎖）。
    if (positives.length < 5) problems.push('self-test fixtures shrunk: ' + positives.length);
    for (const [expected, body] of positives) {
      const f = path.join(dir, 'pos-' + expected + '.html');
      fs.writeFileSync(f, body, { encoding: 'utf8' });
      const hits = scanFile(f).map(h => h.name);
      if (!hits.includes(expected)) {
        problems.push('self-test: ' + expected + ' を検出できなかった (hits=' + JSON.stringify(hits) + ')');
      }
    }
    // 陰性（guard が恒真でないこと）
    const negFile = path.join(dir, 'neg.html');
    fs.writeFileSync(negFile, '<html><body>今日の予定は3件です。天気は晴れ。</body></html>', { encoding: 'utf8' });
    const negHits = scanFile(negFile);
    if (negHits.length) problems.push('self-test: 無害な入力で発火した (' + JSON.stringify(negHits) + ')');
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
    hits.forEach(h => console.log('::error::Forbidden pattern detected in ' + file + ': ' + h.name + ' (例: ' + h.sample + ')'));
    write('### 🔒 Privacy guard FAILED — deployment blocked');
    write('');
    hits.forEach(h => write('- `' + h.name + '` : `' + h.sample + '`'));
    console.log('::error::Privacy guard FAILED — deployment blocked. Fix ' + file + ' and re-push.');
    process.exit(1);
  }
  console.log('Privacy guard passed (' + PATTERN_COUNT + ' patterns, self-test OK).');
  write('### ✅ Privacy guard passed（' + PATTERN_COUNT + ' patterns / 自己テスト込み）');
}

if (require.main === module) main();
module.exports = { guardPatterns_, scanFile, selfTest, PATTERN_COUNT };
