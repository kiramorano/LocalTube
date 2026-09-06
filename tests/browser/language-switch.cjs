// Переключение языка интерфейса: русский / английский.
//
// Проверяем то, что нельзя проверить рендером шаблонов в pytest:
//   * выбор языка в настройках сохраняется в cookie и держится после перехода
//     по страницам, а не только до перезагрузки;
//   * серверная часть страницы приходит уже переведённой (<html lang>, шапка);
//   * клиентский слой (window.t) работает и на строках, которые рисует JS;
//   * возврат на русский ничего не ломает.
//
// Модель не видит изображений, поэтому сравниваем текст и атрибуты.
const { chromium } = require('playwright');
const { requireTestServer } = require('./require-test-server.cjs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';
// Страницы, которые обязаны переводиться целиком.
const PAGES = ['/', '/settings', '/upload'];

// Русские слова, которые не должны остаться на английской странице.
// Названия папок и имена файлов не считаются: их не переводят.
const RU = /[А-Яа-яЁё]/;

async function readPage(page) {
  return page.evaluate(() => {
    const drop = new Set(['SCRIPT', 'STYLE', 'CODE', 'PRE']);
    // Данные библиотеки переводить нечего: названия видео, имена каналов и
    // подписи карточек приходят из файлов пользователя. Их контейнеры
    // исключаем целиком, иначе русское название видео выглядит как пропуск.
    const dataSelectors = [
      '.video-title', '.video-meta', '.video-author-avatar',
      '.short-title', '.short-author',
      '.card h3', '.card .meta', '.channel-name', '.sidebar-channel',
      '.row-title', '.row-meta', '.queue-title', '.playlist-title',
      // Списки, которые целиком заполняются данными пользователя.
      '#sidebarCollections', '#hiddenChannelsList', '#sidebarChannels',
      '#collectionList', '#serverList',
      // Ссылки на каналы в боковой панели: подписи — имена каналов с диска.
      '.sidebar-drawer a.sidebar-item[href^="/channel/"]',
    ];
    const words = [];
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walk.nextNode()) {
      const node = walk.currentNode;
      if (drop.has(node.parentElement?.tagName)) continue;
      if (node.parentElement?.closest(dataSelectors.join(','))) continue;
      // Скрытый текст пользователь не видит, поэтому в счёт не идёт.
      const box = node.parentElement?.getBoundingClientRect();
      if (!box || (box.width === 0 && box.height === 0)) continue;
      const text = node.textContent.trim();
      if (text) words.push(text);
    }
    return {
      lang: document.documentElement.getAttribute('lang'),
      cookie: document.cookie,
      // Функция перевода должна быть доступна коду страницы.
      hasT: typeof window.t === 'function',
      // Проверяем перевод на строке, которую рисует только JS.
      sample: typeof window.t === 'function' ? window.t('Загрузка…') : null,
      texts: words,
    };
  });
}

function russianLeftovers(texts) {
  return texts.filter(t => RU.test(t));
}

(async () => {
  await requireTestServer(BASE, []);
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  const out = [];

  // 1. По умолчанию интерфейс русский.
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  const ru = await readPage(page);
  out.push({
    step: 'по умолчанию русский',
    pass: ru.lang === 'ru' && ru.hasT && ru.sample === 'Загрузка…'
          && russianLeftovers(ru.texts).length > 0,
    lang: ru.lang, hasT: ru.hasT, sample: ru.sample,
    russianCount: russianLeftovers(ru.texts).length,
  });

  // 2. Переключаем на английский в настройках.
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' });
  await page.click('[data-tab="language"]');
  await page.selectOption('#uiLang', 'en');
  // Обработчик перезагружает страницу сам.
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(600);
  const afterSwitch = await readPage(page);
  out.push({
    step: 'выбран английский',
    pass: afterSwitch.lang === 'en'
          && /lt_lang=en/.test(afterSwitch.cookie)
          && afterSwitch.sample === 'Loading…',
    lang: afterSwitch.lang, cookie: afterSwitch.cookie, sample: afterSwitch.sample,
  });

  // 3. Язык держится на других страницах, и русского текста там не остаётся.
  for (const path of PAGES) {
    await page.goto(BASE + path, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    const state = await readPage(page);
    const left = russianLeftovers(state.texts);
    out.push({
      step: `английский на ${path}`,
      pass: state.lang === 'en' && state.hasT && left.length === 0,
      lang: state.lang,
      leftovers: left.slice(0, 12),
      leftoverCount: left.length,
      visibleTexts: state.texts.length,
    });
  }

  // 4. Возврат на русский.
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' });
  await page.click('[data-tab="language"]');
  await page.selectOption('#uiLang', 'ru');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(600);
  const back = await readPage(page);
  out.push({
    step: 'возврат на русский',
    pass: back.lang === 'ru' && /lt_lang=ru/.test(back.cookie)
          && russianLeftovers(back.texts).length > 0,
    lang: back.lang, cookie: back.cookie,
    russianCount: russianLeftovers(back.texts).length,
  });

  out.push({ step: 'ошибок в консоли нет', pass: errors.length === 0, errors });

  await ctx.close();
  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.step));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
})();
