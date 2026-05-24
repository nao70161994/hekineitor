window.HekiRenderers = (() => {
  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null ? '' : String(value);
  }

  function setProgressMessage(message) {
    const el = document.getElementById('question-progress-message');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('hidden', !message);
  }

  function renderWorkTag(work, extraClass = '', helpers = {}) {
    const escapeHtml = helpers.escapeHtml || (value => String(value));
    const safeExternalUrl = helpers.safeExternalUrl || (value => value || null);
    const associateId = helpers.amazonAssociateId || '';
    const title = (typeof work === 'object' && work !== null) ? work.title : work;
    let url = (typeof work === 'object' && work !== null && work.url) ? work.url : null;
    if (!url && associateId) {
      const searchTitle = String(title || '').replace(/[（(][^）)]*[）)]/g, '').trim();
      url = `https://www.amazon.co.jp/s?k=${encodeURIComponent(searchTitle)}&tag=${encodeURIComponent(associateId)}`;
    }
    const className = ['works-tag', extraClass, url ? 'link' : ''].filter(Boolean).join(' ');
    const safeUrl = safeExternalUrl(url);
    if (safeUrl) {
      return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener sponsored" class="${escapeHtml(className)}">${escapeHtml(title)}</a>`;
    }
    return `<span class="${escapeHtml(className)}">${escapeHtml(title)}</span>`;
  }


  function showScreen(id, onShown) {
    ['start-screen','question-screen','result-screen','teach-screen','done-screen']
      .forEach(screenId => {
        const el = document.getElementById(screenId);
        if (!el) return;
        el.classList.add('hidden');
        el.classList.remove('screen-in');
      });
    const target = document.getElementById(id);
    if (!target) return;
    target.classList.remove('hidden');
    void target.offsetWidth;
    target.classList.add('screen-in');
    if (typeof onShown === 'function') onShown(id);
  }

  function showToast(message, color, durationMs = 3000) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.style.background = color || '#e67e22';
    toast.classList.remove('hidden');
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => toast.classList.add('hidden'), durationMs);
  }

  function renderGuess(data, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || (value => String(value ?? ''));
    const safeExternalUrl = helpers.safeExternalUrl || (value => value || null);
    const amazonAssociateId = helpers.amazonAssociateId || '';

    const displayName = data.compound && data.compound.length > 0
      ? [data.fetish_name, ...data.compound.map(item => item.fetish_name)].join(' × ')
      : data.fetish_name;
    setText('result-name', displayName);
    setText('result-desc', data.fetish_desc);
    renderResultDrama(data, displayName, escapeHtml);

    const existingLink = document.getElementById('fetish-detail-link');
    if (existingLink) existingLink.remove();
    if (data.fetish_id != null) {
      const detailLink = document.createElement('a');
      detailLink.id = 'fetish-detail-link';
      detailLink.className = 'fetish-detail-link';
      detailLink.href = `/fetish/${data.fetish_id}`;
      detailLink.target = '_blank';
      detailLink.textContent = '📖 この性癖の詳細ページ';
      document.getElementById('result-desc')?.after(detailLink);
    }

    const card = document.getElementById('result-screen')?.closest('.card');
    if (card) {
      const probability = data.probability;
      if (probability >= 75) {
        card.style.boxShadow = '0 0 24px rgba(245,166,35,0.45), 0 8px 32px rgba(0,0,0,0.4)';
        card.style.border = '1.5px solid rgba(245,166,35,0.6)';
      } else if (probability >= 50) {
        card.style.boxShadow = '0 0 16px rgba(233,69,96,0.25), 0 8px 32px rgba(0,0,0,0.4)';
        card.style.border = '1.5px solid rgba(233,69,96,0.35)';
      } else {
        card.style.boxShadow = '0 8px 32px rgba(0,0,0,0.4)';
        card.style.border = '1.5px solid rgba(255,255,255,0.08)';
      }
    }

    animateProbability(data.probability);
    renderTopChart(data.top_chart, escapeHtml);
    resetFeedbackControls();
    renderConfirmItems(data, escapeHtml);
    renderProfile(data.profile, escapeHtml);
    renderRelated(data.related, escapeHtml);
    renderReasons(data.reasons, escapeHtml);
    renderWorks(data, {escapeHtml, safeExternalUrl, amazonAssociateId});

    const retryBtn = document.getElementById('btn-quick-retry');
    const excluded = [...(window._excludedIds || []), data.fetish_id, ...(data.compound || []).map(item => item.fetish_id)];
    if (retryBtn) retryBtn.style.display = excluded.length > 0 ? '' : 'none';
    return displayName;
  }


  function renderResultDrama(data, displayName, escapeHtml) {
    const probability = Number.parseFloat(data.probability) || 0;
    const title = window.HekiShare?.resultTitle ? window.HekiShare.resultTitle(probability) : '診断タイプ';
    const rarity = window.HekiShare?.resultRarity ? window.HekiShare.resultRarity(probability) : 'R';
    const kicker = document.getElementById('result-kicker');
    const badges = document.getElementById('result-badges');
    const rival = document.getElementById('result-rival');
    if (kicker) {
      kicker.textContent = probability >= 75 ? 'AIが強く反応しました' : 'AIがあなたの気配を検出しました';
    }
    if (badges) {
      badges.innerHTML = `
        <span>称号: ${escapeHtml(title)}</span>
        <span>レア度: ${escapeHtml(rarity)}</span>
        <span>AI一致率: ${escapeHtml(data.probability)}%</span>
      `;
    }
    if (!rival) return;
    const top = Array.isArray(data.top_chart) ? data.top_chart : [];
    if (top.length > 1) {
      const second = top[1];
      const gap = Math.abs((top[0].probability || 0) - (second.probability || 0));
      const verb = gap <= 12 ? '最後まで迷いました' : '次点で見ていました';
      rival.innerHTML = `AIは「${escapeHtml(displayName)}」と「${escapeHtml(second.fetish_name)}」で${verb}`;
      rival.classList.remove('hidden');
    } else {
      rival.textContent = '';
      rival.classList.add('hidden');
    }
  }

  function animateProbability(target) {
    const probEl = document.getElementById('result-prob');
    if (!probEl) return;
    let current = 0;
    const step = Math.max(1, Math.round(target / 30));
    const timer = setInterval(() => {
      current = Math.min(current + step, target);
      probEl.textContent = `一致度: ${current}%`;
      if (current >= target) clearInterval(timer);
    }, 30);
  }

  function renderTopChart(items, escapeHtml) {
    const chartEl = document.getElementById('top-chart');
    if (!chartEl) return;
    if (items && items.length > 1) {
      const maxP = items[0].probability;
      chartEl.innerHTML = items.map((item, index) => {
        const targetW = Math.round(item.probability / maxP * 100);
        const bg = index === 0 ? 'linear-gradient(90deg,#e94560,#f5a623)' : '#1a4a8a';
        return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
          <div style="width:90px;font-size:0.72rem;color:${index===0?'#e94560':'#888'};text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${index===0?'本命 ':''}${escapeHtml(item.fetish_name)}</div>
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
  }

  function resetFeedbackControls() {
    const quickFeedback = document.getElementById('quick-feedback');
    const quickFeedbackStatus = document.getElementById('quick-feedback-status');
    if (quickFeedback) quickFeedback.querySelectorAll('button').forEach(btn => { btn.disabled = false; });
    if (quickFeedbackStatus) {
      quickFeedbackStatus.textContent = '';
      quickFeedbackStatus.classList.add('hidden');
    }
    const detailPanel = document.getElementById('detail-feedback-panel');
    const detailToggle = document.querySelector('[data-action="toggle-detail-feedback"]');
    if (detailPanel) detailPanel.classList.add('hidden');
    if (detailToggle) {
      detailToggle.setAttribute('aria-expanded', 'false');
      detailToggle.textContent = '詳細に○△×を付ける';
      detailToggle.disabled = false;
    }
  }

  function renderConfirmItems(data, escapeHtml) {
    const items = [{fetish_id: data.fetish_id, fetish_name: data.fetish_name, probability: data.probability}];
    (data.compound || []).forEach(item => items.push(item));
    const container = document.getElementById('confirm-items');
    if (!container) return;
    container.innerHTML = items.map(item => {
      const id = Number.parseInt(item.fetish_id, 10);
      return `<div class="confirm-item" id="ci-${id}" data-id="${id}" data-state="">
        <span class="confirm-item-name">${escapeHtml(item.fetish_name)}</span>
        <span class="confirm-item-prob">${escapeHtml(item.probability)}%</span>
        <div class="confirm-toggle">
          <button data-action="set-item-state" data-id="${id}" data-state="yes">○</button>
          <button data-action="set-item-state" data-id="${id}" data-state="maybe">△</button>
          <button data-action="set-item-state" data-id="${id}" data-state="no">×</button>
        </div>
      </div>`;
    }).join('');
  }

  function renderProfile(profile, escapeHtml) {
    const section = document.getElementById('profile-section');
    const list = document.getElementById('profile-list');
    if (!section || !list) return;
    if (profile && profile.length > 0) {
      list.innerHTML = profile.map(row => `<div class="profile-item">${escapeHtml(row.fetish_name)}<span>${escapeHtml(row.probability)}%</span></div>`).join('');
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  }

  function renderRelated(related, escapeHtml) {
    const section = document.getElementById('related-section');
    const tags = document.getElementById('related-tags');
    if (!section || !tags) return;
    if (related && related.length > 0) {
      tags.innerHTML = related.map(row => `<a class="related-tag" href="/fetish/${Number.parseInt(row.fetish_id, 10)}" target="_blank" rel="noopener">${escapeHtml(row.fetish_name)}</a>`).join('');
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  }

  function renderReasons(reasons, escapeHtml) {
    const section = document.getElementById('reasons-section');
    const list = document.getElementById('reasons-list');
    if (!section || !list) return;
    if (reasons && reasons.length) {
      const ansText = {1:'はい', 0.5:'どちらかといえばはい', '-0.5':'どちらかといえばいいえ', '-1':'いいえ'};
      list.innerHTML = reasons.map(row => `<div class="reason-item"><span>${escapeHtml(row.text)}</span><span class="ans-badge">${escapeHtml(ansText[row.ans] || row.ans)}</span></div>`).join('');
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  }

  function renderWorks(data, helpers) {
    const worksSec = document.getElementById('works-section');
    const worksLabel = document.getElementById('works-label');
    const crossTagsEl = document.getElementById('cross-works-tags');
    const worksTagsEl = document.getElementById('works-tags');
    if (!worksSec || !worksLabel || !crossTagsEl || !worksTagsEl) return;
    const isCompound = data.compound && data.compound.length > 0;
    const hasCross = data.cross_works && data.cross_works.length > 0;
    const hasWorks = data.works && data.works.length > 0;
    if (hasCross || hasWorks) {
      worksLabel.textContent = isCompound ? 'この組み合わせが刺さる人へ' : 'おすすめ作品';
      crossTagsEl.innerHTML = hasCross
        ? `<div class="works-cross-label">▶ 両方の要素を持つ作品</div>` + data.cross_works.map(work => renderWorkTag(work, 'cross', helpers)).join('')
        : '';
      worksTagsEl.innerHTML = hasWorks
        ? (hasCross ? '<div class="works-cross-label">▶ それぞれの関連作品</div>' : '') + data.works.map(work => renderWorkTag(work, '', helpers)).join('')
        : '';
      worksSec.classList.remove('hidden');
    } else {
      worksSec.classList.add('hidden');
    }
  }

  return {setText, setProgressMessage, renderWorkTag, showScreen, showToast, renderGuess};
})();
