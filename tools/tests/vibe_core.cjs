// Compile the same TSX used by the episode. No browser render or video encoder.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const {buildSync} = require('esbuild');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const root = path.resolve(__dirname, '../..');
const profile = require(path.join(root, 'tools/profiles/vibe-3.3.json'));
function load(name) {
  const result = buildSync({entryPoints: [path.join(root, 'core/vibe', name)],
    write: false, bundle: true, packages: 'external', platform: 'node', format: 'cjs', jsx: 'automatic'});
  const mod = {exports: {}};
  new Function('module', 'exports', 'require', result.outputFiles[0].text)(mod, mod.exports, require);
  return mod.exports;
}
const {frameClock} = load('clock.ts');
const {characterState, needsMicrospace, TextLifecycle} = load('TextLifecycle.tsx');
const {stageDesign, stageTokens} = load('tokens.ts');
const {StageBase} = load('StageBase.tsx');
const score = {fps: 60, alignClimaxSec: 7, beats: [0, 5].map((s, i) => ({
  id: i+1, hardCut: false, startSec: s, endSec: s+5, readingStartSec: s+1.001,
  readingEndSec: s+2.001, lines: ['解【2】步', '12ms'],
}))};
const clock = frame => frameClock(frame, 60, score, profile);

test('preview/full use identical source ticks, half-open bounds and seam pair', () => {
  for (let frame = 0; frame < 300; frame++) assert.deepEqual(frameClock(frame, 30, score, profile), clock(frame*2));
  assert.equal(clock(60).reading, false);
  assert.equal(clock(61).reading, true);
  assert.equal(clock(120).reading, true);
  assert.equal(clock(121).reading, false);
  assert.deepEqual(clock(300).seam, [299, 300]);
  assert.equal(clock(300).climaxFrame, 420);
  assert.throws(() => clock(600));
});

test('breathing type: lead, opacity-only entrance, stable reading, independent trail and blank tail', () => {
  const state = f => characterState(clock(f), 2, 3);
  assert.equal(state(0).opacity, 1);
  assert.equal(state(300).opacity, 0);
  assert.ok(state(336).opacity > 0 && state(336).opacity < 1);
  assert.equal(state(336).transform, 'none');
  for (let f = 361; f <= 420; f++) {
    assert.deepEqual([state(f).opacity, state(f).transform, state(f).filter], [1, 'none', 'none']);
  }
  const c = clock(575);
  const glyph = state(575);
  const u = c.trailFrame / (c.trailFrames - 0.06 * c.rate);
  assert.equal(glyph.shadows[0], Math.sin(Math.PI*u)*0.46);
  assert.ok(glyph.opacity < 1 && glyph.shadows[0] > 0);
  for (let i = 0; i < 3; i++) {
    const gone = characterState(clock(591), i, 3);
    assert.equal(gone.opacity, 0);
    assert.ok(gone.shadows.every(a => a === 0));
  }
  assert.ok(needsMicrospace('中', '2') && needsMicrospace('2', 'm'));
  assert.equal(needsMicrospace('1', '2'), false);
  const html = renderToStaticMarkup(React.createElement(TextLifecycle, {clock:clock(380), x:1.7}));
  for (const expected of ['data-holding="true"', 'data-beat-id="2"', 'margin-left:0.15em', 'left:2px',
                          'font-size:104px', 'font-size:76px']) assert.ok(html.includes(expected), expected);
});

test('stage tokens follow profile and preserve stationary slots', () => {
  const p = structuredClone(profile);
  p.hard.visual.safeZone[0] = 140;
  const t = stageTokens(p, 'keynote_light', {...stageDesign, strokes:{L1:6, L2:4, L3:3}});
  assert.equal(t.left, 140);
  assert.equal(t.strokes.L3, 3);
  assert.throws(() => stageTokens(p, 'studio_dark', {...stageDesign, strokes:{L1:6, L2:4, L3:2}}));
  const html = renderToStaticMarkup(React.createElement(StageBase, {tokens:t, headline:'HEAD', labels:'LABEL',
    stage:'GEOMETRY', readout:'READOUT', cameraTransform:'scale(1.02)'}));
  assert.match(html, /transform:scale\(1\.02\)">GEOMETRY<\/div><div[^>]*>LABEL/);
  assert.ok(html.indexOf('HEAD') < html.indexOf('scale(1.02)') && html.indexOf('READOUT') > html.indexOf('LABEL'));
});

test('offline faces include both Noto OTF weights and reject missing declared files', async () => {
  const {loadFaces, bundledFaces} = load('Fonts.tsx');
  assert.deepEqual(bundledFaces.map(([family, weight]) => [family, weight]), [
    ['Source Serif 4', '400'], ['Source Serif 4', '600'],
    ['ChillJinshuSong', '400'], ['ChillJinshuSong', '700'],
    ['Noto Sans SC', '400'], ['Noto Sans SC', '500'],
    ['JetBrains Mono', '400'], ['JetBrains Mono', '500'],
  ]);
  const dir = path.join(root, 'assets/fonts');
  const publicDir = path.join(root, 'public/fonts');
  const findFont = file => [dir, publicDir].map(d => path.join(d, file)).find(p => fs.existsSync(p));
  const installedFonts = bundledFaces.every(([, , file]) => findFont(file));
  if (installedFonts) {
    // Full implementation check when all 4-family/8-file binaries are locally present.
    for (const [family, , file] of bundledFaces) {
      const data = fs.readFileSync(findFont(file));
      assert.ok(data.length);
      if (family === 'Noto Sans SC') assert.equal(data.toString('ascii', 0, 4), 'OTTO');
    }
    const notice = fs.readFileSync(path.join(dir, 'FONT-NOTICE.md'), 'utf8');
    assert.match(notice, /4 族 8 文件|4族8文件/);
  } else {
    // No font binaries ship with the OSS repo: assert the documented contract instead.
    const notice = fs.readFileSync(path.join(dir, 'FONT-NOTICE.md'), 'utf8');
    assert.match(notice, /4 族 8 文件|4族8文件/);
    for (const [, , file] of bundledFaces) assert.ok(notice.includes(file), file);
  }
  const installed = [];
  let unavailable = 'NotoSansSC-Regular.otf';
  global.document = {fonts:{add:f => installed.push(f), ready:Promise.resolve()}};
  global.FontFace = class {
    constructor(family, source, {weight}) {Object.assign(this, {family, source, weight});}
    async load() {
      if (this.source.includes(unavailable)) throw Error('file missing');
      return this;
    }
  };
  try {
    await assert.rejects(loadFaces('fonts'), /Noto Sans SC 400.*NotoSansSC-Regular\.otf/);
    assert.equal(installed.length, 0);
    unavailable = 'missing.woff';
    await loadFaces('fonts');
    assert.equal(installed.length, 8);
    const noto = installed.filter(face => face.family === 'Noto Sans SC');
    assert.deepEqual(noto.map(face => face.weight), ['400', '500']);
    for (const face of noto) assert.ok(face.source.endsWith('format("opentype")'));
    await assert.rejects(loadFaces('fonts', 'missing.woff'), /Noto Sans SC 500.*missing\.woff/);
    await assert.rejects(loadFaces('fonts', undefined, [['Episode', '600', 'missing.woff']]), /Episode 600.*missing\.woff/);
    await loadFaces('fonts', 'alternate.otf', [['Episode', '600', 'episode.woff']]);
    const added = installed.slice(8);
    assert.equal(added.length, 9);
    assert.deepEqual(added.filter(f => f.family === 'Noto Sans SC' && f.weight === '500')
      .map(f => f.source.includes('alternate.otf')), [true]);
    assert.equal(added.at(-1).family, 'Episode');
  } finally {delete global.document; delete global.FontFace;}
});
