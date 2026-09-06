// Проверка исправлений: клик по «Очередь» напрямую + отсутствие пустой полосы.
const { chromium } = require('playwright');
const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';

(async () => {
  const browser = await chromium.launch();
  let failures = 0;
  const check = (name, ok, extra) => {
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${name}${extra ? ' | ' + extra : ''}`);
    if (!ok) failures++;
  };

  // --- Десктоп ---
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);

  const desktop = await page.evaluate(() => {
    const d = document.querySelector('.sidebar-drawer').getBoundingClientRect();
    const g = document.getElementById('mainGrid').getBoundingClientRect();
    return { sidebarLeft: Math.round(d.left), gridLeft: Math.round(g.left), sidebarW: Math.round(d.width) };
  });
  check('сайдбар виден на десктопе', desktop.sidebarLeft === 0, JSON.stringify(desktop));
  check('нет пустой полосы слева', desktop.gridLeft <= desktop.sidebarW + 40, `gridLeft=${desktop.gridLeft}`);

  // Клик без гамбургера
  await page.click('[data-nav="queue"]', { timeout: 5000 });
  await page.waitForTimeout(1200);
  const q = await page.evaluate(() => {
    const c = document.getElementById('queueContainer');
    const item = document.querySelector('#queueList .queue-item');
    return {
      visible: c && getComputedStyle(c).display !== 'none',
      itemBg: item ? getComputedStyle(item).backgroundColor : null,
      hasItems: !!item,
      toolbar: !!document.querySelector('.queue-toolbar'),
    };
  });
  check('клик по «Очередь» без гамбургера', q.visible);
  check('панель инструментов очереди на месте', q.toolbar);
  if (q.hasItems) check('карточка очереди не прозрачна', q.itemBg !== 'rgba(0, 0, 0, 0)', q.itemBg);

  // Главный баг «чёрного экрана»: <main> с min-height 100vh оставался в потоке
  // и сдвигал очередь ровно на высоту экрана вниз.
  const pos = await page.evaluate(() => {
    const c = document.getElementById('queueContainer').getBoundingClientRect();
    const m = document.getElementById('mainContent');
    return {
      queueTop: Math.round(c.top),
      mainDisplay: getComputedStyle(m).display,
      viewportH: window.innerHeight,
    };
  });
  check('очередь видна без прокрутки', pos.queueTop < pos.viewportH, JSON.stringify(pos));
  check('основной раздел скрыт на вкладке очереди', pos.mainDisplay === 'none', pos.mainDisplay);

  // Баннер паузы: рисуем состояние напрямую, не трогая рабочую очередь.
  const banner = await page.evaluate(() => {
    const task = { id: 'p1', title: 'T', urls: ['u'], status: 'waiting', progress: 0,
      message: '', error: '', current_index: 0, total_urls: 1, speed: '', eta: '',
      attempts: 0, priority: 'normal', cancelling: false };
    renderQueue([task], true);
    const paused = getComputedStyle(document.getElementById('queuePausedBanner')).display;
    renderQueue([task], false);
    const running = getComputedStyle(document.getElementById('queuePausedBanner')).display;
    return { paused, running };
  });
  check('на паузе показано предупреждение', banner.paused !== 'none', banner.paused);
  check('без паузы предупреждение скрыто', banner.running === 'none', banner.running);

  // Опрос очереди останавливается вне раздела
  await page.click('[data-nav="all"]');
  await page.waitForTimeout(500);
  let polls = 0;
  page.on('request', r => { if (r.url().includes('/api/queue/list')) polls++; });
  await page.waitForTimeout(7000);
  check('нет опроса очереди в разделе «Все видео»', polls === 0, `запросов: ${polls}`);

  // Светлая тема
  await page.evaluate(() => { document.documentElement.setAttribute('data-theme', 'light'); });
  await page.click('[data-nav="queue"]');
  await page.waitForTimeout(1200);
  const light = await page.evaluate(() => {
    const item = document.querySelector('#queueList .queue-item');
    return item ? getComputedStyle(item).backgroundColor : null;
  });
  check('карточка видна в светлой теме', light === null || light !== 'rgba(0, 0, 0, 0)', light);

  // --- Мобильный: сайдбар должен прятаться ---
  const mob = await browser.newPage({ viewport: { width: 420, height: 780 } });
  await mob.goto(BASE, { waitUntil: 'domcontentloaded' });
  await mob.waitForTimeout(1000);
  const mobile = await mob.evaluate(() => {
    const d = document.querySelector('.sidebar-drawer').getBoundingClientRect();
    return { left: Math.round(d.left), offscreen: d.right <= 0 };
  });
  check('на мобильном сайдбар скрыт', mobile.offscreen, JSON.stringify(mobile));
  await mob.click('#sidebarToggle');
  await mob.waitForTimeout(600);
  const opened = await mob.evaluate(() => Math.round(document.querySelector('.sidebar-drawer').getBoundingClientRect().left));
  check('гамбургер открывает сайдбар на мобильном', opened === 0, `left=${opened}`);
  await mob.close();

  // Уборка проб
  await page.evaluate(async () => {
    const d = await (await fetch('/api/queue/list')).json();
    for (const t of (d.tasks || [])) if (t.title === 'UI probe') await fetch('/api/queue/remove/' + t.id, { method: 'DELETE' });
  });

  check('нет ошибок JS', errors.length === 0, errors.join('; '));
  await browser.close();
  console.log(failures ? `\nПРОВАЛОВ: ${failures}` : '\nВсе проверки пройдены');
  process.exit(failures ? 1 : 0);
})();
