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
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
    } catch {
      // History is optional; never block result rendering on storage failures.
    }
  }

  function resultSnapshot(data) {
    if (!data || typeof data !== 'object') return null;
    try {
      const snapshot = JSON.parse(JSON.stringify(data));
      delete snapshot._historyReplay;
      return snapshot;
    } catch {
      return null;
    }
  }

  function saveHistory(name, probability, fetishId, compoundIds = [], resultData = window._guessData) {
    const history = load();
    history.unshift({
      name,
      prob: probability,
      date: new Date().toLocaleDateString('ja-JP'),
      fetish_id: fetishId ?? null,
      compound_ids: Array.isArray(compoundIds) ? compoundIds.filter(id => id != null) : [],
      result: resultSnapshot(resultData),
    });
    if (history.length > 20) history.pop();
    save(history);
    updateHistoryBadge();
  }

  function updateHistoryBadge() {
    const history = load();
    const badge = document.getElementById("history-badge");
    const button = document.getElementById("history-btn");
    if (!badge || !button) return;
    const hasHistory = history.length > 0;
    button.classList.toggle("hidden", !hasHistory);
    badge.classList.toggle("hidden", !hasHistory);
    badge.textContent = hasHistory ? history.length : "";
    if (hasHistory) window.HekiPwa?.markGameCompleted?.();
    if (!hasHistory) {
      document.getElementById("history-panel")?.classList.add("hidden");
      button.setAttribute("aria-expanded", "false");
    }
  }

  function toggleHistory() {
    const panel = document.getElementById('history-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
      panel.classList.add('hidden');
      document.getElementById('history-btn')?.setAttribute('aria-expanded', 'false');
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
          <button class="h-view" data-action="view-history" data-index="${index}">結果を見る</button>
          <button class="h-retry" data-action="retry-excluding" data-index="${index}" title="この診断を除外して再診断">当て直す</button>
        </div>`).join('');
    }
    panel.classList.remove('hidden');
    document.getElementById('history-btn')?.setAttribute('aria-expanded', 'true');
  }

  function retryExcluding(historyIndex) {
    const history = load();
    const entry = history[historyIndex];
    if (!entry || entry.fetish_id == null) {
      startGame();
      return;
    }
    const compoundIds = Array.isArray(entry.compound_ids) ? entry.compound_ids : [];
    const excludeIds = [...(window._excludedIds || []), entry.fetish_id, ...compoundIds];
    if (window.HekiState) window.HekiState.setExcludedIds([...new Set(excludeIds)]);
    else {
      window._excludedIds = [...new Set(excludeIds)];
      if (window.gameState) window.gameState.excludedIds = window._excludedIds;
    }
    startGame(window._excludedIds);
    document.getElementById('history-panel')?.classList.add('hidden');
  }


  function viewHistory(historyIndex) {
    const entry = load()[historyIndex];
    if (!entry) return;
    const result = entry.result || {
      fetish_id: entry.fetish_id,
      fetish_name: entry.name,
      fetish_desc: '過去の診断結果です。',
      probability: entry.prob,
      compound: [],
      top_chart: [],
      profile: [],
      related: [],
      reasons: [],
      works: [],
      cross_works: [],
    };
    result._historyReplay = true;
    showGuess(result);
    document.getElementById('history-panel')?.classList.add('hidden');
    document.getElementById('history-btn')?.setAttribute('aria-expanded', 'false');
    if (window.trackGameplayEvent) {
      window.trackGameplayEvent('history_reopened', {source: 'history', outcome: 'success', result_id: entry.fetish_id});
    }
    if (window._trackShareEvent) {
      window._trackShareEvent('history_revisit', {resultName: entry.name, channel: 'history', success: true});
    }
  }

  return {saveHistory, updateHistoryBadge, toggleHistory, retryExcluding, viewHistory};
})();

window.saveHistory = (name, prob, fetishId, compoundIds, resultData) => window.HekiHistory.saveHistory(name, prob, fetishId, compoundIds, resultData);
window._updateHistoryBadge = () => window.HekiHistory.updateHistoryBadge();
window.toggleHistory = () => window.HekiHistory.toggleHistory();
window.retryExcluding = historyIndex => window.HekiHistory.retryExcluding(historyIndex);
window.viewHistory = historyIndex => window.HekiHistory.viewHistory(historyIndex);
