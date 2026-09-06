// Сворачивание боковой панели на десктопе.
//
// Дефект: на широких экранах кнопка-гамбургер только затемняла экран, а панель
// оставалась на месте. Причина в каскаде инлайновых стилей index.html:
// `@media (min-width: 1000px) { .sidebar-drawer { left: 0 } }` (строка 51)
// закрепляет панель без учёта класса состояния, а `.sidebar-drawer.active`
// (строка 46) стоит выше и потому проигрывает. Оверлей же гасится строкой 52
// внутри того же медиазапроса, но она объявлена ДО `.sidebar-overlay.active`
// (строка 62) при равной специфичности — поэтому затемнение включалось.
//
// Ни один тест этого не ловил: theme-verify.cjs проверяет панель только на
// мобильном вьюпорте, а queue-verify.cjs на десктопе убеждается лишь в том, что
// панель видна.
const { chromium } = require('playwright');
const { requireTestServer } = require('./require-test-server.cjs');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';
// Панель закреплена на широких экранах только там, где контент сдвинут на её
// ширину (#mainContent / #queueContainer). На /upload и /edit панель всегда
// выдвижная — контент там центрирован в .container и место освобождать не нужно.
const PINNED_PAGES = ['/'];
const DRAWER_PAGES = ['/upload'];

async function readState(page) {
  return page.evaluate(() => {
    const drawer = document.getElementById('sidebarDrawer');
    const overlay = document.getElementById('sidebarOverlay');
    const main = document.getElementById('mainContent');
    const dRect = drawer.getBoundingClientRect();
    const oStyle = getComputedStyle(overlay);
    return {
      // Панель считается видимой, если её правый край правее нуля.
      visible: dRect.right > 1,
      left: Math.round(dRect.left),
      width: Math.round(dRect.width),
      collapsed: drawer.classList.contains('collapsed'),
      overlayOpacity: parseFloat(oStyle.opacity),
      overlayHits: oStyle.pointerEvents !== 'none',
      mainLeft: main ? Math.round(main.getBoundingClientRect().left) : null,
      ariaExpanded: document.getElementById('sidebarToggle').getAttribute('aria-expanded'),
    };
  });
}

(async () => {
  await requireTestServer(BASE, []);
  const browser = await chromium.launch();
  const out = [];

  for (const path of PINNED_PAGES) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(BASE + path, { waitUntil: 'networkidle' });

    const initial = await readState(page);
    await page.click('#sidebarToggle');
    await page.waitForTimeout(450);            // ждём transition left .3s
    const afterCollapse = await readState(page);
    await page.click('#sidebarToggle');
    await page.waitForTimeout(450);
    const afterExpand = await readState(page);

    // Панель должна уехать за край, а не просто затемнить экран.
    const collapses = !afterCollapse.visible;
    // Затемнение на десктопе — дефект: панель не перекрывает контент.
    const noDarkening = afterCollapse.overlayOpacity === 0
      && initial.overlayOpacity === 0
      && !afterCollapse.overlayHits;
    // Контент должен занять освободившееся место.
    const contentReflows = afterCollapse.mainLeft < initial.mainLeft - 100;
    const expandsBack = afterExpand.visible && afterExpand.left === 0;
    const ariaOk = initial.ariaExpanded === 'true'
      && afterCollapse.ariaExpanded === 'false'
      && afterExpand.ariaExpanded === 'true';

    out.push({
      path,
      pass: initial.visible && collapses && noDarkening && contentReflows
            && expandsBack && ariaOk && errors.length === 0,
      initial, afterCollapse, afterExpand,
      collapses, noDarkening, contentReflows, expandsBack, ariaOk, errors,
    });
    await page.screenshot({ path: `shots/sidebar-collapsed-${path.replace(/\W+/g, '_')}.png` });
    await ctx.close();
  }

  // Страницы без закрепления: панель выдвижная и на широком экране, кнопка
  // обязана её открывать и закрывать, а оверлей — затемнять фон.
  for (const path of DRAWER_PAGES) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(BASE + path, { waitUntil: 'networkidle' });

    const closed = await readState(page);
    await page.click('#sidebarToggle');
    await page.waitForTimeout(450);
    const opened = await readState(page);
    await page.click('#sidebarToggle');
    await page.waitForTimeout(450);
    const closedAgain = await readState(page);

    out.push({
      path: path + ' (выдвижная)',
      pass: !closed.visible && opened.visible && opened.left === 0
            && !closedAgain.visible && opened.ariaExpanded === 'true'
            && closedAgain.ariaExpanded === 'false' && errors.length === 0,
      closed, opened, closedAgain, errors,
    });
    await ctx.close();
  }

  // Узкий экран: панель обязана остаться выдвижной поверх контента с затемнением.
  const ctx = await browser.newContext({ viewport: { width: 420, height: 820 } });
  const page = await ctx.newPage();
  const mobileErrors = [];
  page.on('pageerror', e => mobileErrors.push(String(e)));
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  const mClosed = await readState(page);
  await page.click('#sidebarToggle');
  await page.waitForTimeout(450);
  const mOpen = await readState(page);
  out.push({
    path: 'mobile 420px',
    pass: !mClosed.visible && mOpen.visible && mOpen.overlayOpacity > 0.5
          && mOpen.overlayHits && mobileErrors.length === 0,
    mClosed, mOpen, errors: mobileErrors,
  });
  await ctx.close();

  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  sidebar ' + r.path));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
})();
