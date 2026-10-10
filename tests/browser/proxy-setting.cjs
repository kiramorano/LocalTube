// Проверка поля прокси в настройках: ввод сохраняется и виден после перезагрузки.
const { chromium } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';
let failed = 0;

function check(name, ok, detail) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name} :: ${detail}`);
  if (!ok) failed++;
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
  await page.click('.tab-btn[data-tab="download"]');

  const field = page.locator('#proxyInput');
  check('поле прокси есть в разделе «Загрузка»', await field.count() === 1,
    `найдено: ${await field.count()}`);
  check('поле видно пользователю', await field.isVisible(), 'visible');

  const label = await page.locator('label[for="proxyInput"]').textContent();
  check('подпись на русском', /прокси/i.test(label || ''), JSON.stringify(label));

  // Ввод без схемы: сервер должен дописать socks5.
  await field.fill('127.0.0.1:1080');
  await page.click('#save');
  await page.waitForTimeout(1200);

  const saved = await page.evaluate(async () => {
    const r = await fetch('/api/auth/options');
    return (await r.json()).proxy;
  });
  check('адрес сохранён с дописанной схемой', saved === 'socks5://127.0.0.1:1080', saved);

  await page.reload({ waitUntil: 'networkidle' });
  await page.click('.tab-btn[data-tab="download"]');
  const shown = await page.locator('#proxyInput').inputValue();
  check('после перезагрузки значение подставлено', shown === 'socks5://127.0.0.1:1080', shown);

  // Возвращаем как было: настройка общая для сервера.
  await page.locator('#proxyInput').fill('');
  await page.click('#save');
  await page.waitForTimeout(1200);
  const cleared = await page.evaluate(async () => {
    const r = await fetch('/api/auth/options');
    return (await r.json()).proxy;
  });
  check('пустое поле сбрасывает настройку', cleared === '', JSON.stringify(cleared));

  check('нет JS-ошибок', errors.length === 0, JSON.stringify(errors));

  await browser.close();
  console.log(`\n=== SUMMARY ===\n${6 - failed}/6 checks passed`);
  process.exit(failed ? 1 : 0);
})();
