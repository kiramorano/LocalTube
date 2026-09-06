// Выбор качества видео в плеере: 144p-2160p.
//
// Проверяется то, что pytest увидеть не может: меню действительно открывается,
// пункты идут от высокого качества к низкому, готовое качество переключает файл
// с сохранением позиции просмотра, недоступное запускает пересборку и показывает
// процент, а гостю недоступные пункты не предлагаются.
//
// Пересборка через ffmpeg занимает минуты, поэтому /api/quality и /api/convert
// подменяются: проверяется поведение интерфейса, а сам ffmpeg покрыт pytest.
const { chromium } = require('playwright');
const { requireTestServer } = require('./require-test-server.cjs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';

// Ожидаемый порядок ступеней. Ключи JSON-объекта Flask сортирует, поэтому
// порядок приходит отдельным полем order — без него 1080p оказывался ниже 144p.
const EXPECTED_ORDER = ['Оригинал', '2160p (4K UHD)', '1440p (2K QHD)',
  '1080p (FHD)', '720p (HD)', '480p (SD)', '360p', '240p',
  'Шакализатор (144p)', 'Улучшайзер (Четкость+)', 'Улучшайзер (4K+Четкость)'];

// Порядок задаётся массивом, а не порядком ключей объекта: числовые ключи вида
// '144' JS переупорядочивает по возрастанию, и подделка ответа сама рассыпала бы
// порядок, который проверяется.
const ORDER = ['original', '2160', '1440', '1080', '720', '480', '360', '240',
  '144', 'enhance', 'enhance_2160'];

function qualityPayload(videoUrl, { available = [], tasks = {} } = {}) {
  const labels = {
    original: 'Оригинал', 2160: '2160p (4K UHD)', 1440: '1440p (2K QHD)',
    1080: '1080p (FHD)', 720: '720p (HD)', 480: '480p (SD)', 360: '360p',
    240: '240p', 144: 'Шакализатор (144p)',
    enhance: 'Улучшайзер (Четкость+)', enhance_2160: 'Улучшайзер (4K+Четкость)',
  };
  const order = ORDER;
  const qualities = {};
  order.forEach(key => {
    const ready = key === 'original' || available.includes(key);
    qualities[key] = {
      label: labels[key],
      available: ready,
      file: key === 'original' ? 'video.mp4' : `video_${key}.mp4`,
      url: ready ? videoUrl : null,
    };
  });
  return { qualities, order, tasks };
}

async function openQualityMenu(page) {
  // Плеер прячет панель управления через 2,5 секунды после начала
  // воспроизведения (класс idle): без наведения курсора кнопка настроек
  // перекрыта содержимым страницы и клик не доходит.
  await page.hover('#playerContainer');
  await page.click('#settingsBtn');
  await page.click('#menuQualityBtn');
  await page.waitForSelector('#qualityOptionsList .quality-option');
}

async function readMenu(page) {
  return page.evaluate(() => {
    const rows = [...document.querySelectorAll('#qualityOptionsList .quality-option')];
    return {
      labels: rows.map(r => r.querySelector('.quality-res').textContent.trim()),
      notes: rows.map(r => (r.querySelector('.quality-codec') || {}).textContent || ''),
      active: rows.filter(r => r.classList.contains('active'))
        .map(r => r.dataset.quality),
      hint: (document.querySelector('#qualityOptionsList > div:last-child .quality-res')
        ? '' : (document.querySelector('#qualityOptionsList > div:last-child') || {}).textContent || ''),
    };
  });
}

(async () => {
  await requireTestServer(BASE, []);
  const catalog = await (await fetch(BASE + '/api/catalog')).json();
  const video = (catalog.videos || [])[0];
  if (!video) {
    console.log('В библиотеке нет видео — проверять нечего.');
    process.exit(1);
  }
  const watch = `${BASE}/watch/${video.id}`;
  const browser = await chromium.launch();
  const out = [];

  // ===== 1. Порядок пунктов и подписи =====
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    let mediaUrl = null;
    await page.goto(watch, { waitUntil: 'networkidle' });
    mediaUrl = await page.evaluate(() => document.getElementById('videoElement').getAttribute('src'));
    await page.route('**/api/quality/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(qualityPayload(mediaUrl)),
    }));
    await openQualityMenu(page);
    const menu = await readMenu(page);

    out.push({
      name: 'порядок ступеней от высокого к низкому',
      pass: JSON.stringify(menu.labels) === JSON.stringify(EXPECTED_ORDER)
            && errors.length === 0,
      labels: menu.labels, expected: EXPECTED_ORDER, errors,
    });
    out.push({
      name: 'оригинал отмечен текущим качеством',
      pass: menu.active.length === 1 && menu.active[0] === 'original',
      active: menu.active,
    });
    out.push({
      name: 'недоступные ступени предлагают пересборку',
      pass: menu.notes.filter(n => n.includes('Пересобрать')).length === 10,
      rebuildable: menu.notes.filter(n => n.includes('Пересобрать')).length,
    });
    await page.screenshot({ path: 'shots/quality-menu.png' });
    await ctx.close();
  }

  // ===== 2. Переключение на готовое качество =====
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(watch, { waitUntil: 'networkidle' });
    const mediaUrl = await page.evaluate(() => document.getElementById('videoElement').getAttribute('src'));
    await page.route('**/api/quality/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(qualityPayload(mediaUrl, { available: ['360'] })),
    }));
    // Отматываем на 12-ю секунду и ставим двойную скорость: смена src сбрасывает
    // плеер целиком — позиция уходит в ноль, скорость к 1x, а атрибут autoplay
    // запускает остановленный ролик заново.
    await page.hover('#playerContainer');
    await page.click('#speedBtn');
    await page.click('#speedBtn');
    await page.evaluate(() => {
      const v = document.getElementById('videoElement');
      v.pause();
      v.currentTime = 12;
    });
    await page.waitForTimeout(300);
    const readState = () => page.evaluate(() => {
      const v = document.getElementById('videoElement');
      return {
        src: v.getAttribute('src'),
        time: v.currentTime,
        rate: v.playbackRate,
        paused: v.paused,
        speedBtn: document.getElementById('speedBtn').textContent.trim(),
        label: document.getElementById('currentQualityLabel').textContent.trim(),
        menuHidden: getComputedStyle(document.getElementById('playerQualityMenu')).display === 'none',
      };
    });
    const before = await readState();

    await openQualityMenu(page);
    await page.click('#qualityOptionsList .quality-option[data-quality="360"]');
    await page.waitForTimeout(1500);

    const after = await readState();

    out.push({
      name: 'готовое качество переключает файл и держит позицию',
      // Допуск 2 секунды: восстановление идёт по loadedmetadata, и плеер может
      // выровняться на ближайший ключевой кадр.
      pass: after.label === '360p' && Math.abs(after.time - before.time) < 2
            && after.menuHidden && errors.length === 0,
      before, after, errors,
    });
    out.push({
      name: 'скорость воспроизведения не сбрасывается',
      // Кнопка продолжала показывать «2x», пока плеер уже играл на 1x: подпись
      // и настоящая скорость расходились.
      pass: after.rate === before.rate && after.speedBtn === before.speedBtn,
      rate: after.rate, expected: before.rate, speedBtn: after.speedBtn,
    });
    out.push({
      name: 'пауза сохраняется при переключении',
      // Атрибут autoplay применяется заново при load(): остановленный ролик
      // начинал играть сам.
      pass: after.paused === true,
      paused: after.paused,
    });
    await ctx.close();
  }

  // ===== 2а. Включённые субтитры остаются после переключения =====
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    // Дорожки подделываются: в библиотеке субтитров может не быть вовсе, а
    // проверяется поведение плеера, а не их скачивание.
    await page.route('**/api/subtitles/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ subtitles: [{ lang: 'ru', label: 'Русские', file: 'ru.vtt' }] }),
    }));
    // Regex, а не '**/subtitles/**': такой шаблон перехватывал и запрос
    // /api/subtitles, отдавал на него VTT вместо JSON, и дорожки не создавались
    // вовсе — проверка молча превращалась в пустую.
    await page.route(/\/subtitles\/[^/]+\/[^/]+\.vtt/, route => route.fulfill({
      status: 200, contentType: 'text/vtt',
      body: 'WEBVTT\n\n00:00:00.000 --> 00:01:00.000\nПроверка\n',
    }));
    await page.goto(watch, { waitUntil: 'networkidle' });
    const mediaUrl = await page.evaluate(() => document.getElementById('videoElement').getAttribute('src'));
    await page.route('**/api/quality/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(qualityPayload(mediaUrl, { available: ['360'] })),
    }));

    // Дорожки подключаются асинхронным запросом уже после загрузки страницы, и
    // русская помечена default — браузер включает её сам. Ждём именно режима
    // showing: клик по кнопке субтитров здесь выключил бы дорожку, а проверка
    // молча превратилась бы в пустую.
    await page.waitForFunction(() => {
      const v = document.getElementById('videoElement');
      return [...v.textTracks].some(tr => tr.mode === 'showing');
    });
    const readSubs = () => page.evaluate(() => {
      const v = document.getElementById('videoElement');
      return [...v.textTracks].filter(tr => tr.mode === 'showing').map(tr => tr.label);
    });
    const shownBefore = await readSubs();

    await openQualityMenu(page);
    await page.click('#qualityOptionsList .quality-option[data-quality="360"]');
    await page.waitForTimeout(1500);
    const shownAfter = await readSubs();

    out.push({
      name: 'включённые субтитры остаются видимыми',
      // Смена src переводит дорожки в disabled: субтитры пропадали молча, и
      // приходилось включать их заново. Пустой shownBefore — это провал, а не
      // повод пропустить проверку: значит, дорожка вообще не включилась.
      pass: shownBefore.length > 0
            && JSON.stringify(shownAfter) === JSON.stringify(shownBefore),
      shownBefore, shownAfter, errors,
    });
    await ctx.close();
  }

  // ===== 3. Пересборка: запуск, процент, готовность =====
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(watch, { waitUntil: 'networkidle' });
    const mediaUrl = await page.evaluate(() => document.getElementById('videoElement').getAttribute('src'));

    let convertBody = null;
    let step = 0;
    await page.route('**/api/convert/**', route => {
      convertBody = route.request().postDataJSON();
      step = 1;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ status: 'started', task_key: 'x_144' }),
      });
    });
    await page.route('**/api/quality/**', route => {
      // Первый ответ — пусто, затем задача на 40%, затем готовый файл.
      const payload = step === 0 ? qualityPayload(mediaUrl)
        : step === 1 ? qualityPayload(mediaUrl, { tasks: { 144: 40 } })
        : qualityPayload(mediaUrl, { available: ['144'] });
      if (step === 1) step = 2;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
    });

    await openQualityMenu(page);
    await page.click('#qualityOptionsList .quality-option[data-quality="144"]');
    // Опрос идёт раз в 2 секунды: ждём один цикл, чтобы увидеть процент.
    await page.waitForTimeout(2600);
    const running = await readMenu(page);
    // Следующий цикл отдаёт готовый файл.
    await page.waitForTimeout(2600);
    const ready = await readMenu(page);

    out.push({
      name: 'клик по недоступному качеству запускает пересборку',
      pass: convertBody && convertBody.quality === '144' && errors.length === 0,
      convertBody, errors,
    });
    out.push({
      name: 'процент пересборки виден в меню',
      pass: running.notes.some(n => n.includes('40')),
      notes: running.notes.filter(Boolean),
    });
    out.push({
      name: 'готовое качество перестаёт предлагать пересборку',
      pass: !ready.notes[8].includes('Пересобрать'),
      note144: ready.notes[8],
    });
    await ctx.close();
  }

  // ===== 4. Гостю пересборка не предлагается =====
  {
    // Гость определяется по адресу клиента, поэтому подменяем сам признак
    // владельца в разметке: поднимать второй сервер на 0.0.0.0 ради одной
    // проверки дороже, а проверяется именно ветка отрисовки.
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.route(watch, async route => {
      const res = await route.fetch();
      const body = (await res.text()).replace('const IS_OWNER = true;', 'const IS_OWNER = false;');
      route.fulfill({ response: res, body, headers: { ...res.headers(), 'content-length': undefined } });
    });
    await page.goto(watch, { waitUntil: 'networkidle' });
    const mediaUrl = await page.evaluate(() => document.getElementById('videoElement').getAttribute('src'));
    await page.route('**/api/quality/**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(qualityPayload(mediaUrl, { available: ['360'] })),
    }));
    await openQualityMenu(page);
    const menu = await readMenu(page);

    out.push({
      name: 'гость видит только готовые качества',
      pass: JSON.stringify(menu.labels) === JSON.stringify(['Оригинал', '360p'])
            && !menu.notes.some(n => n.includes('Пересобрать'))
            && errors.length === 0,
      labels: menu.labels, notes: menu.notes.filter(Boolean), errors,
    });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.name));
  const failed = out.filter(r => !r.pass).length;
  console.log(`\n${out.length - failed}/${out.length} проверок пройдено`);
  process.exit(failed ? 1 : 0);
})();
