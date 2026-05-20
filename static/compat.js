window.setLastFetishName = value => { window.lastFetishName = value || ''; };
window.setDiagnosedName = value => { if (window.HekiShare) window.HekiShare.setDiagnosedName(value); };

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

function setFetching(value) {
  if (window.HekiNetwork) window.HekiNetwork.setFetching(value);
}

async function apiFetch(url, body, timeoutMs = 30000) {
  if (window.HekiNetwork) return window.HekiNetwork.apiFetch(url, body, timeoutMs);
}

function setAnswerButtons(disabled) {
  if (window.HekiNetwork) window.HekiNetwork.setAnswerButtons(disabled);
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
  if (window.HekiShare) window.HekiShare.shareResult();
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
