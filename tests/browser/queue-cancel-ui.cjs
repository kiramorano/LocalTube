// Browser test: queue cancel + priority controls.
// All queue API calls are intercepted, so nothing touches YouTube or real files.
const { chromium } = require('playwright');
const path = require('path');

const BASE = 'http://127.0.0.1:5000';
const SHOTS = path.join(__dirname, 'shots');
const results = [];

function record(test, pass, detail, errors) {
  results.push({ test, pass, detail, errors: errors || [] });
}

function task(over) {
  return Object.assign({
    id: 'x1', title: 'Тестовое видео', urls: ['https://youtu.be/abc'],
    status: 'waiting', progress: 0, message: '', error: '', added_at: new Date().toISOString(),
    current_url: '', current_index: 0, total_urls: 1, speed: '', eta: '',
    attempts: 0, priority: 'normal', cancelling: false,
  }, over);
}

async function openQueue(page, tasks, calls) {
  // Without a dialog handler any confirm() would block the page forever.
  if (!page.listenerCount('dialog')) page.on('dialog', d => d.accept());
  await page.route('**/api/queue/list', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ tasks, paused: false }),
  }));
  await page.route('**/api/queue/cancel/**', route => {
    calls.cancel.push(route.request().url());
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', was_downloading: true }) });
  });
  await page.route('**/api/queue/priority/**', route => {
    calls.priority.push({ url: route.request().url(), body: route.request().postDataJSON() });
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', priority: 'high' }) });
  });
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => filterNav('queue'));
  await page.waitForFunction(() => document.querySelectorAll('#queueList .queue-item').length > 0, { timeout: 15000 });
}

async function main() {
  const browser = await chromium.launch();

  // 1. Waiting task shows cancel button and priority select.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'w1', status: 'waiting' })], calls);
    const detail = await page.evaluate(() => ({
      hasCancel: !!document.querySelector('.cancel-btn'),
      hasPrioritySelect: !!document.querySelector('.queue-priority-select'),
      selectValue: document.querySelector('.queue-priority-select')?.value,
      optionCount: document.querySelectorAll('.queue-priority-select option').length,
    }));
    record('waiting task: cancel + priority controls',
      detail.hasCancel && detail.hasPrioritySelect && detail.selectValue === 'normal' && detail.optionCount === 3,
      detail, errors);
    await page.screenshot({ path: path.join(SHOTS, 'queue-cancel-waiting.png') });
    await page.close();
  }

  // 2. Downloading task can be cancelled (confirm dialog accepted).
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('dialog', d => d.accept());
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'd1', status: 'downloading', progress: 42, speed: '1.5MiB/s', eta: '00:30', current_url: 'https://youtu.be/abc' })], calls);
    const before = await page.evaluate(() => ({
      hasCancel: !!document.querySelector('.cancel-btn'),
      // Active downloads must not be removable without cancelling first.
      hasRemove: !!document.querySelector('.remove-btn'),
    }));
    await page.click('.cancel-btn');
    await page.waitForTimeout(500);
    record('downloading task: cancel calls API',
      before.hasCancel && !before.hasRemove && calls.cancel.length === 1 && calls.cancel[0].includes('/d1'),
      { before, cancelCalls: calls.cancel }, errors);
    await page.close();
  }

  // 3. Declining the confirm dialog must not cancel anything.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('dialog', d => d.dismiss());
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'd2', status: 'downloading', progress: 10 })], calls);
    await page.click('.cancel-btn');
    await page.waitForTimeout(400);
    record('declining confirm keeps download', calls.cancel.length === 0, { cancelCalls: calls.cancel }, errors);
    await page.close();
  }

  // 4. Priority change sends the chosen value.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'p1', status: 'waiting' })], calls);
    await page.selectOption('.queue-priority-select', 'high');
    await page.waitForTimeout(500);
    record('priority select posts new value',
      calls.priority.length === 1 && calls.priority[0].body.priority === 'high' && calls.priority[0].url.includes('/p1'),
      calls.priority, errors);
    await page.close();
  }

  // 5. Cancelling state hides the cancel button and shows progress text.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'd3', status: 'downloading', cancelling: true, message: 'Отмена загрузки...' })], calls);
    const detail = await page.evaluate(() => ({
      hasCancel: !!document.querySelector('.cancel-btn'),
      statusText: document.querySelector('.queue-item-status')?.textContent.trim(),
    }));
    record('cancelling state shows progress, hides button',
      !detail.hasCancel && detail.statusText.includes('Отмена'), detail, errors);
    await page.close();
  }

  // 6. Cancelled task can be retried and removed.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'c1', status: 'cancelled', message: 'Отменено пользователем' })], calls);
    const detail = await page.evaluate(() => ({
      statusText: document.querySelector('.queue-item-status')?.textContent.trim(),
      hasRetry: !!document.querySelector('.retry-btn'),
      hasRemove: !!document.querySelector('.remove-btn'),
      hasCancel: !!document.querySelector('.cancel-btn'),
      summary: document.getElementById('queueSummary')?.textContent || '',
    }));
    record('cancelled task: retry + remove, no cancel',
      detail.hasRetry && detail.hasRemove && !detail.hasCancel &&
      detail.statusText.includes('Отменено') && detail.summary.includes('Отменено: 1'),
      detail, errors);
    await page.screenshot({ path: path.join(SHOTS, 'queue-cancelled.png') });
    await page.close();
  }

  // 7. Priority badge renders for high/low, filter shows cancelled tasks.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [
      task({ id: 'h1', status: 'waiting', priority: 'high', title: 'Срочное' }),
      task({ id: 'l1', status: 'waiting', priority: 'low', title: 'Потом' }),
      task({ id: 'c2', status: 'cancelled', title: 'Отменённое' }),
    ], calls);
    const badges = await page.evaluate(() => Array.from(document.querySelectorAll('.queue-priority')).map(e => e.textContent.trim()));
    await page.selectOption('#queueFilter', 'cancelled');
    await page.waitForTimeout(300);
    const filtered = await page.evaluate(() => ({
      items: document.querySelectorAll('.queue-item').length,
      title: document.querySelector('.queue-item-title')?.textContent.trim(),
    }));
    record('priority badges + cancelled filter',
      badges.length === 2 && badges.some(b => b.includes('Высокий')) && badges.some(b => b.includes('Низкий')) &&
      filtered.items === 1 && filtered.title.includes('Отменённое'),
      { badges, filtered }, errors);
    await page.close();
  }

  // 8. XSS safety: malicious title must not execute or inject markup.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({
      id: 'x2', status: 'waiting',
      title: '<img src=x onerror="window.__pwned=1">',
      current_url: '"><script>window.__pwned2=1</script>',
    })], calls);
    const detail = await page.evaluate(() => ({
      pwned: !!window.__pwned || !!window.__pwned2,
      injectedImg: !!document.querySelector('.queue-item-title img'),
      titleText: document.querySelector('.queue-item-title')?.textContent.trim(),
    }));
    record('malicious title is escaped',
      !detail.pwned && !detail.injectedImg && detail.titleText.includes('<img'), detail, errors);
    await page.close();
  }

  // 9. Frutiger Aero theme keeps controls readable.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.addInitScript(() => localStorage.setItem('lt_theme', 'frutiger-aero'));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'a1', status: 'waiting', priority: 'high' })], calls);
    const detail = await page.evaluate(() => {
      const sel = document.querySelector('.queue-priority-select');
      const btn = document.querySelector('.cancel-btn');
      const rect = sel.getBoundingClientRect();
      const btnRect = btn.getBoundingClientRect();
      return {
        theme: document.documentElement.dataset.theme,
        selectVisible: rect.width > 40 && rect.height > 15,
        buttonVisible: btnRect.width > 40 && btnRect.height > 15,
        optionColor: getComputedStyle(sel.querySelector('option')).color,
      };
    });
    record('aero: controls sized and readable',
      detail.theme === 'frutiger-aero' && detail.selectVisible && detail.buttonVisible, detail, errors);
    await page.screenshot({ path: path.join(SHOTS, 'queue-cancel-aero.png') });
    await page.close();
  }

  // 10. Mobile viewport: controls must not overflow horizontally.
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const calls = { cancel: [], priority: [] };
    await openQueue(page, [task({ id: 'm1', status: 'waiting', priority: 'high', title: 'Очень длинное название видео для проверки переноса на мобильном экране' })], calls);
    const detail = await page.evaluate(() => ({
      hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      cancelVisible: !!document.querySelector('.cancel-btn')?.getBoundingClientRect().width,
      selectVisible: !!document.querySelector('.queue-priority-select')?.getBoundingClientRect().width,
    }));
    record('mobile: no horizontal scroll, controls present',
      !detail.hScroll && detail.cancelVisible && detail.selectVisible, detail, errors);
    await page.screenshot({ path: path.join(SHOTS, 'queue-cancel-mobile.png') });
    await page.close();
  }

  await browser.close();

  console.log(JSON.stringify(results, null, 2));
  console.log('\n=== SUMMARY ===');
  let failed = 0;
  for (const r of results) {
    const jsErrors = r.errors.length ? `  [js errors: ${r.errors.length}]` : '';
    if (!r.pass || r.errors.length) failed++;
    console.log(`${r.pass && !r.errors.length ? 'PASS' : 'FAIL'}  ${r.test}${jsErrors}`);
  }
  process.exitCode = failed ? 1 : 0;
}

main().catch(e => { console.error(e); process.exitCode = 1; });
