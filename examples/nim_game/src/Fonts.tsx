import {useEffect, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';

export const fontFamilyName = 'ChillJinshuSong';
export const chinese = '"' + fontFamilyName + '"';
export const western = '"Source Serif 4"';
export const mono = '"JetBrains Mono"';
export const numeric = `${mono}, ${chinese}`;
export const chineseGlyph = /[\p{Script=Han}、，。：！？（）【】\u3000]/u;

const faces = [
  {family: chinese, weight: 400, file: 'ChillJinshuSongRegular.woff', format: 'woff', sample: '石子后手零局势'},
  {family: chinese, weight: 700, file: 'ChillJinshuSongBold.woff', format: 'woff', sample: '异或博弈最后一颗'},
  {family: western, weight: 400, file: 'SourceSerif4-Regular.ttf.woff2', format: 'woff2', sample: 'NIM 0123456789'},
  {family: western, weight: 600, file: 'SourceSerif4-Semibold.ttf.woff2', format: 'woff2', sample: 'NIM 0123456789'},
  {family: mono, weight: 400, file: 'JetBrainsMono-Regular.woff2', format: 'woff2', sample: 'XOR 0123456789 ⇒⊕≠'},
  {family: mono, weight: 500, file: 'JetBrainsMono-Medium.woff2', format: 'woff2', sample: 'XOR 0123456789 ⇒⊕≠'},
] as const;

function installFontStyles() {
  const style = document.createElement('style');
  style.textContent = faces.map(face => `
    @font-face {
      font-family: ${face.family};
      src: url("${staticFile('fonts/' + face.file)}") format("${face.format}");
      font-weight: ${face.weight};
      font-style: normal;
      font-display: block;
    }
  `).join('\n');
  document.head.appendChild(style);
}

async function loadFontFaces() {
  installFontStyles();
  const checks = faces.map(face => ({...face, spec: `${face.weight} 30px ${face.family}`}));
  const loaded = await Promise.all(checks.map(({spec, sample}) => document.fonts.load(spec, sample)));
  await document.fonts.ready;
  checks.forEach(({family, weight, file, sample, spec}, index) => {
    const matching = loaded[index].find(face =>
      face.family.replace(/['"]/g, '') === family.replace(/['"]/g, '') &&
      (face.weight === String(weight) || (weight === 400 && face.weight === 'normal')) &&
      face.status === 'loaded');
    if (!matching || !document.fonts.check(spec, sample)) {
      const details = Array.from(document.fonts).map(face => `${face.family} ${face.weight} ${face.status}`).join(', ');
      throw new Error(`Font did not load from public/fonts/: ${file} (matched: ${!!matching}; check: ${document.fonts.check(spec, sample)}; ${details})`);
    }
  });
}

let fontsReady: Promise<void> | undefined;
export function loadSceneFonts() {
  fontsReady ??= loadFontFaces();
  return fontsReady;
}

export function FontLayer({preload}: {preload: () => Promise<unknown>}) {
  const [gate] = useState(() => delayRender('Load the packaged Nim episode typefaces and stone textures'));
  useEffect(() => {
    Promise.all([loadSceneFonts(), preload()]).then(() => continueRender(gate), error => cancelRender(error));
  }, [gate, preload]);

  return null;
}
