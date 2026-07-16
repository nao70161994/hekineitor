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
    document.body.innerHTML = '<div id="resume-banner" class="hidden"></div><span id="resume-count"></span>';
    window.gameState = {fetching: false};
    window.setFetching = vi.fn(value => { window.gameState.fetching = value; });
    window.apiFetch = vi.fn();
    window.showQuestion = vi.fn();
    window.showGuess = vi.fn();
    window.eval(source);
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
