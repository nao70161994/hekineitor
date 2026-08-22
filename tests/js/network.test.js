import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/network.js'), 'utf8');

describe('HekiNetwork failures', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="question-screen"><button data-action="send-answer"></button></div>';
    window.gameState = {fetching: false};
    window.HekiApiClient = {requestJson: vi.fn()};
    window.showToast = vi.fn();
    window.showSessionExpired = vi.fn();
    window.trackGameplayEvent = vi.fn();
    window.eval(source);
  });

  it('preserves a retryable message and records an anonymous UI error while offline', async () => {
    Object.defineProperty(navigator, 'onLine', {configurable: true, value: false});
    window.HekiApiClient.requestJson.mockRejectedValue(new Error('network'));

    await expect(window.HekiNetwork.apiFetch('/api/start')).rejects.toThrow('network');

    expect(window.showToast).toHaveBeenCalledWith(
      'オフラインです。接続が戻ったら同じ操作を再試行してください。途中回答は保存されています。',
      '#c0392b',
    );
    expect(window.trackGameplayEvent).toHaveBeenCalledWith(
      'ui_error', {source: 'system', outcome: 'failure'},
    );
  });
});
