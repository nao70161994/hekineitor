window.trackGameplayEvent = (eventName, details = {}) => {
  try {
    fetch('/api/gameplay_event', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({event_name: eventName, ...details}),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // Product metrics must never block gameplay.
  }
};

window.HekiEvents = (() => {
  function handleKeydown(event) {
    if (document.querySelector('.modal-overlay:not(.hidden)')) return;
    const questionScreen = document.getElementById('question-screen');
    if (!questionScreen || questionScreen.classList.contains('hidden')) return;
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;
    const answerMap = {'1': 1, '2': 0.5, '3': 0, '4': -0.5, '5': -1};
    if (answerMap[event.key] !== undefined) {
      event.preventDefault();
      sendAnswer(answerMap[event.key]);
    } else if (event.key === 'Backspace') {
      event.preventDefault();
      goBack();
    }
  }

  function handleAction(el) {
    const action = el.dataset.action;
    if (action === 'start-game') startGame(window._excludedIds || []);
    else if (action === 'toggle-history') toggleHistory();
    else if (action === 'resume-game') resumeGame();
    else if (action === 'discard-draft') discardDraft();
    else if (action === 'go-back') goBack();
    else if (action === 'confirm-restart') confirmRestart();
    else if (action === 'send-answer') sendAnswer(parseFloat(el.dataset.answer));
    else if (action === 'retry-pending-answer') retryPendingAnswer();
    else if (action === 'submit-confirm') submitConfirm();
    else if (action === 'quick-feedback') quickFeedback(el.dataset.feedback);
    else if (action === 'toggle-detail-feedback') toggleDetailFeedback();
    else if (action === 'continue-game') continueGame();
    else if (action === 'show-start') showStart();
    else if (action === 'start-excluding') startExcluding();
    else if (action === 'quick-retry') quickRetry();
    else if (action === 'submit-teach') submitTeach();
    else if (action === 'add-fetish-step1') addFetishStep1();
    else if (action === 'add-fetish-confirm-new') addFetishConfirmNew();
    else if (action === 'add-fetish-step2') addFetishStep2(el.dataset.skip === 'true');
    else if (action === 'add-fetish-more') addFetishMore();
    else if (action === 'add-fetish-done') addFetishDone();
    else if (action === 'skip-teach') skipTeach();
    else if (action === 'share-result') shareResult();
    else if (action === 'share-x-result') shareResultX();
    else if (action === 'close-modal') closeModal(el.dataset.modalId);
    else if (action === 'do-restart') doRestart();
    else if (action === 'discard-restart') discardRestart();
    else if (action === 'toggle-more-works') window.HekiRenderers?.toggleMoreWorks(el);
    else if (action === 'select-share-fallback') window.HekiShare?.selectFallbackText();
    else if (action === 'dismiss-install') dismissInstall();
    else if (action === 'set-item-state') setItemState(parseInt(el.dataset.id, 10), el.dataset.state, el);
    else if (action === 'retry-excluding') retryExcluding(parseInt(el.dataset.index, 10));
    else if (action === 'view-history') viewHistory(parseInt(el.dataset.index, 10));
  }

  function bind() {
    document.addEventListener('click', event => {
      const el = event.target.closest('[data-action]');
      if (!el) return;
      handleAction(el);
    });
    document.addEventListener('keydown', handleKeydown);
    document.addEventListener('keydown', event => window.HekiUi?.handleModalKeydown(event));
    _checkDraft();
    _updateHistoryBadge();
  }

  return {bind, handleAction, handleKeydown};
})();

document.addEventListener('DOMContentLoaded', () => window.HekiEvents.bind());
