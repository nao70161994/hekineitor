window.HekiDraft = (() => {
  const DRAFT_KEY = 'heki_draft';
  let draftPairs = [];

  const VALID_ANSWERS = new Set([1, 0.5, 0, -0.5, -1]);
  const MAX_DRAFT_PAIRS = 30;

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

  function push(questionId, answer) {
    draftPairs.push({q_id: questionId, answer});
  }

  function popLast() {
    draftPairs.pop();
    if (draftPairs.length) saveDraft();
    else clearDraft();
  }

  function saveDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({pairs: draftPairs, ts: Date.now()}));
    } catch {
      // Draft persistence is optional; gameplay must continue when storage is unavailable.
    }
  }

  function clearDraft() {
    draftPairs = [];
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // Ignore storage failures.
    }
  }

  function checkDraft() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return;
      const draft = JSON.parse(raw);
      const pairs = normalizePairs(draft.pairs);
      if (!pairs.length) {
        try { localStorage.removeItem(DRAFT_KEY); } catch {}
        return;
      }
      if (Date.now() - draft.ts > 3600 * 1000) {
        try { localStorage.removeItem(DRAFT_KEY); } catch {}
        return;
      }
      draftPairs = pairs;
      document.getElementById('resume-count').textContent = pairs.length;
      document.getElementById('resume-banner').classList.remove('hidden');
    } catch {}
  }

  async function resumeGame() {
    if (window.gameState?.fetching) return;
    const pairs = [...draftPairs];
    if (!pairs.length) return;
    setFetching(true);
    try {
      const data = await apiFetch('/api/resume', {pairs});
      document.getElementById('resume-banner').classList.add('hidden');
      if (data.action === 'question') {
        draftPairs = pairs;
        saveDraft();
        showQuestion(data);
      } else {
        clearDraft();
        showGuess(data);
      }
    } catch {
      draftPairs = pairs;
      saveDraft();
      document.getElementById('resume-banner').classList.remove('hidden');
    } finally {
      setFetching(false);
    }
  }

  return {push, popLast, saveDraft, clearDraft, checkDraft, resumeGame};
})();

window._pushDraft = (questionId, answer) => window.HekiDraft.push(questionId, answer);
window._saveDraft = () => window.HekiDraft.saveDraft();
window._popDraft = () => window.HekiDraft.popLast();
window._clearDraft = () => window.HekiDraft.clearDraft();
window._checkDraft = () => window.HekiDraft.checkDraft();
window.resumeGame = () => window.HekiDraft.resumeGame();
