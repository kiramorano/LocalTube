const path = require('path');
const SHOTS = path.join(__dirname, 'shots');
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5000';

// Renders queue states purely client-side via renderQueue(); the real queue is never modified.
const FIXTURE = [
  { id: 'w1', title: 'Ожидает загрузки', urls: ['https://example.invalid/one'], status: 'waiting', progress: 0, message: 'Подготовка', current_url: '', current_index: 0, total_urls: 1, speed: '', eta: '', attempts: 1 },
  { id: 'd1', title: 'Загрузка пачки <b>test</b>', urls: ['a', 'b'], status: 'downloading', progress: 47.5, message: '[1/2] Загрузка: 47.5% · 1.20MiB/s · ETA 00:31', current_url: 'https://example.invalid/two?x=1&y=2', current_index: 1, total_urls: 2, speed: '1.20MiB/s', eta: '00:31', attempts: 2 },
  { id: 'c1', title: 'Готово', urls: ['c'], status: 'completed', progress: 100, message: 'Готово', current_url: '', current_index: 1, total_urls: 1, speed: '', eta: '', attempts: 1 },
  { id: 'e1', title: 'Ошибка загрузки', urls: ['d'], status: 'error', progress: 0, message: 'Ошибка скачивания', error: 'Видео недоступно', current_url: '', current_index: 1, total_urls: 1, speed: '', eta: '', attempts: 3 },
];

async function main() {
  const browser = await chromium.launch();
  const results = [];

  for (const theme of ['dark', 'frutiger-aero']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });

    // Stop polling so the fixture is not overwritten by the real (empty) queue.
    await page.evaluate(() => { if (window.queuePollInterval) clearInterval(window.queuePollInterval); });
    await page.evaluate(() => filterNav('queue'));
    await page.waitForTimeout(300);

    const controls = await page.evaluate(() => ({
      queueVisible: getComputedStyle(document.getElementById('queueContainer')).display !== 'none',
      options: [...document.querySelectorAll('#queueFilter option')].map(o => o.value),
      buttons: [...document.querySelectorAll('#queueContainer .queue-toolbar-actions button')].map(b => b.textContent.trim()),
    }));

    const render = await page.evaluate((tasks) => {
      clearInterval(window.queuePollInterval);
      renderQueue(tasks, true);
      const items = [...document.querySelectorAll('.queue-item')];
      const downloading = items.find(i => i.querySelector('.status-downloading'));
      const errorItem = items.find(i => i.querySelector('.status-error'));
      return {
        count: items.length,
        summary: document.getElementById('queueSummary').textContent,
        downloadingText: downloading?.textContent.replace(/\s+/g, ' ').trim() || '',
        progressWidth: downloading?.querySelector('.progress-fill-queue')?.style.width || '',
        currentUrl: downloading?.querySelector('.queue-current-url')?.textContent || '',
        // Title contains raw HTML in the fixture: it must be escaped, not interpreted.
        titleHasBoldElement: !!downloading?.querySelector('.queue-item-title b'),
        titleText: downloading?.querySelector('.queue-item-title')?.textContent || '',
        downloadingHasRemove: !!downloading?.querySelector('.remove-btn'),
        errorHasRetry: !!errorItem?.querySelector('.retry-btn'),
        errorText: errorItem?.textContent.replace(/\s+/g, ' ').trim() || '',
      };
    }, FIXTURE);

    // The change handler re-renders from the module-scoped lastQueueTasks, which
    // cannot be set from outside. Feed the fixture through the API instead.
    await page.route('**/api/queue/list', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ tasks: FIXTURE, paused: false }),
    }));
    await page.evaluate(() => loadQueue());
    await page.waitForFunction(() => document.querySelectorAll('#queueList .queue-item').length === 4, { timeout: 15000 });
    const filters = {};
    for (const value of ['all', 'active', 'waiting', 'downloading', 'completed', 'error', 'cancelled']) {
      // selectOption already triggers the change handler; re-rendering after it
      // was racing with the handler and produced stale counts.
      await page.selectOption('#queueFilter', value);
      await page.waitForTimeout(200);
      filters[value] = await page.evaluate(() => ({
        count: document.querySelectorAll('.queue-item').length,
        empty: document.querySelector('.queue-empty')?.textContent || '',
      }));
    }

    // Empty state
    await page.evaluate(() => { window.lastQueueTasks = []; renderQueue([], false); });
    const emptyState = await page.evaluate(() => ({
      text: document.querySelector('.queue-empty')?.textContent || '',
      summary: document.getElementById('queueSummary').textContent,
    }));

    const pass = errors.length === 0
      && controls.queueVisible
      && controls.options.length === 7 && controls.options.includes('cancelled')
      && controls.buttons.some(b => b.includes('Пауза')) && controls.buttons.some(b => b.includes('Возобновить'))
      && controls.buttons.some(b => b.includes('Повторить ошибки')) && controls.buttons.some(b => b.includes('Очистить'))
      && render.count === 4
      && render.progressWidth === '47.5%'
      && render.downloadingText.includes('1.20MiB/s') && render.downloadingText.includes('ETA 00:31')
      && render.downloadingText.includes('Видео 1/2') && render.downloadingText.includes('Попытка 2')
      && render.currentUrl.includes('example.invalid/two?x=1&y=2')
      && render.titleHasBoldElement === false && render.titleText.includes('<b>test</b>')
      && render.downloadingHasRemove === false && render.errorHasRetry === true
      && render.errorText.includes('Видео недоступно')
      && render.summary.includes('Всего: 4') && render.summary.includes('приостановлена')
      && filters.all.count === 4 && filters.active.count === 2 && filters.waiting.count === 1
      && filters.downloading.count === 1 && filters.completed.count === 1 && filters.error.count === 1
      && filters.cancelled.count === 0
      && emptyState.text.includes('Очередь пуста');

    results.push({ theme, pass, controls, render, filters, emptyState, errors });
    await page.screenshot({ path: path.join(SHOTS, `queue-${theme}.png`), fullPage: true });
    await ctx.close();
  }

  await browser.close();
  console.log(JSON.stringify(results, null, 2));
  console.log('\n=== SUMMARY ===');
  results.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  queue UI [' + r.theme + ']'));
  process.exit(results.some(r => !r.pass) ? 1 : 0);
}
main().catch(e => { console.error(e); process.exit(2); });
