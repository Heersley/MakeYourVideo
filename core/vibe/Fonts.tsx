import {useLayoutEffect, type ReactNode} from 'react';
import {staticFile, useDelayRender} from 'remotion';

export type LocalFace = readonly [family: string, weight: string, file: string];
const noExtraFaces: readonly LocalFace[] = [];

export const bundledFaces = [
  ['Source Serif 4', '400', 'SourceSerif4-Regular.ttf.woff2'],
  ['Source Serif 4', '600', 'SourceSerif4-Semibold.ttf.woff2'],
  ['ChillJinshuSong', '400', 'ChillJinshuSongRegular.woff'],
  ['ChillJinshuSong', '700', 'ChillJinshuSongBold.woff'],
  ['Noto Sans SC', '400', 'NotoSansSC-Regular.otf'],
  ['Noto Sans SC', '500', 'NotoSansSC-Medium.otf'],
  ['JetBrains Mono', '400', 'JetBrainsMono-Regular.woff2'],
  ['JetBrains Mono', '500', 'JetBrainsMono-Medium.woff2'],
] as const;

const pending = new Map<string, Promise<void>>();
export function loadFaces(folder: string, notoMedium?: string, extraFaces = noExtraFaces) {
  const key = JSON.stringify([folder, notoMedium, extraFaces]);
  const existing = pending.get(key);
  if (existing) return existing;
  const faces: LocalFace[] = bundledFaces.map(face =>
    notoMedium && face[0] === 'Noto Sans SC' && face[1] === '500'
      ? [face[0], face[1], notoMedium] : face);
  const job = Promise.all([...faces, ...extraFaces].map(async ([family, weight, file]) => {
    const url = staticFile([folder, file].filter(Boolean).join('/'));
    const format = /\.otf$/i.test(file) ? ' format("opentype")' : '';
    try {
      const face = new FontFace(family, `url(${JSON.stringify(url)})${format}`, {weight});
      return await face.load();
    } catch (cause) {
      throw new Error(`Failed to load ${family} ${weight} from ${url}`, {cause});
    }
  })).then(async loaded => {
    for (const face of loaded) document.fonts.add(face);
    await document.fonts.ready;
  });
  pending.set(key, job);
  job.catch(() => pending.delete(key));
  return job;
}

export function Fonts({folder, notoMedium, extraFaces = noExtraFaces, children}: {
  folder: string; notoMedium?: string; extraFaces?: readonly LocalFace[]; children: ReactNode;
}) {
  const {delayRender, continueRender, cancelRender} = useDelayRender();
  useLayoutEffect(() => {
    const handle = delayRender('Loading local Vibe fonts');
    let pendingHandle = true;
    const release = () => {
      if (pendingHandle) {pendingHandle = false; continueRender(handle);}
    };
    loadFaces(folder, notoMedium, extraFaces).then(release, error => {if (pendingHandle) cancelRender(error);});
    return release;
  }, [folder, notoMedium, extraFaces, delayRender, continueRender, cancelRender]);
  return children;
}
