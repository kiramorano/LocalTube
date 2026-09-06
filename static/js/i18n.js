/* Перевод строк, которые появляются уже в браузере.
 *
 * Разметку страниц переводит сервер (фильтр |t в шаблонах), но часть подписей
 * собирает клиентский код: очередь загрузок, списки каналов, сообщения об
 * ошибках. Для них нужен тот же словарь, поэтому он приходит с сервера, а не
 * дублируется в скрипте: две копии разъезжаются, и в интерфейсе всплывает
 * русский текст посреди английского.
 *
 * Файл подключается синхронно в <head>, до остальных скриптов: t() должна быть
 * готова к моменту первого вызова. Словарь при этом догружается запросом, и до
 * его прихода t() возвращает исходную русскую строку — то есть читаемую, а не
 * пустую.
 */
(function () {
  'use strict';

  var COOKIE = 'lt_lang';
  var DEFAULT_LANG = 'ru';
  var strings = {};
  var lang = DEFAULT_LANG;
  var ready = null;

  function readLang() {
    // Язык берём из того же cookie, что читает сервер: иначе клиентские
    // подписи могли остаться на прежнем языке после переключения.
    var match = document.cookie.match(/(?:^|;\s*)lt_lang=([^;]+)/);
    var value = match ? decodeURIComponent(match[1]) : '';
    // Атрибут lang у <html> ставит сервер: он надёжнее, если cookie нет.
    var fromHtml = document.documentElement.getAttribute('lang') || '';
    var code = (value || fromHtml).toLowerCase().split('-')[0];
    return code === 'en' ? 'en' : DEFAULT_LANG;
  }

  function translate(text) {
    if (typeof text !== 'string') return text;
    if (lang === DEFAULT_LANG) return text;
    var key = text.trim();
    if (!key) return text;
    var value = strings[key];
    // Пропущенная строка остаётся русской: она читаема, в отличие от пустой.
    if (!value) return text;
    // Отступы по краям сохраняем: в подписях они держат пробел между словами.
    var lead = text.slice(0, text.length - text.replace(/^\s+/, '').length);
    var tail = text.slice(text.replace(/\s+$/, '').length);
    return lead + value + tail;
  }

  function load() {
    lang = readLang();
    if (lang === DEFAULT_LANG) {
      // Русский — язык исходных строк, словарь ему не нужен.
      ready = Promise.resolve();
      return ready;
    }
    // Словарь страница отдаёт вместе с разметкой (window.LT_I18N). Так t()
    // отвечает верно с первого вызова: сетевой запрос успевал прийти позже, чем
    // скрипты рисовали шапку, и подписи оставались русскими.
    if (window.LT_I18N && typeof window.LT_I18N === 'object') {
      strings = window.LT_I18N;
      ready = Promise.resolve();
      return ready;
    }
    // Запасной путь: страница словарь не отдала (старый кэш браузера).
    ready = fetch('/api/i18n/' + lang)
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (data && data.strings) strings = data.strings;
      })
      .catch(function () {
        // Сеть недоступна: интерфейс останется русским, но не сломается.
      });
    return ready;
  }

  load();

  window.LocalTubeI18n = {
    t: translate,
    lang: function () { return lang; },
    // Скрипты, которые строят разметку сразу при загрузке, могут дождаться
    // словаря: иначе первая отрисовка успевала бы пройти на русском.
    whenReady: function (callback) {
      (ready || Promise.resolve()).then(callback);
    }
  };

  // Короткое имя: t('Текст') читается лучше, чем window.LocalTubeI18n.t(...),
  // а строк в клиентском коде сотни.
  window.t = translate;
})();
