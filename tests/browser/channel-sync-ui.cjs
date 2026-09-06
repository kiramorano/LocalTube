const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium } = require('playwright');
const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';
const CHANNEL = '/channel/' + encodeURIComponent('ANATA CARS');

// Verifies the sync diagnostics panel without hitting YouTube: network calls to the
// sync-status endpoint are intercepted so every state can be rendered deterministically.
async function withStatus(browser, theme, statusPayload) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
  await page.route('**/sync-status', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(statusPayload) }));
  await page.goto(BASE + CHANNEL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(400);
  await page.evaluate(payload => renderSyncStatus(payload), statusPayload);
  await page.waitForTimeout(150);
  const panel = await page.evaluate(() => ({
    statusText: document.getElementById('syncStatus').textContent.trim(),
    statusClass: document.getElementById('syncStatus').className,
    details: document.getElementById('syncDetails').textContent.trim(),
    errorHidden: document.getElementById('syncError').hidden,
    errorText: document.getElementById('syncError').textContent.trim(),
    buttonText: document.getElementById('syncButton').textContent.trim(),
    buttonDisabled: document.getElementById('syncButton').disabled,
    panelVisible: getComputedStyle(document.querySelector('.sync-panel')).display !== 'none',
  }));
  return { page, ctx, panel, errors };
}

async function main() {
  const browser = await chromium.launch();
  const results = [];

  // 1. never synced
  {
    const { ctx, panel, errors } = await withStatus(browser, 'dark', { status: 'never', error: '', in_progress: false });
    results.push({ test: 'status never', pass: panel.statusText.includes('не выполнялась') && panel.errorHidden && !panel.buttonDisabled && errors.length === 0, panel, errors });
    await ctx.close();
  }

  // 2. checking
  {
    const { ctx, panel, errors } = await withStatus(browser, 'dark', { status: 'checking', error: '', in_progress: true });
    results.push({ test: 'status checking', pass: panel.statusText.includes('Проверка') && panel.buttonDisabled && panel.buttonText.includes('Проверяю') && errors.length === 0, panel, errors });
    await ctx.close();
  }

  // 3. error shows the real message
  {
    const message = 'Connection aborted: ConnectionResetError 10054';
    const { ctx, panel, errors } = await withStatus(browser, 'dark', { status: 'error', error: message, in_progress: false, finished_at: 1786977047 });
    results.push({ test: 'status error', pass: panel.statusText.includes('Ошибка') && !panel.errorHidden && panel.errorText.includes('10054') && panel.details.includes('Последняя попытка') && !panel.buttonDisabled && errors.length === 0, panel, errors });
    await ctx.close();
  }

  // 4. success shows timestamp
  {
    const { ctx, panel, errors } = await withStatus(browser, 'frutiger-aero', { status: 'success', error: '', in_progress: false, finished_at: 1786977047 });
    results.push({ test: 'status success (aero)', pass: panel.statusText.includes('синхронизирован') && panel.errorHidden && panel.details.includes('Последняя попытка') && errors.length === 0, panel, errors });
    await ctx.close();
  }

  // 5. clicking the button starts sync and polls; POST is intercepted so nothing real runs
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    const calls = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    let polls = 0;
    await page.route('**/sync', route => { calls.push(route.request().method()); route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'checking', message: 'Проверка канала запущена' }) }); });
    await page.route('**/sync-status', route => {
      polls += 1;
      const body = polls <= 2
        ? { status: 'checking', in_progress: true, error: '' }
        : { status: 'error', in_progress: false, error: 'YouTube недоступен', finished_at: 1786977100 };
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto(BASE + CHANNEL, { waitUntil: 'domcontentloaded' });
    // Force a clean, enabled state so the click is not blocked by a real background sync.
    await page.evaluate(() => renderSyncStatus({ status: 'never', error: '', in_progress: false }));
    await page.click('#syncButton');
    await page.waitForTimeout(600);
    const during = await page.evaluate(() => ({ disabled: document.getElementById('syncButton').disabled, text: document.getElementById('syncStatus').textContent.trim() }));
    await page.waitForTimeout(4200);
    const after = await page.evaluate(() => ({
      disabled: document.getElementById('syncButton').disabled,
      status: document.getElementById('syncStatus').textContent.trim(),
      error: document.getElementById('syncError').textContent.trim(),
      errorHidden: document.getElementById('syncError').hidden,
    }));
    results.push({
      test: 'sync button flow',
      pass: calls.includes('POST') && during.disabled && during.text.includes('Проверка')
            && !after.disabled && after.status.includes('Ошибка') && after.error.includes('YouTube недоступен') && !after.errorHidden
            && errors.length === 0,
      detail: { calls, polls, during, after }, errors,
    });
    await page.screenshot({ path: path.join(SHOTS, 'channel-sync-error.png'), fullPage: true });
    await ctx.close();
  }

  // 6. bulk download works even when the asset sync failed: the two are unrelated,
  // sync only fetches the banner and description.
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    let remainingCalled = 0;
    let queueBody = null;
    await page.route('**/remaining', route => { remainingCalled += 1; route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'Chan', videos: [{ id: 'a', url: 'https://www.youtube.com/watch?v=a', title: 'A' }], count: 1 }) }); });
    await page.route('**/api/queue/add', route => { queueBody = route.request().postDataJSON(); route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', task_id: 'deadbeef' }) }); });
    await page.route('**/sync-status', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'error', in_progress: false, error: 'Connection reset' }) }));
    await page.goto(BASE + CHANNEL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(300);
    await page.evaluate(() => renderSyncStatus({ status: 'error', error: 'Connection reset', in_progress: false }));
    const hasButton = await page.evaluate(() => !!document.getElementById('downloadRemaining'));
    // The button now opens the picker; the queue call happens on confirm.
    let toastText = '';
    let pickerShown = false;
    if (hasButton) {
      await page.click('#downloadRemaining');
      await page.waitForTimeout(700);
      pickerShown = await page.evaluate(() => !document.getElementById('dlOverlay').hidden);
      await page.click('#dlConfirm');
      await page.waitForTimeout(700);
      toastText = await page.evaluate(() => document.getElementById('toast').textContent.trim());
    }
    results.push({
      test: 'bulk download works despite sync error',
      pass: hasButton && pickerShown && remainingCalled === 1 && toastText.includes('Добавлено в очередь')
            && !!queueBody && queueBody.urls.length === 1 && errors.length === 0,
      detail: { hasButton, pickerShown, remainingCalled, toastText, queueBody }, errors,
    });
    await ctx.close();
  }

  // 7. queue errors returned with HTTP 200 must still surface to the user
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await page.route('**/remaining', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'Chan', videos: [{ id: 'a', url: 'https://www.youtube.com/watch?v=a', title: 'A' }], count: 1 }) }));
    await page.route('**/api/queue/add', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ error: 'Нет ссылок' }) }));
    await page.route('**/sync-status', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success', in_progress: false, error: '' }) }));
    await page.goto(BASE + CHANNEL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(300);
    await page.click('#downloadRemaining');
    await page.waitForTimeout(700);
    await page.click('#dlConfirm');
    await page.waitForTimeout(700);
    const state = await page.evaluate(() => ({
      toast: document.getElementById('toast').textContent.trim(),
      disabled: document.getElementById('downloadRemaining').disabled,
      label: document.getElementById('downloadRemaining').textContent.trim(),
      // On failure the picker must stay open so the choice is not lost.
      pickerOpen: !document.getElementById('dlOverlay').hidden,
      confirmEnabled: !document.getElementById('dlConfirm').disabled,
    }));
    results.push({
      test: 'queue error with HTTP 200 is reported',
      pass: state.toast.includes('Нет ссылок') && !state.disabled && state.label.includes('Скачать остальные')
            && state.pickerOpen && state.confirmEnabled && errors.length === 0,
      detail: state, errors,
    });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
  console.log('\n=== SUMMARY ===');
  results.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.test));
  process.exit(results.some(r => !r.pass) ? 1 : 0);
}
main().catch(e => { console.error(e); process.exit(2); });
