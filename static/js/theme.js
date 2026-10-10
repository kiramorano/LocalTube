/* Единый слой темы для всех страниц.
 *
 * Раньше эти же 120 строк были скопированы в семь шаблонов, и копии разошлись:
 * playlist.html менял обои без кроссфейда, index/video/edit/upload дописывали к
 * ссылке на картинку ?w=&h= (сервер эти параметры игнорирует, а браузер из-за
 * них перекачивал ~2 МБ каждые 30 секунд), а channel и settings вообще не
 * трогали data-theme через общий код. Держать одну реализацию проще, чем семь.
 *
 * Файл подключается синхронно в <head> ДО разметки: тема должна примениться до
 * первой отрисовки. Раньше на <html> жёстко стояло data-theme="dark", а правка
 * приходила из скрипта в конце <body> — пользователь светлой темы и Frutiger
 * Aero видел вспышку тёмного фона на каждом переходе.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'lt_theme';
  var THEMES = ['dark', 'light', 'midnight', 'glass', 'frutiger-aero'];
  var AERO = 'frutiger-aero';
  // Тема -> свой файл стилей. Раньше путь был зашит под frutiger-aero, и
  // любая новая тема получала оформление стандартной тёмной.
  var STYLESHEETS = {
    'midnight': '/static/css/themes/midnight.css',
    'glass': '/static/css/themes/glass.css',
    'frutiger-aero': '/static/css/themes/frutiger-aero.css'
  };
  var ROTATE_MS = 30000;
  var FADE_MS = 1600;
  // Запасные обои — лежат в той же папке, что и основные. Их использует
  // backgroundUrl, и fetchImages применяет их в catch, если API недоступен.
  var FALLBACK_IMAGES = ['aero-1.jpg', 'aero-2.jpg', 'aero-3.jpg', 'aero-4.jpg', 'aero-5.jpg', 'aero-6.jpg'];

  function readTheme() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      return THEMES.indexOf(saved) !== -1 ? saved : 'dark';
    } catch (e) {
      // localStorage недоступен (приватный режим, отключённые куки): тема не
      // повод ронять страницу целиком.
      return 'dark';
    }
  }

  // Атрибут ставим немедленно, ещё до разметки: именно это убирает вспышку.
  var current = readTheme();
  document.documentElement.setAttribute('data-theme', current);

  var bgTimer = null;
  var activeLayer = 2;
  var imagesCache = null;

  function layer(n) { return document.getElementById('bg-layer-' + n); }

  function themeLink() {
    return document.getElementById('theme-style')
        || document.getElementById('theme-style-link');
  }

  function applyStylesheet(theme) {
    var link = themeLink();
    if (!link) return;
    var href = STYLESHEETS[theme];
    if (href) {
      // Сравнение обязательно: переприсваивание того же href заставляет браузер
      // заново применять стили и даёт заметное мигание при каждом вызове.
      if (link.getAttribute('href') !== href) link.setAttribute('href', href);
    } else if (link.getAttribute('href')) {
      // Раньше здесь стояло href = '': пустой href браузер трактует как ссылку
      // на текущую страницу и запрашивает HTML как стиль. Removeattribute
      // отключает ссылку по-настоящему.
      link.removeAttribute('href');
    }
  }

  function clearBackground() {
    if (bgTimer) { clearInterval(bgTimer); bgTimer = null; }
    for (var n = 1; n <= 2; n++) {
      var el = layer(n);
      if (!el) continue;
      el.style.backgroundImage = 'none';
      el.style.opacity = '0';
    }
  }

  function setBackgroundImage(url) {
    var target = layer(activeLayer === 2 ? 1 : 2);
    var other = layer(activeLayer === 2 ? 2 : 1);
    if (!target || !other) return;
    // CSS.escape недоступен в старых движках, поэтому кавычки в имени файла
    // экранируем сами: имя приходит из файловой системы пользователя.
    target.style.backgroundImage = "url('" + String(url).replace(/'/g, "\\'") + "')";
    target.style.opacity = '0';
    requestAnimationFrame(function () {
      target.style.opacity = '1';
      other.style.opacity = '0';
    });
    activeLayer = activeLayer === 2 ? 1 : 2;
    setTimeout(function () {
      // Гасим только если слой всё ещё не активен: за 1.6 с могло прийти
      // переключение темы, и обнуление стёрло бы уже показанные обои.
      if (other.style.opacity === '0') other.style.backgroundImage = 'none';
    }, FADE_MS);
  }

  function backgroundUrl(name) {
    // Без ?w=&h=: сервер эти параметры не читает, а меняющиеся значения
    // (innerWidth/innerHeight) делали ссылку уникальной и обнуляли кэш —
    // каждые 30 секунд заново качалось около 2 МБ на каждую вкладку.
    return '/static/images/themes/' + AERO + '/' + encodeURIComponent(name);
  }

  function pickDifferent(images) {
    if (!images.length) return null;
    if (images.length === 1) return images[0];
    var last = pickDifferent.last;
    var choice;
    // Одну и ту же картинку два раза подряд не показываем: со случайным
    // выбором из шести файлов «смена» обоев в каждом шестом случае была
    // незаметна и выглядела как зависшая ротация.
    do { choice = images[Math.floor(Math.random() * images.length)]; }
    while (choice === last && images.length > 1);
    pickDifferent.last = choice;
    return choice;
  }

  function fetchImages() {
    // Список кэшируем: раньше он запрашивался заново на каждый тик таймера,
    // хотя набор файлов между тиками не меняется.
    if (imagesCache) return Promise.resolve(imagesCache);
    return fetch('/api/theme-backgrounds/' + AERO)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
       .then(function (images) {
         imagesCache = Array.isArray(images) && images.length ? images : FALLBACK_IMAGES.slice();
         return imagesCache;
       }).catch(function (err) {
         console.error('Не удалось загрузить обои темы:', err);
         imagesCache = FALLBACK_IMAGES.slice();
         return imagesCache;
       });
  }

  function startBackground() {
    if (!layer(1) || !layer(2)) return;
    fetchImages().then(function (images) {
      if (!images.length || document.documentElement.getAttribute('data-theme') !== AERO) {
        clearBackground();
        return;
      }
      var first = pickDifferent(images);
      if (first) {
        // Показываем фон сразу: браузер отрисует прогрессивную JPEG по мере
        // загрузки. Раньше дождались полной скачки (~2 МБ) через Image(), и
        // первый кадр появлялся с задержкой в несколько секунд.
        setBackgroundImage(backgroundUrl(first));
      }
      if (bgTimer) clearInterval(bgTimer);
      bgTimer = setInterval(function () {
        // Скрытую вкладку не трогаем: смена обоев в фоне только жгла трафик и
        // держала декодер занятым.
        if (document.hidden) return;
        if (document.documentElement.getAttribute('data-theme') !== AERO) return;
        var next = pickDifferent(images);
        if (next) setBackgroundImage(backgroundUrl(next));
      }, ROTATE_MS);
    }).catch(function (err) {
      console.error('Не удалось загрузить обои темы:', err);
      clearBackground();
    });
  }

  function apply(theme) {
    if (THEMES.indexOf(theme) === -1) theme = 'dark';
    current = theme;
    document.documentElement.setAttribute('data-theme', theme);
    applyStylesheet(theme);
    if (theme === AERO) startBackground();
    else clearBackground();
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) { /* приватный режим: тема просто не запомнится */ }
  }

  // Ссылку на стиль подключаем сразу, не дожидаясь DOM: <link> лежит в <head>
  // выше этого скрипта, поэтому он уже разобран.
  applyStylesheet(current);

  function initBackground() {
    if (current === AERO) startBackground();
  }

  if (document.readyState === 'loading') {
    // Слои фона лежат в <body>, поэтому ждём разметку.
    document.addEventListener('DOMContentLoaded', initBackground);
  } else {
    initBackground();
  }

  // Тема меняется в другой вкладке: раньше открытые страницы оставались в
  // прежнем оформлении до перезагрузки.
  window.addEventListener('storage', function (event) {
    if (event.key === STORAGE_KEY && event.newValue !== current) apply(event.newValue);
  });

  window.LocalTubeTheme = {
    get: function () { return current; },
    apply: apply,
    THEMES: THEMES.slice(),
    backgroundUrl: backgroundUrl,
  };

  // Совместимость: шаблоны исторически вызывают loadTheme(theme).
  window.loadTheme = apply;
})();
