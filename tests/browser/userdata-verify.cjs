// Проверка серверного хранения избранного, истории и скрытых каналов.
// Ключевой сценарий — миграция из localStorage: данные не должны потеряться.
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

async function resetServerData(page) {
  for (const section of ['favorites', 'history', 'hidden_channels']) {
    await page.request.post(`${BASE}/api/userdata/clear/${section}`);
  }
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  // ---------- 1. Миграция из localStorage ----------
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await resetServerData(page);

  const ids = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('.video-card, .short-card'));
    return cards.map(c => c.dataset.id || c.getAttribute('data-id')).filter(Boolean);
  });
  check('на странице есть видео', ids.length > 0, `найдено ${ids.length}`);

  // Кнопка избранного есть только у обычных карточек, у Shorts её нет.
  const favIds = await page.evaluate(() => Array.from(
    document.querySelectorAll('.video-card[data-id]')).map(c => c.getAttribute('data-id')));
  check('есть карточка с кнопкой избранного', favIds.length > 0, `найдено ${favIds.length}`);

  const legacyFav = favIds[0] || ids[0];
  await page.evaluate((fav) => {
    localStorage.setItem('lt_favorites', JSON.stringify([fav]));
    localStorage.setItem('lt_history', JSON.stringify(['legacy_watched']));
    localStorage.setItem('lt_hidden_channels', JSON.stringify(['Legacy Channel']));
  }, legacyFav);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  const afterMigration = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
  check('избранное перенесено на сервер',
    afterMigration.favorites.includes(legacyFav),
    JSON.stringify(afterMigration.favorites));
  check('история перенесена на сервер',
    afterMigration.history.includes('legacy_watched'),
    JSON.stringify(afterMigration.history));
  check('скрытые каналы перенесены на сервер',
    afterMigration.hidden_channels.includes('Legacy Channel'),
    JSON.stringify(afterMigration.hidden_channels));

  const legacyCleared = await page.evaluate(() => ({
    fav: localStorage.getItem('lt_favorites'),
    hist: localStorage.getItem('lt_history'),
    hidden: localStorage.getItem('lt_hidden_channels'),
    backup: localStorage.getItem('lt_migration_backup'),
  }));
  check('localStorage очищен после переноса',
    !legacyCleared.fav && !legacyCleared.hist && !legacyCleared.hidden,
    JSON.stringify(legacyCleared).slice(0, 120));
  check('бэкап миграции сохранён', !!legacyCleared.backup);

  // ---------- 2. Избранное сохраняется между устройствами ----------
  await resetServerData(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  const favBtn = page.locator(`.video-card[data-id="${legacyFav}"] .fav-btn`).first();
  if (await favBtn.count()) {
    await favBtn.click();
    await page.waitForTimeout(600);
    const state = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
    check('клик по звезде сохраняется на сервере',
      state.favorites.includes(legacyFav), JSON.stringify(state.favorites));

    // Новый контекст = другое устройство с пустым localStorage.
    const other = await browser.newContext();
    const otherPage = await other.newPage();
    await otherPage.goto(BASE, { waitUntil: 'domcontentloaded' });
    await otherPage.waitForTimeout(1200);
    const marked = await otherPage.evaluate((id) => {
      const btn = document.querySelector(`.video-card[data-id="${id}"] .fav-btn`);
      return btn ? btn.classList.contains('fav-active') : null;
    }, legacyFav);
    check('избранное видно на другом устройстве', marked === true, `fav-active=${marked}`);

    const stillThere = await otherPage.request.get(`${BASE}/api/userdata`).then(r => r.json());
    check('пустой localStorage не стёр серверные данные',
      stillThere.favorites.includes(legacyFav), JSON.stringify(stillThere.favorites));
    await otherPage.screenshot({ path: path.join(SHOTS, 'userdata-other-device.png') });
    await other.close();
  } else {
    check('кнопка избранного найдена', false, 'нет .fav-btn на карточке');
  }

  // ---------- 3. История пополняется при открытии видео ----------
  await resetServerData(page);
  const watchTarget = ids[0];
  await page.goto(`${BASE}/watch/${watchTarget}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  const histState = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
  check('открытие видео попадает в историю',
    histState.history.includes(watchTarget), JSON.stringify(histState.history));

  // ---------- 4. Скрытие канала переживает перезагрузку ----------
  await resetServerData(page);
  const hideRes = await page.request.post(`${BASE}/api/userdata/hidden-channel`,
    { data: { author: 'Avocado Animations' } }).then(r => r.json());
  check('канал скрыт через API', hideRes.hidden === true);

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  const hiddenVisible = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('#hiddenChannelsList .hidden-channel-item'));
    return items.map(i => i.textContent.trim());
  });
  check('скрытый канал показан в списке настроек',
    hiddenVisible.some(t => t.includes('Avocado Animations')),
    JSON.stringify(hiddenVisible));

  const hiddenCardsShown = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('.video-card'));
    return cards.filter(c => c.getAttribute('data-author') === 'Avocado Animations'
      && c.style.display !== 'none').length;
  });
  check('видео скрытого канала не показываются', hiddenCardsShown === 0,
    `видимых карточек: ${hiddenCardsShown}`);

  // ---------- 5. Данные переживают перезапуск (файл на диске) ----------
  const onDisk = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
  check('состояние сохранено с отметкой времени', onDisk.updated_at > 0,
    `updated_at=${onDisk.updated_at}`);

  await page.screenshot({ path: path.join(SHOTS, 'userdata-index.png'), fullPage: true });

  // ---------- 6. Гонка: клик сразу после загрузки страницы ----------
  // Раньше клик до ответа /api/userdata инвертировал состояние на сервере:
  // клиент видел пустой список и просил «переключить», а сервер снимал отметку.
  await resetServerData(page);
  await page.request.post(`${BASE}/api/userdata/favorite/${legacyFav}`,
    { data: { active: true } });

  const raceContext = await browser.newContext();
  const racePage = await raceContext.newPage();
  const raceErrors = [];
  racePage.on('pageerror', e => raceErrors.push(e.message));
  // Задерживаем ответ, чтобы клик гарантированно случился раньше загрузки.
  await racePage.route('**/api/userdata', async route => {
    await new Promise(r => setTimeout(r, 1500));
    await route.continue();
  });
  await racePage.goto(BASE, { waitUntil: 'domcontentloaded' });
  // Вызываем обработчик напрямую: карточки в это время скрыты маскировкой,
  // поэтому обычный клик до них не доходит (это тоже часть защиты).
  const raceCallResult = await racePage.evaluate((id) => {
    if (typeof toggleFav !== 'function') return 'no-function';
    const btn = document.querySelector(`.video-card[data-id="${id}"] .fav-btn`);
    // Не ждём промис: имитируем нажатие в момент, когда данные ещё не пришли.
    toggleFav(id, btn);
    return 'called';
  }, legacyFav);
  check('обработчик избранного доступен во время загрузки',
    raceCallResult === 'called', raceCallResult);
  await racePage.waitForTimeout(3000);

  const raceState = await racePage.request.get(`${BASE}/api/userdata`).then(r => r.json());
  // Видео было в избранном, нажатие должно его убрать, а не добавить повторно.
  check('нажатие до загрузки данных снимает избранное корректно',
    !raceState.favorites.includes(legacyFav),
    JSON.stringify(raceState.favorites));

  const raceUiMatches = await racePage.evaluate((id) => {
    const btn = document.querySelector(`.video-card[data-id="${id}"] .fav-btn`);
    return btn ? btn.classList.contains('fav-active') : null;
  }, legacyFav);
  check('состояние звезды совпадает с сервером', raceUiMatches === false,
    `fav-active=${raceUiMatches}, сервер=${raceState.favorites.includes(legacyFav)}`);
  check('нет JS-ошибок при гонке', raceErrors.length === 0, raceErrors.join(' | ').slice(0, 150));
  await raceContext.close();

  // ---------- 7. Скрытые каналы не мигают при загрузке ----------
  // Карточки фильтруются на сервере, поэтому скрытого канала нет в разметке
  // с самого начала — даже если запрос /api/userdata медленный.
  await resetServerData(page);
  await page.request.post(`${BASE}/api/userdata/hidden-channel`,
    { data: { author: 'Avocado Animations', hidden: true } });

  const flashContext = await browser.newContext();
  const flashPage = await flashContext.newPage();
  await flashPage.route('**/api/userdata', async route => {
    await new Promise(r => setTimeout(r, 1200));
    await route.continue();
  });
  await flashPage.goto(BASE, { waitUntil: 'domcontentloaded' });

  const immediate = await flashPage.evaluate(() => {
    const grid = document.getElementById('mainGrid');
    return {
      visibility: grid ? getComputedStyle(grid).visibility : 'no-grid',
      hiddenCards: Array.from(document.querySelectorAll('[data-author]'))
        .filter(c => c.getAttribute('data-author') === 'Avocado Animations').length,
    };
  });
  check('контент виден сразу, без ожидания запроса',
    immediate.visibility === 'visible', `visibility=${immediate.visibility}`);
  check('скрытый канал отсутствует в разметке с самого начала',
    immediate.hiddenCards === 0, `карточек: ${immediate.hiddenCards}`);

  await flashPage.waitForTimeout(2000);
  const afterLoad = await flashPage.evaluate(() =>
    Array.from(document.querySelectorAll('[data-author]'))
      .filter(c => c.getAttribute('data-author') === 'Avocado Animations'
        && getComputedStyle(c).display !== 'none').length);
  check('скрытый канал не появился после загрузки', afterLoad === 0,
    `карточек: ${afterLoad}`);
  await flashContext.close();

  // ---------- 8. Контент показывается даже если запрос упал ----------
  const failContext = await browser.newContext();
  const failPage = await failContext.newPage();
  await failPage.route('**/api/userdata', route => route.abort());
  await failPage.goto(BASE, { waitUntil: 'domcontentloaded' });
  await failPage.waitForTimeout(2000);
  const shownDespiteError = await failPage.evaluate(() => {
    const grid = document.getElementById('mainGrid');
    return grid ? getComputedStyle(grid).visibility : 'no-grid';
  });
  check('контент виден несмотря на сбой запроса', shownDespiteError === 'visible',
    `visibility=${shownDespiteError}`);
  await failContext.close();

  // ---------- 9. Очистка данных из настроек ----------
  await resetServerData(page);
  await page.request.post(`${BASE}/api/userdata/favorite/${legacyFav}`, { data: { active: true } });
  await page.request.post(`${BASE}/api/userdata/watched/somevid`);

  await page.goto(`${BASE}/settings`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  const summary = await page.locator('#userdataSummary').textContent();
  check('настройки показывают счётчики данных',
    /избранном 1/.test(summary) && /истории 1/.test(summary), summary);

  page.once('dialog', d => d.accept());
  await page.locator('#clearHistory').click();
  await page.waitForTimeout(800);
  const afterClear = await page.request.get(`${BASE}/api/userdata`).then(r => r.json());
  check('кнопка очищает историю', afterClear.history.length === 0,
    JSON.stringify(afterClear.history));
  check('очистка истории не тронула избранное',
    afterClear.favorites.includes(legacyFav), JSON.stringify(afterClear.favorites));

  await page.screenshot({ path: path.join(SHOTS, 'userdata-settings.png'), fullPage: true });

  // ---------- 10. Отсутствие JS-ошибок ----------
  check('нет JS-ошибок на страницах', errors.length === 0, errors.join(' | ').slice(0, 200));

  // Возвращаем чистое состояние.
  await resetServerData(page);
  await browser.close();

  const failed = results.filter(r => !r.ok);
  console.log('\n=== SUMMARY ===');
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
