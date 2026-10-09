(() => {
  const root = document.documentElement;
  const preference = () => { try { return localStorage.getItem('digitxbd-theme') || 'system'; } catch { return 'system'; } };
  const media = matchMedia('(prefers-color-scheme: dark)');
  function apply() {
    const selected = preference();
    root.dataset.theme = selected === 'system' ? (media.matches ? 'dark' : 'light') : selected;
    root.style.colorScheme = root.dataset.theme;
    document.querySelectorAll('[data-theme-toggle]').forEach(button => { button.textContent = root.dataset.theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'; button.setAttribute('aria-label',button.textContent); });
  }
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    // Keep the public order page limited to its logo and form.
    const host = document.querySelector('.top-actions') || document.querySelector('.public-header') || document.querySelector('.auth-card') || document.querySelector('.track-card') || document.querySelector('.statement-page') || document.querySelector('.print-toolbar');
    if (host) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'theme-toggle secondary no-print'; button.dataset.themeToggle = '';
      host.append(button);
      button.addEventListener('click', () => { try { localStorage.setItem('digitxbd-theme',root.dataset.theme === 'dark' ? 'light' : 'dark'); } catch {} apply(); });
    }
    apply();
  });
  media.addEventListener('change',apply);
})();
