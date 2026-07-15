(() => {
  function icon(path) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"></path></svg>`;
  }

  function buildNavigation() {
    if (document.querySelector('.lt-mobile-nav')) return;
    const path = window.location.pathname;
    const nav = document.createElement('nav');
    nav.className = 'lt-mobile-nav';
    nav.setAttribute('aria-label', 'Основная навигация');
    nav.innerHTML = `
      <a href="/" class="${path === '/' || path.startsWith('/watch/') ? 'active' : ''}">
        ${icon('M4 10v10h6v-6h4v6h6V10l-8-7-8 7z')}<span>Главная</span>
      </a>
      <button type="button" data-lt-download>
        ${icon('M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z')}<span>Скачать</span>
      </button>
      <a href="/upload" class="${path === '/upload' || path.startsWith('/edit/') ? 'active' : ''}">
        ${icon('M12 2l-5 5h3v6h4V7h3l-5-5zM5 18v2h14v-2H5z')}<span>Мои видео</span>
      </a>
      <button type="button" data-lt-settings>
        ${icon('M19.4 13a7.8 7.8 0 000-2l2-1.6-2-3.4-2.5 1a8 8 0 00-1.7-1L15 3.3h-4L10.6 6a8 8 0 00-1.7 1L6.4 6l-2 3.4L6.6 11a7.8 7.8 0 000 2l-2.2 1.6 2 3.4 2.5-1a8 8 0 001.7 1l.4 2.7h4l.4-2.7a8 8 0 001.7-1l2.5 1 2-3.4L19.4 13zM13 15.5A3.5 3.5 0 1113 8a3.5 3.5 0 010 7.5z')}<span>Настройки</span>
      </button>`;
    document.body.appendChild(nav);

    nav.querySelector('[data-lt-download]').addEventListener('click', () => {
      const input = document.querySelector('#urlInput, input[type="url"]');
      if (input) {
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
        input.focus();
      } else {
        window.location.href = '/';
      }
    });
    nav.querySelector('[data-lt-settings]').addEventListener('click', () => {
      if (typeof window.openSettings === 'function') window.openSettings();
      else window.location.href = '/#settings';
    });
  }

  document.addEventListener('DOMContentLoaded', buildNavigation);
})();
