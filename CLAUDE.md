# へきネイター

性癖を当てるAkinator風Webアプリ。質問に答えると最も確率の高い性癖を診断する。

## アーキテクチャ

- `app.py` — Flask APIサーバー。セッションで回答履歴を管理
- `engine.py` — ベイズ推論エンジン。情報利得で次の質問を選択
- `templates/index.html` — シングルページUI
- `templates/admin.html` — 学習データ量管理ページ
- `data/` — questions.json（40問）/ fetishes.json（64件）/ matrix.json（ローカル用・gitignore済み）

## データ永続化

- `DATABASE_URL` 環境変数があればPostgreSQL（Render）を使用
- なければ `data/matrix.json` にローカル保存
- DBテーブル: `fetishes`, `matrix`（fetish_id × question_id の確率行列）

## 推論ロジック（engine.py）

- ナイーブベイズで事後確率を計算
- 情報利得（エントロピー削減量）が最大の質問を次に選択
- 既出の質問と意味が似ている質問は情報利得を最大40%割り引く（相関ペナルティ）
- 確率が `GUESS_THRESHOLD=0.75` 超 or 質問数が `MAX_QUESTIONS=20` で診断確定
- わからない4連続で診断確定
- `learn()` で正解フィードバックをmatrixに反映（正解性癖を強化・他を弱化）
- 0.5/-0.5（どちらかといえば）の回答も強さに比例して学習
- `add_fetish()` で新しい性癖を追加。現在の回答から事後確率が最も高い既存性癖を自動でテンプレートに使用

## 診断結果の複合判定（app.py）

- `COMPOUND_RATIO=0.55`：2位が1位の55%以上なら複合（例：「SM × ヤンデレ」）
- `TRIPLE_RATIO=0.45`：3位が1位の45%以上なら三重複合
- `PROFILE_MIN_RATIO=0.25` / `PROFILE_MIN_PROB=0.08`：それ以下は「他に該当しそうなジャンル」に表示

## 正誤フィードバックのフロー

1. 診断結果画面で主診断・複合それぞれに ○/× をつける
2. ○をつけた項目を即学習
3. × がある場合、外れた件数分だけ正解を選択できるリストを表示
   - リストは事後確率上位15件・診断済み性癖を除外
4. リストにない場合は名前を入力して追加（同名が既存なら追加せず既存として学習）

## APIエンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| POST | /api/start | セッション開始、最初の質問を返す |
| POST | /api/answer | 回答を受け取り次の質問 or 診断結果を返す |
| POST | /api/back | 直前の回答を取り消して前の質問に戻る |
| POST | /api/confirm | 診断結果の正誤をフィードバック（correct=false時に外れリストを返す） |
| POST | /api/teach | 正解の性癖を教える（学習） |
| POST | /api/add_fetish | 新しい性癖を追加（同名の場合は既存として学習） |
| GET  | /admin | 学習データ量管理ページ（Basic認証必須） |

回答値: `1`=はい / `0.5`=どちらかといえばはい / `0`=わからない / `-0.5`=どちらかといえばいいえ / `-1`=いいえ

## 環境変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `SECRET_KEY` | Flaskセッション署名キー | ハードコード値（本番では必須） |
| `DATABASE_URL` | PostgreSQL接続URL | なし（ローカルJSON使用） |
| `ADMIN_USER` | /admin のBasic認証ユーザー名 | `admin` |
| `ADMIN_PASS` | /admin のBasic認証パスワード | なし（未設定時503） |

## 実行

```bash
# ローカル
python app.py

# 本番（Render）
gunicorn app:app --workers 1 --threads 4
```

## 注意

- `data/matrix.json` は `.gitignore` 済み（学習データをgitに含めない）
- gunicornは `--workers 1` 固定（複数プロセスだとin-memoryのmatrixが分裂するため）
- Termux環境では長いコマンドはスクリプトファイルに書いて実行する
