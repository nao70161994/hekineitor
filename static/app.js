const AMAZON_ASSOCIATE_ID = window.APP_CONFIG?.amazonAssociateId || '';
let currentQ = null;
let lastFetishName = '';
let _diagnosedName = '';

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

function safeExternalUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(String(value), window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function show(id) {
  ['start-screen','question-screen','result-screen','teach-screen','done-screen']
    .forEach(s => {
      const el = document.getElementById(s);
      el.classList.add('hidden');
      el.classList.remove('screen-in');
    });
  const target = document.getElementById(id);
  target.classList.remove('hidden');
  void target.offsetWidth;
  target.classList.add('screen-in');
  if (id === 'result-screen' || id === 'done-screen') _updateExcludeButtons();
}

function setGenieState(state) {
  const g = document.getElementById('genie');
  g.classList.remove('thinking', 'reveal');

  const smirk  = document.getElementById('mouth-smirk');
  const think  = document.getElementById('mouth-think');
  const reveal = document.getElementById('mouth-reveal');
  const arm    = document.getElementById('arm-think');
  const browL  = document.getElementById('brow-l');
  const browR  = document.getElementById('brow-r');

  smirk.setAttribute('opacity',  '0');
  think.setAttribute('opacity',  '0');
  reveal.setAttribute('opacity', '0');
  arm.setAttribute('opacity',    '0');
  browL.setAttribute('d', 'M37,53 Q47,48 56,53');
  browR.setAttribute('d', 'M64,53 Q73,48 83,53');

  if (state === 'thinking') {
    g.classList.add('thinking');
    think.setAttribute('opacity', '1');
    arm.setAttribute('opacity', '1');
    // 片眉を上げて考え顔
    browL.setAttribute('d', 'M37,55 Q47,50 56,55');
    browR.setAttribute('d', 'M64,50 Q73,45 83,50');
  } else if (state === 'reveal') {
    g.classList.add('reveal');
    reveal.setAttribute('opacity', '1');
    // 両眉をつり上げてニタァ顔
    browL.setAttribute('d', 'M36,50 Q47,44 56,50');
    browR.setAttribute('d', 'M64,50 Q73,44 84,50');
  } else {
    smirk.setAttribute('opacity', '1');
  }
}

function showStart() {
  if (window._excludedIds && window._excludedIds.length > 0) {
    showToast(`除外リスト (${window._excludedIds.length}件) をリセットしました`, '#555', 2500);
  }
  window._excludedIds = [];
  show('start-screen');
  setGenieState('idle');
  _checkDraft();
}

function showSessionExpired() {
  showToast('セッションが切れました。もう一度スタートしてください。', '#7f8c8d', 8000);
  show('start-screen');
  setGenieState('idle');
}

async function skipTeach() {
  if (window._addOnlyMode === 'add') {
    // 全正解スキップ → 負学習なし
    window._addOnlyMode = false;
    document.getElementById('done-msg').textContent = window._addOnlyDoneMsg || '学習しました！';
    show('done-screen');
  } else if (window._addOnlyMode === 'maybe') {
    // △スキップ → 近い候補として記録し、候補の弱い負学習だけ走らせる
    window._addOnlyMode = false;
    await apiFetch('/api/finalize_added', {items: []});
    document.getElementById('done-msg').textContent = '近い候補として学習しました。';
    show('done-screen');
  } else {
    showStart();
  }
}

function confirmRestart() {
  const n = window._excludedIds && window._excludedIds.length;
  const modal = document.getElementById('modal-restart');
  modal.querySelector('p').innerHTML = n > 0
    ? `最初からやり直しますか？<br>進行状況と除外リスト（${n}件）は失われます。`
    : '最初からやり直しますか？<br>現在の進行状況は失われます。';
  modal.classList.remove('hidden');
}
function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}
function doRestart() {
  closeModal('modal-restart');
  showStart();
}

function showToast(msg, color, durationMs = 3000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color || '#e67e22';
  t.classList.remove('hidden');
  clearTimeout(t._hideTimer);
  t._hideTimer = setTimeout(() => t.classList.add('hidden'), durationMs);
}

let _fetching = false;

async function apiFetch(url, body, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    const msg = e.name === 'AbortError'
      ? 'サーバーへの接続がタイムアウトしました。しばらくしてから再試行してください。'
      : '通信エラーが発生しました。リロードしてください。';
    showToast(msg, '#c0392b');
    throw new Error('network');
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 440) {
    showSessionExpired();
    throw new Error('session_expired');
  }
  if (!res.ok) {
    let msg = `サーバーエラー (${res.status})`;
    try { const e = await res.json(); if (e.message) msg = e.message; } catch {}
    showToast(msg, '#c0392b');
    throw new Error(msg);
  }
  return await res.json();
}

function setAnswerButtons(disabled) {
  document.querySelectorAll('#question-screen .btn').forEach(b => b.disabled = disabled);
}

function _updateExcludeButtons() {
  const n = (window._excludedIds || []).length;
  const label = n > 0 ? `別の性癖を探す (${n}件除外済み) →` : '別の性癖を探す →';
  document.querySelectorAll('.btn-exclude').forEach(b => b.textContent = label);
}

function startExcluding() {
  // 現在診断済みの性癖IDを除外してゲームを再スタート
  const excludeIds = window._excludedIds ? [...window._excludedIds] : [];
  if (window._guessedId != null) excludeIds.push(window._guessedId);
  (window._compoundIds || []).forEach(id => excludeIds.push(id));
  window._excludedIds = [...new Set(excludeIds)];
  startGame(window._excludedIds);
}

async function startGame(excludeIds) {
  _clearDraft();
  document.getElementById('resume-banner').classList.add('hidden');
  const btn = document.querySelector('.btn-start');
  const origText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '起動中...'; }
  const wakeTimer = setTimeout(() => {
    showToast('サーバーを起動中です。少々お待ちください…', '#555', 25000);
  }, 3000);
  const body = excludeIds && excludeIds.length ? {exclude_ids: excludeIds} : undefined;
  try {
    const data = await apiFetch('/api/start', body, 45000);
    clearTimeout(wakeTimer);
    if (excludeIds && excludeIds.length) {
      showToast(`${excludeIds.length}件の性癖を除外して診断します`, '#1a4a8a', 3000);
    }
    showQuestion(data);
  } catch {
    clearTimeout(wakeTimer);
    if (btn) { btn.disabled = false; btn.textContent = origText; }
  }
}

const _axisLabels = {content: 'コンテンツ軸', abstract: '抽象軸', personality: 'パーソナリティ軸'};
function showQuestion(data) {
  currentQ = data.question_id;
  document.getElementById('question-text').textContent = data.question;
  const focusHint = data.hint || '';
  const qHint = data.q_hint || '';
  document.getElementById('question-hint').textContent = focusHint || qHint;
  const axisEl = document.getElementById('question-axis-tag');
  if (data.axis && _axisLabels[data.axis]) {
    axisEl.textContent = _axisLabels[data.axis];
    axisEl.className = 'axis-tag ' + data.axis;
    axisEl.style.display = '';
  } else {
    axisEl.style.display = 'none';
  }
  const pct = Math.round((data.count / data.total) * 100);
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('btn-back').style.visibility = data.count > 0 ? 'visible' : 'hidden';
  show('question-screen');
  setGenieState('thinking');
  const contEl = document.getElementById('contradiction-hint');
  if (data.contradictions && data.contradictions.length) {
    const c = data.contradictions[0];
    const ansTxt = {1:'はい', 0.5:'どちらかといえばはい', '-0.5':'どちらかといえばいいえ', '-1':'いいえ'};
    contEl.textContent = `💡「${c.q1}→${ansTxt[c.a1]}」と「${c.q2}→${ansTxt[c.a2]}」は矛盾しているかもしれません`;
    contEl.classList.remove('hidden');
  } else {
    contEl.classList.add('hidden');
  }
}

async function goBack() {
  if (_fetching) return;
  _fetching = true;
  const backBtn = document.getElementById('btn-back');
  if (backBtn) backBtn.disabled = true;
  try {
    const data = await apiFetch('/api/back');
    if (data.status === 'no_history') return;
    showQuestion(data);
  } finally {
    _fetching = false;
    if (backBtn) backBtn.disabled = false;
    setAnswerButtons(false);
  }
}

async function sendAnswer(ans) {
  if (_fetching) return;
  _fetching = true;
  setAnswerButtons(true);
  try {
    const data = await apiFetch('/api/answer', {question_id: currentQ, answer: ans});
    if (data.action === 'question') {
      _draftPairs.push({q_id: currentQ, answer: ans});
      _saveDraft();
      showQuestion(data);
    } else {
      _clearDraft();
      showGuess(data);
    }
  } finally {
    _fetching = false;
    setAnswerButtons(false);
  }
}

function showGuess(data) {
  setGenieState('reveal');
  window._guessedId   = data.fetish_id;
  window._compoundIds = (data.compound || []).map(c => c.fetish_id);
  window._guessData   = data;

  if (data.compound && data.compound.length > 0) {
    const names = [data.fetish_name, ...data.compound.map(c => c.fetish_name)];
    document.getElementById('result-name').textContent = names.join(' × ');
    lastFetishName = names.join(' × ');
  } else {
    document.getElementById('result-name').textContent = data.fetish_name;
    lastFetishName = data.fetish_name;
  }
  _diagnosedName = lastFetishName;
  document.getElementById('result-desc').textContent = data.fetish_desc;
  // 詳細ページリンク
  const existingLink = document.getElementById('fetish-detail-link');
  if (existingLink) existingLink.remove();
  if (data.fetish_id != null) {
    const dl = document.createElement('a');
    dl.id = 'fetish-detail-link';
    dl.className = 'fetish-detail-link';
    dl.href = `/fetish/${data.fetish_id}`;
    dl.target = '_blank';
    dl.textContent = '📖 この性癖の詳細ページ';
    document.getElementById('result-desc').after(dl);
  }
  // 自信度に応じて結果カードの枠線を変える
  const card = document.getElementById('result-screen')?.closest('.card');
  if (card) {
    const p = data.probability;
    if (p >= 75) {
      card.style.boxShadow = '0 0 24px rgba(245,166,35,0.45), 0 8px 32px rgba(0,0,0,0.4)';
      card.style.border = '1.5px solid rgba(245,166,35,0.6)';
    } else if (p >= 50) {
      card.style.boxShadow = '0 0 16px rgba(233,69,96,0.25), 0 8px 32px rgba(0,0,0,0.4)';
      card.style.border = '1.5px solid rgba(233,69,96,0.35)';
    } else {
      card.style.boxShadow = '0 8px 32px rgba(0,0,0,0.4)';
      card.style.border = '1.5px solid rgba(255,255,255,0.08)';
    }
  }
  const probEl  = document.getElementById('result-prob');
  const target  = data.probability;
  let current   = 0;
  const step    = Math.max(1, Math.round(target / 30));
  const timer   = setInterval(() => {
    current = Math.min(current + step, target);
    probEl.textContent = `一致度: ${current}%`;
    if (current >= target) clearInterval(timer);
  }, 30);

  // 確率バーグラフ（上位5件）
  const chartEl = document.getElementById('top-chart');
  if (data.top_chart && data.top_chart.length > 1) {
    const maxP = data.top_chart[0].probability;
    chartEl.innerHTML = data.top_chart.map((item, i) => {
      const targetW = Math.round(item.probability / maxP * 100);
      const bg = i === 0 ? 'linear-gradient(90deg,#e94560,#f5a623)' : '#1a4a8a';
      return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <div style="width:90px;font-size:0.72rem;color:${i===0?'#e94560':'#888'};text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(item.fetish_name)}</div>
        <div style="flex:1;background:#0f3460;border-radius:3px;height:10px;overflow:hidden;">
          <div class="chart-bar" data-w="${targetW}" style="height:100%;border-radius:3px;width:0%;background:${bg};transition:width 0.6s ease;"></div>
        </div>
        <div style="width:38px;font-size:0.72rem;color:#aaa;">${escapeHtml(item.probability)}%</div>
      </div>`;
    }).join('');
    requestAnimationFrame(() => {
      chartEl.querySelectorAll('.chart-bar').forEach(el => {
        el.style.width = el.dataset.w + '%';
      });
    });
  } else {
    chartEl.innerHTML = '';
  }

  // 項目ごとの正誤ボタンを生成
  const items = [{fetish_id: data.fetish_id, fetish_name: data.fetish_name, probability: data.probability}];
  (data.compound || []).forEach(c => items.push(c));
  const container = document.getElementById('confirm-items');
  container.innerHTML = items.map(item => `
    <div class="confirm-item" id="ci-${Number.parseInt(item.fetish_id, 10)}" data-id="${Number.parseInt(item.fetish_id, 10)}" data-state="">
      <span class="confirm-item-name">${escapeHtml(item.fetish_name)}</span>
      <span class="confirm-item-prob">${escapeHtml(item.probability)}%</span>
      <div class="confirm-toggle">
        <button data-action="set-item-state" data-id="${Number.parseInt(item.fetish_id, 10)}" data-state="yes">○</button>
        <button data-action="set-item-state" data-id="${Number.parseInt(item.fetish_id, 10)}" data-state="maybe">△</button>
        <button data-action="set-item-state" data-id="${Number.parseInt(item.fetish_id, 10)}" data-state="no">×</button>
      </div>
    </div>`).join('');

  const profileSection = document.getElementById('profile-section');
  const profileList    = document.getElementById('profile-list');
  if (data.profile && data.profile.length > 0) {
    profileList.innerHTML = data.profile.map(r =>
      `<div class="profile-item">${escapeHtml(r.fetish_name)}<span>${escapeHtml(r.probability)}%</span></div>`
    ).join('');
    profileSection.classList.remove('hidden');
  } else {
    profileSection.classList.add('hidden');
  }

  const relatedSection = document.getElementById('related-section');
  const relatedTags    = document.getElementById('related-tags');
  if (data.related && data.related.length > 0) {
    relatedTags.innerHTML = data.related.map(r =>
      `<a class="related-tag" href="/fetish/${Number.parseInt(r.fetish_id, 10)}" target="_blank" rel="noopener">${escapeHtml(r.fetish_name)}</a>`
    ).join('');
    relatedSection.classList.remove('hidden');
  } else {
    relatedSection.classList.add('hidden');
  }

  // 「すぐ再挑戦」ボタン: excludedIdsが存在するか、今回の診断IDがあれば表示
  const retryBtn = document.getElementById('btn-quick-retry');
  const allExcluded = [...(window._excludedIds || []), data.fetish_id,
                        ...(data.compound || []).map(c => c.fetish_id)];
  retryBtn.style.display = allExcluded.length > 0 ? '' : 'none';

  // 機能1: なぜこの結果に？
  const reasonsSec = document.getElementById('reasons-section');
  if (data.reasons && data.reasons.length) {
    const ansTxt = {1:'はい', 0.5:'どちらかといえばはい', '-0.5':'どちらかといえばいいえ', '-1':'いいえ'};
    document.getElementById('reasons-list').innerHTML = data.reasons.map(r =>
      `<div class="reason-item"><span>${escapeHtml(r.text)}</span><span class="ans-badge">${escapeHtml(ansTxt[r.ans] || r.ans)}</span></div>`
    ).join('');
    reasonsSec.classList.remove('hidden');
  } else {
    reasonsSec.classList.add('hidden');
  }

  // 機能7: 作品レコメンド（複合診断時は複合特化作品を優先表示、URLありはリンク）
  const worksSec   = document.getElementById('works-section');
  const worksLabel = document.getElementById('works-label');
  const crossTagsEl = document.getElementById('cross-works-tags');
  const isCompound = data.compound && data.compound.length > 0;
  const hasCross   = data.cross_works && data.cross_works.length > 0;
  const hasWorks   = data.works && data.works.length > 0;

  function renderWorkTag(w, extraClass = '') {
    const title = (typeof w === 'object' && w !== null) ? w.title : w;
    let url = (typeof w === 'object' && w !== null && w.url) ? w.url : null;
    // URLが未設定でもAMAZON_ASSOCIATE_IDがあれば検索URLを自動生成
    // 検索キーワードは括弧（補足メモ）を除去してタイトルのみにする
    if (!url && AMAZON_ASSOCIATE_ID) {
      const searchTitle = title.replace(/[（(][^）)]*[）)]/g, '').trim();
      url = `https://www.amazon.co.jp/s?k=${encodeURIComponent(searchTitle)}&tag=${encodeURIComponent(AMAZON_ASSOCIATE_ID)}`;
    }
    const cls = ['works-tag', extraClass, url ? 'link' : ''].filter(Boolean).join(' ');
    const safeUrl = safeExternalUrl(url);
    if (safeUrl) {
      return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener sponsored" class="${escapeHtml(cls)}">${escapeHtml(title)}</a>`;
    }
    return `<span class="${escapeHtml(cls)}">${escapeHtml(title)}</span>`;
  }

  if (hasCross || hasWorks) {
    worksLabel.textContent = isCompound ? 'これらの性癖が好きな方へ' : 'この性癖が好きな方へ';

    crossTagsEl.innerHTML = hasCross
      ? `<div class="works-cross-label">▶ 両方の要素を持つ作品</div>` +
        data.cross_works.map(w => renderWorkTag(w, 'cross')).join('')
      : '';

    document.getElementById('works-tags').innerHTML = hasWorks
      ? (hasCross ? '<div class="works-cross-label">▶ それぞれの関連作品</div>' : '') +
        data.works.map(w => renderWorkTag(w)).join('')
      : '';

    worksSec.classList.remove('hidden');
  } else {
    worksSec.classList.add('hidden');
  }

  // 機能3: 診断履歴に保存
  saveHistory(data.fetish_name, data.probability, data.fetish_id);

  show('result-screen');
}

async function quickRetry() {
  const excludeIds = [
    ...(window._excludedIds || []),
    window._guessedId,
    ...(window._compoundIds || []),
  ].filter(id => id != null);
  window._excludedIds = [...new Set(excludeIds)];
  await startGame(window._excludedIds);
}

function setItemState(id, state, btn) {
  const item = document.getElementById(`ci-${id}`);
  item.dataset.state = state;
  item.className = `confirm-item state-${state}`;
  const btns = item.querySelectorAll('.confirm-toggle button');
  btns.forEach(b => b.className = '');
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
  const maybeIds   = [];
  const wrongIds   = [];
  items.forEach(item => {
    const id = parseInt(item.dataset.id);
    if      (item.dataset.state === 'yes')   correctIds.push(id);
    else if (item.dataset.state === 'maybe') maybeIds.push(id);
    else if (item.dataset.state === 'no')    wrongIds.push(id);
  });

  // ○がついた項目を即学習（total_n で√n スケーリング）
  if (correctIds.length > 0) {
    for (const fid of correctIds) {
      await apiFetch('/api/teach', {fetish_id: fid, total_n: correctIds.length});
    }
  }

  const hasWrong = wrongIds.length > 0 || maybeIds.length > 0;
  if (!hasWrong) {
    // 全部正解
    const names = correctIds.map(id => {
      const el = document.getElementById(`ci-${id}`);
      return el ? el.querySelector('.confirm-item-name').textContent : '';
    }).filter(Boolean);
    lastFetishName = names.join(' × ');
    // 全部正解でも追加選択を許可
    const addData = await apiFetch('/api/confirm', {correct: false, fetish_id: window._guessedId, compound_ids: window._compoundIds || [], add_only: true});
    if (!addData || !addData.fetishes) {
      document.getElementById('done-msg').textContent = `✓「${names.join('」「')}」として学習しました！`;
      show('done-screen');
      return;
    }
    window._teachSelected = new Map();
    window._teachCorrectIds = correctIds;
    window._addOnlyMode = 'add';
    window._addOnlyDoneMsg = `✓「${names.join('」「')}」として学習しました！`;
    document.getElementById('teach-label').textContent = '他に該当する性癖があれば追加できます（任意）';
    const list = document.getElementById('fetish-list');
    list.innerHTML = '';
    addData.fetishes.forEach(f => {
      const div = document.createElement('div');
      div.className = 'fetish-item';
      div.id = `ti-${f.id}`;
      div.innerHTML = `<span>${escapeHtml(f.name)}${f.prob != null ? ` <span style="color:#888;font-size:0.78em">(${escapeHtml(f.prob)}%)</span>` : ''}</span>${f.desc ? `<div style="font-size:0.72rem;color:#666;margin-top:2px;">${escapeHtml(f.desc)}</div>` : ''}`;
      div.onclick = () => toggleTeachItem(f.id, f.name, div);
      list.appendChild(div);
    });
    document.getElementById('teach-submit-btn').style.display = '';
    updateTeachSubmitBtn();
    show('teach-screen');
    return;
  }

  // 外れ/近い項目をサーバーに記録。×は負学習、△は弱い正学習として扱う。
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

  // △のみ（×なし）→ 任意選択モード
  if (wrongIds.length === 0 && maybeIds.length > 0) {
    window._addOnlyMode = 'maybe';
    document.getElementById('teach-label').textContent = '正解の性癖があれば選べます（任意）';
  } else {
    window._addOnlyMode = false;
    document.getElementById('teach-label').textContent = '正解の性癖を選んでください（複数選択可）';
  }

  const list = document.getElementById('fetish-list');
  list.innerHTML = '';
  data.fetishes.forEach(f => {
    const div = document.createElement('div');
    div.className = 'fetish-item';
    div.id = `ti-${f.id}`;
    div.innerHTML = `<span>${escapeHtml(f.name)}${f.prob != null ? ` <span style="color:#888;font-size:0.78em">(${escapeHtml(f.prob)}%)</span>` : ''}</span>${f.desc ? `<div style="font-size:0.72rem;color:#666;margin-top:2px;">${escapeHtml(f.desc)}</div>` : ''}`;
    div.onclick = () => toggleTeachItem(f.id, f.name, div);
    list.appendChild(div);
  });



  document.getElementById('teach-submit-btn').style.display = '';
  updateTeachSubmitBtn();
  show('teach-screen');
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
  const n = window._teachSelected ? window._teachSelected.size : 0;
  btn.textContent = n > 0 ? `${n}件を学習する` : `選んで学習する`;
  btn.disabled = n === 0;
}

async function submitTeach() {
  if (_fetching) return;
  _fetching = true;
  try {
    const selected = window._teachSelected || new Map();
    await apiFetch('/api/finalize_added', {
      items: [...selected.keys()].map(fid => ({id: fid, is_new: false}))
    });
    const correctNames = (window._teachCorrectIds || []).map(id => {
      const el = document.getElementById(`ci-${id}`);
      return el ? el.querySelector('.confirm-item-name').textContent : '';
    }).filter(Boolean);
    const wrongNames = [...selected.values()];
    const allNames = [...correctNames, ...wrongNames];
    window._addedItems = [];
    lastFetishName = allNames.join(' × ') || lastFetishName;
    const msg = allNames.length > 0
      ? `✓「${allNames.join('」「')}」として学習しました！`
      : '✓ 学習しました！ありがとうございます。';
    document.getElementById('done-msg').textContent = msg;
    window._addOnlyMode = false;
    show('done-screen');
  } finally {
    _fetching = false;
  }
}

async function addFetishStep1() {
  if (_fetching) return;
  const name = document.getElementById('new-fetish-name').value.trim();
  if (!name) { alert('名前を入力してください'); return; }
  _fetching = true;
  try {
    const data = await apiFetch('/api/add_fetish', {name});
    if (data.status === 'similar') {
      const list = document.getElementById('add-similar-list');
      list.innerHTML = '';
      data.candidates.forEach(f => {
        const div = document.createElement('div');
        div.className = 'fetish-item';
        div.textContent = f.name;
        div.onclick = () => pickSimilar(f.id, f.name);
        list.appendChild(div);
      });
      document.getElementById('add-step1').style.display = 'none';
      document.getElementById('add-step-similar').style.display = '';
    } else if (data.status === 'needs_desc') {
      _showDescStep(name);
    } else {
      _finishAdd(data);
    }
  } finally {
    _fetching = false;
  }
}

function pickSimilar(id, name) {
  // 学習は完了時にまとめて行う（既存性癖なので is_new=false）
  _finishAdd({fetish_id: id, fetish_name: name, is_new: false});
}

function addFetishConfirmNew() {
  const name = document.getElementById('new-fetish-name').value.trim();
  document.getElementById('add-step-similar').style.display = 'none';
  _showDescStep(name);
}

function _showDescStep(name) {
  document.getElementById('add-confirmed-name').textContent = name;
  document.getElementById('new-fetish-desc').value = '';
  document.getElementById('add-step1').style.display = 'none';
  document.getElementById('add-step2').style.display = '';
}

async function addFetishStep2(skip) {
  if (_fetching) return;
  const name = document.getElementById('new-fetish-name').value.trim();
  const desc = skip ? '' : document.getElementById('new-fetish-desc').value.trim();
  _fetching = true;
  try {
    const data = await apiFetch('/api/add_fetish', {name, desc, confirmed: true});
    _finishAdd(data);
  } finally {
    _fetching = false;
  }
}

function _finishAdd(data) {
  if (!window._addedItems) window._addedItems = [];
  window._addedItems.push({id: data.fetish_id, name: data.fetish_name, is_new: !!data.is_new});

  document.getElementById('add-step1').style.display = 'none';
  document.getElementById('add-step-similar').style.display = 'none';
  document.getElementById('add-step2').style.display = 'none';
  document.getElementById('new-fetish-name').value = '';

  if (window._addedItems.length < 3) {
    _renderAddedList();
    document.getElementById('add-step-more').style.display = '';
    document.getElementById('add-skip-btn').style.display = 'none';
  } else {
    addFetishDone();
  }
}

function _renderAddedList() {
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
    btn.onclick = () => deleteAddedItem(item.id, item.name);
    row.append(name, btn);
    container.appendChild(row);
  });
}

async function deleteAddedItem(id, name) {
  if (_fetching) return;
  _fetching = true;
  try {
    const item = (window._addedItems || []).find(i => i.id === id);
    // 新規追加分のみDBから削除（既存を選んだだけなら記録から外すだけ）
    if (item && item.is_new) {
      const res = await fetch(`/api/fetish/${id}`, {method: 'DELETE'});
      if (!res.ok && res.status !== 404) {
        showToast('削除に失敗しました', '#c0392b'); return;
      }
    }
    window._addedItems = (window._addedItems || []).filter(item => item.id !== id);
    if (window._addedItems.length === 0) {
      document.getElementById('add-step-more').style.display = 'none';
      document.getElementById('add-step1').style.display = '';
      document.getElementById('add-skip-btn').style.display = '';
    } else {
      _renderAddedList();
    }
  } finally {
    _fetching = false;
  }
}

function addFetishMore() {
  document.getElementById('add-step-more').style.display = 'none';
  document.getElementById('add-step1').style.display = '';
  document.getElementById('add-skip-btn').style.display = '';
}

async function addFetishDone() {
  if (_fetching) return;
  const items = window._addedItems || [];
  window._addedItems = [];
  document.getElementById('add-step-more').style.display = 'none';
  document.getElementById('add-step1').style.display = '';
  document.getElementById('add-skip-btn').style.display = '';
  if (items.length > 0) {
    _fetching = true;
    try {
      await apiFetch('/api/finalize_added', {
        items: items.map(i => ({id: i.id, is_new: i.is_new}))
      });
    } finally {
      _fetching = false;
    }
  }
  const names = items.map(i => i.name);
  lastFetishName = names.join(' × ');
  document.getElementById('done-msg').textContent =
    `✓「${names.join('」「')}」を学習しました！`;
  show('done-screen');
}

function _buildShareText(name, prob, guessData) {
  const compound = guessData.compound && guessData.compound.length > 0;
  const p = parseFloat(prob) || 0;

  // 確率・複合に応じたバリエーション
  let opening;
  if (compound) {
    opening = `へきネイターで診断したら複合性癖「${name}」だった。情報量が多い`;
  } else if (p >= 90) {
    opening = `へきネイターに性癖を完全に見破られた: ${name} ${prob}%`;
  } else if (p >= 75) {
    opening = `へきネイターで診断したら「${name}」だった。これ当たってる？ ${prob}%`;
  } else if (p >= 50) {
    opening = `へきネイターの診断結果は「${name}」。否定しきれない ${prob}%`;
  } else {
    opening = `へきネイターに「${name}」って言われた。これは当たってる？`;
  }
  return opening;
}

function shareResult() {
  const origin    = window.location.origin;
  const guessData = window._guessData || {};
  const name = _diagnosedName;
  const prob = guessData.probability || '';
  const desc = (guessData.fetish_desc || '').slice(0, 80);
  const shareUrl = `${origin}/r?f=${encodeURIComponent(name)}&p=${prob}&d=${encodeURIComponent(desc)}`;
  const opening  = _buildShareText(name, prob, guessData);
  const text = `${opening}\n#へきネイター`;
  if (navigator.share) {
    navigator.share({title: `私の性癖は「${name}」`, text, url: shareUrl}).catch(() => {});
    return;
  }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(`${text}\n${shareUrl}`).then(() => showToast('クリップボードにコピーしました', '#27ae60'));
  }
  window.open(
    'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(shareUrl),
    '_blank',
    'noopener'
  );
}
// インストール促進
let deferredPrompt = null;
const banner = document.getElementById('install-banner');

function dismissInstall() {
  banner.classList.add('hidden');
  localStorage.setItem('install-dismissed', '1');
}

// Android / Chrome: beforeinstallprompt を捕捉（ページロード前でも取りこぼさないよう最上位に登録）
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredPrompt = e;
  if (!localStorage.getItem('install-dismissed')) {
    banner.classList.remove('hidden');
  }
});

document.getElementById('btn-install').onclick = async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    banner.classList.add('hidden');
  } else {
    showToast('ブラウザのメニュー →「ホーム画面に追加」からインストールできます', '#1a4a8a');
    banner.classList.add('hidden');
  }
};

// インストール完了時にバナーを消す
window.addEventListener('appinstalled', () => banner.classList.add('hidden'));

// iOS Safari: スタンドアロンでなければ手順を案内
const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
const isStandalone = window.matchMedia('(display-mode: standalone)').matches;
if (isIos && !isStandalone && !localStorage.getItem('install-dismissed')) {
  document.getElementById('install-msg').textContent =
    'ホーム画面に追加：Safari の 共有ボタン → "ホーム画面に追加"';
  document.getElementById('btn-install').style.display = 'none';
  banner.classList.remove('hidden');
}

// SW登録・更新検知
if ('serviceWorker' in navigator) {
  let swReg = null;

  function showUpdateBanner() {
    const msg = document.getElementById('install-msg');
    const btn = document.getElementById('btn-install');
    const banner = document.getElementById('install-banner');
    msg.textContent = '新しいバージョンがあります';
    btn.textContent = '今すぐ更新';
    btn.onclick = () => {
      if (swReg && swReg.waiting) {
        swReg.waiting.postMessage({ type: 'SKIP_WAITING' });
      }
    };
    banner.classList.remove('hidden');
  }

  // 新SW がアクティブになったらリロード（無限ループ防止フラグ付き）
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!reloading) { reloading = true; location.reload(); }
  });

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(reg => {
      swReg = reg;

      // 既に waiting 中の SW がある場合（タブを長時間開いていたケース）
      if (reg.waiting) { showUpdateBanner(); return; }

      // 新しい SW がインストールされたとき
      reg.addEventListener('updatefound', () => {
        const newSW = reg.installing;
        newSW.addEventListener('statechange', () => {
          if (newSW.state === 'installed' && navigator.serviceWorker.controller) {
            showUpdateBanner();
          }
        });
      });
    }).catch(() => {});
  });
}

// ── 途中保存・再開 ────────────────────────────────────
const _DRAFT_KEY = 'heki_draft';
let _draftPairs  = [];  // [{q_id, answer}, ...]

function _saveDraft() {
  localStorage.setItem(_DRAFT_KEY, JSON.stringify({pairs: _draftPairs, ts: Date.now()}));
}
function _clearDraft() {
  _draftPairs = [];
  localStorage.removeItem(_DRAFT_KEY);
}
function _checkDraft() {
  try {
    const raw = localStorage.getItem(_DRAFT_KEY);
    if (!raw) return;
    const d = JSON.parse(raw);
    if (!d.pairs || !d.pairs.length) return;
    if (Date.now() - d.ts > 3600 * 1000) { localStorage.removeItem(_DRAFT_KEY); return; }
    _draftPairs = d.pairs;
    document.getElementById('resume-count').textContent = d.pairs.length;
    document.getElementById('resume-banner').classList.remove('hidden');
  } catch {}
}
async function resumeGame() {
  if (_fetching) return;
  const pairs = [..._draftPairs];
  if (!pairs.length) return;
  _fetching = true;
  try {
    const data = await apiFetch('/api/resume', {pairs});
    document.getElementById('resume-banner').classList.add('hidden');
    if (data.action === 'question') {
      _draftPairs = pairs;
      _saveDraft();
      showQuestion(data);
    } else {
      _clearDraft();
      showGuess(data);
    }
  } catch {
    _draftPairs = pairs;
    _saveDraft();
    document.getElementById('resume-banner').classList.remove('hidden');
  } finally {
    _fetching = false;
  }
}
async function continueGame() {
  if (_fetching) return;
  _fetching = true;
  try {
    const data = await apiFetch('/api/continue');
    if (data.action === 'question') {
      showQuestion(data);
    } else {
      showToast('これ以上質問できません', '#7f8c8d');
    }
  } finally {
    _fetching = false;
  }
}

// 機能3: 診断履歴
function saveHistory(name, prob, fetish_id) {
  const h = JSON.parse(localStorage.getItem('heki_history') || '[]');
  h.unshift({name, prob, date: new Date().toLocaleDateString('ja-JP'), fetish_id: fetish_id || null});
  if (h.length > 20) h.pop();
  localStorage.setItem('heki_history', JSON.stringify(h));
  _updateHistoryBadge();
}
function _updateHistoryBadge() {
  const h = JSON.parse(localStorage.getItem('heki_history') || '[]');
  const badge = document.getElementById('history-badge');
  if (!badge) return;
  if (h.length > 0) {
    badge.textContent = h.length;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}
function toggleHistory() {
  const panel = document.getElementById('history-panel');
  if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
  const h = JSON.parse(localStorage.getItem('heki_history') || '[]');
  if (!h.length) {
    panel.innerHTML = '<p style="color:#666;font-size:0.8rem;text-align:center;">まだ診断履歴がありません</p>';
  } else {
    panel.innerHTML = h.map((e, i) => `
      <div class="history-item">
        <strong>${escapeHtml(e.name)}</strong>
        <span class="h-meta">${escapeHtml(e.prob)}% · ${escapeHtml(e.date)}</span>
        <button class="h-retry" data-action="retry-excluding" data-index="${i}" title="この診断を除外して再診断">再診断</button>
      </div>`).join('');
  }
  panel.classList.remove('hidden');
}
function retryExcluding(historyIndex) {
  const h = JSON.parse(localStorage.getItem('heki_history') || '[]');
  const entry = h[historyIndex];
  if (!entry || !entry.fetish_id) { startGame(); return; }
  const excludeIds = [...(window._excludedIds || []), entry.fetish_id];
  window._excludedIds = [...new Set(excludeIds)];
  startGame(window._excludedIds);
  document.getElementById('history-panel').classList.add('hidden');
}

// キーボードショートカット（質問画面表示中のみ有効）
document.addEventListener('keydown', e => {
  if (document.getElementById('question-screen').classList.contains('hidden')) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  const map = {'1': 1, '2': 0.5, '3': 0, '4': -0.5, '5': -1};
  if (map[e.key] !== undefined) {
    e.preventDefault();
    sendAnswer(map[e.key]);
  } else if (e.key === 'Backspace') {
    e.preventDefault();
    goBack();
  }
});

function handleAppAction(el) {
  const action = el.dataset.action;
  if (action === 'start-game') startGame();
  else if (action === 'toggle-history') toggleHistory();
  else if (action === 'resume-game') resumeGame();
  else if (action === 'go-back') goBack();
  else if (action === 'confirm-restart') confirmRestart();
  else if (action === 'send-answer') sendAnswer(parseFloat(el.dataset.answer));
  else if (action === 'submit-confirm') submitConfirm();
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
  else if (action === 'close-modal') closeModal(el.dataset.modalId);
  else if (action === 'do-restart') doRestart();
  else if (action === 'dismiss-install') dismissInstall();
  else if (action === 'set-item-state') setItemState(parseInt(el.dataset.id, 10), el.dataset.state, el);
  else if (action === 'retry-excluding') retryExcluding(parseInt(el.dataset.index, 10));
}

// ページロード時にdraftチェック
document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('click', event => {
    const el = event.target.closest('[data-action]');
    if (!el) return;
    handleAppAction(el);
  });
  _checkDraft();
  _updateHistoryBadge();
});
