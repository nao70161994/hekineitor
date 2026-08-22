import {readFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {beforeEach, describe, expect, it, vi} from 'vitest';

const testDir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(testDir, '../../static/performance.js'), 'utf8');

describe('HekiPerformance', () => {
  let callbacks;
  let sendBeacon;

  beforeEach(() => {
    callbacks = new Map();
    class FakePerformanceObserver {
      static supportedEntryTypes = ['largest-contentful-paint', 'layout-shift', 'event'];
      constructor(callback) { this.callback = callback; }
      observe(options) { callbacks.set(options.type, entries => this.callback({getEntries: () => entries})); }
    }
    vi.stubGlobal('PerformanceObserver', FakePerformanceObserver);
    sendBeacon = vi.fn(() => true);
    Object.defineProperty(navigator, 'sendBeacon', {value: sendBeacon, configurable: true});
    window.eval(source);
  });

  it('collects bounded LCP, CLS, and interaction latency without identifiers', async () => {
    callbacks.get('largest-contentful-paint')([{startTime: 2345.6}]);
    callbacks.get('layout-shift')([
      {value: 0.12, hadRecentInput: false},
      {value: 0.5, hadRecentInput: true},
    ]);
    callbacks.get('event')([
      {interactionId: 1, duration: 180},
      {interactionId: 1, duration: 120},
      {interactionId: 2, duration: 90},
    ]);

    expect(window.HekiPerformance.snapshot()).toEqual({lcp_ms: 2346, inp_ms: 180, cls_milli: 120});
    window.HekiPerformance.send();
    window.HekiPerformance.send();

    expect(sendBeacon).toHaveBeenCalledOnce();
    expect(sendBeacon.mock.calls[0][0]).toBe('/api/gameplay_event');
    const payload = JSON.parse(await sendBeacon.mock.calls[0][1].text());
    expect(payload).toEqual({
      event_name: 'web_vitals',
      source: 'system',
      outcome: 'success',
      lcp_ms: 2346,
      inp_ms: 180,
      cls_milli: 120,
    });
  });
});
