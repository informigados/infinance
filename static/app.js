(function () {
  function ensureFavicon() {
    var iconMeta = document.querySelector('meta[name="infinance-favicon"]');
    var href = (iconMeta && iconMeta.getAttribute('content')) || '/static/infinance-icon.svg';
    var links = document.querySelectorAll('link[rel*="icon"]');
    if (!links.length) {
      var link = document.createElement('link');
      link.rel = 'icon';
      link.href = href;
      document.head.appendChild(link);
      return;
    }
    links.forEach(function (link) {
      link.href = href;
    });
  }

  function wireConfirmDialogs() {
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (!confirm(form.getAttribute('data-confirm'))) {
          event.preventDefault();
        }
      });
    });
  }

  function wireMobileMenu() {
    var openButton = document.getElementById('menu-toggle');
    var closeButton = document.getElementById('mobile-menu-close');
    var panel = document.getElementById('mobile-menu-panel');
    var overlay = document.getElementById('mobile-menu-overlay');
    if (!openButton || !closeButton || !panel || !overlay) return;
    var menuIcon = openButton.querySelector('[data-menu-icon]');
    var closeIcon = openButton.querySelector('[data-close-icon]');
    var srOnly = openButton.querySelector('.sr-only');

    function setMenuState(isOpen) {
      panel.classList.toggle('translate-x-full', !isOpen);
      overlay.classList.toggle('opacity-0', !isOpen);
      overlay.classList.toggle('pointer-events-none', !isOpen);
      document.body.classList.toggle('overflow-hidden', isOpen);
      openButton.setAttribute('aria-expanded', String(isOpen));
      openButton.setAttribute('aria-label', isOpen ? 'Fechar menu' : 'Abrir menu');
      if (srOnly) {
        srOnly.textContent = isOpen ? 'Fechar menu' : 'Abrir menu';
      }
      if (menuIcon) {
        menuIcon.classList.toggle('hidden', isOpen);
      }
      if (closeIcon) {
        closeIcon.classList.toggle('hidden', !isOpen);
      }
    }

    setMenuState(false);

    openButton.addEventListener('click', function () {
      var isOpen = panel.classList.contains('translate-x-full');
      setMenuState(isOpen);
    });

    closeButton.addEventListener('click', function () {
      setMenuState(false);
    });

    overlay.addEventListener('click', function () {
      setMenuState(false);
    });

    panel.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        setMenuState(false);
      });
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        setMenuState(false);
      }
    });

    if (window.matchMedia) {
      var desktopQuery = window.matchMedia('(min-width: 768px)');
      var closeOnDesktop = function (event) {
        if (event.matches) {
          setMenuState(false);
        }
      };
      if (desktopQuery.addEventListener) {
        desktopQuery.addEventListener('change', closeOnDesktop);
      } else if (desktopQuery.addListener) {
        desktopQuery.addListener(closeOnDesktop);
      }
    }
  }

  function ensureButtonTypes() {
    document.querySelectorAll('form button:not([type])').forEach(function (button) {
      button.setAttribute('type', 'submit');
    });
  }

  function bindLabelsToInputs() {
    var autoIndex = 0;
    document.querySelectorAll('form div').forEach(function (container) {
      var label = container.querySelector(':scope > label');
      if (!label || label.hasAttribute('for')) return;
      var control = container.querySelector(':scope > input, :scope > select, :scope > textarea');
      if (!control) return;
      if (!control.id) {
        autoIndex += 1;
        control.id = 'field-auto-' + autoIndex;
      }
      label.setAttribute('for', control.id);
    });
  }

  function wireFormLoadingStates() {
    document.querySelectorAll('form').forEach(function (form) {
      if (!form.method || form.method.toLowerCase() !== 'post') return;
      if (form.getAttribute('data-loading') === 'off') return;

      form.addEventListener('submit', function (event) {
        if (event.defaultPrevented) return;
        if (form.dataset.submitting === '1') return;
        form.dataset.submitting = '1';

        form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (submitControl) {
          submitControl.disabled = true;
          submitControl.classList.add('opacity-70', 'cursor-not-allowed');

          var loadingText = submitControl.getAttribute('data-loading-text') || 'Processando...';
          if (submitControl.tagName === 'BUTTON') {
            submitControl.dataset.originalText = submitControl.textContent;
            submitControl.textContent = loadingText;
          } else if (submitControl.tagName === 'INPUT') {
            submitControl.dataset.originalValue = submitControl.value;
            submitControl.value = loadingText;
          }
        });
      });
    });
  }

  function wireExportLinkLoading() {
    document.querySelectorAll('a[data-loading-link], a[href*="/export/"]').forEach(function (link) {
      link.addEventListener('click', function () {
        if (link.dataset.busy === '1') return;
        link.dataset.busy = '1';
        link.classList.add('opacity-70', 'pointer-events-none');

        var loadingText = link.getAttribute('data-loading-text') || 'Gerando...';
        link.dataset.originalText = link.textContent;
        link.textContent = loadingText;
      });
    });
  }

  function wireAuthorAvatarFallback() {
    document.querySelectorAll('[data-author-avatar-image]').forEach(function (image) {
      var fallback = image.parentElement && image.parentElement.querySelector('[data-author-avatar-fallback]');
      if (!fallback) return;

      var revealFallback = function () {
        image.classList.add('hidden');
        fallback.classList.remove('hidden');
        fallback.classList.add('flex');
      };

      image.addEventListener('error', revealFallback);

      // Handles cached/failed loads that happened before listeners were attached.
      if (image.complete && image.naturalWidth === 0) {
        revealFallback();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    ensureFavicon();
    wireConfirmDialogs();
    wireFormLoadingStates();
    wireExportLinkLoading();
    wireAuthorAvatarFallback();
    wireMobileMenu();
    ensureButtonTypes();
    bindLabelsToInputs();
  });
})();
