window.HekiGameFlow = (() => {
  let currentQuestionId = null;
  let answeredCount = 0;
  let resultShown = false;
  let dropoffSent = false;
  const axisLabels = {content: 'コンテンツ軸', abstract: '抽象軸', personality: 'パーソナリティ軸'};

function startExcluding() {
  if (_fetching) return;
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
  if (_fetching) return;
  setFetching(true);
  const startButtons = document.querySelectorAll(
    '[data-action="start-game"], [data-action="start-excluding"], [data-action="quick-retry"]',
  );
  startButtons.forEach(button => { button.disabled = true; });
  const btn = document.querySelector('.btn-start');
  const origText = btn ? btn.textContent : '';
  if (btn) btn.textContent = '起動中...';
  const wakeTimer = setTimeout(() => {
    showToast('サーバーを起動中です。少々お待ちください…', '#555', 25000);
  }, 3000);
  const body = excludeIds && excludeIds.length ? {exclude_ids: excludeIds} : undefined;
  try {
    const data = await apiFetch('/api/start', body, 45000);
    _clearDraft();
    answeredCount = 0;
    resultShown = false;
    dropoffSent = false;
    document.getElementById('resume-banner')?.classList.add('hidden');
    if (excludeIds && excludeIds.length) {
      showToast(`${excludeIds.length}件の性癖を除外して診断します`, '#1a4a8a', 3000);
    }
    showQuestion(data);
  } catch {
    // apiFetch already surfaced the error; keep the previous draft available.
  } finally {
    clearTimeout(wakeTimer);
    if (btn) btn.textContent = origText;
    startButtons.forEach(button => { button.disabled = false; });
    setFetching(false);
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
  const total = Math.max(1, Number(data.total || 1));
  const softTotal = Math.min(20, total);
  const isExtended = total > softTotal && answeredCount >= softTotal;
  const pct = isExtended ? 100 : Math.round((answeredCount / total) * 100);
  const progressFill = document.getElementById('progress-fill');
  const progressBar = progressFill?.parentElement;
  const stageLabel = document.getElementById('question-stage-label');
  if (progressFill) progressFill.style.width = pct + '%';
  if (progressBar) {
    progressBar.setAttribute('aria-valuenow', String(pct));
    progressBar.setAttribute('aria-valuetext', isExtended
      ? `追加質問 ${Math.min(total - softTotal, answeredCount - softTotal + 1)}/${total - softTotal}`
      : `質問 ${Math.min(total, answeredCount + 1)}/${total}`);
  }
  if (stageLabel) {
    stageLabel.textContent = isExtended
      ? `追加質問 ${Math.min(total - softTotal, answeredCount - softTotal + 1)}/${total - softTotal}`
      : `質問 ${Math.min(total, answeredCount + 1)}/${total}`;
  }
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
    _pushDraft(currentQuestionId, ans);
    _saveDraft();
    if (data.action === 'question') {
      showQuestion(data);
    } else {
      _pauseDraft();
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

  let renderedName = data.fetish_name;
  if (window.HekiRenderers?.renderGuess) {
    renderedName = window.HekiRenderers.renderGuess(data, {
      escapeHtml,
      safeExternalUrl,
      amazonAssociateId: window.APP_CONFIG?.amazonAssociateId || '',
    });
    window.setLastFetishName(renderedName);
    window.setDiagnosedName(renderedName);
  } else if (data.compound && data.compound.length > 0) {
    const names = [data.fetish_name, ...data.compound.map(c => c.fetish_name)];
    renderedName = names.join(' × ');
    document.getElementById('result-name').textContent = renderedName;
    window.setLastFetishName(renderedName);
    window.setDiagnosedName(renderedName);
  } else {
    document.getElementById('result-name').textContent = data.fetish_name;
    window.setLastFetishName(data.fetish_name);
    window.setDiagnosedName(data.fetish_name);
  }

  if (window.HekiShare?.prepareSharePayload) window.HekiShare.prepareSharePayload();
  saveHistory(renderedName, data.probability, data.fetish_id, window._compoundIds);
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
  if (_fetching) return;
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
      _saveDraft();
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
