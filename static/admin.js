function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}


async function setTestPlayMode(action) {
  const url = action === 'start' ? '/admin/test_play/start' : '/admin/test_play/stop';
  const res = await adminFetch(url, {method: 'POST', body: JSON.stringify({})});
  if (!res) return;
  if (res.ok) {
    window.location.href = action === 'start' ? '/' : '/admin';
    return;
  }
  alert('テストプレイ状態の変更に失敗しました。ページを再読み込みしてください。');
}

async function loadRecentRanking(days) {
  const rank7 = document.getElementById('rank-btn-7');
  const rank30 = document.getElementById('rank-btn-30');
  const label = document.getElementById('recent-rank-label');
  const el = document.getElementById('recent-rank-chart');
  if (!rank7 || !rank30 || !label || !el) return;
  rank7.style.background  = days===7  ? '#e94560' : '#0f3460';
  rank7.style.borderColor = days===7  ? '#e94560' : '#444';
  rank7.style.color       = days===7  ? '#fff'    : '#aaa';
  rank30.style.background  = days===30 ? '#e94560' : '#0f3460';
  rank30.style.borderColor = days===30 ? '#e94560' : '#444';
  rank30.style.color       = days===30 ? '#fff'    : '#aaa';
  const resp = await fetch(`/api/admin/recent_fetish_ranking?days=${days}&top_n=10`);
  const json = await resp.json();
  const rows = json.ranking || [];
  const fallback = json.source === 'all_time_fallback';
  label.textContent = fallback ? '診断回数ランキング（累計）' : `最近の診断ランキング（${days}日）`;
  if (!rows.length) { el.innerHTML = '<p style="color:#555;font-size:0.78rem;">データなし（診断結果が蓄積されると表示されます）</p>'; return; }
  const maxT = Math.max(...rows.map(r => r.guessed || r.total || 0), 1);
  const note = fallback ? '<div style="color:#666;font-size:0.7rem;margin-bottom:5px;">過去の日次診断データがないため、累計診断回数で表示しています。</div>' : '';
  el.innerHTML = note + rows.map(r => {
    const guessed = r.guessed || r.total || 0;
    const feedbackTotal = r.feedback_total != null ? r.feedback_total : (r.correct || 0) + (r.wrong || 0);
    const acc = r.acc != null ? r.acc : null;
    const accStr = acc != null ? `<span style="color:${acc>=60?'#27ae60':'#e74c3c'};min-width:38px;text-align:right;">FB ${acc}%</span>` : '<span style="color:#555;min-width:38px;text-align:right;">FB —</span>';
    const width = Math.max(Math.round(guessed / maxT * 160), guessed > 0 ? 2 : 0);
    return `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
      <div style="width:90px;font-size:0.72rem;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right;" title="${escapeHtml(r.fetish_name)}">${escapeHtml(r.fetish_name)}</div>
      <div style="height:10px;border-radius:3px;overflow:hidden;flex:1;max-width:200px;background:#111;">
        <div style="width:${width}px;height:10px;background:#5b8dd9;"></div>
      </div>
      <div style="font-size:0.7rem;color:#aaa;min-width:34px;">${guessed}</div>
      <div style="font-size:0.7rem;color:#666;min-width:34px;">FB ${feedbackTotal}</div>
      ${accStr}
    </div>`;
  }).join('');
}
function renderStatsChart(days) {
  const chart = document.getElementById('stats-chart');
  const label = document.getElementById('chart-label');
  const btn7 = document.getElementById('chart-btn-7');
  const btn30 = document.getElementById('chart-btn-30');
  if (!chart || !label || !btn7 || !btn30) return;
  const data = (window.ADMIN_STATS_HISTORY || []).slice(-days);
  const maxV = Math.max(1, ...data.map(r => Math.max(r.play, r.learn)));
  label.textContent = `過去${days}日間の推移`;
  btn7.style.background  = days === 7  ? '#e94560' : '#0f3460';
  btn7.style.borderColor = days === 7  ? '#e94560' : '#444';
  btn7.style.color       = days === 7  ? '#fff'    : '#aaa';
  btn30.style.background  = days === 30 ? '#e94560' : '#0f3460';
  btn30.style.borderColor = days === 30 ? '#e94560' : '#444';
  btn30.style.color       = days === 30 ? '#fff'    : '#aaa';
  chart.innerHTML = data.map(r => {
    const ph = Math.round(r.play    / maxV * 48);
    const lh = Math.round(r.learn   / maxV * 48);
    const ch = Math.round(r.correct / maxV * 48);
    const wh = Math.round(r.wrong   / maxV * 48);
    const fb = r.correct + r.wrong;
    const accStr = fb > 0 ? ` 正答率:${Math.round(r.correct/fb*100)}%` : '';
    return `<div style="flex:1;min-width:7px;display:flex;flex-direction:column;align-items:center;gap:1px;height:100%;justify-content:flex-end;" title="${r.date}\nプレイ:${r.play} 学習:${r.learn}\n正解:${r.correct} 外れ:${r.wrong}${accStr}">
      <div style="width:100%;background:#f5a623;border-radius:2px 2px 0 0;height:${ph}px;"></div>
      <div style="width:100%;background:#5b8dd9;border-radius:2px 2px 0 0;height:${lh}px;"></div>
      <div style="width:100%;background:#27ae60;border-radius:2px 2px 0 0;height:${ch}px;"></div>
      <div style="width:100%;background:#e74c3c;border-radius:2px 2px 0 0;height:${wh}px;"></div>
    </div>`;
  }).join('');
}
function worksToInputStr(works) {
  // works配列を「タイトル|URL, タイトル」形式の文字列に変換（入力欄表示用）
  return (works || []).map(w =>
    (typeof w === 'object' && w.url) ? `${w.title}|${w.url}` : (w.title || w)
  ).join(', ');
}

function fillId(nameInputId, idInputId) {
  const val = document.getElementById(nameInputId).value;
  const m = val.match(/\((\d+)\)\s*$/);
  if (m) document.getElementById(idInputId).value = m[1];
}

async function saveParams() {
  const keys = ['guess_threshold','compound_ratio','triple_ratio','ucb_explore_c','focus_threshold'];
  const body = {};
  for (const k of keys) {
    const v = parseFloat(document.getElementById(`param-${k}`).value);
    if (!isNaN(v)) body[k] = v;
  }
  const res  = await adminFetch('/api/admin/params', {method: 'POST', body: JSON.stringify(body)});
  if (!res) return;
  const data = await res.json();
  const msg  = document.getElementById('param-msg');
  if (data.errors && data.errors.length) {
    msg.style.color = '#e74c3c';
    msg.textContent = data.errors.join(', ');
  } else {
    msg.style.color = '#27ae60';
    msg.textContent = '保存しました';
    setTimeout(() => msg.textContent = '', 3000);
  }
}

async function saveShareNote(resultName, targetId, btn) {
  const textarea = document.getElementById(targetId);
  const msg = document.getElementById(`${targetId}-msg`);
  if (!textarea) return;
  if (msg) {
    msg.style.color = '#aaa';
    msg.textContent = '保存中...';
  }
  btn.disabled = true;
  const res = await adminFetch('/api/admin/share_notes', {
    method: 'POST',
    body: JSON.stringify({result_name: resultName, note: textarea.value}),
  });
  btn.disabled = false;
  if (!res) return;
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (res.ok) {
    if (msg) {
      msg.style.color = '#27ae60';
      msg.textContent = textarea.value.trim() ? '保存しました' : '削除しました';
      setTimeout(() => { msg.textContent = ''; }, 3000);
    }
  } else if (msg) {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || '保存に失敗しました';
  }
}

async function cleanupSessions() {
  const res  = await adminFetch('/api/admin/cleanup_sessions', {method: 'POST'});
  if (!res) return;
  const data = await res.json();
  document.getElementById('cleanup-msg').textContent = `${data.deleted} 件削除しました`;
}

let _logSortCol = -1, _logSortAsc = true;
const _initialLogPage = window.ADMIN_CONFIG?.fetishLogPage || {};
let _logPage = Number.parseInt(_initialLogPage.page, 10) || 1;
let _logPages = Number.parseInt(_initialLogPage.pages, 10) || 1;
let _logSort = 'guessed';
let _logOrder = 'desc';

function renderLogRows(rows) {
  const body = document.getElementById('log-table-body');
  body.innerHTML = (rows || []).map((r, i) => {
    const acc = r.acc == null ? -1 : Number.parseFloat(r.acc);
    const warn = acc >= 0 && acc < 40 && Number.parseInt(r.guessed, 10) >= 3;
    const accText = acc >= 0 ? `${acc}%` : '—';
    const accColor = acc >= 0 && acc < 50 ? '#e74c3c' : (acc >= 0 ? '#27ae60' : '#555');
    return `<tr id="logrow-${Number.parseInt(r.id, 10)}"${warn ? ' style="background:#2a1010"' : ''}
      data-name="${escapeHtml(r.name)}" data-guessed="${Number.parseInt(r.guessed, 10)}" data-acc="${acc}">
      <td style="color:#666;font-size:0.75rem">${i + 1 + ((_logPage - 1) * 50)}</td>
      <td style="font-size:0.82rem">${escapeHtml(r.name)}${warn ? '<span class="tag-low" title="wrong率60%超">⚠</span>' : ''}</td>
      <td style="color:#aaa;font-size:0.8rem" data-val="${Number.parseInt(r.guessed, 10)}">${Number.parseInt(r.guessed, 10)}</td>
      <td style="color:#27ae60;font-size:0.8rem" data-val="${Number.parseInt(r.correct, 10)}">${Number.parseInt(r.correct, 10)}</td>
      <td style="color:#e74c3c;font-size:0.8rem" data-val="${Number.parseInt(r.wrong, 10)}">${Number.parseInt(r.wrong, 10)}</td>
      <td style="font-size:0.8rem;color:${accColor}" data-val="${acc}">${accText}</td>
      <td><button class="btn-toggle" data-action="toggle-fetish-history" data-fid="${Number.parseInt(r.id, 10)}" style="font-size:0.72rem;padding:2px 8px;">履歴</button></td>
    </tr>
    <tr id="logrow-hist-${Number.parseInt(r.id, 10)}" style="display:none;">
      <td colspan="7" style="padding:8px 4px 12px;">
        <div id="logrow-hist-content-${Number.parseInt(r.id, 10)}" style="font-size:0.78rem;color:#888;"></div>
      </td>
    </tr>`;
  }).join('');
}

async function loadLogPage(page) {
  _logPage = Math.max(1, page);
  const params = new URLSearchParams({
    page: String(_logPage),
    per_page: '50',
    q: document.getElementById('log-search').value,
    min_guessed: document.getElementById('log-min-guessed').value,
    acc_filter: document.getElementById('log-acc-filter').value,
    sort: _logSort,
    order: _logOrder,
  });
  const res = await adminFetch(`/api/admin/fetish_log_rows?${params}`, {method: 'GET', headers: {}});
  if (!res) return;
  const data = await res.json();
  if (!res.ok) return;
  _logPage = data.page;
  _logPages = data.pages;
  renderLogRows(data.rows || []);
  const info = document.getElementById('log-page-info');
  if (info) info.textContent = `${data.page} / ${data.pages}（${data.total}件）`;
}

function sortLogTable(col) {
  const map = {1: 'name', 2: 'guessed', 3: 'correct', 4: 'wrong', 5: 'acc'};
  if (_logSortCol === col) { _logSortAsc = !_logSortAsc; } else { _logSortCol = col; _logSortAsc = false; }
  _logSort = map[col] || 'guessed';
  _logOrder = _logSortAsc ? 'asc' : 'desc';
  loadLogPage(1);
}

function filterLogTable() {
  loadLogPage(1);
}

async function toggleFetishHistory(fid, btn) {
  const histRow = document.getElementById(`logrow-hist-${fid}`);
  const content = document.getElementById(`logrow-hist-content-${fid}`);
  if (histRow.style.display !== 'none') { histRow.style.display = 'none'; return; }
  content.textContent = '読み込み中…';
  histRow.style.display = '';
  const res = await adminFetch(`/api/admin/fetish_history/${fid}?days=30`, {method: 'GET'});
  if (!res) { histRow.style.display = 'none'; return; }
  const data = await res.json();
  const hasSome = data.some(d => d.correct > 0 || d.wrong > 0);
  if (!hasSome) { content.textContent = 'フィードバックデータなし（記録は今後蓄積されます）'; return; }
  const maxV = Math.max(1, ...data.map(d => d.correct + d.wrong));
  let html = '<div style="display:flex;align-items:flex-end;gap:2px;height:36px;overflow-x:auto;">';
  data.forEach(d => {
    const tot = d.correct + d.wrong;
    const h   = Math.round(tot / maxV * 34);
    const acc = tot > 0 ? Math.round(d.correct / tot * 100) : null;
    const bg  = acc === null ? '#333' : acc >= 70 ? '#27ae60' : acc >= 40 ? '#f5a623' : '#e74c3c';
    html += `<div title="${d.date}: 正解${d.correct}/外れ${d.wrong}${acc!==null?' ('+acc+'%)':''}"
               style="flex:1;min-width:4px;height:${Math.max(h,2)}px;background:${bg};border-radius:2px 2px 0 0;"></div>`;
  });
  html += '</div><div style="font-size:0.72rem;color:#555;margin-top:3px;">過去30日（緑=正解多, 橙=接戦, 赤=外れ多）</div>';
  content.innerHTML = html;
}

async function promotePlayerFetish(fid, btn) {
  if (!confirm(`ID ${fid} の性癖をシード性癖に格上げしますか？\nIDが変わり「プレイヤー追加」扱いではなくなります。`)) return;
  btn.disabled = true;
  const res  = await adminFetch(`/api/admin/promote_fetish/${fid}`, {method: 'POST'});
  if (!res) { btn.disabled = false; return; }
  const data = await res.json();
  if (res.ok) {
    const row = document.getElementById(`pfrow-${fid}`);
    if (row) {
      row.cells[0].textContent = data.new_id;
      row.id = `pfrow-${data.new_id}`;
      row.cells[3].innerHTML = `<span style="color:#27ae60;font-size:0.78rem">シード済 (ID:${data.new_id})</span>`;
    }
  } else {
    alert(data.message || '格上げに失敗しました');
    btn.disabled = false;
  }
}

async function editFetish(fid, btn) {
  const nameEl  = document.getElementById(`pfname-${fid}`);
  const descEl  = document.getElementById(`pfdesc-${fid}`);
  const worksEl = document.getElementById(`pfworks-${fid}`);
  if (btn.dataset.editing) {
    const name  = nameEl.querySelector('input').value.trim();
    const desc  = descEl.querySelector('input').value.trim();
    const worksRaw = worksEl.querySelector('input').value.trim();
    const body  = {name, desc};
    if (worksRaw) body.works = worksRaw.split(',').map(s => s.trim()).filter(Boolean);
    btn.disabled = true;
    const res  = await adminFetch(`/api/admin/edit_fetish/${fid}`, {method: 'POST', body: JSON.stringify(body)});
    btn.disabled = false;
    if (!res) return;
    const data = await res.json();
    if (res.ok) {
      nameEl.textContent  = data.name;
      descEl.textContent  = data.desc;
      worksEl.textContent = data.works && data.works.length ? worksToInputStr(data.works) : '（なし）';
      delete btn.dataset.editing;
      btn.textContent = '編集';
    } else {
      alert(data.message || '保存に失敗しました');
    }
  } else {
    const curName  = nameEl.textContent;
    const curDesc  = descEl.textContent;
    const curWorks = worksEl.textContent === '（なし）' ? '' : worksEl.textContent;
    const inp = 'style="background:#1a1a2e;color:#eee;border:1px solid #555;padding:2px 6px;border-radius:4px;font-size:0.82rem;width:100%"';
    nameEl.innerHTML  = `<input value="${escapeHtml(curName)}" ${inp}>`;
    descEl.innerHTML  = `<input value="${escapeHtml(curDesc)}" ${inp}>`;
    worksEl.innerHTML = `<input value="${escapeHtml(curWorks)}" placeholder="作品名|URL, 作品名, ..." ${inp}>`;
    btn.dataset.editing = '1';
    btn.textContent = '保存';
  }
}

async function editFetishById() {
  const fid   = parseInt(document.getElementById('ef-id').value);
  const name  = document.getElementById('ef-name').value.trim() || undefined;
  const desc  = document.getElementById('ef-desc').value.trim() || undefined;
  const worksRaw = document.getElementById('ef-works').value.trim();
  const msg   = document.getElementById('ef-msg');
  if (!fid) { msg.style.color = '#e74c3c'; msg.textContent = 'IDを入力してください'; return; }
  const body = {};
  if (name) body.name = name;
  if (desc) body.desc = desc;
  if (worksRaw) body.works = worksRaw.split(',').map(s => s.trim()).filter(Boolean);
  const res  = await adminFetch(`/api/admin/edit_fetish/${fid}`, {method: 'POST', body: JSON.stringify(body)});
  if (!res) return;
  const data = await res.json();
  if (res.ok) {
    msg.style.color = '#27ae60';
    const worksCount = data.works ? data.works.length : 0;
    msg.textContent = `保存しました: ${data.name}（作品${worksCount}件）`;
    setTimeout(() => msg.textContent = '', 4000);
    document.getElementById('ef-works').value = '';
  } else {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || 'エラーが発生しました';
  }
}

async function deletePlayerFetish(fid, btn) {
  const text = prompt(`ID ${fid} の性癖を削除します。この操作は元に戻せません。\n続行するには DELETE と入力してください。`);
  if (text !== 'DELETE') return;
  btn.disabled = true;
  const res = await adminFetch(`/api/fetish/${fid}`, {
    method: 'DELETE',
    body: JSON.stringify({confirm_text: text}),
  });
  if (!res) { btn.disabled = false; return; }
  if (res.ok) {
    const row = document.getElementById(`pfrow-${fid}`);
    if (row) row.remove();
  } else {
    alert('削除に失敗しました');
    btn.disabled = false;
  }
}

async function capturepriors() {
  const res  = await adminFetch('/api/admin/capture_priors', {method: 'POST'});
  if (!res) return;
  const data = await res.json();
  const msg  = document.getElementById('capture-msg');
  msg.style.color = data.status === 'ok' ? '#27ae60' : '#e74c3c';
  msg.textContent = data.status === 'ok' ? '保存しました' : 'エラーが発生しました';
  setTimeout(() => msg.textContent = '', 3000);
}

async function adminAddFetish() {
  const name = document.getElementById('af-name').value.trim();
  const desc = document.getElementById('af-desc').value.trim();
  const msg  = document.getElementById('af-msg');
  if (!name) { msg.style.color = '#e74c3c'; msg.textContent = '名前を入力してください'; return; }
  const res  = await adminFetch('/api/admin/add_fetish', {method: 'POST', body: JSON.stringify({name, desc})});
  if (!res) return;
  const data = await res.json();
  if (data.status === 'created') {
    msg.style.color = '#27ae60';
    msg.textContent = `追加しました (ID: ${data.fetish_id})`;
    document.getElementById('af-name').value = '';
    document.getElementById('af-desc').value = '';
  } else if (data.status === 'exists') {
    msg.style.color = '#f5a623';
    msg.textContent = `既に存在します (ID: ${data.fetish_id})`;
  } else {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || 'エラーが発生しました';
  }
}

let _qSortAsc = true;
function sortQTable() {
  const table = document.getElementById('q-table');
  const rows  = Array.from(table.rows).slice(1);
  _qSortAsc = !_qSortAsc;
  rows.sort((a, b) => {
    const av = parseFloat(a.cells[3].textContent);
    const bv = parseFloat(b.cells[3].textContent);
    return _qSortAsc ? av - bv : bv - av;
  });
  rows.forEach((r, i) => { r.cells[0].textContent = i + 1; table.appendChild(r); });
}

async function editQuestion(qId, btn) {
  const cell = document.getElementById(`qtext-${qId}`);
  if (btn.dataset.editing) {
    const inp  = cell.querySelector('input');
    const text = inp ? inp.value.trim() : '';
    if (!text) return;
    btn.disabled = true;
    const res  = await adminFetch(`/api/admin/edit_question/${qId}`, {method: 'POST', body: JSON.stringify({text})});
    btn.disabled = false;
    if (!res) return;
    const data = await res.json();
    if (res.ok) {
      cell.textContent = data.text;
      delete btn.dataset.editing;
      btn.textContent = '編集';
    } else {
      alert(data.message || '保存に失敗しました');
    }
  } else {
    const cur = cell.textContent.replace(/低識別力$/, '').trim();
    cell.innerHTML = `<input value="${escapeHtml(cur)}" style="background:#1a1a2e;color:#eee;border:1px solid #555;padding:2px 6px;border-radius:4px;font-size:0.8rem;width:100%">`;
    btn.dataset.editing = '1';
    btn.textContent = '保存';
    cell.querySelector('input').focus();
  }
}

async function checkSimilarity() {
  const id_a = parseInt(document.getElementById('sim-a').value);
  const id_b = parseInt(document.getElementById('sim-b').value);
  const out  = document.getElementById('sim-result');
  if (!id_a || !id_b) { out.style.color='#e74c3c'; out.textContent='IDを両方入力してください'; return; }
  const res  = await adminFetch('/api/admin/fetish_similarity', {method: 'POST', body: JSON.stringify({id_a, id_b})});
  if (!res) return;
  const d = await res.json();
  if (!res.ok) { out.style.color='#e74c3c'; out.textContent=d.message||'エラー'; return; }
  const pct = Math.round((d.cosine + 1) / 2 * 100);
  const color = pct >= 70 ? '#e94560' : pct >= 40 ? '#f5a623' : '#27ae60';
  let html = `<div style="margin-bottom:8px;">
    <span style="color:#eee;font-weight:bold;">${escapeHtml(d.name_a)}</span>
    <span style="color:#555;"> × </span>
    <span style="color:#eee;font-weight:bold;">${escapeHtml(d.name_b)}</span>
    &nbsp;&nbsp;コサイン類似度: <span style="color:${color};">${escapeHtml(d.cosine)}</span>
  </div>
  <div style="color:#888;margin-bottom:4px;">差異が大きい質問 TOP5:</div>
  <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">`;
  html += `<tr><th style="color:#555;text-align:left;padding:2px 6px;">質問</th><th style="color:#555;padding:2px 6px;">${escapeHtml(d.name_a)}</th><th style="color:#555;padding:2px 6px;">${escapeHtml(d.name_b)}</th></tr>`;
  d.top_diff.forEach(q => {
    html += `<tr style="border-top:1px solid #1a1a2e;">
      <td style="padding:2px 6px;color:#aaa;">${escapeHtml(q.text)}</td>
      <td style="text-align:center;padding:2px 6px;color:#f5a623;">${escapeHtml(q.p_a)}</td>
      <td style="text-align:center;padding:2px 6px;color:#f5a623;">${escapeHtml(q.p_b)}</td>
    </tr>`;
  });
  html += '</table>';
  out.innerHTML = html;
}

function focusMaintenanceEdit(fid) {
  const section = document.getElementById('seed-edit-section');
  if (section) section.open = true;
  const idInput = document.getElementById('ef-id');
  if (idInput) {
    idInput.value = fid;
    idInput.focus();
  }
  if (section) section.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function focusMaintenanceSimilarity(fid, otherId) {
  const section = document.getElementById('similarity-section');
  if (section) section.open = true;
  const a = document.getElementById('sim-a');
  const b = document.getElementById('sim-b');
  if (a) a.value = fid;
  if (b && otherId) b.value = otherId;
  if (section) section.scrollIntoView({behavior: 'smooth', block: 'start'});
  if (a) a.focus();
}

async function mergeFetishes() {
  const id_keep   = parseInt(document.getElementById('mg-keep').value);
  const id_remove = parseInt(document.getElementById('mg-rm').value);
  const new_name  = document.getElementById('mg-name').value.trim() || undefined;
  const new_desc  = document.getElementById('mg-desc').value.trim() || undefined;
  const msg = document.getElementById('mg-msg');
  if (!id_keep || !id_remove) { msg.style.color='#e74c3c'; msg.textContent='IDを両方入力してください'; return; }
  const text = prompt(`ID ${id_keep} に ID ${id_remove} をマージし、ID ${id_remove} を削除します。\n続行するには MERGE と入力してください。`);
  if (text !== 'MERGE') return;
  const body = {id_keep, id_remove, confirm_text: text};
  if (new_name) body.new_name = new_name;
  if (new_desc) body.new_desc = new_desc;
  const res  = await adminFetch('/api/admin/merge_fetishes', {method: 'POST', body: JSON.stringify(body)});
  if (!res) return;
  const data = await res.json();
  if (res.ok) {
    msg.style.color = '#27ae60';
    msg.textContent = `統合しました: ${data.name}`;
  } else {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || 'エラーが発生しました';
  }
}

let _cwLoaded = false;
async function loadCompoundWorks() {
  if (_cwLoaded) return;
  _cwLoaded = true;
  const res = await adminFetch('/api/admin/compound_works', {method: 'GET', headers: {}});
  if (!res || !res.ok) return;
  const items = await res.json();
  renderCompoundWorks(items);
}

function renderCompoundWorks(items) {
  const el = document.getElementById('cw-list');
  if (!items.length) { el.innerHTML = '<p style="color:#555;font-size:0.82rem;">登録なし</p>'; return; }
  el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:0.8rem;margin-top:4px;">
    <tr><th style="text-align:left;color:#888;padding:4px 8px;">ペア</th><th style="text-align:left;color:#888;padding:4px 8px;">作品</th><th></th></tr>
    ${items.map(it => `
    <tr id="cwrow-${escapeHtml(String(it.key).replace(',','-'))}" style="border-top:1px solid #222;">
      <td style="padding:4px 8px;color:#ccc;white-space:nowrap;">${escapeHtml(it.name_a)}<br><span style="color:#888;">× ${escapeHtml(it.name_b)}</span></td>
      <td style="padding:4px 8px;color:#f0d06a;">${escapeHtml(worksToInputStr(it.works))}</td>
      <td style="padding:4px 8px;"><button class="btn-toggle" data-action="delete-compound-works" data-key="${escapeHtml(it.key)}" data-id-a="${Number.parseInt(it.id_a, 10)}" data-id-b="${Number.parseInt(it.id_b, 10)}">削除</button></td>
    </tr>`).join('')}
  </table>`;
}

async function saveCompoundWorks() {
  const id_a = parseInt(document.getElementById('cw-a').value);
  const id_b = parseInt(document.getElementById('cw-b').value);
  const worksRaw = document.getElementById('cw-works').value.trim();
  const msg = document.getElementById('cw-msg');
  if (!id_a || !id_b) { msg.style.color='#e74c3c'; msg.textContent='IDを両方入力してください'; return; }
  if (!worksRaw) { msg.style.color='#e74c3c'; msg.textContent='作品を入力してください'; return; }
  const works = worksRaw.split(',').map(s => s.trim()).filter(Boolean);
  const res = await adminFetch('/api/admin/compound_works', {method: 'POST', body: JSON.stringify({id_a, id_b, works})});
  if (!res) return;
  const data = await res.json();
  if (res.ok) {
    msg.style.color = '#27ae60';
    msg.textContent = `保存しました（${data.works.length}件）`;
    setTimeout(() => msg.textContent = '', 3000);
    document.getElementById('cw-works').value = '';
    _cwLoaded = false;
    loadCompoundWorks();
  } else {
    msg.style.color = '#e74c3c';
    msg.textContent = data.message || 'エラーが発生しました';
  }
}

async function deleteCompoundWorks(key, id_a, id_b) {
  if (!confirm(`ペア (${id_a}, ${id_b}) の複合作品を削除しますか？`)) return;
  const res = await adminFetch(`/api/admin/compound_works/${key}`, {method: 'DELETE', headers: {}});
  if (!res || !res.ok) { alert('削除に失敗しました'); return; }
  const row = document.getElementById(`cwrow-${key.replace(',','-')}`);
  if (row) row.remove();
}

async function toggleQuestion(qId) {
  const res  = await adminFetch(`/api/admin/toggle_question/${qId}`, {method: 'POST'});
  if (!res || !res.ok) { alert('エラーが発生しました'); return; }
  const data = await res.json();
  const row  = document.getElementById(`qrow-${qId}`);
  const btn  = document.getElementById(`qtoggle-${qId}`);
  if (data.disabled) {
    row.style.opacity = '0.4';
    btn.textContent = '無効';
    btn.classList.add('disabled');
  } else {
    row.style.opacity = '';
    btn.textContent = '有効';
    btn.classList.remove('disabled');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('click', event => {
    const el = event.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;
    if (action === 'save-params') saveParams();
    else if (action === 'test-play-start') setTestPlayMode('start');
    else if (action === 'test-play-stop') setTestPlayMode('stop');
    else if (action === 'capture-priors') capturepriors();
    else if (action === 'admin-add-fetish') adminAddFetish();
    else if (action === 'cleanup-sessions') cleanupSessions();
    else if (action === 'save-share-note') saveShareNote(el.dataset.result || '', el.dataset.target || '', el);
    else if (action === 'dry-run-matrix-import') runMatrixImport(true);
    else if (action === 'import-matrix') runMatrixImport(false);
    else if (action === 'restore-matrix-backup') restoreMatrixBackup(el.dataset.name);
    else if (action === 'refresh-matrix-backups') refreshMatrixBackups();
    else if (action === 'load-preflight') loadPreflight();
    else if (action === 'load-performance') loadPerformance();
    else if (action === 'load-works-link-queue') loadWorksLinkQueue();
    else if (action === 'render-stats') renderStatsChart(parseInt(el.dataset.days, 10));
    else if (action === 'recent-ranking') loadRecentRanking(parseInt(el.dataset.days, 10));
    else if (action === 'promote-player-fetish') promotePlayerFetish(parseInt(el.dataset.fid, 10), el);
    else if (action === 'edit-fetish') editFetish(parseInt(el.dataset.fid, 10), el);
    else if (action === 'delete-player-fetish') deletePlayerFetish(parseInt(el.dataset.fid, 10), el);
    else if (action === 'edit-fetish-by-id') editFetishById();
    else if (action === 'sort-q-table') sortQTable();
    else if (action === 'toggle-question') toggleQuestion(parseInt(el.dataset.qid, 10));
    else if (action === 'edit-question') editQuestion(parseInt(el.dataset.qid, 10), el);
    else if (action === 'maintenance-edit-fetish') focusMaintenanceEdit(parseInt(el.dataset.fid, 10));
    else if (action === 'maintenance-compare-fetish') focusMaintenanceSimilarity(parseInt(el.dataset.fid, 10), parseInt(el.dataset.otherId, 10));
    else if (action === 'sort-log') sortLogTable(parseInt(el.dataset.col, 10));
    else if (action === 'log-page-prev') loadLogPage(Math.max(1, _logPage - 1));
    else if (action === 'log-page-next') loadLogPage(Math.min(_logPages, _logPage + 1));
    else if (action === 'toggle-fetish-history') toggleFetishHistory(parseInt(el.dataset.fid, 10), el);
    else if (action === 'load-compound-works') loadCompoundWorks();
    else if (action === 'save-compound-works') saveCompoundWorks();
    else if (action === 'delete-compound-works') deleteCompoundWorks(el.dataset.key, parseInt(el.dataset.idA, 10), parseInt(el.dataset.idB, 10));
    else if (action === 'check-similarity') checkSimilarity();
    else if (action === 'merge-fetishes') mergeFetishes();
  });
  document.addEventListener('input', event => {
    const el = event.target.closest('[data-action]');
    if (!el) return;
    if (el.dataset.action === 'filter-log') filterLogTable();
    else if (el.dataset.action === 'fill-id') fillId(el.id, el.dataset.target);
  });
  document.addEventListener('change', event => {
    const el = event.target.closest('[data-action]');
    if (el && el.dataset.action === 'filter-log') filterLogTable();
  });
  if (document.getElementById('recent-rank-chart')) loadRecentRanking(7);
  if (document.getElementById('stats-chart')) renderStatsChart(30);
  const importFile = document.getElementById('matrix-import-file');
  if (importFile) {
    importFile.addEventListener('change', async event => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      document.getElementById('matrix-import-json').value = await file.text();
      document.getElementById('matrix-import-msg').textContent = `${file.name} を読み込みました`;
    });
  }
});
