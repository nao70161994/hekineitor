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
      window.trackGameplayEvent?.('ui_error', {source: 'system', outcome: 'failure'});
      if (error.status === 440 || error.message === 'session_expired') {
        showSessionExpired();
        throw new Error('session_expired', {cause: error});
      }
      const msg = error.name === 'AbortError'
        ? 'サーバーへの接続がタイムアウトしました。しばらくしてから再試行してください。'
        : (!navigator.onLine
            ? 'オフラインです。接続が戻ったら同じ操作を再試行してください。途中回答は保存されています。'
            : (error.message === 'network'
                ? '通信を確認できませんでした。接続を確認して同じ操作を再試行してください。'
                : error.message || '通信エラーが発生しました。同じ操作を再試行してください。'));
      showToast(msg, '#c0392b');
      throw error;
    }
  }

  function setAnswerButtons(disabled) {
    document.querySelectorAll('#question-screen [data-action="send-answer"]').forEach(button => {
      button.disabled = disabled;
    });
  }

  return {setFetching, apiFetch, setAnswerButtons};
})();

window.setFetching = value => window.HekiNetwork.setFetching(value);
window.apiFetch = (url, body, timeoutMs = 30000) => window.HekiNetwork.apiFetch(url, body, timeoutMs);
window.setAnswerButtons = disabled => window.HekiNetwork.setAnswerButtons(disabled);
