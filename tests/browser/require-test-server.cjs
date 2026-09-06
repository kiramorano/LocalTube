// Общая защита для браузерных проверок, которые меняют данные пользователя.
//
// Скрипты чистят историю, избранное и скрытые каналы, создают плейлисты и меняют
// PIN. Запуск против рабочего сервера (порт 5000) делал это с настоящими данными:
// в userdata.json пользователя так появилась лишняя запись истории.
//
// serve_test.py отдаёт /api/test-mode со списком изолированных файлов. Если
// признака нет, значит сервер рабочий — работать с ним отказываемся.
async function requireTestServer(base, needed) {
  let info;
  try {
    const res = await fetch(base + '/api/test-mode');
    if (!res.ok) throw new Error('код ' + res.status);
    info = await res.json();
  } catch (err) {
    throw new Error(
      `${base} не похож на тестовый сервер (${err.message}).\n` +
      'Проверки меняют данные пользователя, поэтому нужен изолированный сервер:\n' +
      '  python tests/browser/serve_test.py\n' +
      '  LT_BASE=http://127.0.0.1:5004 node <скрипт>.cjs'
    );
  }
  const missing = (needed || []).filter(name => !info.isolated.includes(name));
  if (missing.length) {
    throw new Error(
      `${base}: не изолированы ${missing.join(', ')}. ` +
      'Уберите LT_USE_REAL_* и перезапустите serve_test.py.'
    );
  }
  return info;
}

module.exports = { requireTestServer };
