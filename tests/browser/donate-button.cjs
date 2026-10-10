// Кнопка «Поддержать автора»: видимость, размер для пальца, безопасная ссылка.
const { chromium } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';
const URL = 'https://www.donationalerts.com/r/localteam';
let failed = 0;
let total = 0;

function check(name, ok, detail) {
  total++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name} :: ${detail}`);
  if (!ok) failed++;
}

// Контраст по WCAG: подпись на цветной кнопке должна читаться.
function luminance([r, g, b]) {
  const f = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function parseRgb(value) {
  const m = value.match(/\d+/g);
  return m ? m.slice(0, 3).map(Number) : [0, 0, 0];
}

function ratio(fg, bg) {
  const a = luminance(fg) + 0.05;
  const b = luminance(bg) + 0.05;
  return Math.round((Math.max(a, b) / Math.min(a, b)) * 100) / 100;
}

(async () => {
  const browser = await chromium.launch();
  const errors = [];

  // Панель есть на пяти страницах: пропуск в одной пользователь заметит как
  // исчезающую кнопку.
  const pages = ['/', '/upload'];
  for (const path of pages) {
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    page.on('pageerror', (e) => errors.push(`${path}: ${e}`));
    await page.goto(BASE + path, { waitUntil: 'networkidle' });

    const link = page.locator(`.sidebar-drawer a[href="${URL}"]`);
    check(`${path}: пункт есть в боковой панели`, await link.count() === 1,
      `найдено: ${await link.count()}`);
    check(`${path}: пункт видно`, await link.isVisible(), 'visible');

    const box = await link.boundingBox();
    check(`${path}: высота пригодна для нажатия`, box && box.height >= 32,
      `высота: ${box ? Math.round(box.height) : 'нет'}`);

    const attrs = await link.evaluate((el) => ({
      target: el.getAttribute('target'), rel: el.getAttribute('rel'),
      text: el.textContent.trim(),
    }));
    check(`${path}: открывается в новой вкладке`, attrs.target === '_blank', attrs.target);
    check(`${path}: rel защищает от window.opener`, /noopener/.test(attrs.rel || ''), attrs.rel);
    check(`${path}: подпись на месте`, attrs.text.length > 0, JSON.stringify(attrs.text));
    await page.close();
  }

  // Настройки: кнопка в разделе «Профиль», контраст подписи.
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  page.on('pageerror', (e) => errors.push(`settings: ${e}`));
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });

  const btn = page.locator(`a[href="${URL}"]`);
  check('настройки: кнопка есть', await btn.count() === 1, `найдено: ${await btn.count()}`);
  check('настройки: кнопка видна', await btn.isVisible(), 'visible');

  const colors = await btn.evaluate((el) => {
    const s = getComputedStyle(el);
    return { color: s.color, bg: s.backgroundColor };
  });
  const contrast = ratio(parseRgb(colors.color), parseRgb(colors.bg));
  check('настройки: контраст подписи не ниже 4.5', contrast >= 4.5, `${contrast}`);

  // Телефон: площадь под палец не меньше 44px, как у остальных кнопок.
  await page.setViewportSize({ width: 390, height: 780 });
  await page.waitForTimeout(300);
  const narrow = await btn.boundingBox();
  check('настройки: на телефоне высота не меньше 44', narrow && narrow.height >= 44,
    `высота: ${narrow ? Math.round(narrow.height) : 'нет'}`);
  const centered = await btn.evaluate((el) => {
    const s = getComputedStyle(el);
    // При min-height текст прижимается к верху, если не выровнен по центру.
    return { align: s.alignItems, display: s.display, lh: s.lineHeight, h: s.height };
  });
  check('настройки: подпись не прижата к краю',
    centered.display.includes('flex') || parseFloat(centered.h) <= 46,
    JSON.stringify(centered));
  await page.setViewportSize({ width: 1400, height: 900 });

  // Переход: настоящий сайт не открываем, проверяем только адрес запроса.
  const [popup] = await Promise.all([
    page.waitForEvent('popup'),
    page.route('**donationalerts.com**', (r) => r.fulfill({ status: 200, body: 'ok' })),
    btn.click(),
  ]);
  check('настройки: открывается адрес автора', popup.url().startsWith(URL), popup.url());
  await popup.close();

  check('нет JS-ошибок', errors.length === 0, JSON.stringify(errors));

  await browser.close();
  console.log(`\n=== SUMMARY ===\n${total - failed}/${total} checks passed`);
  process.exit(failed ? 1 : 0);
})();
