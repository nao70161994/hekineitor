window.HekiUi = (() => {
let activeModal = null;
let modalReturnFocus = null;
function show(id) {
  if (window.HekiRenderers?.showScreen) {
    window.HekiRenderers.showScreen(id, shownId => {
      if (shownId === 'result-screen' || shownId === 'done-screen') updateExcludeButtons();
    });
    return;
  }
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
  if (id === 'result-screen' || id === 'done-screen') updateExcludeButtons();
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
  if (window.HekiState) window.HekiState.resetExcludedIds();
  else window._excludedIds = [];
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
  if (window.HekiTeach) return window.HekiTeach.skipTeach();
  showStart();
}


function confirmRestart() {
  const n = window._excludedIds && window._excludedIds.length;
  const desc = document.getElementById('modal-restart-desc');
  if (desc) {
    desc.textContent = n > 0
      ? `回答は7日間保存できます。破棄すると除外リスト（${n}件）も失われます。`
      : '回答はこの端末に7日間保存できます。保存するか破棄するか選んでください。';
  }
  openModal('modal-restart');
}

function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
  activeModal = null;
  modalReturnFocus?.focus();
  modalReturnFocus = null;
}

function doRestart() {
  if (window._saveDraft) window._saveDraft();
  closeModal('modal-restart');
  showStart();
}

function discardRestart() {
  if (window._clearDraft) window._clearDraft();
  closeModal('modal-restart');
  showStart();
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modalReturnFocus = document.activeElement;
  activeModal = modal;
  modal.classList.remove('hidden');
  requestAnimationFrame(() => modal.querySelector('button, textarea, [tabindex="-1"]')?.focus());
}

function handleModalKeydown(event) {
  if (!activeModal || activeModal.classList.contains('hidden')) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    closeModal(activeModal.id);
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = [...activeModal.querySelectorAll(
    'button:not(:disabled), textarea, [href], [tabindex]:not([tabindex="-1"])',
  )];
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function showToast(msg, color, durationMs = 3000) {
  if (window.HekiRenderers?.showToast) {
    window.HekiRenderers.showToast(msg, color, durationMs);
    return;
  }
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color || '#e67e22';
  t.classList.remove('hidden');
  clearTimeout(t._hideTimer);
  t._hideTimer = setTimeout(() => t.classList.add('hidden'), durationMs);
}


function updateExcludeButtons() {
  const n = (window._excludedIds || []).length;
  const label = n > 0 ? `別の性癖を探す (${n}件除外済み) →` : '別の性癖を探す →';
  document.querySelectorAll('.btn-exclude:not(#btn-quick-retry)').forEach(button => { button.textContent = label; });
  const retry = document.getElementById('btn-quick-retry');
  if (retry) retry.textContent = n > 0 ? `当て直す（${n}件除外済み）` : '当て直す';
}


  return {
    show,
    setGenieState,
    showStart,
    showSessionExpired,
    skipTeach,
    confirmRestart,
    closeModal,
    doRestart,
    discardRestart,
    openModal,
    handleModalKeydown,
    showToast,
    updateExcludeButtons,
  };
})();

window.show = id => window.HekiUi.show(id);
window.setGenieState = state => window.HekiUi.setGenieState(state);
window.showStart = () => window.HekiUi.showStart();
window.showSessionExpired = () => window.HekiUi.showSessionExpired();
window.confirmRestart = () => window.HekiUi.confirmRestart();
window.closeModal = id => window.HekiUi.closeModal(id);
window.doRestart = () => window.HekiUi.doRestart();
window.discardRestart = () => window.HekiUi.discardRestart();
window.openModal = id => window.HekiUi.openModal(id);
window.showToast = (msg, color, durationMs = 3000) => window.HekiUi.showToast(msg, color, durationMs);
window._updateExcludeButtons = () => window.HekiUi.updateExcludeButtons();
