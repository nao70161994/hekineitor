import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/share.js'), 'utf8');

describe('HekiShare', () => {
  let writeText;
  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', {value: undefined, configurable: true});
    Object.defineProperty(navigator, 'clipboard', {value: {writeText}, configurable: true});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: false}));
    window.open = vi.fn();
    window.showToast = vi.fn();
    window.trackGameplayEvent = vi.fn();
    window._guessData = {probability: 82, fetish_desc: '説明'};
    window.eval(source);
    window.HekiShare.setDiagnosedName('NTR');
  });
  it('falls back to clipboard when native sharing fails', async () => {
    Object.defineProperty(navigator, 'share', {
      value: vi.fn().mockRejectedValue(new Error('share failed')),
      configurable: true,
    });
    window.HekiShare.shareResult();
    await Promise.resolve();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledOnce();
  });

  it('copies through the secondary share action without opening X', async () => {
    window.HekiShare.shareResult();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledOnce();
    expect(window.open).not.toHaveBeenCalled();
  });

  it('opens X only through the dedicated X action', () => {
    window.HekiShare.openXShare();
    expect(window.open).toHaveBeenCalledOnce();
    expect(window.open.mock.calls[0][0]).toContain('twitter.com/intent/tweet');
  });

  it('records a versioned gameplay work click without player identity', () => {
    document.body.innerHTML = '<a href="https://example.com" data-work-title="作品" data-work-id="work_1" data-edition-id="ed_1">作品</a>';
    document.querySelector('a').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));

    expect(window.trackGameplayEvent).toHaveBeenCalledWith('work_click', {
      source: 'works',
      outcome: 'success',
      work_id: 'work_1',
      edition_id: 'ed_1',
    });
  });
});
