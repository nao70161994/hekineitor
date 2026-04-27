"""
matrix_backup.json から learned_priors.json を再生成するスクリプト。
DB再作成後に実行すると、学習済みP(yes)を復元できる。

使い方:
  python restore_matrix.py
  # → data/learned_priors.json が生成される
  # → アプリ再起動時に自動で読み込まれる
"""
import json, os

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BACKUP   = os.path.join(DATA_DIR, 'matrix_backup.json')
OUTPUT   = os.path.join(DATA_DIR, 'learned_priors.json')

def main():
    if not os.path.exists(BACKUP):
        print("data/matrix_backup.json が見つかりません")
        return

    with open(BACKUP) as f:
        matrix = json.load(f)

    yes_m   = matrix['yes']
    total_m = matrix['total']
    nf = len(yes_m)
    nq = len(yes_m[0]) if nf > 0 else 0

    priors = []
    for i in range(nf):
        row = []
        for q in range(nq):
            t = total_m[i][q]
            y = yes_m[i][q]
            row.append(round(y / t, 6) if t > 0 else 0.5)
        priors.append(row)

    with open(OUTPUT, 'w') as f:
        json.dump(priors, f)

    print(f"復元完了: {nf}性癖 × {nq}質問 → {OUTPUT}")

if __name__ == '__main__':
    main()
