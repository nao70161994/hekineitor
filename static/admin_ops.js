async function adminFetch(url, options = {}) {
  if (window.ADMIN_CONFIG?.csrfExpiresAt && Date.now() / 1000 > window.ADMIN_CONFIG.csrfExpiresAt) {
    alert('管理セッションの確認トークンが期限切れです。ページを再読み込みしてください。');
    return null;
  }
  const headers = {
    'Content-Type': 'application/json',
    'X-CSRF-Token': window.ADMIN_CONFIG?.csrfToken || '',
    ...(options.headers || {}),
  };
  const res = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers,
  });
  if (!res.ok && res.status === 401) {
    alert('認証が必要です。ページを再読み込みしてください。');
    return null;
  }
  if (!res.ok && res.status === 429) {
    try { showRateLimit(res, await res.clone().json()); } catch { showRateLimit(res, null); }
  }
  return res;
}

async function restoreMatrixBackup(name) {
  const text = prompt(`${name} を復元します。現在のmatrixは復元前にバックアップされます。\n続行するには RESTORE と入力してください。`);
  if (text !== 'RESTORE') return;
  const msg = document.getElementById('matrix-restore-msg');
  msg.style.color = '#aaa';
  msg.textContent = '復元中...';
  const res = await adminFetch(`/api/admin/matrix_backups/${encodeURIComponent(name)}/restore`, {
    method: 'POST',
    body: JSON.stringify({confirm_text: text}),
  });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || '復元に失敗しました';
    return;
  }
  msg.style.color = '#27ae60';
  msg.textContent = `復元しました: ${data.restored_rows}件（退避: ${data.pre_restore_backup}）`;
  refreshMatrixBackups();
}

function parseMatrixImportPayload() {
  const raw = document.getElementById('matrix-import-json').value.trim();
  if (!raw) throw new Error('JSONを貼り付けるかファイルを選択してください');
  const parsed = JSON.parse(raw);
  if (Array.isArray(parsed)) return {matrix_rows: parsed};
  if (Array.isArray(parsed.matrix_rows)) return {matrix_rows: parsed.matrix_rows};
  throw new Error('matrix_rows が見つかりません');
}

async function runMatrixImport(dryRun) {
  const msg = document.getElementById('matrix-import-msg');
  msg.style.color = '#aaa';
  msg.textContent = dryRun ? '検証中...' : 'インポート中...';
  let payload;
  try {
    payload = parseMatrixImportPayload();
  } catch (e) {
    msg.style.color = '#e74c3c';
    msg.textContent = e.message;
    return;
  }
  if (!dryRun) {
    const text = prompt('Matrixを本インポートします。現在のmatrixは事前バックアップされます。\n続行するには IMPORT と入力してください。');
    if (text !== 'IMPORT') return;
    payload.confirm_text = text;
  }
  const url = dryRun ? '/api/admin/import_matrix/dry_run' : '/api/admin/import_matrix';
  const res = await adminFetch(url, {method: 'POST', body: JSON.stringify(payload)});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || 'エラーが発生しました';
    return;
  }
  msg.style.color = '#27ae60';
  if (dryRun) {
    msg.textContent = `検証OK: 反映対象 ${data.valid_rows} / 入力 ${data.input_rows}（スキップ ${data.skipped_rows}）`;
  } else {
    msg.textContent = `インポート完了: ${data.imported_rows}件（バックアップ: ${data.backup_path}）`;
    refreshMatrixBackups();
  }
}

function showRateLimit(res, data) {
  if (res.status !== 429) return false;
  const retry = data && data.retry_after ? `${data.retry_after}秒後` : 'しばらく後';
  alert(`リクエストが多すぎます。${retry}に再試行してください。`);
  return true;
}

function renderMatrixBackups(backups) {
  const el = document.getElementById('matrix-backup-list');
  if (!el) return;
  if (!backups || !backups.length) {
    el.innerHTML = '<p style="color:#555;">バックアップはまだありません。</p>';
    return;
  }
  el.innerHTML = backups.slice(0, 10).map(b => `<div style="display:flex;gap:8px;align-items:center;border-top:1px solid #222;padding:6px 0;flex-wrap:wrap;">
    <code style="color:#ccc;">${escapeHtml(b.name)}</code>
    <span style="color:#666;">${Number.parseInt(b.size, 10)} bytes</span>
    <button class="btn-toggle" data-action="restore-matrix-backup" data-name="${escapeHtml(b.name)}">復元</button>
  </div>`).join('');
}

async function refreshMatrixBackups() {
  const msg = document.getElementById('matrix-restore-msg');
  if (msg) { msg.style.color = '#aaa'; msg.textContent = '一覧を更新中...'; }
  const res = await adminFetch('/api/admin/matrix_backups', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    if (msg) { msg.style.color = '#e74c3c'; msg.textContent = data.message || '一覧更新に失敗しました'; }
    return;
  }
  renderMatrixBackups(data.backups || []);
  if (msg) { msg.style.color = '#27ae60'; msg.textContent = '一覧を更新しました'; }
}

async function loadPreflight() {
  const el = document.getElementById('preflight-result');
  if (!el) return;
  el.textContent = 'チェック中...';
  const res = await adminFetch('/api/admin/preflight', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    el.style.color = '#e74c3c';
    el.textContent = data.message || 'チェックに失敗しました';
    return;
  }
  el.style.color = '#aaa';
  el.innerHTML = (data.checks || []).map(c => `<div style="border-top:1px solid #222;padding:5px 0;">
    <code style="color:${c.ok ? '#27ae60' : '#e74c3c'};">${c.ok ? 'OK' : 'WARN'}</code>
    <span style="color:#ccc;">${escapeHtml(c.name)}</span>
    <span style="color:#666;">${escapeHtml(c.detail)}</span>
  </div>`).join('');
}

async function loadPerformance() {
  const el = document.getElementById('performance-result');
  if (!el) return;
  el.textContent = '計測中...';
  const res = await adminFetch('/api/admin/performance', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    el.style.color = '#e74c3c';
    el.textContent = data.message || '計測に失敗しました';
    return;
  }
  el.style.color = '#aaa';
  el.innerHTML = (data.measurements || []).map(m => `<div style="border-top:1px solid #222;padding:5px 0;">
    <span style="color:#ccc;">${escapeHtml(m.name)}</span>
    <code style="color:#f5a623;">${escapeHtml(m.ms)} ms</code>
  </div>`).join('');
}


function renderWorksQueueSamples(samples) {
  const labels = {missing_url: 'URLなし', search_url: '検索URL', missing_asin: 'ASINなし'};
  return Object.entries(samples || {}).map(([key, rows]) => {
    const body = (rows || []).map(r => `<div style="border-top:1px solid #222;padding:5px 0;">
      <code style="color:#f5a623;">${escapeHtml(labels[key] || key)}</code>
      <span style="color:#ccc;">${escapeHtml(r.fetish_name)}</span>
      <span>${escapeHtml(r.title)}</span>
      ${r.url ? `<span style="color:#666;">${escapeHtml(r.url)}</span>` : ''}
    </div>`).join('') || '<div style="color:#555;">該当なし</div>';
    return `<div style="margin-top:8px;"><strong style="color:#ccc;">${escapeHtml(labels[key] || key)}</strong>${body}</div>`;
  }).join('');
}

async function applyWorksSeedBackfill() {
  const msg = document.getElementById('works-seed-backfill-msg');
  const text = prompt('seed の作品リストで、DB上の作品なし性癖だけを補完します。既存作品は上書きしません。\n続行するには BACKFILL_WORKS と入力してください。');
  if (text !== 'BACKFILL_WORKS') return;
  if (msg) {
    msg.style.color = '#aaa';
    msg.textContent = '復元中...';
  }
  const res = await adminFetch('/api/admin/works_seed_backfill', {
    method: 'POST',
    body: JSON.stringify({confirm_text: text}),
  });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    if (msg) {
      msg.style.color = '#e74c3c';
      msg.textContent = data.message || '復元に失敗しました';
    }
    return;
  }
  if (msg) {
    msg.style.color = '#27ae60';
    msg.textContent = `復元しました: ${Number.parseInt(data.updated_count || 0, 10)}件 / 候補 ${Number.parseInt(data.candidate_count || 0, 10)}件`;
  }
}


async function loadWorksLinkQueue() {
  const el = document.getElementById('works-link-queue-result');
  if (!el) return;
  el.textContent = '確認中...';
  const res = await adminFetch('/api/admin/works_link_queue', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    el.style.color = '#e74c3c';
    el.textContent = data.message || 'キュー取得に失敗しました';
    return;
  }
  el.style.color = '#aaa';
  const counts = data.counts || {};
  el.innerHTML = `<div>合計 <strong style="color:#f5a623;">${Number.parseInt(data.total || 0, 10)}</strong> 件 / URLなし ${Number.parseInt(counts.missing_url || 0, 10)} / 検索URL ${Number.parseInt(counts.search_url || 0, 10)} / ASINなし ${Number.parseInt(counts.missing_asin || 0, 10)}</div>` + renderWorksQueueSamples(data.samples || {});
}
