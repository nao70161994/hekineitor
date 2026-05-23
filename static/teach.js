window.HekiTeach = (() => {
  function testPlayMessage(data, normalMessage) {
    return data && data.learning_disabled ? '✓ 保存せず確認しました。' : normalMessage;
  }

  async function skipTeach() {
    if (window._addOnlyMode === 'add') {
      window._addOnlyMode = false;
      document.getElementById('done-msg').textContent = window._addOnlyDoneMsg || '学習しました！';
      show('done-screen');
    } else if (window._addOnlyMode === 'maybe') {
      window._addOnlyMode = false;
      const data = await apiFetch('/api/finalize_added', {items: []});
      document.getElementById('done-msg').textContent = testPlayMessage(data, '近い候補として学習しました。');
      show('done-screen');
    } else {
      showStart();
    }
  }

  function toggleTeachItem(id, name, el) {
    if (window._teachSelected.has(id)) {
      window._teachSelected.delete(id);
      el.classList.remove('selected');
    } else {
      window._teachSelected.set(id, name);
      el.classList.add('selected');
    }
    updateTeachSubmitBtn();
  }

  function updateTeachSubmitBtn() {
    const btn = document.getElementById('teach-submit-btn');
    const selectedCount = window._teachSelected ? window._teachSelected.size : 0;
    btn.textContent = selectedCount > 0 ? `${selectedCount}件を学習する` : '選んで学習する';
    btn.disabled = selectedCount === 0;
  }

  async function submitTeach() {
    if (window.gameState?.fetching) return;
    setFetching(true);
    try {
      const selected = window._teachSelected || new Map();
      const teachData = await apiFetch('/api/finalize_added', {
        items: [...selected.keys()].map(fid => ({id: fid, is_new: false}))
      });
      const correctNames = (window._teachCorrectIds || []).map(id => {
        const el = document.getElementById(`ci-${id}`);
        return el ? el.querySelector('.confirm-item-name').textContent : '';
      }).filter(Boolean);
      const wrongNames = [...selected.values()];
      const allNames = [...correctNames, ...wrongNames];
      window._addedItems = [];
      if (window.setLastFetishName) window.setLastFetishName(allNames.join(' × '));
      const msg = testPlayMessage(teachData, allNames.length > 0
        ? `✓「${allNames.join('」「')}」として学習しました！`
        : '✓ 学習しました！ありがとうございます。');
      document.getElementById('done-msg').textContent = msg;
      window._addOnlyMode = false;
      show('done-screen');
    } finally {
      setFetching(false);
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
          const div = document.createElement('div');
          div.className = 'fetish-item';
          div.textContent = fetish.name;
          div.onclick = () => pickSimilar(fetish.id, fetish.name);
          list.appendChild(div);
        });
        document.getElementById('add-step1').style.display = 'none';
        document.getElementById('add-step-similar').style.display = '';
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
    document.getElementById('add-step-similar').style.display = 'none';
    showDescStep(name);
  }

  function showDescStep(name) {
    document.getElementById('add-confirmed-name').textContent = name;
    document.getElementById('new-fetish-desc').value = '';
    document.getElementById('add-step1').style.display = 'none';
    document.getElementById('add-step2').style.display = '';
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

    document.getElementById('add-step1').style.display = 'none';
    document.getElementById('add-step-similar').style.display = 'none';
    document.getElementById('add-step2').style.display = 'none';
    document.getElementById('new-fetish-name').value = '';

    if (window._addedItems.length < 3) {
      renderAddedList();
      document.getElementById('add-step-more').style.display = '';
      document.getElementById('add-skip-btn').style.display = 'none';
    } else {
      addFetishDone();
    }
  }

  function renderAddedList() {
    const container = document.getElementById('add-added-list');
    container.innerHTML = '';
    (window._addedItems || []).forEach(item => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:4px;';
      const name = document.createElement('span');
      name.style.cssText = 'flex:1;font-size:0.82rem;color:#27ae60;';
      name.textContent = `✓ ${item.name}`;
      const btn = document.createElement('button');
      btn.style.cssText = 'background:none;border:1px solid #555;color:#888;border-radius:4px;padding:2px 8px;font-size:0.75rem;cursor:pointer;';
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
        document.getElementById('add-step-more').style.display = 'none';
        document.getElementById('add-step1').style.display = '';
        document.getElementById('add-skip-btn').style.display = '';
      } else {
        renderAddedList();
      }
    } finally {
      setFetching(false);
    }
  }

  function addFetishMore() {
    document.getElementById('add-step-more').style.display = 'none';
    document.getElementById('add-step1').style.display = '';
    document.getElementById('add-skip-btn').style.display = '';
  }

  async function addFetishDone() {
    if (window.gameState?.fetching) return;
    const items = window._addedItems || [];
    window._addedItems = [];
    document.getElementById('add-step-more').style.display = 'none';
    document.getElementById('add-step1').style.display = '';
    document.getElementById('add-skip-btn').style.display = '';
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
    const names = items.map(item => item.name);
    if (window.setLastFetishName) window.setLastFetishName(names.join(' × '));
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
