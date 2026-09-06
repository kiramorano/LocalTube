// Аудит гостевых страниц Android-приложения (LanPages.kt).
//
// Страницы выгружаются юнит-тестом LanPagesDumpTest в LT_DUMP_DIR, здесь они
// открываются как file:// на эмуляции телефона и измеряются: горизонтальный
// скролл, площадь кнопок под палец, вылезающие за экран блоки.
const path = require('path');
const fs = require('fs');
const { chromium, devices } = require('playwright');

const DUMP = process.env.LT_DUMP_DIR || path.join(process.env.TEMP || '/tmp', 'opencode', 'lanpages');
const SHOTS = path.join(__dirname, 'shots');
const MIN_TAP = 44;

const PAGES = ['index', 'watch', 'channel', 'search', 'search-empty', 'unlock', 'unlock-error', 'empty'];

async function audit(page, name) {
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  const file = path.join(DUMP, name + '.html');
  if (!fs.existsSync(file)) return { page: name, missing: true };
  await page.goto('file:///' + file.replace(/\\/g, '/'), { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(400);

  const report = await page.evaluate((MIN_TAP) => {
    const vw = window.innerWidth;
    const res = { hScroll: document.documentElement.scrollWidth - vw, overflowing: [], smallTaps: [], tiny: [] };

    const visible = el => {
      for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        if (parseFloat(cs.opacity) === 0) return false;
      }
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const label = el => el.tagName.toLowerCase() +
      (el.id ? '#' + el.id : '') +
      (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
    const inScroller = el => {
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        const ox = getComputedStyle(n).overflowX;
        if (ox === 'auto' || ox === 'scroll') return true;
      }
      return false;
    };

    for (const el of document.querySelectorAll('body *')) {
      if (!visible(el) || inScroller(el)) continue;
      if (getComputedStyle(el).position === 'fixed') continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 || r.left < -1) {
        res.overflowing.push({ sel: label(el), left: +r.left.toFixed(1), right: +r.right.toFixed(1) });
      }
    }

    for (const el of document.querySelectorAll('a, button, input, select, [role="button"]')) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < MIN_TAP || r.height < MIN_TAP) {
        const item = {
          sel: label(el), w: +r.width.toFixed(1), h: +r.height.toFixed(1),
          text: (el.getAttribute('aria-label') || el.value || el.textContent || '').trim().slice(0, 34),
        };
        res.smallTaps.push(item);
        // Совсем мелкие цели: меньше 32px по любой стороне.
        if (r.height < 32 || r.width < 32) res.tiny.push(item);
      }
    }

    // Читаемость: размер шрифта основного текста.
    const probe = document.querySelector('.card .t') || document.querySelector('p') || document.body;
    res.fontSize = getComputedStyle(probe).fontSize;
    res.gridCols = (() => {
      const g = document.querySelector('.grid');
      return g ? getComputedStyle(g).gridTemplateColumns : null;
    })();
    res.cardCount = document.querySelectorAll('.card').length;
    // Плотность вёрстки: сколько занимает одна карточка по ширине.
    res.cardWidth = (() => {
      const c = document.querySelector('.card');
      return c ? +c.getBoundingClientRect().width.toFixed(1) : null;
    })();
    return res;
  }, MIN_TAP);

  await page.screenshot({ path: path.join(SHOTS, `lan-${name}.png`), fullPage: true });
  return { page: name, ...report, errors };
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  for (const name of PAGES) {
    const ctx = await browser.newContext({ ...devices['Pixel 5'], hasTouch: true, isMobile: true });
    const page = await ctx.newPage();
    out.push(await audit(page, name));
    await ctx.close();
  }
  await browser.close();

  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY (Pixel 5, 393px) ===');
  for (const r of out) {
    if (r.missing) { console.log(`${r.page}: НЕТ ФАЙЛА`); continue; }
    console.log(
      `${r.page.padEnd(13)} hScroll=${String(r.hScroll).padStart(3)}  overflow=${String(r.overflowing.length).padStart(2)}` +
      `  smallTap=${String(r.smallTaps.length).padStart(2)}  tiny=${String(r.tiny.length).padStart(2)}` +
      `  cards=${String(r.cardCount).padStart(2)}  cardW=${r.cardWidth}  font=${r.fontSize}  err=${r.errors.length}`
    );
  }
})().catch(e => { console.error(e); process.exit(2); });
