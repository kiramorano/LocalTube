const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5000';

async function main() {
  const browser = await chromium.launch();
  const out = [];
  for (const [theme, author] of [['dark', 'Avocado Animations'], ['frutiger-aero', 'Avocado Animations'], ['dark', 'ANATA CARS']]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    await page.goto(BASE + '/channel/' + encodeURIComponent(author), { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);

    const data = await page.evaluate(() => {
      const grab = sel => [...document.querySelectorAll(sel)].map(e => e.textContent.trim());
      const imgs = [...document.querySelectorAll('.thumb img')].map(i => ({ src: i.getAttribute('src'), w: i.naturalWidth, h: i.naturalHeight, loading: i.loading, hidden: !i.getClientRects().length }));
      return {
        theme: document.documentElement.dataset.theme,
        h1: document.querySelector('h1').textContent.trim(),
        stats: document.querySelector('.stats').textContent.trim(),
        videosMeta: grab('#videosGrid .card .meta'),
        videosDur: grab('#videosGrid .duration'),
        shortsMeta: grab('#shortsGrid .card .meta'),
        shortsDur: grab('#shortsGrid .duration'),
        featuredMeta: grab('.featured-card .meta'),
        featuredDur: grab('.featured-card .duration'),
        aboutMeta: grab('.about-meta div'),
        tabs: grab('.tab'),
        images: imgs,
        emptyPanels: [...document.querySelectorAll('.panel')].map(p => ({ id: p.id, active: p.classList.contains('active'), display: getComputedStyle(p).display })),
        hasDownloadBtn: !!document.getElementById('downloadRemaining'),
      };
    });

    // click every tab, verify exactly one panel is visible and it matches
    const tabChecks = [];
    for (const t of ['home', 'videos', 'shorts', 'playlists', 'about']) {
      await page.click(`.tab[data-tab="${t}"]`);
      await page.waitForTimeout(200);
      const state = await page.evaluate(name => {
        const visible = [...document.querySelectorAll('.panel')].filter(p => getComputedStyle(p).display !== 'none').map(p => p.id);
        const activeTabs = [...document.querySelectorAll('.tab.active')].map(e => e.dataset.tab);
        return { visible, activeTabs, expected: name };
      }, t);
      tabChecks.push({ tab: t, ok: state.visible.length === 1 && state.visible[0] === t && state.activeTabs.length === 1 && state.activeTabs[0] === t, state });
    }

    // "О канале" button in the actions row should also switch to about
    await page.click('.tab[data-tab="home"]');
    await page.waitForTimeout(150);
    await page.click('.actions .button[data-tab="about"]');
    await page.waitForTimeout(250);
    const aboutViaButton = await page.evaluate(() => {
      const visible = [...document.querySelectorAll('.panel')].filter(p => getComputedStyle(p).display !== 'none').map(p => p.id);
      return { visible, aboutTabActive: document.querySelector('.tab[data-tab="about"]').classList.contains('active') };
    });

    // sort in shorts grid
    let shortsSort = null;
    const hasShortsCards = await page.evaluate(() => document.querySelectorAll('#shortsGrid .card').length);
    if (hasShortsCards > 1) {
      await page.click('.tab[data-tab="shorts"]');
      await page.selectOption('select[data-sort="shorts"]', 'old');
      await page.waitForTimeout(300);
      shortsSort = await page.evaluate(() => [...document.querySelectorAll('#shortsGrid .card')].map(e => e.dataset.date));
    }

    // After visiting every tab, every thumbnail must be loaded (lazy images resolved)
    for (const t of ['home', 'videos', 'shorts', 'playlists']) { await page.click(`.tab[data-tab="${t}"]`); await page.waitForTimeout(700); }
    const imagesAfterTabs = await page.evaluate(() => [...document.querySelectorAll('.thumb img')].map(i => ({ src: i.getAttribute('src'), w: i.naturalWidth, h: i.naturalHeight })));
    const stillBroken = imagesAfterTabs.filter(i => i.w === 0);

    // Tabs strip must not cause page-level horizontal scroll
    const tabsScroll = await page.evaluate(() => {
      const n = document.querySelector('.tabs');
      return { docScroll: document.documentElement.scrollWidth > innerWidth + 1, tabsScrollable: n.scrollWidth > n.clientWidth + 1 };
    });

    const rawDatePattern = /\b20\d{6}\b/;
    const allText = [...data.videosMeta, ...data.shortsMeta, ...data.featuredMeta, ...data.aboutMeta].join(' | ');
    const badDur = [...data.videosDur, ...data.shortsDur, ...data.featuredDur].filter(d => { const p = d.split(':'); return p.length === 2 && parseInt(p[0], 10) > 59; });
    const brokenImages = data.images.filter(i => i.w === 0 && i.loading !== 'lazy');

    out.push({
      author, theme,
      pass: !rawDatePattern.test(allText) && badDur.length === 0 && brokenImages.length === 0
            && tabChecks.every(t => t.ok) && stillBroken.length === 0 && !tabsScroll.docScroll && aboutViaButton.visible.length === 1 && aboutViaButton.visible[0] === 'about'
            && errors.length === 0,
      rawDateLeak: rawDatePattern.test(allText) ? allText.match(rawDatePattern) : null,
      badDur, brokenImages, stillBroken, tabsScroll, tabChecks: tabChecks.filter(t => !t.ok), aboutViaButton, shortsSort,
      data, errors,
    });
    await page.screenshot({ path: path.join(SHOTS, `chan-${theme}-${author.replace(/\s+/g, '_')}.png`), fullPage: true });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + `  ${r.author} [${r.theme}]`));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
}
main().catch(e => { console.error(e); process.exit(2); });
