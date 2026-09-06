// Аудит мобильной вёрстки: ищет горизонтальный скролл, перекрытые/мелкие
// кнопки, вылезающие за экран блоки и ошибки консоли на эмуляции телефона.
//
// Запуск: LT_BASE=http://127.0.0.1:5004 node tests/browser/mobile-audit.cjs
const path = require('path');
const { chromium, devices } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';
const SHOTS = path.join(__dirname, 'shots');
const VIDEO_ID = process.env.LT_VIDEO_ID || '-dDHUXLW5xQ';
const SHORT_ID = process.env.LT_SHORT_ID || 'r-kf2mm4vfY';
const CHANNEL = process.env.LT_CHANNEL || 'ANATA CARS';

// Ниже 44x44 CSS-пикселей палец промахивается: и Apple HIG, и Material
// требуют такой минимум для сенсорных целей.
const MIN_TAP = 44;

const PAGES = [
  { name: 'index', url: '/' },
  { name: 'watch', url: '/watch/' + VIDEO_ID },
  { name: 'shorts', url: '/watch/' + SHORT_ID },
  { name: 'channel', url: '/channel/' + encodeURIComponent(CHANNEL) },
  { name: 'settings', url: '/settings' },
  { name: 'upload', url: '/upload' },
];

async function auditPage(ctx, page, spec) {
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(BASE + spec.url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1800);

  const report = await page.evaluate((MIN_TAP) => {
    const vw = window.innerWidth;
    const res = { hScroll: null, overflowing: [], smallTaps: [], covered: [] };

    res.hScroll = {
      overflow: document.documentElement.scrollWidth - vw,
      bodyScroll: document.body.scrollWidth - vw,
    };

    // Элемент считается видимым только если ни один его предок не скрыт.
    // Без обхода предков в отчёт попадали кнопки закрытого модального окна
    // и пункты уехавшего за экран сайдбара — оба не видны пользователю.
    const visible = el => {
      for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        if (parseFloat(cs.opacity) === 0) return false;
        if (cs.pointerEvents === 'none' && n !== el) return false;
      }
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };

    // Что вылезает за правый край экрана. Элементы внутри горизонтальных
    // каруселей (shorts-полка, ряд вкладок) пропускаем: у них скролл по замыслу.
    const inScroller = el => {
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        const ox = getComputedStyle(n).overflowX;
        if (ox === 'auto' || ox === 'scroll') return true;
        // Закрытый сайдбар стоит на left: -240px. Сам он position: fixed и уже
        // отфильтрован, но его пункты — статические, и без этой проверки они
        // попадали в отчёт как «уехавшие за левый край».
        const cs = getComputedStyle(n);
        if (cs.position === 'fixed' && n.getBoundingClientRect().right <= 0) return true;
      }
      return false;
    };
    for (const el of document.querySelectorAll('body *')) {
      if (!visible(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.position === 'fixed') continue;
      if (inScroller(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 || r.left < -1) {
        res.overflowing.push({
          sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
          left: +r.left.toFixed(1), right: +r.right.toFixed(1), w: +r.width.toFixed(1),
        });
      }
    }

    // Слишком мелкие для пальца интерактивные элементы.
    const interactive = 'button, a, input, select, textarea, [role="button"], .menu-icon, .control-btn, .action-btn, .chip, .tab';
    for (const el of document.querySelectorAll(interactive)) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight * 3) continue;
      if (r.width < MIN_TAP || r.height < MIN_TAP) {
        res.smallTaps.push({
          sel: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
          w: +r.width.toFixed(1), h: +r.height.toFixed(1),
          label: (el.getAttribute('aria-label') || el.title || el.textContent || '').trim().slice(0, 30),
        });
      }
    }

    // Перекрытые элементы: в центре кнопки должна оказаться она сама.
    // Закреплённая нижняя панель накрывает то, что под ней проезжает, — при
    // какой-то прокрутке под ней оказывается почти любая кнопка, и это не
    // дефект. Поэтому перекрытую кнопку подводим к середине экрана и смотрим
    // снова: сообщаем только о недостижимой ни при какой прокрутке.
    const blocker = (el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.top < 0 || r.bottom > innerHeight) return undefined;
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (!top || top === el || el.contains(top) || top.contains(el)) return null;
      return top;
    };
    for (const el of document.querySelectorAll('button, a.video-card, .menu-icon, .control-btn')) {
      if (!visible(el)) continue;
      let top = blocker(el);
      if (top === null) continue;
      // Либо перекрыта, либо не видна целиком: пробуем вывести на середину.
      el.scrollIntoView({ block: 'center' });
      top = blocker(el);
      if (top === null || top === undefined) continue;
      res.covered.push({
        sel: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''),
        blockedBy: top.tagName.toLowerCase() + (top.id ? '#' + top.id : '') + (top.className && typeof top.className === 'string' ? '.' + String(top.className).trim().split(/\s+/).slice(0, 2).join('.') : ''),
        label: (el.getAttribute('aria-label') || el.title || el.textContent || '').trim().slice(0, 30),
      });
    }
    return res;
  }, MIN_TAP);

  // Проверка бургер-меню: тап должен открывать сайдбар и оверлей.
  let drawer = { present: false };
  const hasDrawer = await page.locator('#sidebarDrawer').count();
  const hasToggle = await page.locator('#sidebarToggle').count();
  if (hasDrawer && hasToggle) {
    const before = await page.evaluate(() => ({
      active: document.getElementById('sidebarDrawer').classList.contains('active'),
      display: getComputedStyle(document.getElementById('sidebarDrawer')).display,
    }));
    let tapError = null;
    try {
      await page.tap('#sidebarToggle');
    } catch (e) { tapError = e.message.split('\n')[0]; }
    await page.waitForTimeout(500);
    const after = await page.evaluate(() => {
      const d = document.getElementById('sidebarDrawer');
      const o = document.getElementById('sidebarOverlay');
      const r = d.getBoundingClientRect();
      return {
        active: d.classList.contains('active'),
        x: +r.x.toFixed(1), w: +r.width.toFixed(1),
        onScreen: r.x >= -1 && r.width > 100,
        overlayActive: o ? o.classList.contains('active') : null,
        display: getComputedStyle(d).display,
      };
    });
    drawer = { present: true, before, after, tapError, opens: before.display === 'none' ? 'n/a' : after.active && after.onScreen };
    // Закрываем, чтобы скриншот показывал саму страницу.
    if (after.active) { try { await page.tap('#sidebarOverlay'); } catch (e) {} await page.waitForTimeout(350); }
  }

  await page.screenshot({ path: path.join(SHOTS, `mobile-audit-${spec.name}.png`) });

  return { page: spec.name, url: spec.url, ...report, drawer, errors };
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  for (const spec of PAGES) {
    const ctx = await browser.newContext({ ...devices['Pixel 5'], hasTouch: true, isMobile: true });
    const page = await ctx.newPage();
    try {
      out.push(await auditPage(ctx, page, spec));
    } catch (e) {
      out.push({ page: spec.name, url: spec.url, fatal: e.message.split('\n')[0] });
    }
    await ctx.close();
  }
  await browser.close();

  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  for (const r of out) {
    if (r.fatal) { console.log(`FATAL ${r.page}: ${r.fatal}`); continue; }
    const bits = [
      `hScroll=${r.hScroll.overflow}`,
      `overflow=${r.overflowing.length}`,
      `smallTap=${r.smallTaps.length}`,
      `covered=${r.covered.length}`,
      `drawer=${r.drawer.present ? r.drawer.opens : 'none'}`,
      `errors=${r.errors.length}`,
    ];
    console.log(`${r.page.padEnd(9)} ${bits.join('  ')}`);
  }
})().catch(e => { console.error(e); process.exit(2); });
