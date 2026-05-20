"""
fetishes.json の作品リンクをまとめたHTMLレポートを生成する。
ブラウザで開いてリンクをクリックして確認できる。

使い方:
  python check_works_links.py
  → works_review.html を生成
"""
import html as html_lib
import json, re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from services.works_links import work_url_status

with open('data/fetishes.json') as f:
    fetishes = json.load(f)

rows = []
for fe in fetishes:
    for w in fe.get('works', []):
        title = w['title'] if isinstance(w, dict) else w
        url   = w.get('url', '') if isinstance(w, dict) else ''
        asin  = ''
        if url:
            m = re.search(r'/dp/([A-Z0-9]{10})', url)
            asin = m.group(1) if m else ''
        status, _ = work_url_status(w)
        rows.append((fe['name'], title, asin, url, status))

def esc(value, *, quote=True):
    return html_lib.escape(str(value), quote=quote)

html = '''<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>作品リンク確認</title>
<style>
body{font-family:sans-serif;font-size:13px;background:#111;color:#ddd;padding:16px;}
table{border-collapse:collapse;width:100%;}
th{background:#222;padding:6px 10px;text-align:left;position:sticky;top:0;}
td{padding:5px 10px;border-bottom:1px solid #222;vertical-align:top;}
tr:hover td{background:#1a1a1a;}
a{color:#7af0a0;}
.no-url{color:#e94560;}
input{background:#222;color:#ddd;border:1px solid #444;padding:4px 8px;border-radius:4px;margin-bottom:10px;width:300px;}
</style>
</head><body>
<h2>作品リンク確認 ''' + f'（{len(rows)}件）' + '''</h2>
<input type="text" id="q" placeholder="性癖名や作品名で絞り込み..." oninput="filter()">
<table id="tbl">
<tr><th>性癖</th><th>作品タイトル</th><th>ASIN</th><th>状態</th><th>リンク</th></tr>
'''

for fetish_name, title, asin, url, status in rows:
    link = (
        f'<a href="{esc(url)}" target="_blank" rel="noopener">Kindle</a>'
        if url else '<span class="no-url">URLなし</span>'
    )
    html += (
        f'<tr><td>{esc(fetish_name)}</td><td>{esc(title)}</td>'
        f'<td>{esc(asin)}</td><td>{esc(status)}</td><td>{link}</td></tr>\n'
    )

html += '''</table>
<script>
function filter() {
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#tbl tr:not(:first-child)').forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
</script>
</body></html>'''

Path('works_review.html').write_text(html, encoding='utf-8')
print(f'生成完了: works_review.html ({len(rows)}件)')
