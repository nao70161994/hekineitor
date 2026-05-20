window.HekiUi = (() => {
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
  document.querySelectorAll('.btn-exclude').forEach(button => { button.textContent = label; });
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
    showToast,
    updateExcludeButtons,
  };
})();
