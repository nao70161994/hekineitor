window.HekiApiClient = (() => {
  async function fetchJson(url, body, options = {}) {
    const timeoutMs = options.timeoutMs || 30000;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: options.method || 'POST',
        headers: {'Content-Type': 'application/json', ...(options.headers || {})},
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
        credentials: options.credentials,
      });
      return res;
    } finally {
      clearTimeout(timer);
    }
  }

  async function requestJson(url, body, options = {}) {
    const res = await fetchJson(url, body, options);
    if (res.status === 440) {
      const error = new Error('session_expired');
      error.status = 440;
      throw error;
    }
    if (!res.ok) {
      let message = `サーバーエラー (${res.status})`;
      try {
        const payload = await res.json();
        if (payload.message) message = payload.message;
      } catch {}
      const error = new Error(message);
      error.status = res.status;
      throw error;
    }
    return await res.json();
  }

  return {fetchJson, requestJson};
})();
