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
          maybe_ids: ids,
          wrong_ids: [],
        });
        if (!data) return;
        const finalizeData = await apiFetch('/api/finalize_added', {items: []});
        showQuickFeedbackStatus(testPlayMessage(finalizeData || data, 'ありがとうございます。近い結果として学習しました。'));
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
    btns.forEach(button => { button.className = ''; });
    btn.className = state === 'yes' ? 'active-yes' : state === 'maybe' ? 'active-maybe' : 'active-no';
  }

  async function submitConfirm() {
    const items = document.querySelectorAll('#confirm-items .confirm-item');
    if (Array.from(items).some(item => !item.dataset.state)) {
      showToast('すべての項目に○△×を選んでください', '#c0392b');
      show('result-screen');
      return;
    }
    const correctIds = [];
    const maybeIds = [];
    const wrongIds = [];
    items.forEach(item => {
      const id = parseInt(item.dataset.id);
      if (item.dataset.state === 'yes') correctIds.push(id);
      else if (item.dataset.state === 'maybe') maybeIds.push(id);
      else if (item.dataset.state === 'no') wrongIds.push(id);
    });

    if (correctIds.length > 0) {
      for (const fid of correctIds) {
        await apiFetch('/api/teach', {fetish_id: fid, total_n: correctIds.length});
      }
    }

    const hasWrong = wrongIds.length > 0 || maybeIds.length > 0;
    if (!hasWrong) {
      const names = correctIds.map(id => {
        const el = document.getElementById(`ci-${id}`);
        return el ? el.querySelector('.confirm-item-name').textContent : '';
      }).filter(Boolean);
      if (window.setLastFetishName) window.setLastFetishName(names.join(' × '));
      const addData = await apiFetch('/api/confirm', {
        correct: false,
        fetish_id: window._guessedId,
        compound_ids: window._compoundIds || [],
        add_only: true,
      });
      if (!addData || !addData.fetishes) {
        document.getElementById('done-msg').textContent = testPlayMessage(addData, `✓「${names.join('」「')}」として学習しました！`);
        show('done-screen');
        return;
      }
      window._teachSelected = new Map();
      window._teachCorrectIds = correctIds;
      window._addOnlyMode = 'add';
      window._addOnlyDoneMsg = testPlayMessage(addData, `✓「${names.join('」「')}」として学習しました！`);
      document.getElementById('teach-label').textContent = '他に該当する性癖があれば追加できます（任意）';
      renderTeachCandidates(addData.fetishes);
      show('teach-screen');
      return;
    }

    const data = await apiFetch('/api/confirm', {
      correct: false,
      fetish_id: window._guessedId,
      compound_ids: window._compoundIds || [],
      maybe_ids: maybeIds,
      wrong_ids: wrongIds,
    });
    if (!data || !data.fetishes) return;

    window._teachSelected = new Map();
    window._teachCorrectIds = correctIds;
    if (wrongIds.length === 0 && maybeIds.length > 0) {
      window._addOnlyMode = 'maybe';
      document.getElementById('teach-label').textContent = '正解の性癖があれば選べます（任意）';
    } else {
      window._addOnlyMode = false;
      document.getElementById('teach-label').textContent = '正解の性癖を選んでください（複数選択可）';
    }
    renderTeachCandidates(data.fetishes);
    show('teach-screen');
  }

  function renderTeachCandidates(fetishes) {
    const list = document.getElementById('fetish-list');
    list.innerHTML = '';
    fetishes.forEach(fetish => {
      const div = document.createElement('div');
      div.className = 'fetish-item';
      div.id = `ti-${fetish.id}`;
      div.innerHTML = `<span>${escapeHtml(fetish.name)}${fetish.prob != null ? ` <span style="color:#888;font-size:0.78em">(${escapeHtml(fetish.prob)}%)</span>` : ''}</span>${fetish.desc ? `<div style="font-size:0.72rem;color:#666;margin-top:2px;">${escapeHtml(fetish.desc)}</div>` : ''}`;
      div.onclick = () => toggleTeachItem(fetish.id, fetish.name, div);
      list.appendChild(div);
    });
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
