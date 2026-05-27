window.HekiGameFlow = (() => {
  let currentQuestionId = null;
  let answeredCount = 0;
  let resultShown = false;
  let dropoffSent = false;
  const axisLabels = {content: 'コンテンツ軸', abstract: '抽象軸', personality: 'パーソナリティ軸'};

function startExcluding() {
  // 現在診断済みの性癖IDを除外してゲームを再スタート
  const excludeIds = window._excludedIds ? [...window._excludedIds] : [];
  if (window._guessedId != null) excludeIds.push(window._guessedId);
  (window._compoundIds || []).forEach(id => excludeIds.push(id));
  (window._confirmedIds || []).forEach(id => excludeIds.push(id));
  if (window.HekiState) window.HekiState.setExcludedIds([...new Set(excludeIds)]);
  else {
    window._excludedIds = [...new Set(excludeIds)];
    if (window.gameState) window.gameState.excludedIds = window._excludedIds;
  }
  startGame(window._excludedIds);
}

async function startGame(excludeIds) {
  _clearDraft();
  answeredCount = 0;
  resultShown = false;
  dropoffSent = false;
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

function showQuestion(data) {
  currentQuestionId = data.question_id;
  answeredCount = Number(data.count || 0);
  resultShown = false;
  if (window.HekiRenderers) {
    window.HekiRenderers.setText('question-text', data.question);
    window.HekiRenderers.setProgressMessage(data.progress_message);
  } else {
    document.getElementById('question-text').textContent = data.question;
    const progressEl = document.getElementById('question-progress-message');
    if (progressEl) {
      progressEl.textContent = data.progress_message || '';
      progressEl.classList.toggle('hidden', !data.progress_message);
    }
  }
  const focusHint = data.hint || '';
  const qHint = data.q_hint || '';
  document.getElementById('question-hint').textContent = focusHint || qHint;
  const axisEl = document.getElementById('question-axis-tag');
  if (data.axis && axisLabels[data.axis]) {
    axisEl.textContent = axisLabels[data.axis];
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
  setFetching(true);
  const backBtn = document.getElementById('btn-back');
  if (backBtn) backBtn.disabled = true;
  try {
    const data = await apiFetch('/api/back');
    if (data.status === 'no_history') return;
    if (window._popDraft) window._popDraft();
    showQuestion(data);
  } finally {
    setFetching(false);
    if (backBtn) backBtn.disabled = false;
    setAnswerButtons(false);
  }
}

async function sendAnswer(ans) {
  if (_fetching) return;
  setFetching(true);
  setAnswerButtons(true);
  try {
    const data = await apiFetch('/api/answer', {question_id: currentQuestionId, answer: ans});
    if (data.action === 'question') {
      _pushDraft(currentQuestionId, ans);
      _saveDraft();
      showQuestion(data);
    } else {
      _clearDraft();
      showGuess(data);
    }
  } finally {
    setFetching(false);
    setAnswerButtons(false);
  }
}

function showGuess(data) {
  resultShown = true;
  setGenieState('reveal');
  window._guessedId = data.fetish_id;
  window._compoundIds = (data.compound || []).map(c => c.fetish_id);
  if (window.setConfirmedIds) window.setConfirmedIds([]);
  else window._confirmedIds = [];
  if (window.HekiState) window.HekiState.setGuessData(data);
  else {
    window._guessData = data;
    if (window.gameState) window.gameState.guessData = data;
  }

  if (window.HekiRenderers?.renderGuess) {
    const renderedName = window.HekiRenderers.renderGuess(data, {
      escapeHtml,
      safeExternalUrl,
      amazonAssociateId: window.APP_CONFIG?.amazonAssociateId || '',
    });
    window.setLastFetishName(renderedName);
    window.setDiagnosedName(renderedName);
  } else if (data.compound && data.compound.length > 0) {
    const names = [data.fetish_name, ...data.compound.map(c => c.fetish_name)];
    document.getElementById('result-name').textContent = names.join(' × ');
    window.setLastFetishName(names.join(' × '));
    window.setDiagnosedName(names.join(' × '));
  } else {
    document.getElementById('result-name').textContent = data.fetish_name;
    window.setLastFetishName(data.fetish_name);
    window.setDiagnosedName(data.fetish_name);
  }

  if (window.HekiShare?.prepareSharePayload) window.HekiShare.prepareSharePayload();
  saveHistory(data.fetish_name, data.probability, data.fetish_id);
  show('result-screen');
}


function reportDropoff() {
  if (dropoffSent || resultShown || currentQuestionId == null) return;
  const questionScreen = document.getElementById('question-screen');
  if (!questionScreen || questionScreen.classList.contains('hidden')) return;
  dropoffSent = true;
  const payload = JSON.stringify({answered_count: answeredCount, question_id: currentQuestionId});
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/api/dropoff', new Blob([payload], {type: 'application/json'}));
    return;
  }
  fetch('/api/dropoff', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

window.addEventListener('pagehide', reportDropoff);


async function quickRetry() {
  const excludeIds = [
    ...(window._excludedIds || []),
    window._guessedId,
    ...(window._compoundIds || []),
    ...(window._confirmedIds || []),
  ].filter(id => id != null);
  if (window.HekiState) window.HekiState.setExcludedIds([...new Set(excludeIds)]);
  else {
    window._excludedIds = [...new Set(excludeIds)];
    if (window.gameState) window.gameState.excludedIds = window._excludedIds;
  }
  await startGame(window._excludedIds);
}


async function continueGame() {
  if (_fetching) return;
  setFetching(true);
  try {
    const data = await apiFetch('/api/continue');
    if (data.action === 'question') {
      showQuestion(data);
    } else {
      showToast('これ以上質問できません', '#7f8c8d');
    }
  } finally {
    setFetching(false);
  }
}


  return {startExcluding, startGame, showQuestion, goBack, sendAnswer, showGuess, quickRetry, continueGame};
})();

window.startExcluding = () => window.HekiGameFlow.startExcluding();
window.startGame = excludeIds => window.HekiGameFlow.startGame(excludeIds);
window.showQuestion = data => window.HekiGameFlow.showQuestion(data);
window.goBack = () => window.HekiGameFlow.goBack();
window.sendAnswer = ans => window.HekiGameFlow.sendAnswer(ans);
window.quickRetry = () => window.HekiGameFlow.quickRetry();
window.showGuess = data => window.HekiGameFlow.showGuess(data);
window.continueGame = () => window.HekiGameFlow.continueGame();
