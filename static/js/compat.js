/* compat.js — поддержка старых движков.
 *
 * Нужен ровно двум случаям: сборке для Windows 7, где внутри лежит Chromium 66
 * (WebView2 на «семёрке» отсутствует и поставить его нельзя), и старым телефонам,
 * с которых библиотеку открывают в локальной сети. В обоих случаях движок не
 * знает части методов, появившихся в 2020 году, и страница ломалась молча: сам
 * скрипт загружался, но первый же вызов replaceChildren выбрасывал TypeError, и
 * дальше не выполнялось ничего — список видео оставался пустым.
 *
 * Здесь только полифиллы методов. Синтаксис (?., ??) полифиллом не лечится:
 * старый парсер отвергает весь блок скрипта целиком, поэтому такие конструкции
 * в шаблонах не используются вовсе.
 *
 * Файл подключается первым, до остальных скриптов и до разметки: полифиллы
 * должны существовать раньше первого обращения к ним.
 */
(function () {
  'use strict';

  // ===== Element.replaceChildren (Chrome 86) =====
  // Обновление списка видео, очереди и плейлистов идёт через него.
  if (typeof Element !== 'undefined' && !Element.prototype.replaceChildren) {
    Element.prototype.replaceChildren = function () {
      // Сначала чистим: textContent = '' быстрее поштучного removeChild и не
      // оставляет обработчиков на удалённых узлах.
      this.textContent = '';
      for (var i = 0; i < arguments.length; i++) {
        var item = arguments[i];
        this.appendChild(typeof item === 'string'
          ? document.createTextNode(item)
          : item);
      }
    };
    if (typeof DocumentFragment !== 'undefined'
        && !DocumentFragment.prototype.replaceChildren) {
      DocumentFragment.prototype.replaceChildren = Element.prototype.replaceChildren;
    }
  }

  // ===== String.prototype.matchAll (Chrome 73) =====
  // Разбор описания канала на ссылки.
  if (!String.prototype.matchAll) {
    String.prototype.matchAll = function (pattern) {
      // Флаг g обязателен по спецификации: без него настоящий matchAll бросает
      // TypeError, и полифилл должен вести себя так же, иначе ошибка всплывёт
      // только на новых движках.
      if (!(pattern instanceof RegExp)) {
        pattern = new RegExp(pattern, 'g');
      } else if (pattern.flags.indexOf('g') === -1) {
        // Текст исключения по-английски, как у настоящих ошибок движка: это
        // сообщение для разработчика в консоли, а не строка интерфейса, и
        // переводить его через t() незачем.
        throw new TypeError('String.prototype.matchAll called with a non-global RegExp');
      }
      var text = String(this);
      // Своя копия регулярного выражения: иначе повторный вызов продолжал бы с
      // прежнего lastIndex и пропускал совпадения.
      var re = new RegExp(pattern.source, pattern.flags);
      var results = [];
      var match;
      while ((match = re.exec(text)) !== null) {
        results.push(match);
        // Совпадение нулевой длины не двигает lastIndex, и цикл вешал браузер.
        if (match[0] === '') re.lastIndex++;
      }
      return results;
    };
  }

  // ===== Array.prototype.flat и flatMap (Chrome 69) =====
  if (!Array.prototype.flat) {
    Array.prototype.flat = function (depth) {
      var limit = depth === undefined ? 1 : Number(depth);
      var flatten = function (list, level) {
        return list.reduce(function (acc, item) {
          if (Array.isArray(item) && level > 0) {
            return acc.concat(flatten(item, level - 1));
          }
          acc.push(item);
          return acc;
        }, []);
      };
      return flatten(this, limit);
    };
  }
  if (!Array.prototype.flatMap) {
    Array.prototype.flatMap = function (callback, thisArg) {
      return this.map(callback, thisArg).flat();
    };
  }

  // ===== Object.fromEntries (Chrome 73) =====
  if (!Object.fromEntries) {
    Object.fromEntries = function (entries) {
      var result = {};
      // Аргумент может быть Map или любым перебираемым, поэтому forEach у него
      // может и не быть: обходим через for...of, он есть с Chrome 38.
      for (var pair of entries) {
        result[pair[0]] = pair[1];
      }
      return result;
    };
  }

  // ===== String.prototype.replaceAll (Chrome 85) =====
  if (!String.prototype.replaceAll) {
    String.prototype.replaceAll = function (search, replacement) {
      if (search instanceof RegExp) {
        if (search.flags.indexOf('g') === -1) {
          throw new TypeError('replaceAll must be called with a global RegExp');
        }
        return this.replace(search, replacement);
      }
      // split/join, а не replace с регулярным выражением: экранировать
      // спецсимволы в искомой строке иначе пришлось бы вручную.
      return this.split(String(search)).join(String(replacement));
    };
  }

  // ===== Promise.allSettled (Chrome 76) =====
  if (!Promise.allSettled) {
    Promise.allSettled = function (promises) {
      return Promise.all(Array.prototype.map.call(promises, function (item) {
        return Promise.resolve(item).then(
          function (value) { return { status: 'fulfilled', value: value }; },
          function (reason) { return { status: 'rejected', reason: reason }; }
        );
      }));
    };
  }

  // ===== ParentNode.append и prepend (Chrome 54) =====
  // Есть даже в Chromium 66, но не в старых WebKit на телефонах.
  ['append', 'prepend'].forEach(function (name) {
    if (typeof Element === 'undefined' || Element.prototype[name]) return;
    Element.prototype[name] = function () {
      var fragment = document.createDocumentFragment();
      for (var i = 0; i < arguments.length; i++) {
        var item = arguments[i];
        fragment.appendChild(typeof item === 'string'
          ? document.createTextNode(item)
          : item);
      }
      if (name === 'append') this.appendChild(fragment);
      else this.insertBefore(fragment, this.firstChild);
    };
  });

  // ===== legacy.css =====
  // Старым движкам не хватает свойств, на которых держится вся вёрстка. Файл с
  // заменами подключается отсюда, а не тегом <link>: на WebView2 и WebKitGTK он
  // тогда не загружается вовсе и не может ничего испортить.
  //
  // Каждая нехватка отмечается своим классом на <html>, и правила в legacy.css
  // разделены по ним. Одного общего флага мало: flex gap появился в Chrome 84, а
  // aspect-ratio только в 88, и на движках между ними (сюда же Safari 14.1 на
  // iPhone) отступы применились бы поверх работающего gap — вышло бы вдвое.
  //
  // Проверяем через CSS.supports, а не по строке User-Agent: она подделывается и
  // ничего не говорит о реальных возможностях.
  if (typeof document !== 'undefined') {
    var root = document.documentElement;
    var head = document.head || document.getElementsByTagName('head')[0];
    var supports = function (prop, value) {
      try {
        // Нет самого CSS.supports (он с Chrome 28) — считаем, что свойства нет.
        if (!(window.CSS && CSS.supports)) return false;
        return CSS.supports(prop, value);
      } catch (e) {
        return false;
      }
    };
    var missing = [];
    if (!supports('aspect-ratio', '16 / 9')) missing.push('lt-no-aspect-ratio');
    if (!supports('width', 'min(10px, 100%)')) missing.push('lt-no-min-max');
    if (!supports('inset', '0')) missing.push('lt-no-inset');
    // Отдельной проверки на flex gap в CSS.supports не существует: свойство gap
    // объявлено валидным и там, где оно работает только в grid (Chrome 66-83).
    // Поэтому измеряем поведение: два блока по 10px в flex-контейнере с gap 10px
    // дают ширину 30px там, где gap учитывается, и 20px там, где нет.
    var probe = document.createElement('div');
    probe.style.cssText = 'display:flex;gap:10px;position:absolute;'
      + 'visibility:hidden;width:auto;left:-9999px;top:0';
    probe.innerHTML = '<i style="width:10px;height:1px;flex:0 0 auto"></i>'
      + '<i style="width:10px;height:1px;flex:0 0 auto"></i>';
    // Замена gap отступами. Списком селекторов в CSS это делать нельзя: у одного
    // и того же класса направление зависит от страницы и медиазапроса
    // (.video-details — ряд, .card-assets — колонка, у label вообще нет flex), и
    // при ручной раскладке отступ уезжал не в ту сторону. Поэтому спрашиваем у
    // движка: сколько был gap и куда смотрит ось, тому и соответствует margin.
    // Читается ли gap из computed style. В Chromium 66 свойство разбирается (оно
    // появилось там для grid), поэтому значение обычно доступно и на flex, просто
    // не влияет на раскладку. Но если движок ещё старше и отдаёт 'normal',
    // фактический отступ узнать негде — тогда берём типовой, иначе интерфейс
    // остался бы совсем без отступов.
    var gapReadable = false;
    var FALLBACK_ROW_GAP = 10;
    var FALLBACK_COLUMN_GAP = 8;

    var emulateFlexGap = function () {
      var nodes = document.querySelectorAll('*');
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var cs;
        try {
          cs = getComputedStyle(el);
        } catch (e) {
          continue;
        }
        if (cs.display !== 'flex' && cs.display !== 'inline-flex') continue;
        var column = cs.flexDirection.indexOf('column') === 0;
        // rowGap отвечает за расстояние между строками, columnGap — между
        // колонками. В flex-ряду разделяет columnGap, в flex-колонке — rowGap.
        var raw = column ? cs.rowGap : cs.columnGap;
        var size = parseFloat(raw);
        if (!gapReadable) {
          // Значение недоступно: расставляем типовой отступ всем flex-контейнерам.
          // Лишний отступ там, где gap не задавали, заметен меньше, чем полное
          // отсутствие отступов во всём интерфейсе.
          size = column ? FALLBACK_COLUMN_GAP : FALLBACK_ROW_GAP;
        }
        // 'normal' даёт NaN — gap не задан, отступ и не нужен.
        if (!size) continue;
        // reverse: визуальный порядок обратный, но margin ставится соседу по
        // разметке, поэтому сторона тоже переворачивается.
        var reverse = cs.flexDirection.indexOf('reverse') > 0;
        var prop = column
          ? (reverse ? 'marginBottom' : 'marginTop')
          : (reverse ? 'marginRight' : 'marginLeft');
        // wrap: перенесённые строки без row-gap слиплись бы по вертикали.
        var wraps = cs.flexWrap.indexOf('wrap') === 0;
        var crossSize = gapReadable
          ? parseFloat(column ? cs.columnGap : cs.rowGap)
          : size;
        var kids = el.children;
        for (var k = 0; k < kids.length; k++) {
          // Первый элемент пропускаем: иначе появился бы отступ от края.
          if (k > 0) kids[k].style[prop] = size + 'px';
          if (wraps && crossSize) {
            kids[k].style[column ? 'marginRight' : 'marginBottom'] =
              crossSize + 'px';
          }
        }
      }
    };
    var measureFlexGap = function () {
      var host = document.body || root;
      if (!host) return;
      host.appendChild(probe);
      var gapWorks = probe.getBoundingClientRect().width >= 25;
      // Та же проба отвечает и на второй вопрос: отдаёт ли движок заданный gap
      // обратно. Спрашиваем до удаления узла — вне документа computed style
      // пустой.
      gapReadable = parseFloat(getComputedStyle(probe).columnGap) === 10;
      host.removeChild(probe);
      if (gapWorks) return;
      applyLegacy(['lt-no-flex-gap']);
      emulateFlexGap();
      // Интерфейс перерисовывает списки на ходу (очередь загрузок, результаты
      // фильтра), и новым узлам отступы тоже нужны. MutationObserver есть с
      // Chrome 27, но на всякий случай проверяем.
      if (typeof MutationObserver === 'function') {
        var pending = null;
        var observer = new MutationObserver(function () {
          // Пересчёт пачкой: сам emulateFlexGap меняет style у детей, и на
          // каждое такое изменение наблюдатель срабатывал бы снова.
          if (pending) return;
          pending = setTimeout(function () {
            pending = null;
            observer.disconnect();
            emulateFlexGap();
            observer.observe(document.body, { childList: true, subtree: true });
          }, 100);
        });
        observer.observe(document.body, { childList: true, subtree: true });
      }
    };
    var legacyLoaded = false;
    var applyLegacy = function (classes) {
      for (var i = 0; i < classes.length; i++) {
        if (root && root.classList) root.classList.add(classes[i]);
      }
      if (legacyLoaded || !head) return;
      legacyLoaded = true;
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/static/css/legacy.css';
      // Последним в head: правила должны перебивать ui.css и mobile.css при
      // равной специфичности.
      head.appendChild(link);
    };
    if (missing.length) applyLegacy(missing);
    // Измерение требует готового документа: скрипт подключён в <head>, где body
    // ещё не существует.
    if (document.body) measureFlexGap();
    else document.addEventListener('DOMContentLoaded', measureFlexGap);
  }

  // ===== :focus-visible =====
  // Селектор появился в Chrome 86. В старых движках правило целиком отбрасывается
  // вместе со всем блоком стилей, поэтому подсветка фокуса просто исчезала.
  // Отмечаем клавиатурный фокус классом, а стили дублируют его в CSS.
  if (typeof document !== 'undefined') {
    var supportsFocusVisible = false;
    try {
      supportsFocusVisible = !!(document.body
        && document.body.matches
        && CSS && CSS.supports && CSS.supports('selector(:focus-visible)'));
    } catch (e) {
      supportsFocusVisible = false;
    }
    if (!supportsFocusVisible) {
      var usingKeyboard = false;
      document.addEventListener('keydown', function (event) {
        // Только навигационные клавиши: при вводе текста рамка фокуса не нужна.
        if (event.key === 'Tab' || event.key === 'ArrowUp' || event.key === 'ArrowDown'
            || event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          usingKeyboard = true;
        }
      }, true);
      document.addEventListener('mousedown', function () {
        usingKeyboard = false;
      }, true);
      document.addEventListener('focusin', function (event) {
        if (usingKeyboard && event.target && event.target.classList) {
          event.target.classList.add('lt-focus-visible');
        }
      }, true);
      document.addEventListener('focusout', function (event) {
        if (event.target && event.target.classList) {
          event.target.classList.remove('lt-focus-visible');
        }
      }, true);
    }
  }
})();
