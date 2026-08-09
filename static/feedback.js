window.HekiFeedback = (() => {
  function resultFeedbackIds() {
    return Array.from(document.querySelectorAll('#confirm-items .confirm-item'))
      .map(item => parseInt(item.dataset.id, 10))
      .filter(id => Number.isFinite(id));
  }

  function setAllItemStates(state) {
    document.querySelectorAll('#confirm-items .confirm-item').forEach(item => {
      const id = parseInt(item.dataset.id, 10);
      const btn = item.querySelector(`.confirm-toggle button[data-state="${state}"]`);
      if (Number.isFinite(id) && btn) setItemState(id, state, btn);
    });
  }

  function showQuickFeedbackStatus(message) {
    const status = document.getElementById('quick-feedback-status');
    if (!status) return;
    status.textContent = message;
    status.classList.remove('hidden');
  }

  function testPlayMessage(data, normalMessage) {
    return data && data.learning_disabled ? 'ありがとうございます。保存せず確認しました。' : normalMessage;
  }

  function lockQuickFeedback() {
    const quickFeedback = document.getElementById('quick-feedback');
    if (quickFeedback) quickFeedback.querySelectorAll('button').forEach(btn => { btn.disabled = true; });
    const detailToggle = document.querySelector('[data-action="toggle-detail-feedback"]');
    if (detailToggle) detailToggle.disabled = true;
  }

  function toggleDetailFeedback() {
    const panel = document.getElementById('detail-feedback-panel');
    const toggle = document.querySelector('[data-action="toggle-detail-feedback"]');
    if (!panel || !toggle) return;
    const willOpen = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !willOpen);
    toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    toggle.textContent = willOpen ? '詳細FBを閉じる' : '詳細に○△×を付ける';
  }

  async function quickFeedback(kind) {
    if (window.gameState?.fetching) return;
    const ids = resultFeedbackIds();
    if (!ids.length) return;
    setFetching(true);
    try {
      if (kind === 'yes') {
        setAllItemStates('yes');
        const data = await apiFetch('/api/confirm', {
          correct: true,
          fetish_id: window._guessedId,
          compound_ids: window._compoundIds || [],
        });
        if (!data) return;
        showQuickFeedbackStatus(testPlayMessage(data, 'ありがとうございます。正解として学習しました。'));
      } else if (kind === 'maybe') {
        setAllItemStates('maybe');
        const data = await apiFetch('/api/confirm', {
          correct: false,
          fetish_id: window._guessedId,
          compound_ids: window._compoundIds || [],
          maybe_ids: [],
          wrong_ids: [],
          defer_learning: true,
        });
        if (!data) return;
        if (data.fetishes && data.fetishes.length > 0) {
          window._teachSelected = new Map();
          window._teachCorrectIds = [];
          window._addOnlyMode = 'maybe_deferred';
          document.getElementById('teach-label').textContent = '最も近い候補を1つ選んでください';
          renderTeachCandidates(data.fetishes, {compact: true});
          show('teach-screen');
          return;
        }
        const finalizeData = await apiFetch('/api/finalize_added', {items: []});
        showQuickFeedbackStatus(testPlayMessage(finalizeData || data, 'ありがとうございます。あなたの癖に近いものとして学習しました。'));
      } else if (kind === 'no') {
        setAllItemStates('no');
        const data = await apiFetch('/api/confirm', {
          correct: false,
          fetish_id: window._guessedId,
          compound_ids: window._compoundIds || [],
          maybe_ids: [],
          wrong_ids: ids,
        });
        if (!data) return;
        if (data.fetishes && data.fetishes.length > 0) {
          window._teachSelected = new Map();
          window._teachCorrectIds = [];
          window._addOnlyMode = false;
          document.getElementById('teach-label').textContent = '正解の性癖を選んでください（なければ下から追加できます）';
          renderTeachCandidates(data.fetishes);
          show('teach-screen');
          return;
        }
        const finalizeData = await apiFetch('/api/finalize_added', {items: []});
        showQuickFeedbackStatus(testPlayMessage(finalizeData || data, 'ありがとうございます。外れとして学習し、次の診断に反映します。'));
      }
      lockQuickFeedback();
    } finally {
      setFetching(false);
    }
  }

  function setItemState(id, state, btn) {
    const item = document.getElementById(`ci-${id}`);
    if (!item) return;
    item.dataset.state = state;
    item.className = `confirm-item state-${state}`;
    const btns = item.querySelectorAll('.confirm-toggle button');
    btns.forEach(button => {
      button.className = '';
      button.setAttribute('aria-pressed', 'false');
    });
    btn.className = state === 'yes' ? 'active-yes' : state === 'maybe' ? 'active-maybe' : 'active-no';
    btn.setAttribute('aria-pressed', 'true');
  }

  async function submitConfirm() {
    if (window.gameState?.fetching) return;
    const items = document.querySelectorAll('#confirm-items .confirm-item');
    if (Array.from(items).some(item => !item.dataset.state)) {
      showToast('すべての項目に○△×を選んでください', '#c0392b');
      show('result-screen');
      return;
    }
    setFetching(true);
    try {
      const correctIds = [];
      const maybeIds = [];
      const wrongIds = [];
      items.forEach(item => {
        const id = parseInt(item.dataset.id, 10);
        if (item.dataset.state === 'yes') correctIds.push(id);
        else if (item.dataset.state === 'maybe') maybeIds.push(id);
        else if (item.dataset.state === 'no') wrongIds.push(id);
      });

      const names = correctIds.map(id => {
        const el = document.getElementById(`ci-${id}`);
        return el ? el.querySelector('.confirm-item-name').textContent : '';
      }).filter(Boolean);
      if (window.setConfirmedIds) window.setConfirmedIds(correctIds);
      const data = await apiFetch('/api/confirm', {
        correct: false,
        fetish_id: window._guessedId,
        compound_ids: window._compoundIds || [],
        correct_ids: correctIds,
        maybe_ids: maybeIds,
        wrong_ids: wrongIds,
      });
      if (!data) return;
      if (data.status === 'learned') {
        document.getElementById('done-msg').textContent = testPlayMessage(
          data,
          `✓「${names.join('」「')}」として学習しました！`
        );
        show('done-screen');
        return;
      }
      if (!data.fetishes) return;

      window._teachSelected = new Map();
      window._teachCorrectIds = correctIds;
      if (wrongIds.length === 0 && maybeIds.length > 0) {
        window._addOnlyMode = 'maybe';
        document.getElementById('teach-label').textContent = 'あなたの癖に近いものがあれば選べます（任意）';
      } else {
        window._addOnlyMode = false;
        document.getElementById('teach-label').textContent = '正解の性癖を選んでください（複数選択可）';
      }
      renderTeachCandidates(data.fetishes);
      show('teach-screen');
    } finally {
      setFetching(false);
    }
  }

  function renderTeachCandidates(fetishes, options = {}) {
    const list = document.getElementById('fetish-list');
    list.innerHTML = '';
    const compact = options.compact === true;
    fetishes.forEach((fetish, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'fetish-item';
      button.id = `ti-${fetish.id}`;
      button.setAttribute('aria-pressed', 'false');
      if (compact && index >= 3) button.classList.add('candidate-extra', 'hidden');
      button.innerHTML = `<span>${escapeHtml(fetish.name)}${fetish.prob != null ? ` <span style="color:#888;font-size:0.78em">(${escapeHtml(fetish.prob)}%)</span>` : ''}</span>${fetish.desc ? `<span class="fetish-item-desc">${escapeHtml(fetish.desc)}</span>` : ''}`;
      button.onclick = () => toggleTeachItem(fetish.id, fetish.name, button);
      list.appendChild(button);
    });
    const moreButton = document.getElementById('teach-more-candidates');
    if (moreButton) {
      moreButton.classList.toggle('hidden', !compact || fetishes.length <= 3);
      moreButton.setAttribute('aria-expanded', 'false');
      moreButton.textContent = 'ほかの候補を見る';
    }
    document.getElementById('teach-submit-btn').style.display = '';
    updateTeachSubmitBtn();
  }

  return {resultFeedbackIds, toggleDetailFeedback, quickFeedback, setItemState, submitConfirm};
})();

window._resultFeedbackIds = () => window.HekiFeedback.resultFeedbackIds();
window.toggleDetailFeedback = () => window.HekiFeedback.toggleDetailFeedback();
window.quickFeedback = kind => window.HekiFeedback.quickFeedback(kind);
window.setItemState = (id, state, btn) => window.HekiFeedback.setItemState(id, state, btn);
window.submitConfirm = () => window.HekiFeedback.submitConfirm();
