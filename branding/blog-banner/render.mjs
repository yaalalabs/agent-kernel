// Renders blog banners from template.html and banners.json with headless Chrome.
//
//   node render.mjs                 render every banner in banners.json
//   node render.mjs <slug> ...      render only the named banners
//
// Output goes to docs/static/img/blog/<slug>-banner.png at 3200 by 1680 px
// (1600 by 840 CSS px at device scale 2). Needs Node 22 or later and Google Chrome.
// Set CHROME to the browser binary if it is not in the default macOS location.
//
// The script is also a small page-to-PNG tool, used for one-off artwork:
//   node render.mjs --page <file.html> --out <file.png> --width 800 --height 400 [--scale 2] [--transparent]
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '..', '..');
const chromePath = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** Opens one headless Chrome and returns a function that turns a URL into a PNG file. */
async function openBrowser() {
  const port = 9300 + (process.pid % 600);
  const profile = mkdtempSync(join(tmpdir(), 'banner-'));
  const chrome = spawn(chromePath, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--hide-scrollbars', '--no-first-run', '--allow-file-access-from-files', 'about:blank'], { stdio: 'ignore' });
  let socketUrl;
  for (let i = 0; i < 80 && !socketUrl; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      socketUrl = pages.find((page) => page.type === 'page')?.webSocketDebuggerUrl;
    } catch {
      // Chrome is still starting.
    }
    if (!socketUrl) await sleep(250);
  }
  if (!socketUrl) throw new Error('Chrome did not start');
  const socket = new WebSocket(socketUrl);
  await new Promise((opened, failed) => {
    socket.onopen = opened;
    socket.onerror = failed;
  });
  let id = 0;
  const pending = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((done) => {
      const call = ++id;
      pending.set(call, done);
      socket.send(JSON.stringify({ id: call, method, params }));
    });
  await send('Page.enable');

  const shoot = async ({ url, out, width, height, scale = 2, transparent = false }) => {
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false });
    await send('Emulation.setDefaultBackgroundColorOverride', transparent ? { color: { r: 0, g: 0, b: 0, a: 0 } } : {});
    await send('Page.navigate', { url });
    await sleep(600);
    // Wait for the web fonts and the images, so no banner is drawn in a fallback face.
    await send('Runtime.evaluate', {
      expression: 'Promise.all([document.fonts.ready, ...[...document.images].map((image) => image.decode().catch(() => null))]).then(() => true)',
      awaitPromise: true,
    });
    await sleep(400);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log('wrote', out);
  };
  const close = async () => {
    socket.close();
    chrome.kill('SIGKILL');
    await sleep(300);
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {
      // The profile folder is temporary: leaving it behind is harmless.
    }
  };
  return { shoot, close };
}

const args = process.argv.slice(2);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);

const browser = await openBrowser();
try {
  if (option('--page')) {
    await browser.shoot({
      url: pathToFileURL(resolve(option('--page'))).href,
      out: resolve(option('--out')),
      width: Number(option('--width') || 1600),
      height: Number(option('--height') || 840),
      scale: Number(option('--scale') || 2),
      transparent: args.includes('--transparent'),
    });
  } else {
    const banners = JSON.parse(readFileSync(join(here, 'banners.json'), 'utf8'));
    const wanted = banners.filter((banner) => args.length === 0 || args.includes(banner.slug));
    for (const banner of wanted) {
      // The template reads its content from the query string.
      const url = `${pathToFileURL(join(here, 'template.html')).href}?${new URLSearchParams(banner)}`;
      await browser.shoot({ url, out: join(repo, 'docs', 'static', 'img', 'blog', `${banner.slug}-banner.png`), width: 1600, height: 840 });
    }
  }
} finally {
  await browser.close();
}
