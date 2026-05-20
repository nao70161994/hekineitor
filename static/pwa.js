window.HekiPwa = (() => {
  let deferredPrompt = null;
  const banner = document.getElementById('install-banner');

  function dismissInstall() {
    if (!banner) return;
    banner.classList.add('hidden');
    localStorage.setItem('install-dismissed', '1');
  }

  function showUpdateBanner(swReg) {
    const msg = document.getElementById('install-msg');
    const btn = document.getElementById('btn-install');
    const installBanner = document.getElementById('install-banner');
    if (!msg || !btn || !installBanner) return;
    msg.textContent = '新しいバージョンがあります';
    btn.textContent = '今すぐ更新';
    btn.onclick = () => {
      if (swReg && swReg.waiting) swReg.waiting.postMessage({type: 'SKIP_WAITING'});
    };
    installBanner.classList.remove('hidden');
  }

  function bindInstallPrompt() {
    if (!banner) return;
    window.addEventListener('beforeinstallprompt', event => {
      event.preventDefault();
      deferredPrompt = event;
      if (!localStorage.getItem('install-dismissed')) banner.classList.remove('hidden');
    });

    const installBtn = document.getElementById('btn-install');
    if (installBtn) {
      installBtn.onclick = async () => {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          await deferredPrompt.userChoice;
          deferredPrompt = null;
          banner.classList.add('hidden');
        } else {
          showToast('ブラウザのメニュー →「ホーム画面に追加」からインストールできます', '#1a4a8a');
          banner.classList.add('hidden');
        }
      };
    }

    window.addEventListener('appinstalled', () => banner.classList.add('hidden'));

    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches;
    if (isIos && !isStandalone && !localStorage.getItem('install-dismissed')) {
      const msg = document.getElementById('install-msg');
      const btn = document.getElementById('btn-install');
      if (msg) msg.textContent = 'ホーム画面に追加：Safari の 共有ボタン → "ホーム画面に追加"';
      if (btn) btn.style.display = 'none';
      banner.classList.remove('hidden');
    }
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    let swReg = null;
    let reloading = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!reloading) { reloading = true; location.reload(); }
    });
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').then(reg => {
        swReg = reg;
        if (reg.waiting) { showUpdateBanner(swReg); return; }
        reg.addEventListener('updatefound', () => {
          const newSW = reg.installing;
          newSW.addEventListener('statechange', () => {
            if (newSW.state === 'installed' && navigator.serviceWorker.controller) showUpdateBanner(swReg);
          });
        });
      }).catch(() => {});
    });
  }

  function init() {
    bindInstallPrompt();
    registerServiceWorker();
  }

  init();
  return {dismissInstall};
})();
