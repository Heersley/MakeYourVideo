const fs = require('node:fs/promises');
const path = require('node:path');
const {withPipePage, evaluate, seek, capture} = require('./render_episode.cjs');

function measure() {
  const bounds = node => {
    const {left, top, right, bottom} = node.getBoundingClientRect();
    return [Math.floor(left), Math.floor(top), Math.ceil(right), Math.ceil(bottom)];
  };
  const boxes = [...document.querySelectorAll('[data-vibe-static-text]:not([data-holding="false"])')]
    .map(node => {
      const chain = [];
      for (let item = node; item; item = item.parentElement) chain.push(getComputedStyle(item));
      return {box: bounds(node), opacity: chain.reduce((v, css) => v * Number(css.opacity), 1),
        stationary: chain.every(css => css.transform === 'none' && css.filter === 'none')};
    });
  const faces = [...document.fonts].map(face => ({
    family: face.family.replace(/^["']|["']$/g, ''), weight: face.weight, status: face.status
  }));
  const details = [...document.querySelectorAll('[data-vibe-evidence]')].map(node => ({
    data: {...node.dataset}, box: bounds(node), text: node.textContent
  }));
  return {boxes, faces, details};
}

async function main() {
  const config = path.resolve(process.argv[2]);
  const work = path.dirname(config);
  const {plan, frames, pngFrames} = JSON.parse(await fs.readFile(config, 'utf8'));
  const png = new Set(pngFrames);
  await withPipePage({...plan, work}, async (cdp, sessionId) => {
    const {product} = await cdp.send('Browser.getVersion');
    const measurements = {};
    for (const frame of frames) {
      if (!Number.isInteger(frame) || frame < 0 || frame >= plan.frames) {
        throw Error('Evidence frame out of bounds: ' + frame);
      }
      await seek(cdp, sessionId, frame, plan.composition);
      await evaluate(cdp, sessionId, 'document.fonts.ready.then(() => true)');
      measurements[frame] = await evaluate(cdp, sessionId, '(' + measure.toString() + ')()');
      if (png.has(frame)) {
        await fs.writeFile(path.join(work, 'frame-' + frame + '.png'), await capture(cdp, sessionId));
      }
    }
    await fs.writeFile(path.join(work, 'dom.json'), JSON.stringify({browser: product, frames: measurements}));
  });
}

if (require.main === module) main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
