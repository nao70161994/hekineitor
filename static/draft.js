window.HekiDraft = (() => {
  const DRAFT_KEY = 'heki_draft';
  let draftPairs = [];

  function push(questionId, answer) {
    draftPairs.push({q_id: questionId, answer});
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
      if (!draft.pairs || !draft.pairs.length) return;
      if (Date.now() - draft.ts > 3600 * 1000) {
        try { localStorage.removeItem(DRAFT_KEY); } catch {}
        return;
      }
      draftPairs = draft.pairs;
      document.getElementById('resume-count').textContent = draft.pairs.length;
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

  return {push, saveDraft, clearDraft, checkDraft, resumeGame};
})();

window._pushDraft = (questionId, answer) => window.HekiDraft.push(questionId, answer);
window._saveDraft = () => window.HekiDraft.saveDraft();
window._clearDraft = () => window.HekiDraft.clearDraft();
window._checkDraft = () => window.HekiDraft.checkDraft();
window.resumeGame = () => window.HekiDraft.resumeGame();
