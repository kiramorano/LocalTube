// Проверка серверной фильтрации скрытых каналов и кнопки на странице канала.
// Раньше скрытие работало только в браузере: сервер продолжал отдавать видео.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = 'http://127.0.0.1:5000';
const SHOTS = path.join(__dirname, 'shots');
if (!fs.existsSync(SHOTS)) fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.request.post(`${BASE}/api/userdata/clear/hidden_channels`);

  // Выбираем канал, у которого есть карточки на главной.
  await page.reload({ waitUntil: 'domcontentloaded' });
  const authors = await page.evaluate(() => Array.from(new Set(
    Array.from(document.querySelectorAll('[data-author]'))
      .map(c => c.getAttribute('data-author')))));
  check('на главной есть карточки с авторами', authors.length > 0, JSON.stringify(authors));
  const target = authors[0];

  // ---------- 1. Кнопка на странице канала ----------
  await page.goto(`${BASE}/channel/${encodeURIComponent(target)}`,
    { waitUntil: 'domcontentloaded' });
  const btn = page.locator('#hideChannelBtn');
  check('кнопка скрытия есть на странице канала', await btn.count() === 1);
  check('надпись кнопки — Скрыть канал',
    (await btn.textContent()).trim() === 'Скрыть канал', await btn.textContent());
  check('aria-pressed отражает состояние',
    await btn.getAttribute('aria-pressed') === 'false');

  await btn.click();
  await page.waitForTimeout(900);
  check('после нажатия надпись меняется',
    (await btn.textContent()).trim() === 'Показать канал', await btn.textContent());
  check('aria-pressed стал true',
    await btn.getAttribute('aria-pressed') === 'true');

  const state = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
  check('канал скрыт на сервере', state.hidden_channels.includes(target),
    JSON.stringify(state.hidden_channels));

  await page.screenshot({ path: path.join(SHOTS, 'channel-hide-button.png') });

  // ---------- 2. Сервер больше не отдаёт видео скрытого канала ----------
  const catalog = await page.request.get(`${BASE}/api/catalog`).then(r => r.json());
  const catalogAuthors = [...new Set(catalog.videos.concat(catalog.shorts).map(v => v.author))];
  check('каталог не содержит скрытый канал', !catalogAuthors.includes(target),
    JSON.stringify(catalogAuthors));
  check('скрытый канал убран из списка авторов',
    !catalog.authors.some(a => a.name === target),
    JSON.stringify(catalog.authors.map(a => a.name)));

  const search = await page.request
    .get(`${BASE}/api/search?q=${encodeURIComponent(target)}`).then(r => r.json());
  check('поиск не находит видео скрытого канала',
    !search.results.some(r => r.author === target),
    `найдено ${search.results.length}`);

  const inclusive = await page.request
    .get(`${BASE}/api/catalog?include_hidden=1`).then(r => r.json());
  check('include_hidden=1 возвращает скрытый канал',
    inclusive.authors.some(a => a.name === target),
    JSON.stringify(inclusive.authors.map(a => a.name)));

  // ---------- 3. Главная не рендерит карточки скрытого канала ----------
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  const renderedAuthors = await page.evaluate(() => Array.from(new Set(
    Array.from(document.querySelectorAll('[data-author]'))
      .map(c => c.getAttribute('data-author')))));
  check('карточки скрытого канала не отрендерены',
    !renderedAuthors.includes(target), JSON.stringify(renderedAuthors));

  // Список для сайдбара всё равно должен приходить.
  const sidebarHidden = await page.evaluate(() => Array.from(
    document.querySelectorAll('#hiddenChannelsList .hidden-channel-item'))
    .map(i => i.textContent.trim()));
  check('скрытый канал показан в сайдбаре',
    sidebarHidden.some(t => t.includes(target)), JSON.stringify(sidebarHidden));

  // ---------- 4. Никакой вспышки: сетка видима сразу ----------
  const visibility = await page.evaluate(() => {
    const grid = document.getElementById('mainGrid');
    return grid ? getComputedStyle(grid).visibility : 'no-grid';
  });
  check('сетка видима без ожидания запроса', visibility === 'visible', visibility);

  // ---------- 5. Возврат канала через сайдбар ----------
  // Сайдбар — выдвижная панель за левым краем экрана, её нужно открыть.
  await page.locator('#sidebarToggle').click();
  await page.waitForTimeout(500);

  const unhideBtn = page.locator('#hiddenChannelsList .unhide-btn').first();
  if (await unhideBtn.count()) {
    await unhideBtn.scrollIntoViewIfNeeded();
    await unhideBtn.click();
    await page.waitForTimeout(900);
    const after = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
    check('канал возвращён через сайдбар', !after.hidden_channels.includes(target),
      JSON.stringify(after.hidden_channels));
  } else {
    check('кнопка возврата найдена', false, 'нет .unhide-btn');
  }

  // ---------- 6. Страница скрытого канала остаётся рабочей ----------
  await page.request.post(`${BASE}/api/userdata/hidden-channel`,
    { data: { author: target, hidden: true } });
  const channelRes = await page.goto(`${BASE}/channel/${encodeURIComponent(target)}`,
    { waitUntil: 'domcontentloaded' });
  check('страница скрытого канала открывается', channelRes.status() === 200,
    `status=${channelRes.status()}`);
  const ownVideos = await page.evaluate(() =>
    document.querySelectorAll('#videosGrid a, #shortsGrid a').length);
  check('на странице канала видео видны', ownVideos > 0, `видео: ${ownVideos}`);

  check('нет JS-ошибок', errors.length === 0, errors.join(' | ').slice(0, 200));

  await page.request.post(`${BASE}/api/userdata/clear/hidden_channels`);
  await browser.close();

  const failed = results.filter(r => !r.ok);
  console.log('\n=== SUMMARY ===');
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
