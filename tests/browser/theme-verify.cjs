// Проверки темы в настоящем браузере.
//
// Тесты на исходники (tests/test_theme_ui.py) не видят главного: применилась ли
// тема до первой отрисовки и виден ли текст на самом деле. Здесь считаются
// реальные computed styles и контраст, потому что все правки темы ловились
// раньше только глазами.
//
// Требуется запущенный сервер: LT_BASE=http://127.0.0.1:5004
const { chromium } = require('playwright');

const BASE = process.env.LT_BASE || 'http://127.0.0.1:5004';
// /playlist маршрута нет: templates/playlist.html не отдаётся ни одним
// эндпоинтом (плейлисты показываются на главной и на странице канала).
const PAGES = ['/', '/settings', '/upload'];
// Страница видео проверяется отдельно: нужен id существующего ОБЫЧНОГО видео.
// У Shorts своя разметка без меню плеера ({% if not is_short %} в шаблоне),
// поэтому на вертикальном видео проверять меню бессмысленно.
const VIDEO_ID = process.env.LT_VIDEO_ID || '';

const failures = [];
const checks = [];

function check(name, ok, detail) {
  checks.push({ name, ok, detail });
  if (!ok) failures.push(`${name}: ${detail}`);
}

// Разбирает 'rgb(a)' в компоненты. Прозрачность важна: именно из-за
// transparent пропадал текст активных элементов.
function parseColor(value) {
  const m = String(value).match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(',').map(p => parseFloat(p.trim()));
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
}

function luminance({ r, g, b }) {
  const f = c => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(fg, bg) {
  const l1 = luminance(fg), l2 = luminance(bg);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  for (const theme of ['dark', 'light', 'midnight', 'glass', 'frutiger-aero']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(e.message));

    await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
    await page.evaluate(t => localStorage.setItem('lt_theme', t), theme);

    for (const path of PAGES) {
      const response = await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
      if (!response || response.status() >= 400) {
        check(`${theme} ${path} открывается`, false, `HTTP ${response && response.status()}`);
        continue;
      }

      // Тема должна стоять уже в domcontentloaded, без ожидания сети:
      // именно это отличает «нет вспышки» от «есть вспышка».
      const applied = await page.getAttribute('html', 'data-theme');
      check(`${theme} ${path} тема до отрисовки`, applied === theme,
        `data-theme=${applied}, ожидалось ${theme}`);

      const themedLink = await page.evaluate(() => {
        const link = document.getElementById('theme-style') || document.getElementById('theme-style-link');
        return link ? (link.getAttribute('href') || '') : null;
      });
      // dark и light — базовые: их значения объявлены инлайном в шаблоне, и
      // отдельного файла у них нет. У остальных тем он обязателен, иначе тема
      // молча выглядит как стандартная тёмная.
      const ownFile = { midnight: 'midnight.css', glass: 'glass.css', 'frutiger-aero': 'frutiger-aero.css' }[theme];
      check(`${theme} ${path} ссылка на стиль темы`,
        ownFile ? themedLink.includes(ownFile) : themedLink === '',
        `href=${JSON.stringify(themedLink)}`);

      await page.waitForLoadState('networkidle');

      // Текст не должен быть прозрачным. Раньше активный фильтр, вкладка
      // «Похожие» и пункт меню плеера получали color: var(--yt-bg), а в
      // frutiger-aero это transparent.
      const invisible = await page.evaluate(() => {
        const out = [];
        for (const el of document.querySelectorAll('body *')) {
          if (!el.textContent || !el.textContent.trim()) continue;
          const r = el.getBoundingClientRect();
          if (r.width < 1 || r.height < 1) continue;
          const style = getComputedStyle(el);
          if (style.visibility === 'hidden' || style.display === 'none') continue;
          const color = style.color;
          if (/rgba\([^)]*,\s*0\s*\)/.test(color) || color === 'transparent') {
            out.push((el.tagName.toLowerCase()) +
              (el.id ? '#' + el.id : '') +
              (typeof el.className === 'string' && el.className.trim()
                ? '.' + el.className.trim().split(/\s+/).join('.') : ''));
          }
        }
        return [...new Set(out)].slice(0, 8);
      });
      check(`${theme} ${path} нет прозрачного текста`, invisible.length === 0,
        invisible.join(', '));

      // Контраст: белым по белому текст формально виден, но прочитать его
      // нельзя. Считаем по ближайшему непрозрачному фону предка.
      const lowContrast = await page.evaluate(() => {
        // Полупрозрачные слои надо смешивать, а не пропускать: тёмное стекло
        // с alpha 0.45 поверх светлых обоев даёт средний тон, на котором белый
        // текст читается. Пропуск таких слоёв давал ложные срабатывания.
        function bgOf(el) {
          const layers = [];
          let node = el;
          while (node) {
            const m = String(getComputedStyle(node).backgroundColor).match(/rgba?\(([^)]+)\)/);
            if (m) {
              const p = m[1].split(',').map(v => parseFloat(v.trim()));
              const alpha = p.length > 3 ? p[3] : 1;
              if (alpha > 0) {
                layers.push({ r: p[0], g: p[1], b: p[2], a: alpha });
                if (alpha >= 0.999) break;
              }
            }
            node = node.parentElement;
          }
          if (!layers.length) return null;
          // Смешиваем от самого нижнего слоя к верхнему.
          let acc = layers[layers.length - 1];
          if (acc.a < 0.999) return null;  // до непрозрачного фона не дошли
          for (let i = layers.length - 2; i >= 0; i--) {
            const top = layers[i];
            acc = {
              r: top.r * top.a + acc.r * (1 - top.a),
              g: top.g * top.a + acc.g * (1 - top.a),
              b: top.b * top.a + acc.b * (1 - top.a),
              a: 1,
            };
          }
          return { r: Math.round(acc.r), g: Math.round(acc.g), b: Math.round(acc.b) };
        }
        const out = [];
        // Только элементы с собственным текстом: у контейнеров цвет
        // наследуется и даёт ложные срабатывания.
        for (const el of document.querySelectorAll('button, a, .chip, .related-tab, .settings-menu-item, .queue-item-status, label, h1, h2, h3, option')) {
          const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
          if (!own) continue;
          const r = el.getBoundingClientRect();
          if (r.width < 1 || r.height < 1) continue;
          const style = getComputedStyle(el);
          if (style.visibility === 'hidden') continue;
          const bg = bgOf(el);
          if (!bg) continue;
          out.push({
            sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/)[0] : ''),
            color: style.color,
            bg: `rgb(${bg.r}, ${bg.g}, ${bg.b})`,
            shadow: style.textShadow,
          });
        }
        return out;
      });

      const badContrast = lowContrast.filter(item => {
        const fg = parseColor(item.color), bg = parseColor(item.bg);
        if (!fg || !bg) return false;
        // Тень под текстом добавляет читаемости, её порог математически не
        // учесть — такие элементы пропускаем.
        if (item.shadow && item.shadow !== 'none') return false;
        return contrast(fg, bg) < 2.5;
      }).map(i => `${i.sel} ${i.color} на ${i.bg}`);
      check(`${theme} ${path} контраст текста`, badContrast.length === 0,
        [...new Set(badContrast)].slice(0, 6).join(' | '));

      // Горизонтальная прокрутка на широком экране означает, что что-то
      // вылезло за края: с border-radius: 40px на склеенной «пилюле» поиска
      // элементы наезжали друг на друга и растягивали страницу.
      const layout = await page.evaluate(() => {
        const de = document.documentElement;
        const wide = [...document.querySelectorAll('body *')]
          .filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.right > window.innerWidth + 2;
          })
          .slice(0, 5)
          .map(el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
            (typeof el.className === 'string' && el.className.trim()
              ? '.' + el.className.trim().split(/\s+/)[0] : ''));
        return { hScroll: de.scrollWidth > de.clientWidth + 1, wide };
      });
      check(`${theme} ${path} без горизонтальной прокрутки`, !layout.hScroll,
        `scrollWidth больше clientWidth; торчат: ${layout.wide.join(', ')}`);

      check(`${theme} ${path} без ошибок в консоли`, errors.length === 0,
        errors.slice(0, 4).join(' | '));
      errors.length = 0;
    }

    // Геометрия «пилюли» поиска: поле, выбор качества и кнопка должны стоять
    // вплотную и по одной высоте. Тема задавала всем радиус 40px, из-за чего
    // склейка распадалась на три отдельные плашки.
    await page.goto(BASE + '/', { waitUntil: 'networkidle' });
    const pill = await page.evaluate(() => {
      const input = document.querySelector('.search-container .url-input');
      const quality = document.querySelector('.search-container .url-quality');
      const button = document.querySelector('.search-container .download-btn');
      if (!input || !quality || !button) return null;
      const r = el => el.getBoundingClientRect();
      const radius = el => getComputedStyle(el);
      return {
        gapInputQuality: Math.round(r(quality).left - r(input).right),
        gapQualityButton: Math.round(r(button).left - r(quality).right),
        sameHeight: Math.abs(r(input).height - r(button).height) < 2,
        inputRightRadius: radius(input).borderTopRightRadius,
        buttonLeftRadius: radius(button).borderTopLeftRadius,
        inputLeftRadius: radius(input).borderTopLeftRadius,
        buttonRightRadius: radius(button).borderTopRightRadius,
      };
    });
    if (!pill) {
      check(`${theme} пилюля поиска найдена`, false, 'элементы поиска не найдены');
    } else {
      check(`${theme} пилюля поиска склеена`,
        Math.abs(pill.gapInputQuality) <= 1 && Math.abs(pill.gapQualityButton) <= 1,
        `зазоры: ${pill.gapInputQuality} и ${pill.gapQualityButton}`);
      check(`${theme} пилюля поиска одной высоты`, pill.sameHeight, JSON.stringify(pill));
      // В стыке радиус должен быть нулевым, по краям — скруглённым.
      check(`${theme} пилюля поиска: стык без скругления`,
        parseFloat(pill.inputRightRadius) === 0 && parseFloat(pill.buttonLeftRadius) === 0,
        `внутренние радиусы: ${pill.inputRightRadius} / ${pill.buttonLeftRadius}`);
      check(`${theme} пилюля поиска: края скруглены`,
        parseFloat(pill.inputLeftRadius) > 0 && parseFloat(pill.buttonRightRadius) > 0,
        `внешние радиусы: ${pill.inputLeftRadius} / ${pill.buttonRightRadius}`);
    }

    // Превью не должно выступать за скруглённый край карточки.
    const cardRadius = await page.evaluate(() => {
      const card = document.querySelector('.video-card');
      if (!card) return null;
      const thumb = card.querySelector('.video-thumb');
      if (!thumb) return null;
      const cs = getComputedStyle(card), ts = getComputedStyle(thumb);
      return {
        cardRadius: parseFloat(cs.borderTopLeftRadius),
        thumbRadius: parseFloat(ts.borderTopLeftRadius),
        overflow: cs.overflow,
      };
    });
    if (cardRadius) {
      // Либо карточка обрезает содержимое, либо радиусы совпадают.
      const ok = cardRadius.overflow === 'hidden' ||
        Math.abs(cardRadius.cardRadius - cardRadius.thumbRadius) <= 1;
      check(`${theme} углы превью не торчат из карточки`, ok, JSON.stringify(cardRadius));
    }

    // Список: кнопка переключения вида навешивала класс, для которого не было
    // ни одного правила, поэтому вид не менялся.
    const listView = await page.evaluate(() => {
      const grid = document.getElementById('mainGrid');
      if (!grid) return null;
      const before = getComputedStyle(grid).display;
      if (typeof toggleView !== 'function') return { before, missing: true };
      toggleView();
      const after = getComputedStyle(grid).display;
      toggleView();
      return { before, after, restored: getComputedStyle(grid).display };
    });
    if (listView) {
      check(`${theme} переключение вида работает`,
        !listView.missing && listView.before !== listView.after,
        JSON.stringify(listView));
      check(`${theme} вид возвращается обратно`,
        listView.restored === listView.before, JSON.stringify(listView));
    }

    // Меню плеера на странице видео: фон панели светлый, а текст наследовался
    // белым — получалось белое на белом, и настройки качества было не прочитать.
    if (VIDEO_ID) {
      // domcontentloaded, а не networkidle: плеер держит соединение с видео
      // открытым, поэтому сеть на этой странице никогда не «замолкает».
      const response = await page.goto(`${BASE}/watch/${VIDEO_ID}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(1200);
      if (!response || response.status() >= 400) {
        check(`${theme} страница видео открывается`, false, `HTTP ${response && response.status()}`);
      } else {
        check(`${theme} страница видео: тема до отрисовки`,
          (await page.getAttribute('html', 'data-theme')) === theme, '');

        const menus = await page.evaluate(() => {
          function blend(el) {
            const layers = [];
            let node = el;
            while (node) {
              const m = String(getComputedStyle(node).backgroundColor).match(/rgba?\(([^)]+)\)/);
              if (m) {
                const p = m[1].split(',').map(v => parseFloat(v.trim()));
                const a = p.length > 3 ? p[3] : 1;
                if (a > 0) { layers.push({ r: p[0], g: p[1], b: p[2], a }); if (a >= 0.999) break; }
              }
              node = node.parentElement;
            }
            if (!layers.length || layers[layers.length - 1].a < 0.999) return null;
            let acc = layers[layers.length - 1];
            for (let i = layers.length - 2; i >= 0; i--) {
              const t = layers[i];
              acc = { r: t.r * t.a + acc.r * (1 - t.a), g: t.g * t.a + acc.g * (1 - t.a), b: t.b * t.a + acc.b * (1 - t.a), a: 1 };
            }
            return acc;
          }
          const out = [];
          // Меню скрыты, поэтому показываем их на время замера.
          for (const id of ['playerSettingsMenu', 'playerQualityMenu', 'playerEqualizerMenu', 'playerBassMenu']) {
            const menu = document.getElementById(id);
            if (!menu) continue;
            const prev = menu.style.display;
            menu.style.display = 'block';
            for (const item of menu.querySelectorAll('.settings-menu-item, .settings-menu-header, .quality-option')) {
              const bg = blend(item);
              if (!bg) continue;
              out.push({ menu: id, color: getComputedStyle(item).color, bg: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})` });
            }
            menu.style.display = prev;
          }
          return out;
        });

        const unreadable = menus.filter(m => {
          const fg = parseColor(m.color), bg = parseColor(m.bg);
          return fg && bg && contrast(fg, bg) < 3;
        }).map(m => `${m.menu}: ${m.color} на ${m.bg}`);
        check(`${theme} меню плеера читается`, unreadable.length === 0,
          [...new Set(unreadable)].slice(0, 5).join(' | '));
        check(`${theme} меню плеера найдено`, menus.length > 0, 'пунктов меню не найдено');
      }
    }

    // Мобильный сайдбар: кнопка меню — это <svg>, у которого нет метода
    // click(). Из-за этого клавиатурное открытие меню падало с ошибкой.
    if (VIDEO_ID) {
      const mobile = await browser.newPage({ viewport: { width: 420, height: 900 } });
      const mobileErrors = [];
      mobile.on('pageerror', e => mobileErrors.push(e.message));
      await mobile.addInitScript(t => localStorage.setItem('lt_theme', t), theme);
      await mobile.goto(`${BASE}/watch/${VIDEO_ID}`, { waitUntil: 'domcontentloaded' });
      await mobile.waitForTimeout(900);

      const readState = () => mobile.evaluate(() => {
        const drawer = document.getElementById('sidebarDrawer');
        const toggle = document.getElementById('sidebarToggle');
        return {
          open: !!drawer && drawer.classList.contains('active'),
          expanded: toggle ? toggle.getAttribute('aria-expanded') : null,
          role: toggle ? toggle.getAttribute('role') : null,
        };
      });
      // Клик мышью по кнопке.
      await mobile.click('#sidebarToggle');
      await mobile.waitForTimeout(200);
      const opened = await readState();
      check(`${theme} сайдбар открывается кликом`, opened.open, JSON.stringify(opened));
      check(`${theme} сайдбар: aria-expanded=true`, opened.expanded === 'true',
        JSON.stringify(opened));

      // Escape должен закрыть (mobile.js шлёт click на оверлей).
      await mobile.keyboard.press('Escape');
      await mobile.waitForTimeout(200);
      const closed = await readState();
      check(`${theme} сайдбар закрывается по Escape`, !closed.open, JSON.stringify(closed));
      check(`${theme} сайдбар: aria-expanded=false`, closed.expanded === 'false',
        JSON.stringify(closed));

      // Клавиатура: Enter на кнопке меню.
      await mobile.focus('#sidebarToggle');
      await mobile.keyboard.press('Enter');
      await mobile.waitForTimeout(200);
      const viaKeyboard = await readState();
      check(`${theme} сайдбар открывается с клавиатуры`, viaKeyboard.open,
        JSON.stringify(viaKeyboard));
      check(`${theme} сайдбар: роль кнопки для скринридера`, viaKeyboard.role === 'button',
        JSON.stringify(viaKeyboard));
      check(`${theme} сайдбар без ошибок в консоли`, mobileErrors.length === 0,
        mobileErrors.slice(0, 3).join(' | '));
      await mobile.close();
    }

    // Обои: у слоёв должна появиться картинка, и только в своей теме.
    if (theme === 'frutiger-aero') {
      await page.goto(BASE + '/', { waitUntil: 'networkidle' });
      await page.waitForFunction(() => {
        const l1 = document.getElementById('bg-layer-1');
        const l2 = document.getElementById('bg-layer-2');
        return (l1 && l1.style.backgroundImage && l1.style.backgroundImage !== 'none') ||
               (l2 && l2.style.backgroundImage && l2.style.backgroundImage !== 'none');
      }, null, { timeout: 10000 }).then(
        () => check('frutiger-aero обои загружены', true, ''),
        () => check('frutiger-aero обои загружены', false, 'ни один слой не получил картинку'));

      // В ссылке не должно быть cache-buster: иначе ~2 МБ качаются заново
      // каждые 30 секунд.
      const url = await page.evaluate(() => {
        const l1 = document.getElementById('bg-layer-1');
        const l2 = document.getElementById('bg-layer-2');
        return [l1, l2].map(l => l && l.style.backgroundImage).filter(v => v && v !== 'none')[0] || '';
      });
      check('frutiger-aero обои без cache-buster', !/[?&]w=/.test(url), url);
    } else {
      await page.goto(BASE + '/', { waitUntil: 'networkidle' });
      const hasBg = await page.evaluate(() => {
        const l1 = document.getElementById('bg-layer-1');
        const l2 = document.getElementById('bg-layer-2');
        return [l1, l2].some(l => l && l.style.backgroundImage && l.style.backgroundImage !== 'none');
      });
      check(`${theme} без обоев`, !hasBg, 'обои показаны в теме без обоев');
    }

    await context.close();
  }

  // Переключение темы на месте: раньше каждая страница делала это по-своему.
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' });
  await page.selectOption('#theme', 'frutiger-aero');
  await page.waitForTimeout(300);
  const afterSwitch = await page.getAttribute('html', 'data-theme');
  check('переключение темы применяется сразу', afterSwitch === 'frutiger-aero', `data-theme=${afterSwitch}`);
  const stored = await page.evaluate(() => localStorage.getItem('lt_theme'));
  check('переключение темы сохраняется', stored === 'frutiger-aero', `lt_theme=${stored}`);

  // Мусор в localStorage не должен приводить к запросу постороннего стиля.
  await page.evaluate(() => localStorage.setItem('lt_theme', '../../etc/passwd'));
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  const fallback = await page.getAttribute('html', 'data-theme');
  check('битая тема откатывается к dark', fallback === 'dark', `data-theme=${fallback}`);
  await context.close();

  await browser.close();

  for (const c of checks) {
    console.log(`${c.ok ? 'OK  ' : 'FAIL'} ${c.name}${c.ok || !c.detail ? '' : ' -> ' + c.detail}`);
  }
  console.log(`\n${checks.filter(c => c.ok).length}/${checks.length} проверок пройдено`);
  if (failures.length) {
    console.error(`\nПровалено ${failures.length}:`);
    for (const f of failures) console.error('  - ' + f);
    process.exit(1);
  }
})();
