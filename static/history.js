window.HekiHistory = (() => {
  const HISTORY_KEY = 'heki_history';

  function load() {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    } catch {
      return [];
    }
  }

  function save(items) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
  }

  function saveHistory(name, probability, fetishId) {
    const history = load();
    history.unshift({
      name,
      prob: probability,
      date: new Date().toLocaleDateString('ja-JP'),
      fetish_id: fetishId || null,
    });
    if (history.length > 20) history.pop();
    save(history);
    updateHistoryBadge();
  }

  function updateHistoryBadge() {
    const history = load();
    const badge = document.getElementById('history-badge');
    if (!badge) return;
    if (history.length > 0) {
      badge.textContent = history.length;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  }

  function toggleHistory() {
    const panel = document.getElementById('history-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
      panel.classList.add('hidden');
      return;
    }
    const history = load();
    if (!history.length) {
      panel.innerHTML = '<p style="color:#666;font-size:0.8rem;text-align:center;">まだ診断履歴がありません</p>';
    } else {
      panel.innerHTML = history.map((entry, index) => `
        <div class="history-item">
          <strong>${escapeHtml(entry.name)}</strong>
          <span class="h-meta">${escapeHtml(entry.prob)}% · ${escapeHtml(entry.date)}</span>
          <button class="h-retry" data-action="retry-excluding" data-index="${index}" title="この診断を除外して再診断">再診断</button>
        </div>`).join('');
    }
    panel.classList.remove('hidden');
  }

  function retryExcluding(historyIndex) {
    const history = load();
    const entry = history[historyIndex];
    if (!entry || !entry.fetish_id) {
      startGame();
      return;
    }
    const excludeIds = [...(window._excludedIds || []), entry.fetish_id];
    if (window.HekiState) window.HekiState.setExcludedIds([...new Set(excludeIds)]);
    else {
      window._excludedIds = [...new Set(excludeIds)];
      if (window.gameState) window.gameState.excludedIds = window._excludedIds;
    }
    startGame(window._excludedIds);
    document.getElementById('history-panel')?.classList.add('hidden');
  }

  return {saveHistory, updateHistoryBadge, toggleHistory, retryExcluding};
})();

window.saveHistory = (name, prob, fetishId) => window.HekiHistory.saveHistory(name, prob, fetishId);
window._updateHistoryBadge = () => window.HekiHistory.updateHistoryBadge();
window.toggleHistory = () => window.HekiHistory.toggleHistory();
window.retryExcluding = historyIndex => window.HekiHistory.retryExcluding(historyIndex);
