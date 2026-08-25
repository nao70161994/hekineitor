window.HekiDraft = (() => {
  const DRAFT_KEY = 'heki_draft';
  let draftPairs = [];

  const VALID_ANSWERS = new Set([1, 0.5, 0, -0.5, -1]);
  const MAX_DRAFT_PAIRS = 30;
  const MAX_EXCLUDE_IDS = 256;
  const DRAFT_TTL_MS = 7 * 24 * 3600 * 1000;

  function formatDateTime(timestamp) {
    return new Intl.DateTimeFormat('ja-JP', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(timestamp));
  }
  function setResumeVisible(visible) {
    document.getElementById("resume-banner")?.classList.toggle("hidden", !visible);
    document.getElementById("start-screen")?.classList.toggle("has-resume", visible);
    const startButton = document.querySelector('[data-action="start-game"]');
    if (startButton) {
      startButton.textContent = visible ? "最初から始める" : "診断をはじめる";
      startButton.classList.toggle("btn-start-secondary", visible);
    }
  }


  function validPair(pair) {
    if (!pair || pair.q_id === undefined) return false;
    const questionId = Number(pair.q_id);
    const answer = Number(pair.answer);
    return Number.isInteger(questionId) && questionId >= 0 && VALID_ANSWERS.has(answer);
  }

  function normalizePairs(pairs) {
    if (!Array.isArray(pairs) || pairs.length > MAX_DRAFT_PAIRS) return [];
    const normalized = pairs.map(pair => ({q_id: Number(pair.q_id), answer: Number(pair.answer)}));
    return normalized.every(validPair) ? normalized : [];
  }

  function normalizeExcludeIds(ids) {
    if (!Array.isArray(ids) || ids.length > MAX_EXCLUDE_IDS) return [];
    const normalized = ids.map(Number);
    if (!normalized.every(id => Number.isInteger(id) && id >= 0)) return [];
    return [...new Set(normalized)];
  }

  function currentExcludeIds() {
    if (window.HekiState?.getExcludedIds) return normalizeExcludeIds(window.HekiState.getExcludedIds());
    return normalizeExcludeIds(window._excludedIds || []);
  }

  function restoreExcludeIds(ids) {
    const normalized = normalizeExcludeIds(ids);
    if (window.HekiState?.setExcludedIds) window.HekiState.setExcludedIds(normalized);
    else {
      window._excludedIds = normalized;
      if (window.gameState) window.gameState.excludedIds = normalized;
    }
    return normalized;
  }

  function push(questionId, answer) {
    const pair = {q_id: Number(questionId), answer: Number(answer)};
    if (!validPair(pair)) return;
    const existingIndex = draftPairs.findIndex(item => item.q_id === pair.q_id);
    if (existingIndex >= 0) draftPairs[existingIndex] = pair;
    else if (draftPairs.length < MAX_DRAFT_PAIRS) draftPairs.push(pair);
  }

  function pauseDraft() {
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // Keep the in-memory answers available for optional additional questions.
    }
  }

  function getPairs() {
    return [...draftPairs];
  }

  function popLast() {
    draftPairs.pop();
    if (draftPairs.length) saveDraft();
    else clearDraft();
  }

  function saveDraft() {
    try {
      const updatedAt = Date.now();
      localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({
          pairs: draftPairs,
          exclude_ids: currentExcludeIds(),
          ts: updatedAt,
          expires_at: updatedAt + DRAFT_TTL_MS,
        }),
      );
    } catch {
      // Draft persistence is optional; gameplay must continue when storage is unavailable.
    }
  }

  function clearDraft() {
    setResumeVisible(false);
    draftPairs = [];
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // Ignore storage failures.
    }
  }


  function discardDraft() {
    clearDraft();
    restoreExcludeIds([]);
    if (window.showToast) showToast('途中経過を破棄しました', '#555');
    if (window.trackGameplayEvent) {
      window.trackGameplayEvent('draft_discarded', {source: 'draft', outcome: 'discarded'});
    }
  }

  function checkDraft() {
    setResumeVisible(false);
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw);
      const pairs = normalizePairs(draft.pairs);
      if (!pairs.length) {
        draftPairs = [];
        restoreExcludeIds([]);
        try { localStorage.removeItem(DRAFT_KEY); } catch {}
        return;
      }
      const updatedAt = Number(draft.ts);
      const declaredExpiresAt = Number(draft.expires_at || (updatedAt + DRAFT_TTL_MS));
      const expiresAt = Math.min(declaredExpiresAt, updatedAt + DRAFT_TTL_MS);
      if (!Number.isFinite(updatedAt) || !Number.isFinite(expiresAt) || Date.now() > expiresAt) {
        try { localStorage.removeItem(DRAFT_KEY); } catch {}
        draftPairs = [];
        restoreExcludeIds([]);
        if (window.trackGameplayEvent) {
          window.trackGameplayEvent('draft_discarded', {source: 'draft', outcome: 'expired'});
        }
        return;
      }
      draftPairs = pairs;
      restoreExcludeIds(draft.exclude_ids || []);
      document.getElementById('resume-count').textContent = pairs.length;
      const updatedEl = document.getElementById('resume-updated-at');
      const expiresEl = document.getElementById('resume-expires-at');
      if (updatedEl) {
        updatedEl.textContent = formatDateTime(updatedAt);
        updatedEl.dateTime = new Date(updatedAt).toISOString();
      }
      if (expiresEl) {
        expiresEl.textContent = formatDateTime(expiresAt);
        expiresEl.dateTime = new Date(expiresAt).toISOString();
      }
      setResumeVisible(true);
    } catch {}
  }

  async function resumeGame() {
    if (window.gameState?.fetching) return;
    const pairs = [...draftPairs];
    if (!pairs.length) return;
    setFetching(true);
    try {
      const excludeIds = currentExcludeIds();
      const data = await apiFetch('/api/resume', {pairs, exclude_ids: excludeIds});
      restoreExcludeIds(excludeIds);
      setResumeVisible(false);
      document.getElementById('resume-banner').classList.add('hidden');
      if (data.action === 'question') {
        draftPairs = pairs;
        saveDraft();
        showQuestion(data);
      } else {
        draftPairs = pairs;
        pauseDraft();
        showGuess(data);
      }
    } catch {
      draftPairs = pairs;
      saveDraft();
      setResumeVisible(true);
    } finally {
      setFetching(false);
    }
  }

  return {push, popLast, saveDraft, pauseDraft, getPairs, clearDraft, discardDraft, checkDraft, resumeGame};
})();

window._pushDraft = (questionId, answer) => window.HekiDraft.push(questionId, answer);
window._saveDraft = () => window.HekiDraft.saveDraft();
window._popDraft = () => window.HekiDraft.popLast();
window._pauseDraft = () => window.HekiDraft.pauseDraft();
window._clearDraft = () => window.HekiDraft.clearDraft();
window.discardDraft = () => window.HekiDraft.discardDraft();
window._checkDraft = () => window.HekiDraft.checkDraft();
window.resumeGame = () => window.HekiDraft.resumeGame();
