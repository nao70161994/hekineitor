import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/history.js'), 'utf8');

describe('HekiHistory', () => {
  let storage;
  beforeEach(() => {
    storage = new Map();
    vi.stubGlobal('localStorage', {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
    });
    document.body.innerHTML = '<span id="history-badge" class="hidden"></span><div id="history-panel" class="hidden"></div>';
    window.escapeHtml = value => String(value);
    window.startGame = vi.fn();
    window._excludedIds = [];
    window.HekiState = {setExcludedIds: vi.fn(ids => { window._excludedIds = ids; })};
    window.eval(source);
  });

  it('stores and excludes result ID zero instead of treating it as missing', () => {
    window.HekiHistory.saveHistory('NTR', 80, 0);
    const saved = JSON.parse(storage.get('heki_history'));
    expect(saved[0].fetish_id).toBe(0);

    window.HekiHistory.retryExcluding(0);
    expect(window.startGame).toHaveBeenCalledWith([0]);
  });

  it('stores a compound display name and excludes every result in the combination', () => {
    window.HekiHistory.saveHistory('主結果 × 複合結果', 70, 3, [4, 5]);
    const saved = JSON.parse(storage.get('heki_history'));
    expect(saved[0]).toMatchObject({name: '主結果 × 複合結果', fetish_id: 3, compound_ids: [4, 5]});

    window.HekiHistory.retryExcluding(0);
    expect(window.startGame).toHaveBeenCalledWith([3, 4, 5]);
  });
});
