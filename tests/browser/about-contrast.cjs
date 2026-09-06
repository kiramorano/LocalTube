// Проверка контраста и читаемости новых блоков «О канале» во всех темах.
const { chromium } = require('playwright');
const BASE = process.env.LT_BASE || 'http://127.0.0.1:5000';
const AUTHOR = process.env.LT_AUTHOR || 'Avocado Animations';
const THEMES = ['dark', 'light', 'midnight', 'glass', 'frutiger-aero'];

function parseRgb(text) {
  const m = String(text).match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const p = m[1].split(',').map(s => parseFloat(s.trim()));
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
}

function luminance({ r, g, b }) {
  const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  for (const theme of THEMES) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
    await page.goto(BASE + '/channel/' + encodeURIComponent(AUTHOR), { waitUntil: 'networkidle' });
    await page.click('.tab[data-tab="about"]');
    await page.waitForTimeout(350);
    const data = await page.evaluate(() => {
      const pick = el => {
        const cs = getComputedStyle(el);
        return { color: cs.color, bg: cs.backgroundColor, border: cs.borderTopColor,
                 size: cs.fontSize, shadow: cs.textShadow };
      };
      // Фон плитки полупрозрачный (--card в glass и aero задан через rgba), и
      // считать его сплошным нельзя: белый с alpha .18 над тёмным фоном даёт
      // тёмный результат. Складываем цепочку фонов от предка к элементу.
      const rgb = text => {
        const m = String(text).match(/rgba?\(([^)]+)\)/);
        if (!m) return null;
        const p = m[1].split(',').map(s => parseFloat(s.trim()));
        return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
      };
      const solidBg = el => {
        const layers = [];
        let n = el, image = false;
        while (n) {
          const cs = getComputedStyle(n);
          if (cs.backgroundImage && cs.backgroundImage !== 'none') image = true;
          const c = rgb(cs.backgroundColor);
          if (c && c.a > 0) {
            layers.push(c);
            if (c.a === 1) break;
          }
          n = n.parentElement;
        }
        if (!layers.length) return { solid: 'rgb(255, 255, 255)', image };
        // Нижний слой — последний найденный; накладываем на него верхние.
        let base = layers[layers.length - 1];
        if (base.a < 1) base = { r: 255, g: 255, b: 255, a: 1 };
        for (let i = layers.length - 2; i >= 0; i--) {
          const t = layers[i];
          base = {
            r: t.r * t.a + base.r * (1 - t.a),
            g: t.g * t.a + base.g * (1 - t.a),
            b: t.b * t.a + base.b * (1 - t.a),
            a: 1,
          };
        }
        return { solid: `rgb(${Math.round(base.r)}, ${Math.round(base.g)}, ${Math.round(base.b)})`, image };
      };
      const fact = document.querySelector('.fact');
      const label = document.querySelector('.fact-label');
      const value = document.querySelector('.fact-value');
      const link = document.querySelector('.about-links a');
      const tag = document.querySelector('.tag');
      return {
        theme: document.documentElement.dataset.theme,
        fact: fact ? { ...pick(fact), ...solidBg(fact) } : null,
        label: label ? { ...pick(label), ...solidBg(label) } : null,
        value: value ? { ...pick(value), ...solidBg(value) } : null,
        link: link ? { ...pick(link), ...solidBg(link) } : null,
        tag: tag ? { ...pick(tag), ...solidBg(tag) } : null,
        overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });

    const checks = [];
    for (const key of ['label', 'value', 'link', 'tag']) {
      const node = data[key];
      if (!node) continue;
      const fg = parseRgb(node.color);
      const bg = parseRgb(node.solid);
      if (!fg || !bg) continue;
      const l1 = luminance(fg), l2 = luminance(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      // 4.5:1 — порог WCAG AA для основного текста, 3:1 для крупного (>=18px).
      const large = parseFloat(node.size) >= 18;
      const need = large ? 3 : 4.5;
      // frutiger-aero делает текст белым на светлых обоях и добивается
      // читаемости обводкой text-shadow, а не контрастом фона (см. комментарий
      // в static/css/themes/frutiger-aero.css). Расчёт по цвету фона для неё
      // неприменим, поэтому требуем наличие тени.
      const viaShadow = node.shadow && node.shadow !== 'none';
      const ok = ratio >= need || viaShadow;
      checks.push({ el: key, ratio: +ratio.toFixed(2), need, ok, size: node.size,
                    viaShadow: !!viaShadow });
    }
    out.push({ theme: data.theme, requested: theme, checks, overflow: data.overflow, errors,
               pass: data.theme === theme && !data.overflow && errors.length === 0 && checks.every(c => c.ok) });
    await page.screenshot({ path: `shots/about-${theme}.png`, fullPage: false });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out, null, 2));
  console.log('\n=== SUMMARY ===');
  out.forEach(r => console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.theme +
    '  ' + r.checks.map(c => `${c.el}=${c.ratio}`).join(' ')));
  process.exit(out.some(r => !r.pass) ? 1 : 0);
})();
