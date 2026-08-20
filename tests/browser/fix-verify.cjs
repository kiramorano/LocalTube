const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5000';
const SHORT_ID = 'r-kf2mm4vfY';
const CHANNEL = '/channel/' + encodeURIComponent('ANATA CARS');

async function setTheme(page, theme) {
  await page.addInitScript((t) => {
    localStorage.setItem('lt_theme', t);
  }, theme);
}

async function main() {
  const browser = await chromium.launch();
  const results = [];

  // ---- 1. Settings page background on frutiger-aero ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await setTheme(page, 'frutiger-aero');
    await page.goto(BASE + '/settings', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2500);
    const bg = await page.evaluate(() => {
      const l1 = getComputedStyle(document.getElementById('bg-layer-1'));
      const l2 = getComputedStyle(document.getElementById('bg-layer-2'));
      const sec = document.querySelector('section');
      return {
        theme: document.documentElement.dataset.theme,
        themeCss: document.getElementById('theme-style').getAttribute('href'),
        layer1: { img: l1.backgroundImage, op: l1.opacity },
        layer2: { img: l2.backgroundImage, op: l2.opacity },
        bodyBg: getComputedStyle(document.body).backgroundColor,
        sectionBg: sec ? getComputedStyle(sec).backgroundColor : null,
        sectionBlur: sec ? getComputedStyle(sec).backdropFilter : null,
        font: getComputedStyle(document.body).fontFamily,
      };
    });
    const visibleBg = (bg.layer1.img !== 'none' && bg.layer1.op !== '0') || (bg.layer2.img !== 'none' && bg.layer2.op !== '0');
    results.push({ test: 'settings frutiger background', pass: visibleBg, detail: bg, errors });
    await page.screenshot({ path: path.join(SHOTS, 'fix-settings-aero.png'), fullPage: true });
    await ctx.close();
  }

  // ---- 2. Settings page: dark theme must NOT show background ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await setTheme(page, 'dark');
    await page.goto(BASE + '/settings', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1200);
    const bg = await page.evaluate(() => {
      const l1 = getComputedStyle(document.getElementById('bg-layer-1'));
      const l2 = getComputedStyle(document.getElementById('bg-layer-2'));
      return { l1: l1.backgroundImage, l2: l2.backgroundImage, op1: l1.opacity, op2: l2.opacity, bodyBg: getComputedStyle(document.body).backgroundColor };
    });
    const clean = bg.l1 === 'none' && bg.l2 === 'none';
    results.push({ test: 'settings dark has no bg image', pass: clean, detail: bg, errors: [] });
    await ctx.close();
  }

  // ---- 3. Shorts on frutiger-aero: no black backdrop ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await setTheme(page, 'frutiger-aero');
    await page.goto(BASE + '/watch/' + SHORT_ID, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2800);
    const info = await page.evaluate(() => {
      const item = document.querySelector('.short-item');
      const wrap = document.querySelector('.short-video-wrapper');
      const pc = document.querySelector('.page-content');
      const l1 = document.getElementById('bg-layer-1'), l2 = document.getElementById('bg-layer-2');
      return {
        theme: document.documentElement.dataset.theme,
        shortItemBg: item ? getComputedStyle(item).backgroundColor : null,
        pageContentBg: pc ? getComputedStyle(pc).backgroundColor : null,
        wrapperBg: wrap ? getComputedStyle(wrap).backgroundColor : null,
        wrapperBlur: wrap ? getComputedStyle(wrap).backdropFilter : null,
        layer1: l1 ? { img: getComputedStyle(l1).backgroundImage, op: getComputedStyle(l1).opacity } : null,
        layer2: l2 ? { img: getComputedStyle(l2).backgroundImage, op: getComputedStyle(l2).opacity } : null,
      };
    });
    const itemTransparent = info.shortItemBg === 'rgba(0, 0, 0, 0)' || info.shortItemBg === 'transparent';
    const bgVisible = (info.layer1 && info.layer1.img !== 'none' && info.layer1.op !== '0') || (info.layer2 && info.layer2.img !== 'none' && info.layer2.op !== '0');
    results.push({ test: 'shorts frutiger not black', pass: itemTransparent && bgVisible, detail: info, errors });
    await page.screenshot({ path: path.join(SHOTS, 'fix-shorts-aero.png') });
    await ctx.close();
  }

  // ---- 4. Shorts volume slider actually works (drag + mute button) ----
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await setTheme(page, 'dark');
    await page.goto(BASE + '/watch/' + SHORT_ID, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);

    const initial = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const s = document.querySelector('.short-vol-slider');
      return { volume: v.volume, muted: v.muted, sliderValue: s.value, thumbVisible: getComputedStyle(s).appearance };
    });

    // hover wrapper to open slider
    await page.hover('.short-vol-wrapper');
    await page.waitForTimeout(500);
    const opened = await page.evaluate(() => {
      const c = document.querySelector('.short-vol-slider-container');
      const cs = getComputedStyle(c);
      const r = c.getBoundingClientRect();
      return { active: c.classList.contains('active'), opacity: cs.opacity, visibility: cs.visibility, pointerEvents: cs.pointerEvents, rect: { x: r.x, y: r.y, w: r.width, h: r.height } };
    });

    // check the slider thumb is actually rendered (non-zero size)
    const thumbInfo = await page.evaluate(() => {
      const s = document.querySelector('.short-vol-slider');
      const r = s.getBoundingClientRect();
      return { w: r.width, h: r.height, x: r.x, y: r.y, transform: getComputedStyle(s).transform };
    });

    // Drag the slider using mouse: because it is rotated -90deg, use keyboard as robust check too
    const box = await page.locator('.short-vol-slider').boundingBox();
    let dragResult = null;
    if (box) {
      // Click near the "high" end of the rotated slider (top of visual column = max)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.5);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2, box.y + 2, { steps: 10 });
      await page.mouse.up();
      await page.waitForTimeout(300);
      dragResult = await page.evaluate(() => {
        const v = document.querySelector('.short-video');
        const s = document.querySelector('.short-vol-slider');
        return { volume: v.volume, muted: v.muted, sliderValue: s.value };
      });
    }

    // Keyboard control check
    await page.locator('.short-vol-slider').focus();
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('ArrowUp');
    await page.waitForTimeout(250);
    const afterKeys = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const s = document.querySelector('.short-vol-slider');
      const icon = document.querySelector('.short-mute-btn svg use');
      return { volume: v.volume, muted: v.muted, sliderValue: s.value, icon: icon ? icon.getAttribute('href') : null };
    });

    // Set slider to 0 -> should mute
    await page.evaluate(() => {
      const s = document.querySelector('.short-vol-slider');
      s.value = 0;
      s.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.waitForTimeout(200);
    const atZero = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const icon = document.querySelector('.short-mute-btn svg use');
      return { volume: v.volume, muted: v.muted, icon: icon ? icon.getAttribute('href') : null };
    });

    // Set slider to 0.8 -> unmute and apply
    await page.evaluate(() => {
      const s = document.querySelector('.short-vol-slider');
      s.value = 0.8;
      s.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.waitForTimeout(200);
    const atHigh = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const icon = document.querySelector('.short-mute-btn svg use');
      return { volume: v.volume, muted: v.muted, icon: icon ? icon.getAttribute('href') : null };
    });

    // Mute button toggle
    await page.click('.short-mute-btn');
    await page.waitForTimeout(250);
    const afterMuteClick = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const icon = document.querySelector('.short-mute-btn svg use');
      return { volume: v.volume, muted: v.muted, icon: icon ? icon.getAttribute('href') : null };
    });

    const sliderWorks = atZero.muted === true && Math.abs(atHigh.volume - 0.8) < 0.01 && atHigh.muted === false
      && atZero.icon === '#icon-vol-muted' && atHigh.icon === '#icon-vol-high';
    results.push({
      test: 'shorts volume slider works',
      pass: sliderWorks && opened.active && thumbInfo.w > 10,
      detail: { initial, opened, thumbInfo, dragResult, afterKeys, atZero, atHigh, afterMuteClick },
      errors,
    });
    await page.screenshot({ path: path.join(SHOTS, 'fix-shorts-volume.png') });
    await ctx.close();
  }

  // ---- 5. Channel page: dates, durations, sort, theme bg ----
  for (const theme of ['dark', 'frutiger-aero']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await setTheme(page, theme);
    await page.goto(BASE + CHANNEL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(2200);

    const info = await page.evaluate(() => {
      const metas = [...document.querySelectorAll('#videosGrid .card .meta')].map(e => e.textContent.trim());
      const durations = [...document.querySelectorAll('#videosGrid .duration')].map(e => e.textContent.trim());
      const dates = [...document.querySelectorAll('#videosGrid .card')].map(e => e.dataset.date);
      const banner = document.querySelector('.banner');
      const l1 = document.getElementById('bg-layer-1'), l2 = document.getElementById('bg-layer-2');
      return {
        theme: document.documentElement.dataset.theme,
        metas: metas.slice(0, 6),
        durations: durations.slice(0, 6),
        dates: dates.slice(0, 8),
        bannerImage: banner ? getComputedStyle(banner).backgroundImage : null,
        layer1: l1 ? { img: getComputedStyle(l1).backgroundImage, op: getComputedStyle(l1).opacity } : null,
        layer2: l2 ? { img: getComputedStyle(l2).backgroundImage, op: getComputedStyle(l2).opacity } : null,
        font: getComputedStyle(document.body).fontFamily,
        textColor: getComputedStyle(document.querySelector('h1')).color,
      };
    });

    // raw yyyymmdd must not leak into visible text
    const rawDate = info.metas.some(t => /\b20\d{6}\b/.test(t));
    // durations must not exceed 59 minutes without hour part
    const badDuration = info.durations.some(d => { const p = d.split(':'); return p.length === 2 && parseInt(p[0], 10) > 59; });
    // default order should be newest-first
    const visibleDates = info.dates.filter(Boolean);
    const sortedDesc = visibleDates.every((d, i) => i === 0 || visibleDates[i - 1] >= d);

    // sort select toggles order
    await page.click('.tab[data-tab="videos"]');
    await page.selectOption('select[data-sort="videos"]', 'old');
    await page.waitForTimeout(400);
    const afterSort = await page.evaluate(() => [...document.querySelectorAll('#videosGrid .card')].map(e => e.dataset.date).filter(Boolean));
    const sortedAsc = afterSort.every((d, i) => i === 0 || afterSort[i - 1] <= d);

    // tabs switch panels
    await page.click('.tab[data-tab="about"]');
    await page.waitForTimeout(300);
    const aboutVisible = await page.evaluate(() => {
      const p = document.getElementById('about');
      return { display: getComputedStyle(p).display, active: p.classList.contains('active'), text: p.querySelector('#description').textContent.slice(0, 60) };
    });

    const bgOk = theme === 'frutiger-aero'
      ? ((info.layer1 && info.layer1.img !== 'none' && info.layer1.op !== '0') || (info.layer2 && info.layer2.img !== 'none' && info.layer2.op !== '0'))
      : (info.layer1.img === 'none' && info.layer2.img === 'none');

    results.push({
      test: `channel page (${theme})`,
      pass: !rawDate && !badDuration && sortedDesc && sortedAsc && aboutVisible.active && bgOk && errors.length === 0,
      detail: { ...info, rawDate, badDuration, sortedDesc, afterSort, sortedAsc, aboutVisible, bgOk },
      errors,
    });
    await page.screenshot({ path: path.join(SHOTS, `fix-channel-${theme}.png`), fullPage: true });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
  const failed = results.filter(r => !r.pass);
  console.log('\n=== SUMMARY ===');
  results.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.test + (r.errors.length ? '  [errors: ' + r.errors.length + ']' : '')));
  process.exit(failed.length ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(2); });
