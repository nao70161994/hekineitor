import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/pwa.js'), 'utf8');

describe('HekiPwa', () => {
  let registration;
  let serviceWorkerListeners;
  let windowListeners;

  beforeEach(() => {
    document.body.innerHTML = `
      <div class="install-banner hidden" id="install-banner" data-mode="install">
        <p id="install-msg"></p><button id="btn-install"></button>
      </div>`;
    const values = new Map();
    vi.stubGlobal('localStorage', {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
    });
    serviceWorkerListeners = new Map();
    windowListeners = new Map();
    vi.spyOn(window, 'addEventListener').mockImplementation((name, callback) => {
      windowListeners.set(name, callback);
    });
    registration = {
      waiting: {postMessage: vi.fn()},
      addEventListener: vi.fn(),
    };
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        controller: {},
        register: vi.fn().mockResolvedValue(registration),
        addEventListener: vi.fn((name, callback) => serviceWorkerListeners.set(name, callback)),
      },
    });
    vi.stubGlobal('matchMedia', vi.fn(() => ({matches: false})));
    window.showToast = vi.fn();
    window._saveDraft = vi.fn();
    window.gameState = {fetching: false};
    window.eval(source);
  });

  it('defers updates while sending and saves the draft before activating', async () => {
    windowListeners.get('load')();
    await vi.waitFor(() => expect(navigator.serviceWorker.register).toHaveBeenCalledWith('/sw.js'));
    await vi.waitFor(() => expect(document.getElementById('install-msg').textContent).toContain('新しい'));

    window.gameState.fetching = true;
    document.getElementById('btn-install').click();
    expect(registration.waiting.postMessage).not.toHaveBeenCalled();
    expect(window.showToast).toHaveBeenCalledWith(
      '回答の送信が終わってから更新してください', '#7c4a03', 5000,
    );

    window.gameState.fetching = false;
    document.getElementById('btn-install').click();
    expect(window._saveDraft).toHaveBeenCalledOnce();
    expect(registration.waiting.postMessage).toHaveBeenCalledWith({type: 'SKIP_WAITING'});
  });

  it('announces offline and restored connections', () => {
    windowListeners.get('offline')();
    windowListeners.get('online')();

    expect(window.showToast).toHaveBeenNthCalledWith(
      1, 'オフラインです。途中回答は端末に保存されます', '#7c4a03', 6000,
    );
    expect(window.showToast).toHaveBeenNthCalledWith(
      2, '接続が戻りました。操作を再試行できます', '#167a43', 5000,
    );
  });
  it("shows the install invitation only after a completed game", () => {
    const promptEvent = {preventDefault: vi.fn(), prompt: vi.fn(), userChoice: Promise.resolve({outcome: "dismissed"})};
    windowListeners.get("beforeinstallprompt")(promptEvent);
    expect(promptEvent.preventDefault).toHaveBeenCalledOnce();
    expect(document.getElementById("install-banner").classList.contains("hidden")).toBe(true);
    window.HekiPwa.markGameCompleted();
    expect(localStorage.getItem("heki-game-completed")).toBe("1");
    expect(document.getElementById("install-banner").classList.contains("hidden")).toBe(false);
  });
});
