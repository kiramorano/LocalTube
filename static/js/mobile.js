/* Общий слой боковой панели и мобильных доработок.
 *
 * Переключение панели было скопировано в пять шаблонов (index, video, playlist,
 * upload, edit) одной и той же строкой `classList.toggle('active')`, а CSS-часть
 * разъехалась: только index.html закреплял панель на широких экранах правилом
 * `@media (min-width: 1000px) { .sidebar-drawer { left: 0 } }`. Специфичность у
 * него ниже, чем у `.sidebar-drawer.active`, но объявлено оно позже — поэтому на
 * десктопе панель оставалась раскрытой при любом состоянии класса, а кнопка
 * фактически управляла только затемняющим оверлеем. Теперь состояние хранится
 * на <html>, а не на самой панели: медиазапросы внутри шаблонов больше не могут
 * перебить правило сворачивания.
 */
(() => {
  'use strict';

  const drawer = document.getElementById('sidebarDrawer');
  const overlay = document.getElementById('sidebarOverlay');
  const toggle = document.getElementById('sidebarToggle');

  if (!drawer || !toggle) return;

  const root = document.documentElement;
  const STORAGE_KEY = 'lt_sidebar_collapsed';
  // Порог закрепления панели совпадает с медиазапросом в ui.css: ниже него
  // панель работает как выдвижная поверх контента и обязана затемнять фон.
  const PINNED_QUERY = '(min-width: 1000px)';

  // Закрепление есть не на всех страницах: /upload и /edit центрируют контент в
  // .container, там панель выдвижная при любой ширине. Признак — контейнер,
  // который сдвинут на ширину панели; без этой проверки кнопка на /upload
  // переключала несуществующее состояние и не делала ничего.
  const hasPinnedLayout = () => !!document.querySelector('#mainContent, #queueContainer');

  const isPinned = () => hasPinnedLayout() && window.matchMedia(PINNED_QUERY).matches;

  // Кнопка — это <svg>, а не <button>. У SVGElement нет метода click() (он
  // определён только у HTMLElement), поэтому toggle.click() падал бы с
  // "toggle.click is not a function". Синтетический click работает для обоих.
  const activate = (element) => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  };

  const readCollapsed = () => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1';
    } catch (e) {
      // Приватный режим или отключённые куки: панель не должна ронять страницу.
      return false;
    }
  };

  const saveCollapsed = (collapsed) => {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
    } catch (e) {
      /* состояние просто не запомнится */
    }
  };

  const isOpen = () => (isPinned()
    ? !root.classList.contains('sidebar-collapsed')
    : drawer.classList.contains('active'));

  const syncAria = () => {
    toggle.setAttribute('aria-expanded', isOpen() ? 'true' : 'false');
  };

  function applyPinnedState(collapsed) {
    root.classList.toggle('sidebar-collapsed', collapsed);
    // На закреплённой панели выдвижное состояние не нужно: иначе после
    // изменения размера окна остаётся класс от мобильного режима.
    drawer.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
  }

  function toggleSidebar() {
    if (isPinned()) {
      const collapsed = !root.classList.contains('sidebar-collapsed');
      applyPinnedState(collapsed);
      saveCollapsed(collapsed);
    } else {
      // Узкий экран: панель выезжает поверх контента, затемнение обязательно —
      // иначе непонятно, что остальная страница не принимает клики.
      drawer.classList.toggle('active');
      if (overlay) overlay.classList.toggle('active');
    }
    syncAria();
  }

  // Состояние восстанавливаем до первой отрисовки, иначе панель мигает.
  if (isPinned()) applyPinnedState(readCollapsed());

  toggle.setAttribute('role', 'button');
  toggle.setAttribute('tabindex', '0');
  toggle.setAttribute('aria-label', t('Боковое меню'));
  toggle.setAttribute('aria-controls', 'sidebarDrawer');
  syncAria();

  toggle.addEventListener('click', toggleSidebar);
  if (overlay) {
    overlay.addEventListener('click', () => {
      // Оверлей есть только у выдвижного режима, но клик по нему должен
      // закрывать панель и после изменения размера окна.
      drawer.classList.remove('active');
      overlay.classList.remove('active');
      syncAria();
    });
  }

  toggle.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activate(toggle);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    // Escape закрывает только выдвижную панель: на закреплённой она ничего не
    // перекрывает, и её сворачивание было бы неожиданным.
    if (drawer.classList.contains('active')) {
      drawer.classList.remove('active');
      if (overlay) overlay.classList.remove('active');
      syncAria();
    }
  });

  // Переход между режимами по ресайзу: класс, оставшийся от другого режима,
  // иначе оставляет панель раскрытой без возможности закрыть.
  const pinnedWatcher = window.matchMedia(PINNED_QUERY);
  const onModeChange = () => {
    if (isPinned()) {
      applyPinnedState(readCollapsed());
    } else {
      root.classList.remove('sidebar-collapsed');
    }
    syncAria();
  };
  if (typeof pinnedWatcher.addEventListener === 'function') {
    pinnedWatcher.addEventListener('change', onModeChange);
  } else if (typeof pinnedWatcher.addListener === 'function') {
    pinnedWatcher.addListener(onModeChange);
  }

  // aria-expanded держим в синхронизации с классом: разметку страницы меняют и
  // другие скрипты (например, закрытие панели при переходе по разделу).
  if (typeof MutationObserver === 'function') {
    new MutationObserver(syncAria).observe(drawer, {
      attributes: true, attributeFilter: ['class'],
    });
  }
})();
