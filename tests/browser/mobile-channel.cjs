const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium, devices } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const out = [];
  for (const theme of ['dark', 'frutiger-aero']) {
    const ctx = await b.newContext({ ...devices['Pixel 5'], hasTouch: true, isMobile: true });
    const p = await ctx.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push('pageerror: ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    await p.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    await p.goto('http://127.0.0.1:5000/channel/' + encodeURIComponent('ANATA CARS'), { waitUntil: 'networkidle' });
    await p.waitForTimeout(1500);
    const before = await p.evaluate(() => {
      const n = document.querySelector('.tabs');
      return { docHScroll: document.documentElement.scrollWidth > innerWidth + 1, tabsScrollable: n.scrollWidth > n.clientWidth + 1, scrollLeft: n.scrollLeft, hasFade: !!getComputedStyle(document.querySelector('.tabs-wrap'), '::after').content };
    });
    // tapping the last tab must scroll it into view
    await p.tap('.tab[data-tab="about"]');
    await p.waitForTimeout(600);
    const after = await p.evaluate(() => {
      const n = document.querySelector('.tabs');
      const t = document.querySelector('.tab[data-tab="about"]');
      const tr = t.getBoundingClientRect(), nr = n.getBoundingClientRect();
      const visible = [...document.querySelectorAll('.panel')].filter(x => getComputedStyle(x).display !== 'none').map(x => x.id);
      return { scrollLeft: Math.round(n.scrollLeft), tabFullyVisible: tr.left >= nr.left - 1 && tr.right <= nr.right + 1, visible, docHScroll: document.documentElement.scrollWidth > innerWidth + 1 };
    });
    out.push({ theme, pass: !before.docHScroll && !after.docHScroll && after.tabFullyVisible && after.visible.length === 1 && after.visible[0] === 'about' && errs.length === 0, before, after, errs });
    await p.screenshot({ path: path.join(SHOTS, `mobile-channel-${theme}.png`), fullPage: true });
    await ctx.close();
  }
  await b.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  mobile channel [' + r.theme + ']'));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });