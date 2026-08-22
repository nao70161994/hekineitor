window.HekiPerformance = (() => {
  const state = {lcpMs: null, inpMs: null, cls: 0};
  const interactionDurations = new Map();
  let sent = false;

  function observe(type, callback, options = {}) {
    if (!('PerformanceObserver' in window)) return;
    if (!PerformanceObserver.supportedEntryTypes?.includes(type)) return;
    try {
      const observer = new PerformanceObserver(list => callback(list.getEntries()));
      observer.observe({type, buffered: true, ...options});
    } catch {
      // Older browsers simply omit unsupported metrics.
    }
  }

  observe('largest-contentful-paint', entries => {
    const last = entries.at(-1);
    if (last) state.lcpMs = last.startTime;
  });

  observe('layout-shift', entries => {
    for (const entry of entries) {
      if (!entry.hadRecentInput) state.cls += entry.value;
    }
  });

  observe('event', entries => {
    for (const entry of entries) {
      if (!entry.interactionId) continue;
      const previous = interactionDurations.get(entry.interactionId) || 0;
      interactionDurations.set(entry.interactionId, Math.max(previous, entry.duration));
    }
    const durations = [...interactionDurations.values()].sort((a, b) => b - a);
    const rank = Math.min(durations.length - 1, Math.floor(durations.length / 50));
    if (rank >= 0) state.inpMs = durations[rank];
  }, {durationThreshold: 40});

  function snapshot() {
    return {
      lcp_ms: state.lcpMs == null ? null : Math.max(0, Math.min(120000, Math.round(state.lcpMs))),
      inp_ms: state.inpMs == null ? null : Math.max(0, Math.min(60000, Math.round(state.inpMs))),
      cls_milli: Math.max(0, Math.min(10000, Math.round(state.cls * 1000))),
    };
  }

  function send() {
    if (sent) return;
    const metrics = snapshot();
    if (metrics.lcp_ms == null && metrics.inp_ms == null && metrics.cls_milli === 0) return;
    sent = true;
    const body = JSON.stringify({
      event_name: 'web_vitals',
      source: 'system',
      outcome: 'success',
      ...metrics,
    });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/gameplay_event', new Blob([body], {type: 'application/json'}));
      } else {
        fetch('/api/gameplay_event', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body,
          keepalive: true,
        }).catch(() => {});
      }
    } catch {
      // Performance measurement must never affect gameplay.
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') send();
  });
  window.addEventListener('pagehide', send);

  return {snapshot, send};
})();
