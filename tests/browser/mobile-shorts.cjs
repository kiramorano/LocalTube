const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium, devices } = require('playwright');
const BASE = 'http://127.0.0.1:5000';
const SHORT_ID = 'r-kf2mm4vfY';

(async () => {
  const browser = await chromium.launch();
  const out = [];

  for (const theme of ['dark', 'frutiger-aero']) {
    const ctx = await browser.newContext({ ...devices['Pixel 5'], hasTouch: true, isMobile: true });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    await page.goto(BASE + '/watch/' + SHORT_ID, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);

    // On touch devices there is no hover: tapping the mute button must reveal the slider.
    const beforeTap = await page.evaluate(() => ({
      active: document.querySelector('.short-vol-slider-container').classList.contains('active'),
      muted: document.querySelector('.short-video').muted,
    }));
    await page.tap('.short-mute-btn');
    await page.waitForTimeout(400);
    const afterTap = await page.evaluate(() => {
      const c = document.querySelector('.short-vol-slider-container');
      const s = document.querySelector('.short-vol-slider');
      const v = document.querySelector('.short-video');
      const cs = getComputedStyle(c);
      const sr = s.getBoundingClientRect(), cr = c.getBoundingClientRect();
      const icon = document.querySelector('.short-mute-btn svg use');
      return {
        active: c.classList.contains('active'), opacity: cs.opacity, visibility: cs.visibility, pointerEvents: cs.pointerEvents,
        muted: v.muted, volume: v.volume, icon: icon ? icon.getAttribute('href') : null,
        sliderBox: { w: +sr.width.toFixed(1), h: +sr.height.toFixed(1) },
        containerBox: { x: +cr.x.toFixed(1), y: +cr.y.toFixed(1), w: +cr.width.toFixed(1), h: +cr.height.toFixed(1) },
        inViewport: cr.y >= 0 && cr.x >= 0 && cr.right <= innerWidth && cr.bottom <= innerHeight,
      };
    });

    // Slider must respond to programmatic input on mobile as well.
    await page.evaluate(() => { const s = document.querySelector('.short-vol-slider'); s.value = 0.35; s.dispatchEvent(new Event('input', { bubbles: true })); });
    await page.waitForTimeout(200);
    const afterSet = await page.evaluate(() => {
      const v = document.querySelector('.short-video');
      const icon = document.querySelector('.short-mute-btn svg use');
      return { volume: +v.volume.toFixed(2), muted: v.muted, icon: icon ? icon.getAttribute('href') : null };
    });

    // Backdrop / theme checks on mobile
    const visuals = await page.evaluate(() => {
      const item = document.querySelector('.short-item');
      const wrap = document.querySelector('.short-video-wrapper');
      const l1 = document.getElementById('bg-layer-1'), l2 = document.getElementById('bg-layer-2');
      const row = document.querySelector('.short-controls-row');
      const rr = row.getBoundingClientRect();
      return {
        itemBg: getComputedStyle(item).backgroundColor,
        wrapBg: getComputedStyle(wrap).backgroundColor,
        layer1: { img: getComputedStyle(l1).backgroundImage, op: getComputedStyle(l1).opacity },
        layer2: { img: getComputedStyle(l2).backgroundImage, op: getComputedStyle(l2).opacity },
        controlsInViewport: rr.right <= innerWidth && rr.bottom <= innerHeight && rr.x >= 0,
        hScroll: document.documentElement.scrollWidth > innerWidth + 1,
        muteBtnSize: (() => { const r = document.querySelector('.short-mute-btn').getBoundingClientRect(); return { w: +r.width.toFixed(1), h: +r.height.toFixed(1) }; })(),
      };
    });

    const bgOk = theme === 'frutiger-aero'
      ? (visuals.layer1.img !== 'none' && visuals.layer1.op !== '0') || (visuals.layer2.img !== 'none' && visuals.layer2.op !== '0')
      : visuals.layer1.img === 'none' && visuals.layer2.img === 'none';

    out.push({
      theme,
      pass: afterTap.active && afterTap.sliderBox.w > 10 && afterTap.inViewport
            && afterSet.volume === 0.35 && afterSet.muted === false && afterSet.icon === '#icon-vol-high'
            && bgOk && !visuals.hScroll && visuals.controlsInViewport
            && visuals.muteBtnSize.w >= 40 && visuals.muteBtnSize.h >= 40
            && errors.length === 0,
      beforeTap, afterTap, afterSet, visuals, bgOk, errors,
    });
    await page.screenshot({ path: path.join(SHOTS, `mobile-shorts-${theme}.png`) });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  mobile shorts [' + r.theme + ']'));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
