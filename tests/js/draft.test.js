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
    document.body.innerHTML = '<div id="resume-banner" class="hidden"></div><span id="resume-count"></span><time id="resume-updated-at"></time><time id="resume-expires-at"></time>';
    window.gameState = {fetching: false};
    window.setFetching = vi.fn(value => { window.gameState.fetching = value; });
    window.apiFetch = vi.fn();
    window.showQuestion = vi.fn();
    window.showGuess = vi.fn();
    window.eval(source);
  });
  it('keeps a two-day-old draft and exposes update and expiry times', () => {
    const updatedAt = Date.now() - 2 * 24 * 3600 * 1000;
    localStorage.setItem('heki_draft', JSON.stringify({pairs: [{q_id: 4, answer: 1}], ts: updatedAt}));
    window.HekiDraft.checkDraft();
    expect(document.getElementById('resume-banner').classList.contains('hidden')).toBe(false);
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
});
