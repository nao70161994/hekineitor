import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/draft.js'), 'utf8');

describe('HekiDraft', () => {
  beforeEach(() => {
    const storage = new Map();
    vi.stubGlobal('localStorage', {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
      clear: () => storage.clear(),
    });
    document.body.innerHTML = "<section id=start-screen><button class=btn-start data-action=start-game>診断をはじめる</button><div id=resume-banner class=hidden></div><span id=resume-count></span><time id=resume-updated-at></time><time id=resume-expires-at></time></section>";
    window.gameState = {fetching: false};
    window._excludedIds = [];
    window.HekiState = {
      getExcludedIds: () => window._excludedIds,
      setExcludedIds: vi.fn(ids => { window._excludedIds = ids; }),
    };
    window.setFetching = vi.fn(value => { window.gameState.fetching = value; });
    window.apiFetch = vi.fn();
    window.showQuestion = vi.fn();
    window.showGuess = vi.fn();
    window.trackGameplayEvent = vi.fn();
    window.eval(source);
  });
  it('keeps a two-day-old draft and exposes update and expiry times', () => {
    const updatedAt = Date.now() - 2 * 24 * 3600 * 1000;
    localStorage.setItem('heki_draft', JSON.stringify({pairs: [{q_id: 4, answer: 1}], ts: updatedAt}));
    window.HekiDraft.checkDraft();
    expect(document.getElementById('resume-banner').classList.contains('hidden')).toBe(false);
    expect(document.querySelector("[data-action=start-game]").textContent).toBe("最初から始める");
    expect(document.querySelector("[data-action=start-game]").classList.contains("btn-start-secondary")).toBe(true);
    expect(document.getElementById('resume-updated-at').dateTime).toBe(new Date(updatedAt).toISOString());
    expect(document.getElementById('resume-expires-at').dateTime).toBe(new Date(updatedAt + 7 * 24 * 3600 * 1000).toISOString());
  });

  it('keeps answers ordered and replaces a repeated question instead of duplicating it', () => {
    window.HekiDraft.push(4, 1);
    window.HekiDraft.push(7, -1);
    window.HekiDraft.push(4, 0.5);
    window.HekiDraft.saveDraft();

    expect(window.HekiDraft.getPairs()).toEqual([
      {q_id: 4, answer: 0.5},
      {q_id: 7, answer: -1},
    ]);
    expect(JSON.parse(localStorage.getItem('heki_draft')).pairs).toHaveLength(2);
  });

  it('removes a completed draft from storage while retaining it for additional questions', () => {
    window.HekiDraft.push(4, 1);
    window.HekiDraft.saveDraft();
    window.HekiDraft.pauseDraft();

    expect(localStorage.getItem('heki_draft')).toBeNull();
    expect(window.HekiDraft.getPairs()).toEqual([{q_id: 4, answer: 1}]);

    window.HekiDraft.saveDraft();
    expect(JSON.parse(localStorage.getItem('heki_draft')).pairs).toEqual([{q_id: 4, answer: 1}]);
  });

  it('retains all pairs when resume immediately reaches a result', async () => {
    window.HekiDraft.push(4, 1);
    window.HekiDraft.push(7, -0.5);
    window.HekiDraft.saveDraft();
    window.apiFetch.mockResolvedValue({action: 'guess', fetish_id: 1});

    await window.HekiDraft.resumeGame();

    expect(window.showGuess).toHaveBeenCalledOnce();
    expect(window.HekiDraft.getPairs()).toHaveLength(2);
    expect(localStorage.getItem('heki_draft')).toBeNull();

  });
  it('persists exclusions for seven days and restores them with the saved answers', async () => {
    window._excludedIds = [2, 7, 2];
    window.HekiDraft.push(4, 1);
    window.HekiDraft.saveDraft();
    const saved = JSON.parse(localStorage.getItem('heki_draft'));
    expect(saved.exclude_ids).toEqual([2, 7]);
    expect(saved.expires_at - saved.ts).toBe(7 * 24 * 3600 * 1000);

    window._excludedIds = [];
    window.HekiDraft.checkDraft();
    expect(window._excludedIds).toEqual([2, 7]);
    window.apiFetch.mockResolvedValue({action: 'question', question_id: 8});
    await window.HekiDraft.resumeGame();
    expect(window.apiFetch).toHaveBeenCalledWith('/api/resume', {
      pairs: [{q_id: 4, answer: 1}], exclude_ids: [2, 7],
    });
  });

  it('keeps old drafts compatible and clears exclusions only on explicit discard', () => {
    const updatedAt = Date.now();
    localStorage.setItem('heki_draft', JSON.stringify({pairs: [{q_id: 4, answer: 1}], ts: updatedAt}));
    window._excludedIds = [9];
    window.HekiDraft.checkDraft();
    expect(window._excludedIds).toEqual([]);

    window._excludedIds = [3, 5];
    window.HekiDraft.saveDraft();
    window.HekiDraft.clearDraft();
    expect(window._excludedIds).toEqual([3, 5]);
    window.HekiDraft.discardDraft();
    expect(window._excludedIds).toEqual([]);
  });
  it('expires answers and exclusions after seven days even with a later declared expiry', () => {
    const updatedAt = Date.now() - 8 * 24 * 3600 * 1000;
    localStorage.setItem('heki_draft', JSON.stringify({
      pairs: [{q_id: 4, answer: 1}],
      exclude_ids: [3],
      ts: updatedAt,
      expires_at: Date.now() + 30 * 24 * 3600 * 1000,
    }));
    window._excludedIds = [9];
    window.HekiDraft.checkDraft();
    expect(localStorage.getItem('heki_draft')).toBeNull();
    expect(window.HekiDraft.getPairs()).toEqual([]);
    expect(window._excludedIds).toEqual([]);
    expect(window.trackGameplayEvent).toHaveBeenCalledWith('draft_discarded', {
      source: 'draft', outcome: 'expired',
    });
  });
});
