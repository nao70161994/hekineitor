let _fetching = window.gameState?.fetching || false;

window.HekiNetwork = (() => {
  function setFetching(value) {
    _fetching = value;
    if (window.HekiState) window.HekiState.setFetching(value);
    else if (window.gameState) window.gameState.fetching = value;
  }

  async function apiFetch(url, body, timeoutMs = 30000) {
    try {
      if (window.HekiApiClient?.requestJson) {
        return await window.HekiApiClient.requestJson(url, body, {timeoutMs});
      }
      const res = await window.HekiApiClient.fetchJson(url, body, {timeoutMs});
      if (!res.ok) throw new Error(`サーバーエラー (${res.status})`);
      return await res.json();
    } catch (error) {
      if (error.status === 440 || error.message === 'session_expired') {
        showSessionExpired();
        throw new Error('session_expired');
      }
      const msg = error.name === 'AbortError'
        ? 'サーバーへの接続がタイムアウトしました。しばらくしてから再試行してください。'
        : (error.message === 'network' ? '通信エラーが発生しました。リロードしてください。' : error.message || '通信エラーが発生しました。リロードしてください。');
      showToast(msg, '#c0392b');
      throw error;
    }
  }

  function setAnswerButtons(disabled) {
    document.querySelectorAll('#question-screen .btn').forEach(button => { button.disabled = disabled; });
  }

  return {setFetching, apiFetch, setAnswerButtons};
})();
