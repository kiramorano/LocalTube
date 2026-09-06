// Проверка UI экспорта cookies из браузера на странице настроек.
// Запуск: LT_BASE=http://127.0.0.1:5004 node cookies-browser-ui.cjs
const { chromium } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';

// Перезагружает список с настоящего сервера после подменённого ответа.
// Ждём именно ответ сервера: loadBrowsers() завершается раньше, чем список
// перерисован, и без этого ожидания в списке оставались варианты заглушки.
async function loadListAgain(page, expected) {
  await Promise.all([
    page.waitForResponse(r => r.url().includes('/api/cookies/browsers') && r.ok()),
    page.evaluate(() => loadBrowsers()),
  ]);
  await page.waitForFunction(
    n => document.querySelectorAll('#cookieBrowser option').length === n,
    expected, { timeout: 10000 });
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  // Ниже намеренно проверяется ответ 400, и браузер сам пишет о нём в консоль.
  // Такое сообщение — не ошибка страницы, поэтому его не учитываем.
  const expectedNoise = /Failed to load resource/;
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !expectedNoise.test(m.text())) errors.push(m.text());
  });

  // Импорт из браузера не должен выполняться по-настоящему: он читает
  // профиль и перезаписывает cookies.txt. Перехватываем запрос.
  // Режим ответа переключается переменной: снимать и ставить обработчик
  // заново ненадёжно, старый остаётся в цепочке.
  let importPayload = null;
  let failNext = false;
  await page.route('**/api/cookies/from-browser', async route => {
    importPayload = JSON.parse(route.request().postData() || '{}');
    if (failNext) {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Google Chrome: не удалось расшифровать cookies.' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', cookies_count: 42, browser: importPayload.browser }),
    });
  });

  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });

  // Настройки разделены на разделы, cookies живут в «Загрузке». Без открытия
  // раздела элементы есть в разметке, но скрыты, и клик не проходит.
  await page.click('.tab-btn[data-tab="download"]');

  const select = page.locator('#cookieBrowser');
  if (!(await select.count())) throw new Error('нет выбора браузера на странице настроек');

  // Список должен подгрузиться с сервера, а не остаться заглушкой.
  await page.waitForFunction(
    () => document.querySelectorAll('#cookieBrowser option').length > 1,
    null, { timeout: 10000 });

  const options = await page.locator('#cookieBrowser option').evaluateAll(
    els => els.map(e => ({ value: e.value, text: e.textContent, disabled: e.disabled })));
  if (!options.some(o => o.value === 'firefox')) {
    throw new Error('в списке нет firefox: ' + JSON.stringify(options));
  }
  const enabled = options.filter(o => !o.disabled && o.value);
  if (!enabled.length) throw new Error('нет ни одного доступного браузера');
  // Ненайденные браузеры должны быть помечены и недоступны для выбора.
  const marked = options.filter(o => /не найден/.test(o.text));
  if (!marked.length) throw new Error('ни один отсутствующий браузер не помечен');
  for (const o of marked) {
    if (!o.disabled) throw new Error('отсутствующий браузер доступен для выбора: ' + o.value);
  }
  for (const o of options.filter(o => o.disabled)) {
    if (!/не найден/.test(o.text)) {
      throw new Error('отключённый браузер без пометки: ' + JSON.stringify(o));
    }
  }

  // Список с сервера отдаёт установленные первыми, поэтому «выбран
  // установленный» выполнилось бы и без явной установки value. Проверяем
  // отдельно на списке, где первым идёт отсутствующий браузер.
  // Подменяем ответ на уровне сети, а не window.fetch: подмена внутри
  // страницы оставляла в списке варианты из заглушки, потому что вернуть
  // настоящий fetch в finally недостаточно — список уже был перерисован.
  await page.route('**/api/cookies/browsers', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({browsers: [
        {name: 'safari', label: 'Safari', installed: false},
        {name: 'firefox', label: 'Firefox', installed: true},
      ]}),
    });
  });
  await page.evaluate(() => loadBrowsers());
  await page.waitForFunction(
    () => document.querySelectorAll('#cookieBrowser option').length === 2,
    null, { timeout: 10000 });
  const forcedOrder = await select.inputValue();
  // Возвращаем настоящий ответ сервера.
  await page.unroute('**/api/cookies/browsers');
  if (forcedOrder !== 'firefox') {
    throw new Error(`по умолчанию выбран недоступный браузер: ${forcedOrder}`);
  }

  await loadListAgain(page, options.length);
  // По умолчанию выбран установленный браузер.
  const selected = await select.inputValue();
  if (!enabled.some(o => o.value === selected)) {
    throw new Error(`по умолчанию выбран недоступный браузер: ${selected}`);
  }

  // Клик по кнопке отправляет выбранный браузер и показывает результат.
  // Ответ /api/auth/status задерживаем: обработчик кнопки тоже обновляет общий
  // статус, и без задержки гонка не видна — сообщение об успехе успевало
  // остаться на экране случайно.
  await page.route('**/api/auth/status', async route => {
    await new Promise(r => setTimeout(r, 400));
    await route.continue();
  });
  await page.locator('#importFromBrowser').click();
  await page.waitForFunction(
    () => /сохранены/.test(document.getElementById('status').textContent),
    null, { timeout: 10000 });
  // Сообщение должно остаться, а не мигнуть: authStatus() затирал его.
  await page.waitForTimeout(1200);
  const status = await page.locator('#status').textContent();
  if (!/сохранены/.test(status)) {
    throw new Error('сообщение об успехе затёрто обновлением статуса: ' + status);
  }
  if (!status.includes('42')) throw new Error('число cookies не показано: ' + status);
  if (!importPayload || importPayload.browser !== selected) {
    throw new Error('на сервер ушёл не тот браузер: ' + JSON.stringify(importPayload));
  }

  // Ошибка сервера должна доходить до пользователя.
  failNext = true;
  await page.locator('#importFromBrowser').click();
  await page.waitForFunction(
    () => /расшифровать/.test(document.getElementById('status').textContent),
    null, { timeout: 10000 });

  // Кнопка должна вернуться в рабочее состояние после ошибки.
  if (await page.locator('#importFromBrowser').isDisabled()) {
    throw new Error('кнопка осталась заблокированной после ошибки');
  }

  if (errors.length) throw new Error('ошибки на странице: ' + errors.join(' | '));

  console.log(JSON.stringify({
    browsers: options.length,
    installed: enabled.map(o => o.value),
    defaultSelected: selected,
  }, null, 2));
  console.log('cookies-browser-ui: OK');
  await browser.close();
})().catch(err => {
  console.error('cookies-browser-ui FAILED:', err.message);
  console.error(err.stack);
  process.exit(1);
});
