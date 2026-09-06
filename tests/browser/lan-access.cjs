// Проверка доступа из локальной сети: раздел «Сеть» в настройках, гостевой
// интерфейс и вход по PIN.
// Запуск: LT_BASE=http://127.0.0.1:5012 LT_LAN=http://192.168.0.22:5012 node lan-access.cjs
//
// Сервер должен быть запущен через serve_test.py с LT_HOST=0.0.0.0: с адреса
// 127.0.0.1 любой клиент считается владельцем, и роль гостя не проверить.
const { chromium } = require('playwright');
const { requireTestServer } = require('./require-test-server.cjs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';

const LAN = process.env.LT_LAN || '';

let passed = 0;
const failures = [];
function check(name, condition, detail) {
  if (condition) { passed++; return; }
  failures.push(`${name}${detail ? ': ' + detail : ''}`);
}

// Возвращает настройки доступа в исходное состояние: тумблер включён, лишние
// серверы убраны. Вызывается и при падении, иначе прерванный прогон оставил бы
// сервер закрытым для сети.
async function cleanup(page) {
  return page.evaluate(async base => {
    await fetch(base + '/api/network/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: true }),
    });
    const res = await fetch(base + '/api/network/servers');
    const items = (await res.json()).servers || [];
    for (const item of items) {
      await fetch(base + '/api/network/servers', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: item.url }),
      });
    }
    const after = await fetch(base + '/api/network/servers');
    return ((await after.json()).servers || []).length;
  }, BASE);
}

(async () => {
  // Проверки меняют PIN, тумблер доступа и список чужих серверов: на рабочем
  // сервере это отключило бы устройства, впущенные пользователем.
  await requireTestServer(BASE, ['access', 'userdata']);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  const expectedNoise = /Failed to load resource|net::ERR/;
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => {
    if (m.type() === 'error' && !expectedNoise.test(m.text())) errors.push(m.text());
  });

  // ===== Раздел «Сеть» в настройках =====
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
  check('есть вкладка «Сеть»', await page.$('.tab-btn[data-tab="network"]') !== null);
  await page.click('.tab-btn[data-tab="network"]');
  await page.waitForTimeout(300);
  check('панель сети видна', await page.isVisible('#panel-network'));
  check('панель загрузки скрыта', !(await page.isVisible('#panel-download')));

  // Адрес в сети должен появиться сам, без действий пользователя.
  await page.waitForFunction(() => {
    const box = document.getElementById('netAddresses');
    return box && box.textContent.includes('http://');
  }, { timeout: 10000 });
  const addressText = await page.textContent('#netAddresses');
  check('показан адрес сервера', addressText.includes('http://'), addressText);
  check('адрес не только loopback', !/^\s*http:\/\/127\./.test(addressText.trim()), addressText);
  check('есть кнопка копирования', (await page.$$('#netAddresses button')).length > 0);

  const pinText = (await page.textContent('#netPin')).trim();
  check('PIN из шести цифр', /^\d{6}$/.test(pinText), pinText);

  check('тумблер включён', await page.isChecked('#netEnabled'));
  const hint = await page.textContent('#netEnabledHint');
  check('подпись тумблера объясняет состояние', hint.length > 10, hint);

  // QR: картинка должна реально загрузиться, а не остаться битой.
  await page.click('#netShowQr');
  await page.waitForTimeout(700);
  check('QR показан', await page.isVisible('#netQrBox'));
  const qrOk = await page.evaluate(() => {
    const img = document.getElementById('netQrImage');
    return !!img && img.complete && img.naturalWidth > 20;
  });
  check('QR-картинка загрузилась', qrOk);
  await page.click('#netShowQr');
  await page.waitForTimeout(300);
  check('QR скрывается повторным нажатием', !(await page.isVisible('#netQrBox')));

  // ===== Смена PIN =====
  page.once('dialog', d => d.accept());
  await page.click('#netRegenPin');
  await page.waitForFunction(old => {
    const el = document.getElementById('netPin');
    return el && el.textContent.trim() !== old;
  }, pinText, { timeout: 10000 });
  const newPin = (await page.textContent('#netPin')).trim();
  check('PIN сменился', /^\d{6}$/.test(newPin) && newPin !== pinText, `${pinText} -> ${newPin}`);

  // Отказ от подтверждения не должен менять PIN.
  page.once('dialog', d => d.dismiss());
  await page.click('#netRegenPin');
  await page.waitForTimeout(600);
  check('отказ оставил PIN прежним', (await page.textContent('#netPin')).trim() === newPin);

  // ===== Чужие серверы =====
  await page.fill('#netServerUrl', '192.168.77.88:5000');
  await page.click('#netAddServer');
  await page.waitForFunction(() => {
    const box = document.getElementById('netServers');
    return box && box.textContent.includes('192.168.77.88');
  }, { timeout: 10000 });
  check('сервер добавлен в список', (await page.textContent('#netServers')).includes('192.168.77.88'));
  check('поле адреса очищено', (await page.inputValue('#netServerUrl')) === '');

  const rowsBefore = (await page.$$('#netServers .net-row')).length;
  check('строка сервера отрисована', rowsBefore >= 1, `строк ${rowsBefore}`);

  // Проверка связи с недоступным адресом должна дать понятный ответ.
  const checkBtn = await page.$('#netServers .net-row button');
  await checkBtn.click();
  await page.waitForFunction(() => {
    const el = document.getElementById('netScanStatus');
    return el && el.textContent.includes('192.168.77.88');
  }, { timeout: 20000 });
  const probeText = await page.textContent('#netScanStatus');
  check('недоступный сервер помечен', probeText.includes('не отвечает'), probeText);

  // Битый адрес должен отклоняться с объяснением.
  await page.fill('#netServerUrl', 'хост с пробелом');
  await page.click('#netAddServer');
  await page.waitForFunction(() => {
    const el = document.getElementById('netScanStatus');
    return el && el.textContent.includes('Не удалось добавить');
  }, { timeout: 10000 });
  check('битый адрес отклонён', (await page.textContent('#netScanStatus')).includes('Не удалось добавить'));

  // Удаление сервера.
  const buttons = await page.$$('#netServers .net-row button');
  await buttons[buttons.length - 1].click();
  await page.waitForFunction(() => {
    const box = document.getElementById('netServers');
    return box && !box.textContent.includes('192.168.77.88');
  }, { timeout: 10000 });
  check('сервер убран из списка', !(await page.textContent('#netServers')).includes('192.168.77.88'));

  // ===== Тумблер доступа =====
  await page.uncheck('#netEnabled');
  await page.waitForFunction(() => {
    const el = document.getElementById('netEnabledHint');
    return el && el.textContent.includes('только с этого компьютера');
  }, { timeout: 10000 });
  check('выключение отражено в подписи', true);
  const disabledState = await page.evaluate(async base => {
    const res = await fetch(base + '/api/network/info');
    return (await res.json()).enabled;
  }, BASE);
  check('сервер запомнил выключение', disabledState === false, String(disabledState));
  await page.check('#netEnabled');
  await page.waitForTimeout(700);
  const enabledState = await page.evaluate(async base => {
    const res = await fetch(base + '/api/network/info');
    return (await res.json()).enabled;
  }, BASE);
  check('сервер запомнил включение', enabledState === true, String(enabledState));

  // ===== Владелец видит свои кнопки =====
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  check('владелец видит поле ссылки', await page.$('#urlInput') !== null);
  check('владелец видит очередь', await page.$('[data-nav="queue"]') !== null);
  check('владелец видит плейлисты', await page.$('#sidebarCollections') !== null);
  check('у владельца нет кнопки PIN', await page.$('#guestUnlockBtn') === null);

  // ===== Гость из локальной сети =====
  if (!LAN) {
    console.log('LT_LAN не задан — гостевая часть пропущена.');
  } else {
    // Отдельный контекст: у гостя не должно быть cookie владельца.
    const guestContext = await browser.newContext();
    const guest = await guestContext.newPage();
    const guestErrors = [];
    guest.on('pageerror', e => guestErrors.push(String(e)));
    guest.on('console', m => {
      if (m.type() === 'error' && !expectedNoise.test(m.text())) guestErrors.push(m.text());
    });

    await guest.goto(`${LAN}/`, { waitUntil: 'domcontentloaded' });
    check('главная открывается у гостя', guest.url().startsWith(LAN), guest.url());
    check('гость помечен как гость',
      await guest.evaluate(() => typeof IS_OWNER !== 'undefined' && IS_OWNER === false));
    check('гость не видит поле ссылки', await guest.$('#urlInput') === null);
    check('гость не видит очередь', await guest.$('[data-nav="queue"]') === null);
    check('гость не видит плейлисты', await guest.$('#sidebarCollections') === null);
    check('гость не видит скрытые каналы', await guest.$('#hiddenChannelsList') === null);
    check('гостю доступен поиск', await guest.$('#searchInput') !== null);
    check('гость видит кнопку входа по PIN', await guest.$('#guestUnlockBtn') !== null);
    check('PIN не попал на страницу гостя',
      !(await guest.content()).includes(newPin));

    // Настройки закрыты: сервер отвечает 403.
    const settingsCode = await guest.evaluate(async lan => {
      const res = await fetch(lan + '/settings');
      return res.status;
    }, LAN);
    check('настройки закрыты гостю', settingsCode === 403, `код ${settingsCode}`);

    const userdataCode = await guest.evaluate(async lan => {
      const res = await fetch(lan + '/api/userdata');
      return res.status;
    }, LAN);
    check('личные данные закрыты гостю', userdataCode === 403, `код ${userdataCode}`);

    // Избранное гостя должно жить у него, а не уходить на сервер.
    const favBtn = await guest.$('.video-card .fav-btn, .card-actions .fav-btn');
    if (favBtn) {
      await favBtn.click();
      await guest.waitForTimeout(600);
      const localFavs = await guest.evaluate(() =>
        JSON.parse(localStorage.getItem('lt_guest_favorites') || '[]').length);
      check('избранное гостя сохранилось локально', localFavs > 0, `записей ${localFavs}`);
      // Ключи владельца гость трогать не должен: их читает перенос старых
      // данных на сервер, и при входе по PIN избранное гостя уехало бы владельцу.
      const ownerKeysTouched = await guest.evaluate(() =>
        !!localStorage.getItem('lt_favorites') || !!localStorage.getItem('lt_history'));
      check('гость не пишет в ключи владельца', !ownerKeysTouched);
      const ownerFavsBefore = await page.evaluate(async base => {
        const res = await fetch(base + '/api/userdata');
        return ((await res.json()).favorites || []).length;
      }, BASE);
      check('избранное владельца не тронуто', ownerFavsBefore === 0, `записей ${ownerFavsBefore}`);
    }

    // ===== Вход по PIN =====
    guest.once('dialog', d => d.accept(newPin));
    await guest.click('#guestUnlockBtn');
    await guest.waitForTimeout(2500);
    const afterUnlock = await guest.evaluate(async lan => {
      const res = await fetch(lan + '/api/userdata');
      return res.status;
    }, LAN);
    check('после PIN личные данные открылись', afterUnlock === 200, `код ${afterUnlock}`);
    await guest.goto(`${LAN}/`, { waitUntil: 'domcontentloaded' });
    check('после PIN вернулись кнопки владельца', await guest.$('#urlInput') !== null);
    // Здесь и был настоящий дефект: гость писал в lt_favorites, а перенос
    // старых данных отправлял этот ключ на сервер сразу после входа по PIN.
    await guest.waitForTimeout(1500);
    const ownerFavsAfter = await page.evaluate(async base => {
      const res = await fetch(base + '/api/userdata');
      return ((await res.json()).favorites || []).length;
    }, BASE);
    check('избранное гостя не утекло владельцу после PIN', ownerFavsAfter === 0,
      `записей ${ownerFavsAfter}`);

    // Выход возвращает права гостя.
    await guest.evaluate(async lan => {
      await fetch(lan + '/api/network/lock', { method: 'POST' });
    }, LAN);
    await guest.goto(`${LAN}/`, { waitUntil: 'domcontentloaded' });
    check('после выхода снова гость', await guest.$('#urlInput') === null);

    // Выключенный тумблер закрывает гостя целиком.
    await page.evaluate(async base => {
      await fetch(base + '/api/network/enabled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: false }),
      });
    }, BASE);
    const closedCode = await guest.evaluate(async lan => {
      const res = await fetch(lan + '/api/catalog');
      return res.status;
    }, LAN);
    check('выключенный доступ закрывает гостя', closedCode === 403, `код ${closedCode}`);
    await page.evaluate(async base => {
      await fetch(base + '/api/network/enabled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true }),
      });
    }, BASE);

    check('нет ошибок в консоли у гостя', guestErrors.length === 0, guestErrors.join(' | '));
    await guestContext.close();
  }

  const leftovers = await cleanup(page);
  check('добавленные серверы убраны', leftovers === 0, `осталось ${leftovers}`);

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
  // Уборка нужна и при падении: иначе сервер останется закрытым для сети, а в
  // списке останутся выдуманные адреса.
  console.error(e);
  try {
    const browser = await chromium.launch();
    const page = await browser.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await cleanup(page);
    await browser.close();
    console.log('Настройки доступа восстановлены.');
  } catch (inner) {
    console.error('Восстановить настройки не удалось: ' + inner.message);
  }
  process.exit(1);
});
