// Загрузка по ссылке из хедера главной страницы.
//
// Разметку поля ввода однажды потеряли при переписывании главной: CSS остался,
// а поля и кнопки не было — скачать видео через интерфейс стало нечем. Этот
// скрипт проверяет весь путь: валидацию ссылки, сборку format_id по качеству,
// отправку в очередь, Enter и доступность поля на узком экране.
const { chromium } = require('playwright');
const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';

(async () => {
  const browser = await chromium.launch();
  let failures = 0;
  const check = (name, ok, extra) => {
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${name}${extra ? ' | ' + extra : ''}`);
    if (!ok) failures++;
  };

  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  // Очередь подменяем: настоящую задачу создавать не нужно, важна нагрузка.
  let captured = null;
  let addCalls = 0;
  await page.route('**/api/queue/add', async route => {
    addCalls++;
    captured = JSON.parse(route.request().postData() || '{}');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ task_id: 'browser-test' }),
    });
  });
  await page.route('**/api/queue/list', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ tasks: [], paused: false }),
  }));

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);

  check('поле ввода ссылки видно', await page.isVisible('#urlInput'));
  check('кнопка загрузки видна', await page.isVisible('#downloadBtn'));
  check('селект качества виден', await page.isVisible('#urlQuality'));

  // Пустое поле не должно ничего отправлять.
  await page.click('#downloadBtn');
  await page.waitForTimeout(400);
  check('пустое поле не уходит в очередь', addCalls === 0, `вызовов=${addCalls}`);

  // Мусор вместо ссылки: ошибка сразу, запроса нет.
  await page.fill('#urlInput', 'какой-то текст');
  await page.click('#downloadBtn');
  await page.waitForTimeout(500);
  check('не-ссылка не уходит в очередь', addCalls === 0, `вызовов=${addCalls}`);
  check('показано сообщение об ошибке',
        (await page.locator('.toast').count()) > 0);

  // TikTok-ролик должен уходить в очередь так же, как YouTube.
  captured = null;
  await page.fill('#urlInput', 'https://www.tiktok.com/@creator/video/7461234567890123456');
  await page.click('#downloadBtn');
  await page.waitForResponse(r => r.url().includes('/api/queue/add'), { timeout: 10000 });
  await page.waitForTimeout(400);
  check('ссылка TikTok отправлена в очередь', addCalls === 1, `вызовов=${addCalls}`);
  check('ссылка TikTok передана верно',
        JSON.stringify(captured && captured.urls) ===
        JSON.stringify(['https://www.tiktok.com/@creator/video/7461234567890123456']),
        JSON.stringify(captured));
  check('TikTok не получает селектор YouTube',
        captured && captured.format_id === undefined, JSON.stringify(captured));

  // Рабочая ссылка с выбранным качеством.
  await page.selectOption('#urlQuality', '720');
  await page.fill('#urlInput', 'https://www.youtube.com/watch?v=jNQXAC9IVRw');
  await page.click('#downloadBtn');
  await page.waitForResponse(r => r.url().includes('/api/queue/add'), { timeout: 10000 });
  await page.waitForTimeout(500);
  check('ссылка отправлена в очередь', addCalls === 2, `вызовов=${addCalls}`);
  check('ссылка передана верно',
        JSON.stringify(captured && captured.urls) ===
        JSON.stringify(['https://www.youtube.com/watch?v=jNQXAC9IVRw']),
        JSON.stringify(captured));
  check('качество ушло в format_id',
        captured && captured.format_id === 'bestvideo[height<=720]+bestaudio/best',
        captured && captured.format_id);
  check('поле очистилось', (await page.inputValue('#urlInput')) === '');
  check('очередь показана после добавления', await page.isVisible('#queueContainer'));

  // Максимальное качество: format_id не передаём вовсе.
  captured = null;
  await page.selectOption('#urlQuality', 'best');
  await page.fill('#urlInput', 'https://youtu.be/jNQXAC9IVRw');
  await page.press('#urlInput', 'Enter');
  await page.waitForResponse(r => r.url().includes('/api/queue/add'), { timeout: 10000 });
  await page.waitForTimeout(400);
  check('Enter в поле запускает загрузку', addCalls === 3, `вызовов=${addCalls}`);
  check('короткая ссылка youtu.be принята',
        JSON.stringify(captured && captured.urls) ===
        JSON.stringify(['https://youtu.be/jNQXAC9IVRw']), JSON.stringify(captured));
  check('при «Максимум» format_id не передаётся',
        captured && captured.format_id === undefined,
        JSON.stringify(captured));

  // Ошибка сервера не должна выглядеть как успех.
  await page.unroute('**/api/queue/add');
  await page.route('**/api/queue/add', route => route.fulfill({
    status: 500,
    contentType: 'application/json',
    body: JSON.stringify({ error: 'очередь недоступна' }),
  }));
  await page.fill('#urlInput', 'https://www.youtube.com/watch?v=jNQXAC9IVRw');
  await page.click('#downloadBtn');
  await page.waitForTimeout(900);
  check('ошибка сервера показана пользователю',
        (await page.locator('.toast', { hasText: 'очередь недоступна' }).count()) > 0);
  check('ссылка сохранена для повтора',
        (await page.inputValue('#urlInput')) !== '');
  check('кнопка снова активна',
        await page.isEnabled('#downloadBtn'));

  // Ссылка на страницу загрузки своего файла.
  check('в навигации есть ссылка на /upload',
        (await page.locator('.sidebar-drawer a[href="/upload"]').count()) > 0);

  // Узкий экран: поле обязано остаться доступным и не выезжать за границы.
  const mobile = await browser.newPage({ viewport: { width: 390, height: 780 } });
  const mobileErrors = [];
  mobile.on('pageerror', e => mobileErrors.push(e.message));
  await mobile.goto(BASE, { waitUntil: 'domcontentloaded' });
  await mobile.waitForTimeout(600);
  check('поле ввода видно на мобильной ширине', await mobile.isVisible('#urlInput'));
  check('кнопка видна на мобильной ширине', await mobile.isVisible('#downloadBtn'));
  const box = await mobile.locator('.search-container').boundingBox();
  check('строка ввода не выходит за экран',
        box !== null && box.x + box.width <= 390 + 1,
        box && `right=${Math.round(box.x + box.width)}`);

  // Поле в хедере уже сжимало гамбургер до нулевой ширины: меню на телефоне
  // становилось некликабельным. Проверяем, что кнопка меню осталась рабочей.
  const toggle = await mobile.locator('#sidebarToggle').boundingBox();
  check('гамбургер не сжат полем ввода',
        toggle !== null && toggle.width >= 20,
        toggle && `width=${Math.round(toggle.width)}`);
  await mobile.click('#sidebarToggle');
  await mobile.waitForTimeout(500);
  const drawerLeft = await mobile.evaluate(
    () => Math.round(document.getElementById('sidebarDrawer').getBoundingClientRect().left));
  check('гамбургер открывает меню на телефоне', drawerLeft === 0, `left=${drawerLeft}`);

  check('нет ошибок JS на десктопе', errors.length === 0, errors.join('; '));
  check('нет ошибок JS на мобильной версии', mobileErrors.length === 0,
        mobileErrors.join('; '));

  await browser.close();
  if (failures) {
    console.log(`\n${failures} проверок провалено`);
    process.exitCode = 1;
  } else {
    console.log('\nвсе проверки загрузки по ссылке прошли');
  }
})().catch(err => {
  console.error(err.stack || err);
  process.exitCode = 1;
});
