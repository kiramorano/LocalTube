// Runs every browser check in sequence and exits non-zero if any of them fails.
// Requires a running LocalTube server: python app.py
const { spawnSync } = require('child_process');
const path = require('path');

const SCRIPTS = [
  'fix-verify.cjs',
  'channel-verify.cjs',
  'channel-sync-ui.cjs',
  'about-contrast.cjs',
  'queue-ui.cjs',
  'queue-cancel-ui.cjs',
  'queue-verify.cjs',
  'url-download-ui.cjs',
  'picker-verify.cjs',
  'userdata-verify.cjs',
  'cookies-browser-ui.cjs',
  'settings-sections.cjs',
  'collections-ui.cjs',
  // Сворачивание боковой панели на десктопе и её выдвижение на узком экране.
  'sidebar-collapse.cjs',
  // Переключение языка интерфейса: cookie, серверный рендер и клиентские строки.
  'language-switch.cjs',
  // Выбор качества 144p-2160p: порядок ступеней, пересборка и её прогресс.
  'quality-switch.cjs',
  // Доступ из локальной сети. Гостевую часть проверяет только при LT_LAN:
  // сервер надо поднять на 0.0.0.0 (LT_HOST), иначе всякий клиент — владелец.
  'lan-access.cjs',
  'hidden-channels.cjs',
  'mobile-shorts.cjs',
  'mobile-channel.cjs',
  // Тема: проверяет применение до отрисовки, контраст текста, геометрию поиска
  // и обои. Для проверки меню плеера нужен LT_VIDEO_ID обычного (не Shorts) видео.
  'theme-verify.cjs',
  'visual-audit.cjs',
];

let failed = 0;
for (const script of SCRIPTS) {
  process.stdout.write(`\n=== ${script} ===\n`);
  const res = spawnSync(process.execPath, [path.join(__dirname, script)], {
    stdio: 'inherit',
    cwd: __dirname,
  });
  if (res.status !== 0) {
    failed++;
    process.stdout.write(`--- ${script} FAILED (exit ${res.status}) ---\n`);
  }
}

process.stdout.write(`\n${SCRIPTS.length - failed}/${SCRIPTS.length} browser scripts passed\n`);
process.exitCode = failed ? 1 : 0;
