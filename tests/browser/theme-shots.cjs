// Скриншоты тем для визуальной проверки редизайна.
//
// Тесты считают контраст и геометрию, но не показывают, выглядит ли интерфейс
// цельным. Этот скрипт снимает главную, настройки и страницу канала в каждой
// теме, чтобы результат можно было посмотреть глазами.
//
// Требуется запущенный сервер: LT_BASE=http://127.0.0.1:5004
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';
const OUT = path.join(__dirname, 'shots', 'themes');
const THEMES = ['dark', 'light', 'midnight', 'glass', 'frutiger-aero'];
const PAGES = [['/', 'home'], ['/settings', 'settings']];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  for (const theme of THEMES) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    // addInitScript, а не evaluate после перехода: тема должна стоять до
    // первой отрисовки, иначе на снимке окажется кадр стандартной тёмной.
    await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    for (const [url, name] of PAGES) {
      await page.goto(BASE + url, { waitUntil: 'networkidle' });
      await page.waitForTimeout(theme === 'frutiger-aero' ? 2500 : 600);
      await page.screenshot({ path: path.join(OUT, `${theme}-${name}.png`) });
      console.log(`снят ${theme}-${name}.png`);
    }
    await context.close();
  }
  await browser.close();
})().catch(err => {
  console.error(err.stack || err);
  process.exitCode = 1;
});
