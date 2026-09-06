// Проверка своих плейлистов: боковое меню, окно выбора на странице видео,
// страница плейлиста.
// Запуск: LT_BASE=http://127.0.0.1:5004 node collections-ui.cjs
//
// Сервер должен быть запущен через serve_test.py: он изолирует userdata.json,
// иначе проверка создаст плейлисты в настоящих данных пользователя.
const { chromium } = require('playwright');
const { requireTestServer } = require('./require-test-server.cjs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';

let passed = 0;
const failures = [];
function check(name, condition, detail) {
  if (condition) { passed++; return; }
  failures.push(`${name}${detail ? ': ' + detail : ''}`);
}

// Метка прогона: своя на каждый запуск, иначе повторный прогон находил
// плейлист от прошлого раза и проверки счётчиков врали.
const stamp = Date.now().toString().slice(-6);

// Убирает всё, что создал прогон. Вызывается и при падении: свои плейлисты
// живут в userdata.json и после прерванного запуска остаются мусором.
async function cleanup(page) {
  return page.evaluate(async ([base, mark]) => {
    const res = await fetch(base + '/api/collections');
    const items = (await res.json()).collections || [];
    for (const c of items.filter(c => c.title.includes(mark))) {
      await fetch(`${base}/api/collections/${encodeURIComponent(c.id)}`, { method: 'DELETE' });
    }
    // «Смотреть позже» удалить нельзя, поэтому только вынимаем добавленное.
    const later = items.find(c => c.id === 'watch-later');
    if (later) {
      for (const vid of later.videos || []) {
        await fetch(`${base}/api/collections/watch-later/videos/${encodeURIComponent(vid)}`,
          { method: 'DELETE' });
      }
    }
    const after = await fetch(base + '/api/collections');
    return ((await after.json()).collections || []).filter(c => c.title.includes(mark)).length;
  }, [BASE, stamp]);
}

(async () => {
  await requireTestServer(BASE, ['userdata']);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  const expectedNoise = /Failed to load resource|net::ERR/;
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !expectedNoise.test(m.text())) errors.push(m.text());
  });

  // ===== Боковое меню на главной =====
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  check('есть место под плейлисты', await page.$('#sidebarCollections') !== null);
  check('есть кнопка создания', await page.$('#createCollectionBtn') !== null);

  // Создание через prompt: диалог принимаем с названием, в котором есть кавычка
  // и угловая скобка — так проверяем, что название не ломает разметку.
  const tricky = `Тест "плейлист" <b> ${stamp}`;
  page.once('dialog', d => d.accept(tricky));
  await page.click('#createCollectionBtn');
  await page.waitForTimeout(700);
  const titles = await page.$$eval('#sidebarCollections .sidebar-item span', els => els.map(e => e.textContent.trim()));
  check('плейлист появился в меню', titles.some(t => t.includes(tricky)), `в меню: ${JSON.stringify(titles)}`);
  const brokenMarkup = await page.$$eval('#sidebarCollections b', els => els.length);
  check('название не превратилось в разметку', brokenMarkup === 0, `нашлось <b>: ${brokenMarkup}`);

  // Пустое название отклоняем на сервере, в меню ничего не добавляется.
  const before = (await page.$$('#sidebarCollections .sidebar-item')).length;
  page.once('dialog', d => d.accept('   '));
  await page.click('#createCollectionBtn');
  await page.waitForTimeout(600);
  const after = (await page.$$('#sidebarCollections .sidebar-item')).length;
  check('пустое название не создаёт плейлист', after === before, `было ${before}, стало ${after}`);

  // ===== Окно выбора на странице видео =====
  const firstVideo = await page.$eval('.video-card a, a.video-card', el => el.getAttribute('href')).catch(() => null);
  if (!firstVideo) {
    check('на главной есть хотя бы одно видео', false, 'не нашлось ссылки на видео');
  } else {
    await page.goto(`${BASE}${firstVideo}`, { waitUntil: 'networkidle' });
    check('кнопка «Сохранить» видна', await page.isVisible('#saveToCollectionBtn'));
    // Окно скрыто через opacity и pointer-events, а не display: isVisible на
    // такой элемент отвечает true, поэтому смотрим на класс.
    const modalOpen = () => page.$eval('#collectionModal', el => el.classList.contains('active'));
    check('окно закрыто до нажатия', !(await modalOpen()));

    await page.click('#saveToCollectionBtn');
    await page.waitForTimeout(600);
    check('окно открылось', await modalOpen());
    const options = await page.$$eval('.collection-option span', els => els.map(e => e.textContent.trim()));
    check('в окне есть созданный плейлист', options.some(t => t.includes(tricky)),
      `варианты: ${JSON.stringify(options)}`);

    // Добавляем видео и проверяем, что счётчик вырос ровно на единицу.
    // Ищем строку своего плейлиста по названию: порядок в списке не задан, а
    // «Смотреть позже» мог накопить видео от прошлых прогонов.
    const row = page.locator('.collection-option', { hasText: stamp }).first();
    const box = row.locator('input');
    const labelBefore = (await row.locator('span').textContent()).trim();
    const countBefore = Number((labelBefore.match(/\((\d+)\)$/) || [0, 0])[1]);
    check('галочка снята до сохранения', !(await box.isChecked()));
    await box.check();
    await page.waitForTimeout(700);
    check('галочка осталась стоять', await box.isChecked());
    const labelAfter = (await row.locator('span').textContent()).trim();
    const countAfter = Number((labelAfter.match(/\((\d+)\)$/) || [0, 0])[1]);
    check('счётчик вырос на одно видео', countAfter === countBefore + 1,
      `было ${countBefore} (${labelBefore}), стало ${countAfter} (${labelAfter})`);

    // «Смотреть позже» создаётся сама при первом обращении.
    await page.click('#watchLaterBtn');
    await page.waitForTimeout(800);
    const afterLater = await page.$$eval('.collection-option span', els => els.map(e => e.textContent.trim()));
    check('появился «Смотреть позже»', afterLater.some(t => t.includes('Смотреть позже')),
      `варианты: ${JSON.stringify(afterLater)}`);

    // Создание нового плейлиста прямо из окна кладёт в него текущее видео.
    const fromModal = `Из окна ${stamp}`;
    await page.fill('#collectionNewTitle', fromModal);
    await page.click('#collectionCreate');
    await page.waitForTimeout(900);
    const created = await page.$$eval('.collection-option span', els => els.map(e => e.textContent.trim()));
    check('новый плейлист создан из окна', created.some(t => t.startsWith(fromModal)),
      `варианты: ${JSON.stringify(created)}`);
    check('видео сразу попало в новый плейлист', created.some(t => t.startsWith(fromModal) && /\(1\)/.test(t)),
      `варианты: ${JSON.stringify(created)}`);

    // Пустое название в окне не создаёт плейлист, а показывает подсказку.
    const optsBefore = (await page.$$('.collection-option')).length;
    await page.fill('#collectionNewTitle', '   ');
    await page.click('#collectionCreate');
    await page.waitForTimeout(500);
    const optsAfter = (await page.$$('.collection-option')).length;
    check('пустое название в окне отклонено', optsAfter === optsBefore,
      `было ${optsBefore}, стало ${optsAfter}`);
    check('показана причина отказа', (await page.textContent('#collectionModalStatus')).trim().length > 0);

    await page.click('#collectionModalClose');
    await page.waitForTimeout(300);
    check('окно закрылось', !(await modalOpen()));
    // Закрытое окно не должно перехватывать клики по странице.
    const blocks = await page.$eval('#collectionModal', el => getComputedStyle(el).pointerEvents);
    check('закрытое окно не ловит клики', blocks === 'none', `pointer-events: ${blocks}`);
  }

  // ===== Страница плейлиста =====
  const list = await page.evaluate(async base => {
    const res = await fetch(base + '/api/collections');
    return (await res.json()).collections || [];
  }, BASE);
  const own = list.find(c => c.title.startsWith(`Из окна ${stamp}`));
  check('плейлист «Из окна» есть в API', own !== undefined);

  if (own) {
    await page.goto(`${BASE}/collection/${own.id}`, { waitUntil: 'networkidle' });
    check('заголовок плейлиста показан', (await page.textContent('#collectionTitle')).includes(stamp));
    const rows = await page.$$('.video-row');
    check('видео показано в плейлисте', rows.length === 1, `строк: ${rows.length}`);
    check('есть кнопка просмотра', await page.isVisible('#playAllBtn'));
    check('можно переименовать свой плейлист', await page.isVisible('#renameBtn'));
    check('можно удалить свой плейлист', await page.isVisible('#deleteBtn'));

    // Просмотр по порядку: кнопка добавляет ?collection= и страница видео
    // должна этот параметр использовать, а не просто получить в адресе.
    // networkidle тут не наступает: видео тянется потоком всё время.
    await page.click('#playAllBtn');
    await page.waitForSelector('#playlistStrip', { timeout: 15000 }).catch(() => null);
    check('переход на видео с плейлистом', page.url().includes('collection='), page.url());
    check('видна подпись плейлиста', await page.isVisible('#playlistStrip'));
    const stripText = await page.textContent('#playlistStrip');
    check('подпись показывает место в списке', /Плейлист:\s*1 из 1|Плейлист:\s*1 видео/.test(stripText),
      `подпись: ${stripText}`);
    check('есть ссылка назад к плейлисту',
      (await page.getAttribute('#playlistStrip a', 'href')).includes('/collection/'));
    const nextWired = await page.evaluate(() => typeof PLAYLIST_ORDER !== 'undefined' && PLAYLIST_ORDER.length);
    check('порядок видео пришёл на страницу', nextWired === 1, `длина списка: ${nextWired}`);

    // Переход к следующему видео. Нужны два ролика в плейлисте: берём их id из
    // карточек главной (отдельного эндпоинта со списком видео в проекте нет).
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    const ids = await page.$$eval('.video-card[data-id]', els => els.slice(0, 2).map(e => e.dataset.id));
    if (ids.length < 2) {
      check('на главной есть два видео для проверки перехода', false, `нашлось ${ids.length}`);
    } else {
      await page.evaluate(async ([base, id, vids]) => {
        for (const v of vids) {
          await fetch(`${base}/api/collections/${encodeURIComponent(id)}/videos`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_id: v }),
          });
        }
      }, [BASE, own.id, ids]);
      await page.goto(`${BASE}/watch/${ids[0]}?collection=${encodeURIComponent(own.id)}`,
        { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('#playlistStrip', { timeout: 15000 }).catch(() => null);
      const place = await page.textContent('#playlistStrip');
      check('на первом видео показано место в списке', /из [2-9]/.test(place), `подпись: ${place}`);
      // Досматриваем: событие ended должно увести именно на следующий ролик.
      const before = page.url();
      await page.evaluate(() => {
        const p = document.getElementById('videoElement');
        if (p) p.dispatchEvent(new Event('ended'));
      });
      await page.waitForTimeout(1500);
      check('после конца видео открылся другой ролик',
        page.url() !== before && !page.url().includes(`/watch/${ids[0]}?`),
        `было ${before}, стало ${page.url()}`);
      check('параметр плейлиста сохранён при переходе', page.url().includes('collection='), page.url());
    }

    await page.goto(`${BASE}/collection/${own.id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#collectionTitle');

    // Переименование. Метку прогона оставляем в названии, иначе уборка в конце
    // не найдёт этот плейлист и он останется мусором.
    const renamed = `Переименован ${stamp}`;
    page.once('dialog', d => d.accept(renamed));
    await page.click('#renameBtn');
    await page.waitForTimeout(700);
    check('название обновилось без перезагрузки',
      (await page.textContent('#collectionTitle')).trim() === renamed,
      await page.textContent('#collectionTitle'));

    // Снятие видео: кнопка внутри ссылки, страница уходить не должна.
    // Видео к этому моменту несколько (добавляли для проверки перехода),
    // поэтому считаем разницу, а не ждём ровно ноль строк.
    const rowsBefore = (await page.$$('.video-row')).length;
    await page.click('.row-remove');
    await page.waitForTimeout(800);
    check('остались на странице плейлиста', page.url().includes('/collection/'), page.url());
    const rowsAfter = (await page.$$('.video-row')).length;
    check('строка убрана', rowsAfter === rowsBefore - 1, `было ${rowsBefore}, стало ${rowsAfter}`);
    // Снимаем остальные: пустое состояние должно появиться на последнем.
    while ((await page.$$('.video-row')).length) {
      await page.click('.row-remove');
      await page.waitForTimeout(500);
    }
    check('показано пустое состояние', await page.isVisible('#emptyNote'));
    check('кнопка просмотра убрана у пустого плейлиста', await page.$('#playAllBtn') === null);

    // Удаление плейлиста уводит на главную.
    page.once('dialog', d => d.accept());
    await page.click('#deleteBtn');
    await page.waitForTimeout(900);
    check('после удаления вернулись на главную', new URL(page.url()).pathname === '/', page.url());
  }

  // ===== Встроенный «Смотреть позже» нельзя править =====
  await page.goto(`${BASE}/collection/watch-later`, { waitUntil: 'networkidle' });
  check('страница «Смотреть позже» открывается', (await page.textContent('#collectionTitle')).includes('Смотреть позже'));
  check('переименование скрыто', await page.$('#renameBtn') === null);
  check('удаление скрыто', await page.$('#deleteBtn') === null);

  // ===== Неизвестный плейлист =====
  const status = await page.evaluate(async base => {
    const res = await fetch(base + '/collection/нет-такого');
    return res.status;
  }, BASE);
  check('неизвестный плейлист даёт 404', status === 404, `статус ${status}`);

  const leftovers = await cleanup(page);
  check('созданные плейлисты убраны', leftovers === 0, `осталось ${leftovers}`);

  check('нет ошибок в консоли', errors.length === 0, errors.join(' | '));

  await browser.close();

  console.log(`Проверок пройдено: ${passed}`);
  if (failures.length) {
    console.log('ПРОВАЛЫ:');
    for (const f of failures) console.log('  - ' + f);
    process.exit(1);
  }
  console.log('Все проверки прошли.');
})().catch(async e => {
  // Уборка нужна и при падении: прерванный прогон однажды оставил два
  // плейлиста, и следующий запуск считал их своими.
  console.error(e);
  try {
    const browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await cleanup(page);
    await browser.close();
    console.log('Мусор после падения убран.');
  } catch (inner) {
    console.error('Убрать мусор не удалось: ' + inner.message);
  }
  process.exit(1);
});
