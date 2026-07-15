import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/game_state.js'), 'utf8');

function loadGameState() {
  window.gameState = undefined;
  delete window.HekiState;
  window.eval(source);
}

describe('HekiState', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    delete window._excludedIds;
    delete window._guessData;
    delete window._confirmedIds;
    delete window.lastFetishName;
    delete window.gameState;
    loadGameState();
  });

  it('keeps legacy globals synchronized with state updates', () => {
    expect(window.HekiState.setFetching(1)).toBe(true);
    expect(window.HekiState.setGuessData({id: 12})).toEqual({id: 12});
    expect(window._guessData).toEqual({id: 12});
  });

  it('normalizes collection state and resets exclusions', () => {
    expect(window.HekiState.setExcludedIds([1, 2])).toEqual([1, 2]);
    expect(window.HekiState.getExcludedIds()).toEqual([1, 2]);
    expect(window.HekiState.resetExcludedIds()).toEqual([]);
    expect(window.HekiState.setConfirmedIds([3, null, 4])).toEqual([3, 4]);
    expect(window._confirmedIds).toEqual([3, 4]);
    expect(window.HekiState.setLastFetishName('眼鏡')).toBe('眼鏡');
    expect(window.lastFetishName).toBe('眼鏡');
  });
});
