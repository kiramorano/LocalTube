// Скриншоты мобильных страниц во всех темах. Служебный инструмент для сверки
// дизайна: результат кладётся в shots/mobile-<тема>-<страница>.png.
const fs = require('fs');
const path = require('path');
const { chromium, devices } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5011';
const TAG = process.env.LT_TAG || 'now';
const THEMES = (process.env.LT_THEMES || 'dark,light,midnight,glass,frutiger-aero').split(',');
const VIDEO = process.env.LT_VIDEO_ID || 'WnZ1xSQNErc';
const SHORT = process.env.LT_SHORT_ID || 'r-kf2mm4vfY';
const CHANNEL = process.env.LT_CHANNEL || 'ANATA CARS';

const PAGES = [
  ['index', '/'],
  ['watch', `/watch/${VIDEO}`],
  ['shorts', `/watch/${SHORT}`],
  ['channel', `/channel/${encodeURIComponent(CHANNEL)}`],
  ['settings', '/settings'],
  ['upload', '/upload'],
];

(async () => {
  const dir = path.join(__dirname, 'shots');
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch();
  for (const theme of THEMES) {
    const context = await browser.newContext({ ...devices['Pixel 5'] });
    await context.addInitScript((value) => {
      try { localStorage.setItem('lt_theme', value); } catch (err) { /* приватный режим */ }
    }, theme);
    const page = await context.newPage();
    for (const [name, url] of PAGES) {
      await page.goto(BASE + url, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(700);
      const file = path.join(dir, `mobile-${TAG}-${theme}-${name}.png`);
      await page.screenshot({ path: file, fullPage: name !== 'shorts' });
      const scroll = await page.evaluate(() => ({
        h: document.documentElement.scrollWidth - window.innerWidth,
        vw: window.innerWidth,
      }));
      console.log(`${theme}/${name} hScroll=${scroll.h} vw=${scroll.vw}`);
    }
    await context.close();
  }
  await browser.close();
})();
