// Проверка разделов настроек (Профиль / Хранение / Загрузка) и путей хранения.
// Запуск: LT_BASE=http://127.0.0.1:5004 node settings-sections.cjs
//
// Сервер должен быть запущен через serve_test.py: он изолирует config.json,
// иначе проверка перезапишет настоящие пути пользователя.
const { chromium } = require('playwright');
const os = require('os');
const path = require('path');
const fs = require('fs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';

const PATH_KEYS = ['video_dir', 'avatars_dir', 'banners_dir', 'meta_dir',
  'playlists_dir', 'subtitles_dir', 'uservideos_dir'];

let passed = 0;
const failures = [];
function check(name, condition, detail) {
  if (condition) { passed++; return; }
  failures.push(`${name}${detail ? ': ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  const expectedNoise = /Failed to load resource/;
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !expectedNoise.test(m.text())) errors.push(m.text());
  });

  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });

  // ===== Вкладки =====
  const tabs = await page.$$eval('.tab-btn', els => els.map(e => e.dataset.tab));
  check('пять вкладок', tabs.length === 5, `найдено ${tabs.length}: ${tabs}`);
  for (const t of ['profile', 'storage', 'download', 'language', 'network']) {
    check(`есть вкладка ${t}`, tabs.includes(t));
  }

  // По умолчанию открыт Профиль, остальные скрыты.
  check('профиль открыт', await page.isVisible('#panel-profile'));
  check('хранение скрыто', !(await page.isVisible('#panel-storage')));
  check('загрузка скрыта', !(await page.isVisible('#panel-download')));
  check('сеть скрыта', !(await page.isVisible('#panel-network')));

  // Поле профиля не должно быть доступно, пока открыт другой раздел:
  // иначе разделение чисто визуальное.
  await page.click('.tab-btn[data-tab="storage"]');
  check('хранение открылось', await page.isVisible('#panel-storage'));
  check('профиль скрылся', !(await page.isVisible('#panel-profile')));
  check('поле имени скрыто', !(await page.isVisible('#username')));

  await page.click('.tab-btn[data-tab="download"]');
  check('загрузка открылась', await page.isVisible('#panel-download'));
  check('cookies в разделе загрузки', await page.isVisible('#cookieBrowser'));
  check('плагины в разделе загрузки', await page.isVisible('#authCheck'));

  // Выбранный раздел должен запоминаться между заходами.
  await page.reload({ waitUntil: 'networkidle' });
  check('раздел запомнен', await page.isVisible('#panel-download'));

  await page.click('.tab-btn[data-tab="storage"]');

  // ===== Поля путей заполнены с сервера =====
  for (const key of PATH_KEYS) {
    const value = await page.inputValue(`[data-path="${key}"]`);
    check(`поле ${key} заполнено`, value.length > 0, `значение ${JSON.stringify(value)}`);
  }

  // Абсолютный путь показывается подсказкой: относительное "videos" не
  // объясняет, где лежат файлы.
  const hint = await page.textContent('#hint-video_dir');
  check('показан абсолютный путь', /[\\/]/.test(hint) && hint.length > 3, hint);

  // ===== Пустое поле не отправляется =====
  let posted = 0;
  page.on('request', r => {
    if (r.url().includes('/api/storage') && r.method() === 'POST') posted++;
  });
  await page.fill('[data-path="video_dir"]', '   ');
  await page.click('#saveStorage');
  await page.waitForTimeout(400);
  check('пустой путь не отправлен', posted === 0, `отправлено запросов: ${posted}`);
  const emptyMsg = await page.textContent('#storageStatus');
  check('сообщение о пустом пути', /пуст/i.test(emptyMsg), emptyMsg);

  // ===== Ошибка сервера показывается =====
  const bogus = process.platform === 'win32' ? 'Q:/нет диска/lib' : '/proc/нельзя/lib';
  await page.fill('[data-path="video_dir"]', bogus);
  await Promise.all([
    page.waitForResponse(r => r.url().includes('/api/storage') && r.request().method() === 'POST'),
    page.click('#saveStorage'),
  ]);
  await page.waitForTimeout(300);
  const errMsg = await page.textContent('#storageStatus');
  check('ошибка сервера видна', errMsg.length > 0 && !/сохранены/.test(errMsg), errMsg);
  check('кнопка разблокирована', !(await page.isDisabled('#saveStorage')));
  const keptValue = await page.inputValue('[data-path="video_dir"]');
  check('путь остался в поле', keptValue === bogus, keptValue);

  // ===== Успешное сохранение и применение без перезапуска =====
  const tmpLib = path.join(os.tmpdir(), 'lt_storage_check_' + Date.now());
  await page.fill('[data-path="video_dir"]', tmpLib);
  const [saveRes] = await Promise.all([
    page.waitForResponse(r => r.url().includes('/api/storage') && r.request().method() === 'POST'),
    page.click('#saveStorage'),
  ]);
  check('сохранение прошло', saveRes.ok(), `HTTP ${saveRes.status()}`);
  const okMsg = await page.textContent('#storageStatus');
  check('сообщение об успехе', /сохранены/.test(okMsg), okMsg);
  check('папка создана на диске', fs.existsSync(tmpLib), tmpLib);

  // Подсказка обновилась на новый путь без перезагрузки страницы.
  const newHint = await page.textContent('#hint-video_dir');
  check('подсказка обновилась', newHint.includes('lt_storage_check'), newHint);

  // Сервер отдаёт новый путь сразу: это и означает применение без перезапуска.
  const applied = await page.evaluate(async () => (await (await fetch('/api/storage')).json()).video_dir);
  check('путь применён на сервере', applied === tmpLib, applied);

  // Библиотека должна открываться, а не падать на новой пустой папке.
  const homeRes = await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  check('главная работает после смены пути', homeRes.status() === 200, `HTTP ${homeRes.status()}`);

  // ===== Возврат значений по умолчанию =====
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
  await page.click('.tab-btn[data-tab="storage"]');
  await page.click('#resetStorage');
  const restored = await page.inputValue('[data-path="video_dir"]');
  check('кнопка сброса вернула значение', restored === 'videos', restored);
  await Promise.all([
    page.waitForResponse(r => r.url().includes('/api/storage') && r.request().method() === 'POST'),
    page.click('#saveStorage'),
  ]);
  const finalPath = await page.evaluate(async () => (await (await fetch('/api/storage')).json()).video_dir);
  check('путь возвращён', finalPath === 'videos', finalPath);

  // ===== Мобильная ширина: вкладки не должны рвать вёрстку =====
  await page.setViewportSize({ width: 390, height: 780 });
  await page.reload({ waitUntil: 'networkidle' });
  const scroll = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
  }));
  check('нет горизонтальной прокрутки', scroll.sw <= scroll.cw + 1,
    `scrollWidth=${scroll.sw} clientWidth=${scroll.cw}`);
  check('вкладки видны на телефоне', await page.isVisible('.tab-btn[data-tab="storage"]'));

  // ===== Ни один элемент управления не потерян =====
  // Разделение на вкладки — перестановка разметки, и элемент легко выпадает из
  // всех панелей: тогда он есть в HTML, но добраться до него нельзя.
  // Регрессия уже случалась: клик по кнопке экспорта cookies перестал
  // проходить, потому что раздел «Загрузка» был закрыт.
  await page.setViewportSize({ width: 1280, height: 900 });
  const controls = {
    profile: ['username', 'avatar', 'theme', 'clearHistory', 'clearFavorites',
      'clearHidden', 'userdataSummary'],
    storage: ['video_dir', 'saveStorage', 'resetStorage', 'downloadAvatars', 'generateThumbs'],
    download: ['client', 'po', 'cookieBrowser', 'importFromBrowser', 'cookies',
      'importCookies', 'deleteCookies', 'authCheck', 'authRefresh', 'status'],
    network: ['netEnabled', 'netAddresses', 'netShowQr', 'netRegenPin', 'netPin',
      'netServerUrl', 'netAddServer', 'netScan', 'netServers'],
  };
  for (const [tab, ids] of Object.entries(controls)) {
    await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
    await page.click(`.tab-btn[data-tab="${tab}"]`);
    for (const id of ids) {
      check(`${id} доступен в разделе ${tab}`, await page.isVisible('#' + id));
    }
  }
  // Кнопка сохранения профиля и yt-dlp общая, она вне панелей.
  check('кнопка сохранения видна', await page.isVisible('#save'));

  check('нет ошибок в консоли', errors.length === 0, errors.join(' | '));

  await browser.close();

  console.log(`Проверок пройдено: ${passed}`);
  if (failures.length) {
    console.log('ПРОВАЛЫ:');
    for (const f of failures) console.log('  - ' + f);
    process.exit(1);
  }
  console.log('Все проверки прошли.');
})().catch(e => { console.error(e); process.exit(1); });
