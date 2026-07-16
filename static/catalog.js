window.HekiCatalog = (() => {
  const HISTORY_KEY = 'heki_history';

  function discoveredIds() {
    try {
      const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
      const ids = new Set();
      history.forEach(entry => {
        if (entry?.fetish_id != null) ids.add(Number(entry.fetish_id));
        (entry?.compound_ids || []).forEach(id => {
          if (id != null) ids.add(Number(id));
        });
      });
      return ids;
    } catch {
      return new Set();
    }
  }

  function normalize(value) {
    return String(value || '').trim().toLocaleLowerCase('ja-JP');
  }

  function init() {
    const grid = document.getElementById('catalog-grid');
    const search = document.getElementById('catalog-search');
    const category = document.getElementById('catalog-category');
    const discovery = document.getElementById('catalog-discovery');
    const randomButton = document.getElementById('catalog-random');
    if (!grid || !search || !category || !discovery || !randomButton) return;

    const items = [...grid.querySelectorAll('.item[data-fetish-id]')];
    const diagnosed = discoveredIds();
    items.forEach(item => {
      item.classList.toggle('is-discovered', diagnosed.has(Number(item.dataset.fetishId)));
    });

    function applyFilters() {
      const query = normalize(search.value);
      let visibleCount = 0;
      items.forEach(item => {
        const isDiscovered = diagnosed.has(Number(item.dataset.fetishId));
        const matchesDiscovery = discovery.value === 'all'
          || (discovery.value === 'discovered' && isDiscovered)
          || (discovery.value === 'undiscovered' && !isDiscovered);
        const visible = (!query || normalize(item.dataset.search).includes(query))
          && (!category.value || item.dataset.category === category.value)
          && matchesDiscovery;
        item.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      const count = document.getElementById('catalog-count');
      const progress = document.getElementById('catalog-progress');
      const empty = document.getElementById('catalog-empty');
      if (count) count.textContent = `${visibleCount}/${items.length}種類を表示`;
      if (progress) {
        const diagnosedCount = items.filter(item => diagnosed.has(Number(item.dataset.fetishId))).length;
        progress.textContent = `診断済み ${diagnosedCount}/${items.length}`;
      }
      if (empty) {
        empty.hidden = visibleCount !== 0;
        empty.classList.toggle('hidden', visibleCount !== 0);
      }
    }

    [search, category, discovery].forEach(control => {
      control.addEventListener(control === search ? 'input' : 'change', applyFilters);
    });
    randomButton.addEventListener('click', () => {
      const candidates = items.filter(item => !item.hidden);
      if (!candidates.length) return;
      items.forEach(item => item.classList.remove('is-random-pick'));
      const picked = candidates[Math.floor(Math.random() * candidates.length)];
      picked.classList.add('is-random-pick');
      picked.scrollIntoView({block: 'center', behavior: 'smooth'});
      picked.focus({preventScroll: true});
    });
    applyFilters();
  }

  return {discoveredIds, init};
})();

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', window.HekiCatalog.init);
else window.HekiCatalog.init();
