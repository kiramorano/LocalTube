// Runs every browser check in sequence and exits non-zero if any of them fails.
// Requires a running LocalTube server: python app.py
const { spawnSync } = require('child_process');
const path = require('path');

const SCRIPTS = [
  'fix-verify.cjs',
  'channel-verify.cjs',
  'channel-sync-ui.cjs',
  'queue-ui.cjs',
  'queue-cancel-ui.cjs',
  'userdata-verify.cjs',
  'hidden-channels.cjs',
  'mobile-shorts.cjs',
  'mobile-channel.cjs',
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
