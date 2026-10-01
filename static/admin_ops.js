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
  setAdminTone(msg, '#aaa');
  msg.textContent = '復元中...';
  const res = await adminFetch(`/api/admin/matrix_backups/${encodeURIComponent(name)}/restore`, {
    method: 'POST',
    body: JSON.stringify({confirm_text: text}),
  });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    setAdminTone(msg, '#e74c3c');
    msg.textContent = data.message || '復元に失敗しました';
    return;
  }
  setAdminTone(msg, '#27ae60');
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
  setAdminTone(msg, '#aaa');
  msg.textContent = dryRun ? '検証中...' : 'インポート中...';
  let payload;
  try {
    payload = parseMatrixImportPayload();
  } catch (e) {
    setAdminTone(msg, '#e74c3c');
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
    setAdminTone(msg, '#e74c3c');
    msg.textContent = data.message || 'エラーが発生しました';
    return;
  }
  setAdminTone(msg, '#27ae60');
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
    el.innerHTML = '<p class="admin-copy--muted-2915f89">バックアップはまだありません。</p>';
    return;
  }
  el.innerHTML = backups.slice(0, 10).map(b => `<div class="admin-layout-flex--default-306a85e">
    <code class="admin-copy--default-6040e88">${escapeHtml(b.name)}</code>
    <span class="admin-copy--muted-3c8164b">${Number.parseInt(b.size, 10)} bytes</span>
    <button class="btn-toggle" data-action="restore-matrix-backup" data-name="${escapeHtml(b.name)}">復元</button>
  </div>`).join('');
}

async function refreshMatrixBackups() {
  const msg = document.getElementById('matrix-restore-msg');
  if (msg) { setAdminTone(msg, '#aaa'); msg.textContent = '一覧を更新中...'; }
  const res = await adminFetch('/api/admin/matrix_backups', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    if (msg) { setAdminTone(msg, '#e74c3c'); msg.textContent = data.message || '一覧更新に失敗しました'; }
    return;
  }
  renderMatrixBackups(data.backups || []);
  if (msg) { setAdminTone(msg, '#27ae60'); msg.textContent = '一覧を更新しました'; }
}

async function loadPreflight() {
  const el = document.getElementById('preflight-result');
  if (!el) return;
  el.textContent = 'チェック中...';
  const res = await adminFetch('/api/admin/preflight', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    setAdminTone(el, '#e74c3c');
    el.textContent = data.message || 'チェックに失敗しました';
    return;
  }
  setAdminTone(el, '#aaa');
  el.innerHTML = (data.checks || []).map(c => `<div class="admin-content--default-9fb7568">
    <code class="admin-tone--${c.ok ? 'positive' : 'danger'}">${c.ok ? 'OK' : 'WARN'}</code>
    <span class="admin-copy--default-6040e88">${escapeHtml(c.name)}</span>
    <span class="admin-copy--muted-3c8164b">${escapeHtml(c.detail)}</span>
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
    setAdminTone(el, '#e74c3c');
    el.textContent = data.message || '計測に失敗しました';
    return;
  }
  setAdminTone(el, '#aaa');
  el.innerHTML = (data.measurements || []).map(m => `<div class="admin-content--default-9fb7568">
    <span class="admin-copy--default-6040e88">${escapeHtml(m.name)}</span>
    <code class="admin-copy--warning-962e4f3">${escapeHtml(m.ms)} ms</code>
  </div>`).join('');
}


function renderWorksQueueSamples(samples) {
  const labels = {missing_url: 'URLなし', search_url: '検索URL', missing_asin: 'ASINなし'};
  return Object.entries(samples || {}).map(([key, rows]) => {
    const body = (rows || []).map(r => `<div class="admin-content--default-9fb7568">
      <code class="admin-copy--warning-962e4f3">${escapeHtml(labels[key] || key)}</code>
      <span class="admin-copy--default-6040e88">${escapeHtml(r.fetish_name)}</span>
      <span>${escapeHtml(r.title)}</span>
      ${r.url ? `<span class="admin-copy--muted-3c8164b">${escapeHtml(r.url)}</span>` : ''}
    </div>`).join('') || '<div class="admin-copy--muted-2915f89">該当なし</div>';
    return `<div class="admin-content--default-a6c1e92"><strong class="admin-copy--default-6040e88">${escapeHtml(labels[key] || key)}</strong>${body}</div>`;
  }).join('');
}

async function loadWorksLinkQueue() {
  const el = document.getElementById('works-link-queue-result');
  if (!el) return;
  el.textContent = '確認中...';
  const res = await adminFetch('/api/admin/works_link_queue', {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    setAdminTone(el, '#e74c3c');
    el.textContent = data.message || 'キュー取得に失敗しました';
    return;
  }
  setAdminTone(el, '#aaa');
  const counts = data.counts || {};
  el.innerHTML = `<div>合計 <strong class="admin-copy--warning-962e4f3">${Number.parseInt(data.total || 0, 10)}</strong> 件 / URLなし ${Number.parseInt(counts.missing_url || 0, 10)} / 検索URL ${Number.parseInt(counts.search_url || 0, 10)} / ASINなし ${Number.parseInt(counts.missing_asin || 0, 10)}</div>` + renderWorksQueueSamples(data.samples || {});
}

function renderResultExposureBackfill(data) {
  const el = document.getElementById('result-exposure-backfill-result');
  if (!el) return;
  const rows = data.candidates || [];
  const topRows = rows.slice(0, 8).map(row => `<div class="admin-layout-flex--default-1b3d221">
    <span class="admin-copy--default-a729eed">${escapeHtml(row.fetish_name)}</span>
    <span class="admin-copy--muted-3c8164b">ID ${Number.parseInt(row.fetish_id, 10)}</span>
    <span class="admin-copy--muted-093e73f">raw ${Number.parseInt(row.raw_count || 0, 10)}</span>
    <span class="admin-copy--warning-962e4f3">backfill ${Number.parseInt(row.backfill_count || 0, 10)}</span>
  </div>`).join('');
  const skipped = data.skipped ? `<div class="admin-copy--warning-962e4f3">既にbackfill済みのため通常はスキップされます。再投入は行わないでください。</div>` : '';
  el.innerHTML = `<div>mode <code>${escapeHtml(data.mode || '')}</code> / raw ${Number.parseInt(data.raw_total || 0, 10)} / planned ${Number.parseInt(data.planned_total || 0, 10)} / existing ${Number.parseInt(data.existing_backfill_count || 0, 10)}</div>${skipped}${topRows || '<div class="admin-copy--muted-2915f89">候補なし</div>'}`;
}

async function previewResultExposureBackfill() {
  const maxInput = document.getElementById('result-exposure-backfill-max');
  const msg = document.getElementById('result-exposure-backfill-msg');
  const maxEvents = Math.max(1, Math.min(Number.parseInt(maxInput?.value || '1000', 10) || 1000, 5000));
  if (msg) { setAdminTone(msg, '#aaa'); msg.textContent = '確認中...'; }
  const res = await adminFetch(`/api/admin/result_exposures/backfill?max_events=${maxEvents}`, {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    if (msg) { setAdminTone(msg, '#e74c3c'); msg.textContent = data.message || '確認に失敗しました'; }
    return;
  }
  renderResultExposureBackfill(data);
  if (msg) { setAdminTone(msg, data.skipped ? '#f5a623' : '#27ae60'); msg.textContent = data.skipped ? '既にbackfill済みです' : `予定 ${Number.parseInt(data.planned_total || 0, 10)}件`; }
}

async function applyResultExposureBackfill() {
  const maxInput = document.getElementById('result-exposure-backfill-max');
  const msg = document.getElementById('result-exposure-backfill-msg');
  const maxEvents = Math.max(1, Math.min(Number.parseInt(maxInput?.value || '1000', 10) || 1000, 5000));
  const text = prompt('過去の診断回数から分散ボーナス用の補助露出ログをPostgresへ追加します。通常は1回だけ実行してください。\n続行するには BACKFILL_RESULT_EXPOSURES と入力してください。');
  if (text !== 'BACKFILL_RESULT_EXPOSURES') return;
  if (msg) { setAdminTone(msg, '#aaa'); msg.textContent = '適用中...'; }
  const res = await adminFetch('/api/admin/result_exposures/backfill', {
    method: 'POST',
    body: JSON.stringify({confirm_text: text, max_events: maxEvents}),
  });
  if (!res) return;
  const data = await res.json();
  if (!res.ok) {
    if (msg) { setAdminTone(msg, '#e74c3c'); msg.textContent = data.message || '適用に失敗しました'; }
    renderResultExposureBackfill(data);
    return;
  }
  renderResultExposureBackfill(data);
  if (msg) { setAdminTone(msg, data.skipped ? '#f5a623' : '#27ae60'); msg.textContent = data.skipped ? '既にbackfill済みです' : `追加しました: ${Number.parseInt(data.inserted_count || 0, 10)}件`; }
}
