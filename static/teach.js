window.HekiTeach = (() => {
  function setVisible(id, visible) {
    document.getElementById(id)?.classList.toggle('hidden', !visible);
  }

  function testPlayMessage(data, normalMessage) {
    return data && data.learning_disabled ? '✓ 保存せず確認しました。' : normalMessage;
  }

  async function skipTeach() {
    if (window.gameState?.fetching) return;
    if (window._addOnlyMode === 'add') {
      window._addOnlyMode = false;
      document.getElementById('done-msg').textContent = window._addOnlyDoneMsg || '学習しました！';
      show('done-screen');
    } else if (window._addOnlyMode === 'maybe') {
      setFetching(true);
      try {
        const data = await apiFetch('/api/finalize_added', {items: []});
        if (!data) return;
        window._addOnlyMode = false;
        document.getElementById('done-msg').textContent = testPlayMessage(data, 'あなたの癖に近いものとして学習しました。');
        show('done-screen');
      } finally {
        setFetching(false);
      }
    } else if (window._addOnlyMode === 'maybe_deferred') {
      setFetching(true);
      try {
        const data = await apiFetch('/api/finalize_added', {items: []});
        if (!data) return;
        window._addOnlyMode = false;
        document.getElementById('done-msg').textContent = testPlayMessage(data, '「惜しい」という評価を学習しました。');
        show('done-screen');
      } finally {
        setFetching(false);
      }
    } else {
      setFetching(true);
      try {
        const data = await apiFetch('/api/finalize_added', {items: []});
        if (!data) return;
        window._addOnlyMode = false;
        document.getElementById('done-msg').textContent = testPlayMessage(data, '「違う」という評価を学習しました。');
        show('done-screen');
      } finally {
        setFetching(false);
      }
    }
  }

  function toggleTeachItem(id, name, el) {
    if (window._teachSelected.has(id)) {
      window._teachSelected.delete(id);
      el.classList.remove('selected');
      el.setAttribute('aria-pressed', 'false');
    } else {
      if (window._addOnlyMode === 'maybe_deferred') {
        document.querySelectorAll('#fetish-list .fetish-item.selected').forEach(item => {
          item.classList.remove('selected');
          item.setAttribute('aria-pressed', 'false');
        });
        window._teachSelected.clear();
      }
      window._teachSelected.set(id, name);
      el.classList.add('selected');
      el.setAttribute('aria-pressed', 'true');
    }
    updateTeachSubmitBtn();
  }

  function showMoreCandidates() {
    document.querySelectorAll('#fetish-list .candidate-extra').forEach(item => item.classList.remove('hidden'));
    const button = document.getElementById('teach-more-candidates');
    if (button) {
      button.classList.add('hidden');
      button.setAttribute('aria-expanded', 'true');
    }
  }

  function updateTeachSubmitBtn() {
    const btn = document.getElementById('teach-submit-btn');
    const selectedCount = window._teachSelected ? window._teachSelected.size : 0;
    btn.textContent = selectedCount > 0 ? `${selectedCount}件を学習する` : '候補を選んで学習する';
    btn.disabled = selectedCount === 0;
  }

  async function submitTeach() {
    if (window.gameState?.fetching) return;
    const btn = document.getElementById('teach-submit-btn');
    const previousText = btn ? btn.textContent : '';
    if (btn) btn.textContent = '学習中...';
    setFetching(true);
    try {
      const selected = window._teachSelected || new Map();
      const teachData = await apiFetch('/api/finalize_added', {
        items: [...selected.keys()].map(fid => ({id: fid, is_new: false}))
      });
      if (!teachData) return;
      const correctNames = (window._teachCorrectIds || []).map(id => {
        const el = document.getElementById(`ci-${id}`);
        return el ? el.querySelector('.confirm-item-name').textContent : '';
      }).filter(Boolean);
      const wrongNames = [...selected.values()];
      const allNames = [...correctNames, ...wrongNames];
      window._addedItems = [];
      if (window.setConfirmedIds) window.setConfirmedIds([...selected.keys(), ...(window._teachCorrectIds || [])]);
      const msg = testPlayMessage(teachData, allNames.length > 0
        ? `✓「${allNames.join('」「')}」として学習しました！`
        : '✓ 学習しました！ありがとうございます。');
      document.getElementById('done-msg').textContent = msg;
      window._addOnlyMode = false;
      show('done-screen');
    } finally {
      setFetching(false);
      if (btn && !document.getElementById('teach-screen')?.classList.contains('hidden')) {
        btn.textContent = previousText;
      }
    }
  }

  async function addFetishStep1() {
    if (window.gameState?.fetching) return;
    const name = document.getElementById('new-fetish-name').value.trim();
    if (!name) { alert('名前を入力してください'); return; }
    setFetching(true);
    try {
      const data = await apiFetch('/api/add_fetish', {name});
      if (data.status === 'similar') {
        const list = document.getElementById('add-similar-list');
        list.innerHTML = '';
        data.candidates.forEach(fetish => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'fetish-item';
          button.textContent = fetish.name;
          button.onclick = () => pickSimilar(fetish.id, fetish.name);
          list.appendChild(button);
        });
        setVisible('add-step1', false);
        setVisible('add-step-similar', true);
      } else if (data.status === 'needs_desc') {
        showDescStep(name);
      } else {
        finishAdd(data);
      }
    } finally {
      setFetching(false);
    }
  }

  function pickSimilar(id, name) {
    finishAdd({fetish_id: id, fetish_name: name, is_new: false});
  }

  function addFetishConfirmNew() {
    const name = document.getElementById('new-fetish-name').value.trim();
    setVisible('add-step-similar', false);
    showDescStep(name);
  }

  function showDescStep(name) {
    document.getElementById('add-confirmed-name').textContent = name;
    document.getElementById('new-fetish-desc').value = '';
    setVisible('add-step1', false);
    setVisible('add-step2', true);
  }

  async function addFetishStep2(skip) {
    if (window.gameState?.fetching) return;
    const name = document.getElementById('new-fetish-name').value.trim();
    const desc = skip ? '' : document.getElementById('new-fetish-desc').value.trim();
    setFetching(true);
    try {
      const data = await apiFetch('/api/add_fetish', {name, desc, confirmed: true});
      finishAdd(data);
    } finally {
      setFetching(false);
    }
  }

  function finishAdd(data) {
    if (!window._addedItems) window._addedItems = [];
    window._addedItems.push({id: data.fetish_id, name: data.fetish_name, is_new: !!data.is_new});

    setVisible('add-step1', false);
    setVisible('add-step-similar', false);
    setVisible('add-step2', false);
    document.getElementById('new-fetish-name').value = '';

    if (window._addedItems.length < 3) {
      renderAddedList();
      setVisible('add-step-more', true);
      setVisible('add-skip-btn', false);
    } else {
      addFetishDone();
    }
  }

  function renderAddedList() {
    const container = document.getElementById('add-added-list');
    container.innerHTML = '';
    (window._addedItems || []).forEach(item => {
      const row = document.createElement('div');
      row.className = 'teach-added-row';
      const name = document.createElement('span');
      name.className = 'teach-added-name';
      name.textContent = `✓ ${item.name}`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'teach-added-delete';
      btn.setAttribute('aria-label', `${item.name}を取り消す`);
      btn.textContent = '×';
      btn.onclick = () => deleteAddedItem(item.id);
      row.append(name, btn);
      container.appendChild(row);
    });
  }

  async function deleteAddedItem(id) {
    if (window.gameState?.fetching) return;
    setFetching(true);
    try {
      const item = (window._addedItems || []).find(candidate => candidate.id === id);
      if (item && item.is_new) {
        const res = await fetch(`/api/fetish/${id}`, {method: 'DELETE'});
        if (!res.ok && res.status !== 404) {
          showToast('削除に失敗しました', '#c0392b'); return;
        }
      }
      window._addedItems = (window._addedItems || []).filter(candidate => candidate.id !== id);
      if (window._addedItems.length === 0) {
        setVisible('add-step-more', false);
        setVisible('add-step1', true);
        setVisible('add-skip-btn', true);
      } else {
        renderAddedList();
      }
    } finally {
      setFetching(false);
    }
  }

  function addFetishMore() {
    setVisible('add-step-more', false);
    setVisible('add-step1', true);
    setVisible('add-skip-btn', true);
  }

  async function addFetishDone() {
    if (window.gameState?.fetching) return;
    const items = window._addedItems || [];
    if (items.length > 0) {
      setFetching(true);
      try {
        var finalizeData = await apiFetch('/api/finalize_added', {
          items: items.map(item => ({id: item.id, is_new: item.is_new}))
        });
      } finally {
        setFetching(false);
      }
    }
    window._addedItems = [];
    setVisible('add-step-more', false);
    setVisible('add-step1', true);
    setVisible('add-skip-btn', true);
    const names = items.map(item => item.name);
    if (window.setConfirmedIds) window.setConfirmedIds(items.map(item => item.id));
    document.getElementById('done-msg').textContent = testPlayMessage(finalizeData, `✓「${names.join('」「')}」を学習しました！`);
    show('done-screen');
  }

  return {
    skipTeach,
    toggleTeachItem,
    updateTeachSubmitBtn,
    submitTeach,
    addFetishStep1,
    pickSimilar,
    addFetishConfirmNew,
    addFetishStep2,
    addFetishMore,
    addFetishDone,
    deleteAddedItem,
    showMoreCandidates,
  };
})();

window.skipTeach = () => window.HekiTeach.skipTeach();
window.toggleTeachItem = (id, name, el) => window.HekiTeach.toggleTeachItem(id, name, el);
window.updateTeachSubmitBtn = () => window.HekiTeach.updateTeachSubmitBtn();
window.submitTeach = () => window.HekiTeach.submitTeach();
window.addFetishStep1 = () => window.HekiTeach.addFetishStep1();
window.pickSimilar = (id, name) => window.HekiTeach.pickSimilar(id, name);
window.addFetishConfirmNew = () => window.HekiTeach.addFetishConfirmNew();
window.addFetishStep2 = skip => window.HekiTeach.addFetishStep2(skip);
window.addFetishMore = () => window.HekiTeach.addFetishMore();
window.addFetishDone = () => window.HekiTeach.addFetishDone();
window.showMoreCandidates = () => window.HekiTeach.showMoreCandidates();
