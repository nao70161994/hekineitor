let _diagnosedName = '';
window.setLastFetishName = value => { window.lastFetishName = value || ''; };
window.setDiagnosedName = value => { _diagnosedName = value || ''; };

function escapeHtml(value) {
  return window.HekiUtils ? window.HekiUtils.escapeHtml(value) : String(value ?? '');
}

function safeExternalUrl(value) {
  return window.HekiUtils ? window.HekiUtils.safeExternalUrl(value) : (value || null);
}

function show(id) {
  if (window.HekiUi) window.HekiUi.show(id);
}

function setGenieState(state) {
  if (window.HekiUi) window.HekiUi.setGenieState(state);
}

function showStart() {
  if (window.HekiUi) window.HekiUi.showStart();
}

function showSessionExpired() {
  if (window.HekiUi) window.HekiUi.showSessionExpired();
}

async function skipTeach() {
  if (window.HekiUi) return window.HekiUi.skipTeach();
}

function confirmRestart() {
  if (window.HekiUi) window.HekiUi.confirmRestart();
}

function closeModal(id) {
  if (window.HekiUi) window.HekiUi.closeModal(id);
}

function doRestart() {
  if (window.HekiUi) window.HekiUi.doRestart();
}

function showToast(msg, color, durationMs = 3000) {
  if (window.HekiUi) window.HekiUi.showToast(msg, color, durationMs);
}

function _updateExcludeButtons() {
  if (window.HekiUi) window.HekiUi.updateExcludeButtons();
}

let _fetching = window.gameState?.fetching || false;
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
  } catch (e) {
    if (e.status === 440 || e.message === 'session_expired') {
      showSessionExpired();
      throw new Error('session_expired');
    }
    const msg = e.name === 'AbortError'
      ? 'サーバーへの接続がタイムアウトしました。しばらくしてから再試行してください。'
      : (e.message === 'network' ? '通信エラーが発生しました。リロードしてください。' : e.message || '通信エラーが発生しました。リロードしてください。');
    showToast(msg, '#c0392b');
    throw e;
  }
}


function setAnswerButtons(disabled) {
  document.querySelectorAll('#question-screen .btn').forEach(b => b.disabled = disabled);
}

function startExcluding() {
  if (window.HekiGameFlow) return window.HekiGameFlow.startExcluding();
}

async function startGame(excludeIds) {
  if (window.HekiGameFlow) return window.HekiGameFlow.startGame(excludeIds);
}

function showQuestion(data) {
  if (window.HekiGameFlow) window.HekiGameFlow.showQuestion(data);
}

async function goBack() {
  if (window.HekiGameFlow) return window.HekiGameFlow.goBack();
}

async function sendAnswer(ans) {
  if (window.HekiGameFlow) return window.HekiGameFlow.sendAnswer(ans);
}

async function quickRetry() {
  if (window.HekiGameFlow) return window.HekiGameFlow.quickRetry();
}

function showGuess(data) {
  if (window.HekiGameFlow) window.HekiGameFlow.showGuess(data);
}

async function continueGame() {
  if (window.HekiGameFlow) return window.HekiGameFlow.continueGame();
}

function _resultFeedbackIds() {
  return window.HekiFeedback ? window.HekiFeedback.resultFeedbackIds() : [];
}

function toggleDetailFeedback() {
  if (window.HekiFeedback) window.HekiFeedback.toggleDetailFeedback();
}

async function quickFeedback(kind) {
  if (window.HekiFeedback) return window.HekiFeedback.quickFeedback(kind);
}

function setItemState(id, state, btn) {
  if (window.HekiFeedback) window.HekiFeedback.setItemState(id, state, btn);
}

async function submitConfirm() {
  if (window.HekiFeedback) return window.HekiFeedback.submitConfirm();
}


function toggleTeachItem(id, name, el) {
  if (window.HekiTeach) window.HekiTeach.toggleTeachItem(id, name, el);
}

function updateTeachSubmitBtn() {
  if (window.HekiTeach) window.HekiTeach.updateTeachSubmitBtn();
}

async function submitTeach() {
  if (window.HekiTeach) return window.HekiTeach.submitTeach();
}

async function addFetishStep1() {
  if (window.HekiTeach) return window.HekiTeach.addFetishStep1();
}

function pickSimilar(id, name) {
  if (window.HekiTeach) window.HekiTeach.pickSimilar(id, name);
}

function addFetishConfirmNew() {
  if (window.HekiTeach) window.HekiTeach.addFetishConfirmNew();
}

async function addFetishStep2(skip) {
  if (window.HekiTeach) return window.HekiTeach.addFetishStep2(skip);
}

function addFetishMore() {
  if (window.HekiTeach) window.HekiTeach.addFetishMore();
}

async function addFetishDone() {
  if (window.HekiTeach) return window.HekiTeach.addFetishDone();
}


function _buildShareText(name, prob, guessData) {
  return window.HekiShare ? window.HekiShare.buildShareText(name, prob, guessData) : '';
}

function shareResult() {
  if (window.HekiShare) window.HekiShare.shareResult(_diagnosedName);
}

function dismissInstall() {
  if (window.HekiPwa) window.HekiPwa.dismissInstall();
}

function _pushDraft(questionId, answer) {
  if (window.HekiDraft) window.HekiDraft.push(questionId, answer);
}

function _saveDraft() {
  if (window.HekiDraft) window.HekiDraft.saveDraft();
}

function _clearDraft() {
  if (window.HekiDraft) window.HekiDraft.clearDraft();
}

function _checkDraft() {
  if (window.HekiDraft) window.HekiDraft.checkDraft();
}

async function resumeGame() {
  if (window.HekiDraft) return window.HekiDraft.resumeGame();
}

// 機能3: 診断履歴
function saveHistory(name, prob, fetish_id) {
  if (window.HekiHistory) window.HekiHistory.saveHistory(name, prob, fetish_id);
}
function _updateHistoryBadge() {
  if (window.HekiHistory) window.HekiHistory.updateHistoryBadge();
}
function toggleHistory() {
  if (window.HekiHistory) window.HekiHistory.toggleHistory();
}
function retryExcluding(historyIndex) {
  if (window.HekiHistory) window.HekiHistory.retryExcluding(historyIndex);
}
