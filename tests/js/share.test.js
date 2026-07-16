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
    window._guessData = {probability: 82, fetish_desc: '説明'};
    window.eval(source);
    window.HekiShare.setDiagnosedName('NTR');
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
});
