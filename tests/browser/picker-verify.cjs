// Модалка выбора видео: перехватываем /remaining, чтобы не зависеть от сети.
const { chromium } = require('playwright');
const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';

const FAKE = {
  count: 3,
  videos: [
    { id: 'v1', url: 'https://www.youtube.com/watch?v=v1', title: 'Первое видео <b>с тегами</b>', duration: 95.4 },
    { id: 'v2', url: 'https://www.youtube.com/watch?v=v2', title: 'Второе видео', duration: 620 },
    { id: 'v3', url: 'https://www.youtube.com/watch?v=v3', title: 'Третье видео', duration: null },
  ],
};

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

  // Находим канал с кнопкой «Скачать остальные видео»
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  const channelHref = await page.evaluate(() => {
    const a = document.querySelector('a[href^="/channel/"]');
    return a ? a.getAttribute('href') : null;
  });
  if (!channelHref) { console.log('FAIL нет ни одного канала в библиотеке'); process.exit(1); }
  console.log('канал:', channelHref);

  let addPayload = null;
  await page.route('**/remaining', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(FAKE),
  }));
  await page.route('**/api/queue/add', route => {
    addPayload = JSON.parse(route.request().postData() || '{}');
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', task_id: 'fake' }) });
  });

  await page.goto(BASE + channelHref, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);

  const hasButton = await page.locator('#downloadRemaining').count();
  if (!hasButton) { console.log('FAIL на странице канала нет кнопки #downloadRemaining'); process.exit(1); }

  check('модалка скрыта до клика', await page.locator('#dlOverlay').isHidden());
  await page.click('#downloadRemaining');
  await page.waitForTimeout(700);
  check('модалка открылась', await page.locator('#dlOverlay').isVisible());

  const rendered = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('#dlList .dl-row'));
    return {
      rows: rows.length,
      allChecked: rows.every(r => r.querySelector('input').checked),
      firstTitle: rows[0].querySelector('.dl-title').textContent,
      firstTitleHtml: rows[0].querySelector('.dl-title').innerHTML,
      durations: rows.map(r => { const d = r.querySelector('.dl-ext'); return d ? d.textContent : null; }),
      count: document.getElementById('dlCount').textContent,
      sub: document.getElementById('dlSub').textContent,
    };
  });
  check('показаны все 3 видео', rendered.rows === 3, `строк: ${rendered.rows}`);
  check('по умолчанию отмечены все', rendered.allChecked);
  check('название не интерпретируется как HTML', !rendered.firstTitleHtml.includes('<b>'), rendered.firstTitleHtml.slice(0, 60));
  check('длительность 95.4с -> 1:35', rendered.durations[0] === '1:35', JSON.stringify(rendered.durations));
  check('длительность 620с -> 10:20', rendered.durations[1] === '10:20');
  check('без длительности — нет метки', rendered.durations[2] === null);
  check('счётчик выбранных верен', /3 из 3/.test(rendered.count), rendered.count);

  // Снять все -> кнопка блокируется
  await page.click('#dlSelectNone');
  await page.waitForTimeout(200);
  check('после «Снять все» кнопка выключена', await page.locator('#dlConfirm').isDisabled());
  check('счётчик показывает 0', /0 из 3/.test(await page.locator('#dlCount').textContent()));

  // Выбираем два видео, качество 720p, mkv
  await page.click('#dlSelectAll');
  await page.locator('#dlList .dl-row input').nth(2).uncheck();
  await page.selectOption('#dlQuality', '720');
  await page.selectOption('#dlFormat', 'mkv');
  await page.waitForTimeout(200);
  check('счётчик после снятия одного', /2 из 3/.test(await page.locator('#dlCount').textContent()));

  await page.click('#dlConfirm');
  await page.waitForTimeout(900);

  check('запрос в очередь отправлен', !!addPayload);
  if (addPayload) {
    check('ушли только выбранные ссылки',
      JSON.stringify(addPayload.urls) === JSON.stringify([FAKE.videos[0].url, FAKE.videos[1].url]),
      JSON.stringify(addPayload.urls));
    check('селектор качества по высоте',
      addPayload.format_id === 'bestvideo[height<=720]+bestaudio/best', String(addPayload.format_id));
    check('формат контейнера передан', addPayload.merge_format === 'mkv', String(addPayload.merge_format));
    check('в заголовке верное число', /\(2\)/.test(addPayload.title || ''), addPayload.title);
  }
  check('модалка закрылась после добавления', await page.locator('#dlOverlay').isHidden());

  // «Максимальное доступное» не должно посылать format_id
  addPayload = null;
  await page.click('#downloadRemaining');
  await page.waitForTimeout(600);
  await page.selectOption('#dlQuality', 'best');
  await page.click('#dlConfirm');
  await page.waitForTimeout(800);
  check('для «максимального» format_id не передаётся', addPayload && !('format_id' in addPayload),
    addPayload ? JSON.stringify(addPayload.format_id) : 'нет запроса');

  // Только звук
  addPayload = null;
  await page.click('#downloadRemaining');
  await page.waitForTimeout(600);
  await page.selectOption('#dlQuality', 'audio');
  await page.click('#dlConfirm');
  await page.waitForTimeout(800);
  check('«только звук» -> bestaudio/best', addPayload && addPayload.format_id === 'bestaudio/best',
    addPayload ? String(addPayload.format_id) : 'нет запроса');

  // Escape закрывает
  await page.click('#downloadRemaining');
  await page.waitForTimeout(600);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  check('Escape закрывает модалку', await page.locator('#dlOverlay').isHidden());

  check('нет ошибок JS', errors.length === 0, errors.join('; '));
  await page.screenshot({ path: 'picker.png' });
  await browser.close();
  console.log(failures ? `\nПРОВАЛОВ: ${failures}` : '\nВсе проверки пройдены');
  process.exit(failures ? 1 : 0);
})();
