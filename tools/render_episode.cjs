// Internal runner. episode.py checks the human gate before creating this plan.
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {pathToFileURL} = require('node:url');


function encoderArgs(plan) {
  const cfg = plan.renderConfig;
  for (const key of ['encoder','profile','level','pixFmt','colorSpace','crf','preset','gop','movflags']) {
    if (cfg?.[key] == null) throw Error('Missing renderConfig.' + key);
  }
  return ['-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'image2pipe', '-c:v', 'png', '-framerate', String(plan.fps), '-i', 'pipe:0',
    '-vf', 'scale=out_color_matrix='+cfg.colorSpace+':out_range=tv', '-c:v', cfg.encoder,
    '-profile:v', cfg.profile, '-level:v', cfg.level, '-pix_fmt', cfg.pixFmt,
    '-colorspace', cfg.colorSpace, '-color_primaries', cfg.colorSpace, '-color_trc', cfg.colorSpace,
    '-crf', String(cfg.crf), '-preset', cfg.preset, '-g', String(cfg.gop), '-movflags', cfg.movflags,
    '-metadata', 'comment=AI-assisted scientific animation', path.join(plan.work, 'picture.mp4')];
}


function probeLoopback(timeout = 200) {
  return new Promise(resolve => {
    const server = net.createServer();
    let settled = false;
    const finish = (ok, error) => {
      if (settled) return;
      settled = true;
      try {server.close();} catch {}
      resolve({ok, error});
    };
    server.once('error', error => finish(false, String(error.code || error.message)));
    server.listen(0, '127.0.0.1', () => {
      const socket = net.connect({host: '127.0.0.1', port: server.address().port});
      socket.once('connect', () => {socket.destroy(); finish(true, null);});
      socket.once('error', error => finish(false, String(error.code || error.message)));
    });
    setTimeout(() => finish(false, 'ETIMEDOUT'), timeout);
  });
}


function findChrome() {
  // Same lookup order as the episode evidence collector that already renders in
  // the Codex desktop sandbox: explicit override, machine-wide Chrome, Edge, and
  // only then a per-user Chrome so a Program Files install is never shadowed.
  const candidates = [process.env.VIBE_CHROME,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe')];
  for (const candidate of candidates) {
    if (candidate && fsSync.existsSync(candidate)) return candidate;
  }
  throw Error('No Chrome/Edge found for cdp-pipe; set VIBE_CHROME');
}


// Chrome fires its Crashpad handler before the first CDP packet. In a restricted
// desktop sandbox that handler cannot write %LOCALAPPDATA%/%TEMP% and the whole
// browser dies with exit 4294930433 (-36863) before any page loads. Every
// writable location is therefore redirected into the run directory, and the
// crash reporter is disabled outright: the same recipe the Salt evidence
// collector already proved at 94 frames.
const CHROME_SANDBOX_ENV = ['LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'];

async function prepareChromeTemp(plan) {
  const root = path.join(plan.work, 'chrome_tmp');
  const dirs = {local: path.join(root, 'local'), roaming: path.join(root, 'roaming'),
    temp: path.join(root, 'tmp'), config: path.join(root, 'config'),
    cache: path.join(root, 'cache'), profile: path.join(root, 'profile'),
    crash: path.join(root, 'crash')};
  for (const dir of Object.values(dirs)) await fs.mkdir(dir, {recursive: true});
  const env = {...process.env, LOCALAPPDATA: dirs.local, APPDATA: dirs.roaming,
    TEMP: dirs.temp, TMP: dirs.temp, XDG_CONFIG_HOME: dirs.config, XDG_CACHE_HOME: dirs.cache};
  return {root, dirs, env};
}

function chromeArgs(dirs) {
  return ['--headless', '--no-sandbox', '--disable-crash-reporter-for-testing', '--disable-breakpad',
    '--no-crash-upload', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-extensions', '--allow-file-access-from-files',
    '--disable-gpu', '--hide-scrollbars', '--mute-audio',
    '--user-data-dir=' + dirs.profile, '--crash-dumps-dir=' + dirs.crash,
    '--remote-debugging-pipe', 'about:blank'];
}


class PipeCDP {
  constructor(child, launch = () => null) {
    this.child = child;
    this.buffer = Buffer.alloc(0);
    this.nextId = 0;
    this.pending = new Map();
    this.launch = launch;
    this.failure = null;
    child.stdio[4].on('data', chunk => this.onData(chunk));
    child.stdio[3].on('error', error => this.abort(this.exitError(error?.message || error)));
    child.on('error', error => this.abort(this.exitError(error?.message || error)));
    child.on('exit', code => this.abort(this.exitError(code)));
  }

  // The real code plus the captured stderr tail, never a bare "exited null".
  exitError(code) {
    const info = this.launch() || {};
    const tail = String(info.stderrTail || '').trim().slice(-800);
    const suffix = code === null || code === undefined ? '' : ' ' + code;
    return Error('Chrome exited' + suffix + (tail ? ' | stderr: ' + tail : '') +
      ' | see chrome-launch.json and chrome-stderr.log in the run directory');
  }

  abort(error) {
    if (!this.failure) this.failure = error;
    for (const task of this.pending.values()) {
      clearTimeout(task.timer);
      task.reject(this.failure);
    }
    this.pending.clear();
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const end = this.buffer.indexOf(0);
      if (end < 0) return;
      const text = this.buffer.subarray(0, end).toString('utf8');
      this.buffer = this.buffer.subarray(end + 1);
      let message;
      try {message = JSON.parse(text);} catch {continue;}
      if (message.id && this.pending.has(message.id)) {
        const task = this.pending.get(message.id);
        this.pending.delete(message.id);
        clearTimeout(task.timer);
        if (message.error) task.reject(Error(message.error.message || 'CDP error'));
        else task.resolve(message.result);
      }
    }
  }

  send(method, params = {}, sessionId) {
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.nextId;
    const payload = {id, method, params};
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(Error('CDP timeout: ' + method));
      }, 60000);
      this.pending.set(id, {resolve, reject, timer});
      this.child.stdio[3].write(JSON.stringify(payload) + '\0');
    });
  }
}


const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// The exit record is the durable trace of Chrome's real code, so the runner
// waits for it instead of letting the event loop drain first.
function waitExit(child, settled, timeout = 3000) {
  return new Promise(resolve => {
    if (settled()) return resolve();
    const timer = setTimeout(resolve, timeout);
    child.once('exit', () => {clearTimeout(timer); resolve();});
  });
}

async function evaluate(cdp, sessionId, expression) {
  const {result, exceptionDetails} = await cdp.send('Runtime.evaluate',
    {expression, returnByValue: true, awaitPromise: true}, sessionId);
  if (exceptionDetails) throw Error(exceptionDetails.exception?.description || exceptionDetails.text);
  return result.value;
}

async function waitReady(cdp, sessionId, timeout = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const error = await evaluate(cdp, sessionId,
      'window.remotion_cancelledError || document.documentElement.getAttribute("data-pipe-error")');
    if (error) throw Error('Pipe page error: ' + error);
    if (await evaluate(cdp, sessionId,
      'window.remotion_renderReady === true && document.fonts.status === "loaded"')) return;
    await sleep(25);
  }
  throw Error('Timed out waiting for the composition');
}

async function seek(cdp, sessionId, frame, composition) {
  await cdp.send('Runtime.evaluate', {expression:
    'window.remotion_setFrame(' + frame + ', ' + JSON.stringify(composition) + ', 0)',
    returnByValue: true}, sessionId);
  const start = Date.now();
  let pending = false;
  while (Date.now() - start < 10000) {
    const {error, ready} = await evaluate(cdp, sessionId,
      '({error: window.remotion_cancelledError, ready: window.remotion_renderReady})');
    if (error) throw Error(error);
    if (ready === false) pending = true;
    if (ready === true && (pending || Date.now() - start > 80)) return;
    await sleep(10);
  }
  throw Error('Frame ' + frame + ' did not settle');
}

async function writeHarness(plan, serveUrl) {
  const index = await fs.readFile(path.join(serveUrl, 'index.html'), 'utf8');
  const assetRoot = path.join(serveUrl, 'public');
  const entries = fsSync.existsSync(assetRoot)
    ? await fs.readdir(assetRoot, {recursive: true, withFileTypes: true}) : [];
  const localAssets = await Promise.all(entries.filter(item => item.isFile()).map(async item => {
    const file = path.join(item.parentPath, item.name);
    const stat = await fs.stat(file);
    return {name: path.relative(assetRoot, file).split(path.sep).join('/'),
      src: pathToFileURL(file).href, size: stat.size, lastModified: stat.mtimeMs};
  }));
  const prelude = `<script>
window.remotion_inputProps = ${JSON.stringify(JSON.stringify(plan.inputProps)).replaceAll('<', '\\u003c')};
window.remotion_puppeteerTimeout = 90000;
window.process ??= {};
window.process.env ??= {};
window.process.env.NODE_ENV = 'production';
window.remotion_initialFrame = 0;
window.remotion_attempt = 0;
window.remotion_videoEnabled = true;
window.remotion_audioEnabled = false;
window.remotion_logLevel = 'error';
window.remotion_staticFiles = ${JSON.stringify(localAssets).replaceAll('<', '\\u003c')};
window.addEventListener('error', e => document.documentElement.setAttribute('data-pipe-error', String(e.message)));
window.addEventListener('unhandledrejection', e => document.documentElement.setAttribute('data-pipe-error', String(e.reason)));
</script>`;
  let html = index.replace(
    'window.remotion_staticBase = new URL("./public", window.location.href).pathname;',
    'window.remotion_staticBase = new URL("./public", window.location.href).href;');
  const marker = '<script src="./bundle.js"></script>';
  if (!html.includes(marker)) throw Error('Unexpected Remotion bundle markup');
  html = html.replace(marker, prelude + marker);
  const file = path.join(serveUrl, 'pipe-harness.html');
  await fs.writeFile(file, html);
  return file;
}


async function withPipePage(plan, usePage) {
  const {bundle} = require('@remotion/bundler');
  const serveUrl = await bundle({entryPoint: plan.entry, publicDir: plan.publicDir,
    outDir: path.join(plan.work, 'bundle')});
  const harness = await writeHarness(plan, serveUrl);
  const chrome = findChrome();
  const sandbox = await prepareChromeTemp(plan);
  const launch = {executable: chrome, args: chromeArgs(sandbox.dirs), startedAt: new Date().toISOString(),
    tempRoot: sandbox.root, sandboxEnv: Object.fromEntries(CHROME_SANDBOX_ENV.map(key => [key, sandbox.env[key]])),
    exitCode: null, signal: null, spawnError: null, stderrTail: ''};
  const launchFile = path.join(plan.work, 'chrome-launch.json');
  const stderrFile = path.join(plan.work, 'chrome-stderr.log');
  const record = () => {
    try {fsSync.writeFileSync(launchFile, JSON.stringify(launch, null, 2));} catch {}
  };
  fsSync.writeFileSync(stderrFile, '');
  record();
  const child = spawn(chrome, launch.args, {stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'],
    env: sandbox.env, cwd: plan.work, windowsHide: true});
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', text => {
    launch.stderrTail = (launch.stderrTail + text).slice(-8192);
    try {fsSync.appendFileSync(stderrFile, text);} catch {}
  });
  child.on('error', error => {
    launch.spawnError = String(error?.message || error);
    launch.exitCode = launch.exitCode ?? -1;
    launch.endedAt = launch.endedAt || new Date().toISOString();
    record();
  });
  child.on('exit', (code, signal) => {
    launch.exitCode = code;
    launch.signal = signal;
    launch.endedAt = new Date().toISOString();
    record();
  });
  const cdp = new PipeCDP(child, () => launch);
  try {
    const {targetInfos} = await cdp.send('Target.getTargets');
    const page = targetInfos.find(target => target.type === 'page') ||
      {targetId: (await cdp.send('Target.createTarget', {url: 'about:blank'})).targetId};
    const {sessionId} = await cdp.send('Target.attachToTarget',
      {targetId: page.targetId, flatten: true});
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride', {width: plan.width, height: plan.height,
      deviceScaleFactor: plan.scale, mobile: false}, sessionId);
    const navigation = await cdp.send('Page.navigate', {url: pathToFileURL(harness).href}, sessionId);
    if (navigation.errorText) throw Error(navigation.errorText);
    const boot = Date.now();
    while (await evaluate(cdp, sessionId, 'typeof window.remotion_setBundleMode') !== 'function') {
      if (Date.now() - boot > 30000) {
        const info = await evaluate(cdp, sessionId,
          'JSON.stringify({error:document.documentElement.getAttribute("data-pipe-error"),' +
          'scripts:[...document.scripts].map(s=>s.src),ready:window.remotion_renderReady,' +
          'keys:Object.keys(window).filter(k=>k.indexOf("remotion_")===0).slice(0,12)})');
        throw Error('Remotion bundle did not expose setBundleMode: ' + info);
      }
      await sleep(25);
    }
    await evaluate(cdp, sessionId, 'window.remotion_setBundleMode(' + JSON.stringify({
      type: 'composition', compositionName: plan.composition,
      serializedResolvedPropsWithSchema: JSON.stringify(plan.inputProps),
      compositionDurationInFrames: plan.frames, compositionFps: plan.fps,
      compositionHeight: plan.height, compositionWidth: plan.width}) + ')');
    await waitReady(cdp, sessionId);
    return await usePage(cdp, sessionId);
  } finally {
    try {await cdp.send('Browser.close');} catch {}
    await waitExit(child, () => Boolean(launch.endedAt));
    if (!launch.endedAt) {
      try {child.kill();} catch {}
      await waitExit(child, () => Boolean(launch.endedAt), 5000);
    }
  }
}


async function capture(cdp, sessionId) {
  const shot = await cdp.send('Page.captureScreenshot',
    {format: 'png', fromSurface: true, captureBeyondViewport: false}, sessionId);
  return Buffer.from(shot.data, 'base64');
}


async function renderCdp(plan, args, samples) {
  await withPipePage(plan, async (cdp, sessionId) => {
    const ffmpeg = spawn(plan.ffmpeg, args, {stdio: ['pipe', 'ignore', 'inherit'], windowsHide: true});
    const finished = once(ffmpeg, 'close');
    finished.catch(() => {});
    let failure;
    const abort = error => {failure = error; ffmpeg.kill();};
    ffmpeg.stdin.on('error', abort);
    ffmpeg.on('error', abort);
    const expected = [Math.round(plan.width * plan.scale), Math.round(plan.height * plan.scale)];
    try {
      for (let frame = 0; frame < plan.frames; frame++) {
        if (failure) throw failure;
        await seek(cdp, sessionId, frame, plan.composition);
        const buffer = await capture(cdp, sessionId);
        if (frame === 0 && (buffer.readUInt32BE(16) !== expected[0] ||
            buffer.readUInt32BE(20) !== expected[1])) {
          throw Error('Pipe frame ' + buffer.readUInt32BE(16) + 'x' + buffer.readUInt32BE(20) +
            ' != ' + expected[0] + 'x' + expected[1]);
        }
        if (samples.has(frame)) {
          await fs.writeFile(path.join(plan.work, 'frame-' + frame + '.png'), buffer);
        }
        await new Promise((resolve, reject) =>
          ffmpeg.stdin.write(buffer, error => error ? reject(error) : resolve()));
      }
      ffmpeg.stdin.end();
      const [code] = await finished;
      if (code !== 0 || failure) throw failure || Error('FFmpeg exited: ' + code);
    } finally {
      if (ffmpeg.exitCode === null) ffmpeg.kill();
    }
  });
}


async function run(plan) {
  const {bundle} = require('@remotion/bundler');
  const {renderFrames, selectComposition} = require('@remotion/renderer');
  const args = encoderArgs(plan);
  const serveUrl = await bundle({entryPoint:plan.entry, publicDir:plan.publicDir,
    outDir:path.join(plan.work, 'bundle')});
  const composition = await selectComposition({serveUrl, id:plan.composition, inputProps:plan.inputProps});
  for (const key of ['width','height','fps']) {
    if (composition[key] !== plan[key]) throw Error('Composition mismatch: ' + key);
  }
  if (composition.durationInFrames !== plan.frames) throw Error('Composition duration mismatch');
  const samples = new Set(plan.timeline?.frames || []);
  await fs.writeFile(path.join(plan.work, 'encoder.json'), JSON.stringify(args));
  const child = spawn(plan.ffmpeg, args, {stdio:['pipe','ignore','inherit'], windowsHide:true});
  const finished = once(child, 'close');
  finished.catch(() => {});
  // Remotion may finish concurrent frames out of order. Each worker holds at most one PNG.
  let next = 0;
  const waiting = new Map();
  let failure;
  function abort(error) {
    failure = error;
    for (const waiter of waiting.values()) waiter.reject(error);
    waiting.clear();
  }
  child.stdin.on('error', abort);
  child.on('error', abort);
  child.on('exit', code => {if (code !== 0) abort(Error('FFmpeg exited: ' + code));});
  try {
    await renderFrames({serveUrl, composition, inputProps:plan.inputProps, outputDir:null, imageFormat:'png',
      scale:plan.scale, concurrency:plan.concurrency, muted:true, onStart:()=>{}, onFrameUpdate:()=>{},
      onFrameBuffer:async (buffer, frame) => {
        if (failure) throw failure;
        if (frame !== next) await new Promise((resolve,reject)=>waiting.set(frame,{resolve,reject}));
        if (failure) throw failure;
        if (samples.has(frame)) await fs.writeFile(path.join(plan.work, 'frame-' + frame + '.png'), buffer);
        await new Promise((resolve,reject)=>child.stdin.write(buffer, err=>err ? reject(err) : resolve()));
        next++;
        waiting.get(next)?.resolve();
        waiting.delete(next);
      }});
    child.stdin.end();
    const [code] = await finished;
    if (code !== 0 || next !== plan.frames) throw Error('Incomplete frame stream');
  } finally {
    abort(Error('Renderer stopped'));
    if (child.exitCode === null) child.kill();
  }
}


async function main() {
  const argv = process.argv.slice(2);
  const planPath = argv.find(item => !item.startsWith('--'));
  const index = argv.findIndex(item => item === '--transport' || item.startsWith('--transport='));
  let transport = null;
  if (index >= 0) {
    transport = argv[index].includes('=') ? argv[index].split('=')[1] : argv[index + 1];
  }
  const plan = JSON.parse(await fs.readFile(planPath, 'utf8'));
  const requested = transport || process.env.VIBE_RENDER_TRANSPORT || plan.transport || 'auto';
  const automatic = requested === 'auto';
  const args = encoderArgs(plan);
  const samples = new Set(plan.timeline?.frames || []);
  await fs.writeFile(path.join(plan.work, 'encoder.json'), JSON.stringify(args));
  let resolved = requested;
  if (automatic) {
    const probe = await probeLoopback();
    resolved = probe.ok ? 'remotion' : 'cdp-pipe';
    console.error('[render] loopback ' + (probe.ok ? 'ok' : 'blocked (' + probe.error + ')') +
      '; transport=' + resolved);
  }
  if (resolved === 'cdp-pipe') {
    await renderCdp(plan, args, samples);
    return;
  }
  try {
    await run(plan);
  } catch (error) {
    const code = String(error.code || '');
    if (!automatic || !/EACCES|EPERM/.test(code + ' ' + String(error.message))) throw error;
    console.error('[render] remotion blocked (' + code + '); falling back to cdp-pipe');
    await renderCdp(plan, args, samples);
  }
}

module.exports = {encoderArgs, probeLoopback, withPipePage, evaluate, seek, capture};
if (require.main === module) {
  main().catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
}
