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

function _buildShareText(name, prob, guessData) {
  return window.HekiShare ? window.HekiShare.buildShareText(name, prob, guessData) : '';
}

function shareResult() {
  if (window.HekiShare) window.HekiShare.shareResult();
}

function dismissInstall() {
  if (window.HekiPwa) window.HekiPwa.dismissInstall();
}
