import json
import math
import os
import tempfile
import threading

try:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as psycopg2_pool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DATA_DIR              = os.path.join(os.path.dirname(__file__), 'data')
DATABASE_URL          = os.environ.get('DATABASE_URL', '')
PLAYER_FETISH_BASE_ID = 10000  # プレイヤー追加性癖のIDはここから開始（シードIDとの競合防止）

# 質問の3軸構造（best_question で軸の多様性確保・idk連続時の切替に使用）
QUESTION_AXES = [
    ('content',     range(0, 55)),    # 0-54: コンテンツ軸（55問）
    ('abstract',    range(55, 63)),   # 55-62: 抽象軸（8問）
    ('personality', range(63, 87)),   # 63-86: パーソナリティ軸（24問）
]

_conn_pool      = None
_conn_pool_lock = threading.Lock()

def _get_pool():
    global _conn_pool
    if _conn_pool is None:
        with _conn_pool_lock:
            if _conn_pool is None:
                url = DATABASE_URL
                if url.startswith('postgres://'):
                    url = url.replace('postgres://', 'postgresql://', 1)
                _conn_pool = psycopg2_pool.SimpleConnectionPool(2, 20, url, sslmode='require')
    return _conn_pool

# (fetish_idx, question_idx, probability)
DOMAIN_PRIORS = [
    # NTR(0): 裏切り・嫉妬・禁断・受け身・秘密
    (0,8,0.95),(0,6,0.7),(0,0,0.5),(0,1,0.4),(0,3,0.4),(0,37,0.4),
    # 百合(1): 同性・強い女性・甘い・嫉妬
    (1,9,0.95),(1,31,0.6),(1,5,0.3),(1,6,0.3),
    # BL(2): 同性・力関係・禁断
    (2,9,0.95),(2,0,0.4),(2,1,0.3),(2,15,0.2),
    # SM(3): 力関係・恐怖痛み・拘束・所有物・受け身
    (3,0,0.95),(3,7,0.8),(3,22,0.8),(3,4,0.7),(3,3,0.6),
    # ケモノ(4): 非人間・体が違う・変身・ファンタジー世界
    (4,10,0.9),(4,11,0.85),(4,25,0.7),(4,38,0.5),
    # 触手(5): 非人間・体が違う・拘束・受け身・恐怖
    (5,10,0.9),(5,11,0.85),(5,22,0.8),(5,3,0.7),(5,7,0.5),
    # 年上攻め(6): 年上・力関係・体格差・献身
    (6,12,0.9),(6,0,0.4),(6,30,0.4),(6,36,0.4),
    # 年下攻め(7): 年下・幼い見た目
    (7,13,0.9),(7,29,0.4),(7,0,0.3),
    # 義兄妹(8): 禁断・血縁・秘密・幼馴染的
    (8,1,0.9),(8,26,0.7),(8,37,0.6),(8,14,0.5),
    # 師弟(9): 力関係・禁断・雇用・日常・秘密
    (9,0,0.7),(9,1,0.7),(9,27,0.5),(9,18,0.5),(9,37,0.4),
    # ヤンデレ(10): 執着・嫉妬・所有物・恐怖・復讐
    (10,2,0.95),(10,6,0.9),(10,4,0.7),(10,7,0.4),(10,21,0.3),
    # TSF(11): 性別曖昧・変身・同性的
    (11,15,0.95),(11,25,0.6),(11,9,0.2),
    # ハーレム(12): 3人以上・複数同時・甘い・異世界
    (12,16,0.9),(12,24,0.6),(12,5,0.5),(12,17,0.4),
    # 逆ハーレム(13): 3人以上・複数同時・強い女性
    (13,16,0.9),(13,24,0.6),(13,31,0.6),
    # モンスター娘(14): 非人間・体が違う・ファンタジー世界・強い女性
    (14,10,0.9),(14,11,0.8),(14,38,0.6),(14,31,0.5),
    # 吸血鬼(15): 非人間・永遠の命・超常・力関係
    (15,10,0.9),(15,34,0.9),(15,33,0.5),(15,0,0.4),
    # 幼馴染(16): 幼い頃から知っている・甘い・日常・秘密
    (16,14,0.95),(16,5,0.7),(16,18,0.6),(16,37,0.4),
    # 溺愛(17): 執着・甘い・献身的・嫉妬
    (17,2,0.9),(17,5,0.8),(17,36,0.8),(17,6,0.6),
    # 調教洗脳(18): 思考コントロール・力関係・所有物・拘束・恐怖
    (18,23,0.95),(18,0,0.9),(18,4,0.8),(18,22,0.7),(18,7,0.6),
    # 女装(19): 性別曖昧・幼い見た目・同性的
    (19,15,0.6),(19,29,0.4),(19,9,0.3),
    # 百合NTR(20): 同性・裏切り・嫉妬
    (20,9,0.9),(20,8,0.9),(20,6,0.7),
    # 異世界転生チート(21): 異世界・チート・超常・ファンタジー種族
    (21,17,0.95),(21,19,0.9),(21,33,0.7),(21,38,0.5),
    # 復讐・ざまぁ(22): 復讐・最初弱い・チート・対立から
    (22,21,0.95),(22,32,0.8),(22,19,0.5),(22,20,0.3),
    # ツンデレ(23): 対立から惹かれ・クール・甘い・日常
    (23,20,0.9),(23,35,0.5),(23,5,0.5),(23,18,0.5),
    # お姉さん・熟女(24): 年上・強い女性・体格差・献身
    (24,12,0.9),(24,31,0.7),(24,30,0.6),(24,36,0.5),
    # ロリ・幼女(25): 年下・幼い見た目・甘い
    (25,13,0.8),(25,29,0.9),(25,5,0.4),
    # 身長差・体格差(26): 体格差・力関係・年上
    (26,30,0.95),(26,0,0.4),(26,12,0.3),
    # メイド・主従関係(27): 雇用・力関係・献身・日常
    (27,27,0.95),(27,0,0.7),(27,36,0.7),(27,18,0.4),
    # アンドロイド・ロボ娘(28): 機械・非人間・献身・思考コントロール
    (28,28,0.95),(28,10,0.8),(28,36,0.5),(28,23,0.4),
    # エルフ・ファンタジー種族(29): ファンタジー世界・非人間・永遠の命・超常
    (29,38,0.9),(29,10,0.7),(29,34,0.8),(29,33,0.5),
    # 近親相姦(30): 血縁・禁断・秘密
    (30,26,0.95),(30,1,0.8),(30,37,0.6),
    # クーデレ(31): クール・特別反応・甘い・対立から
    (31,35,0.95),(31,39,0.9),(31,5,0.5),(31,20,0.4),
    # 感覚遮断落とし穴(32): 拘束・受け身・恐怖・力関係・禁断
    (32,22,0.95),(32,3,0.9),(32,7,0.8),(32,0,0.7),(32,1,0.5),(32,23,0.4),
    # 人格排泄(33): 思考コントロール・所有物・変身的変容・力関係・恐怖
    (33,23,0.95),(33,4,0.9),(33,25,0.8),(33,0,0.8),(33,7,0.7),(33,3,0.6),
    # 催眠術(34): 思考コントロール・力関係・受け身・所有物・拘束
    (34,23,0.95),(34,0,0.8),(34,3,0.75),(34,4,0.65),(34,22,0.4),
    # オメガバース(35): 力関係・執着・禁断・所有物・甘い
    (35,0,0.85),(35,2,0.75),(35,1,0.65),(35,4,0.6),(35,5,0.35),
    # 悪役令嬢(36): 対立から・異世界・禁断・復讐・チート
    (36,20,0.9),(36,17,0.75),(36,1,0.65),(36,21,0.55),(36,19,0.45),
    # 女騎士・女戦士(37): 強い女性・対立から・ファンタジー・力関係・体格差
    (37,31,0.9),(37,20,0.7),(37,38,0.65),(37,0,0.55),(37,30,0.35),
    # 孕ませ・子作り(38): 所有物・執着・力関係・体の変化・甘い
    (38,4,0.75),(38,2,0.65),(38,0,0.55),(38,25,0.5),(38,5,0.3),
    # 後輩×先輩(39): 日常・秘密・禁断・甘い・力関係
    (39,18,0.9),(39,37,0.7),(39,1,0.55),(39,5,0.5),(39,0,0.45),
    # メスガキ・小悪魔(40): 幼い見た目・年下・受け身・力関係・対立から
    (40,29,0.85),(40,13,0.75),(40,3,0.7),(40,0,0.7),(40,20,0.5),
    # 強引な女性・逆押し(41): 強い女性・力関係・受け身・恐怖
    (41,31,0.9),(41,0,0.85),(41,3,0.85),(41,7,0.4),(41,30,0.35),
    # 職場・社内恋愛(42): 日常・秘密・禁断・力関係・年上
    (42,18,0.9),(42,37,0.8),(42,1,0.7),(42,0,0.55),(42,12,0.4),
    # 魔法少女(43): 変身・超常・幼い見た目・強い女性・ファンタジー
    (43,25,0.9),(43,33,0.85),(43,29,0.55),(43,31,0.55),(43,38,0.45),
    # 聖女・清楚ヒロイン(44): 献身・甘い・超常・秘密・ファンタジー
    (44,36,0.9),(44,5,0.75),(44,33,0.6),(44,38,0.5),(44,37,0.35),
    # 乱交・多人数(45): 複数同時・3人以上・受け身・力関係
    (45,24,0.95),(45,16,0.9),(45,3,0.6),(45,0,0.5),(45,7,0.3),
    # ショタ(46): 幼い見た目・年下・体格差
    (46,29,0.9),(46,13,0.85),(46,30,0.65),(46,0,0.5),(46,15,0.3),
    # 獣耳メイド(47): 体が違う・献身・雇用・甘い・幼い見た目
    (47,11,0.8),(47,36,0.85),(47,27,0.8),(47,5,0.65),(47,29,0.4),
    # 堕天使・悪魔っ娘(48): 非人間・超常・禁断・力関係・体が違う
    (48,10,0.9),(48,33,0.85),(48,1,0.75),(48,0,0.6),(48,11,0.5),
    # ゾンビ・アンデッド(49): 非人間・体が違う・永遠の命・恐怖・超常
    (49,10,0.9),(49,11,0.85),(49,34,0.7),(49,7,0.6),(49,33,0.6),
    # 人魚・水棲系(50): 体が違う・非人間・ファンタジー・甘い・禁断
    (50,11,0.9),(50,10,0.85),(50,38,0.75),(50,5,0.55),(50,1,0.5),
    # 幼なじみNTR(51): 幼い頃から・裏切り・嫉妬・秘密
    (51,14,0.95),(51,8,0.9),(51,6,0.8),(51,37,0.6),(51,1,0.5),
    # 寝取らせ(52): 裏切り・嫉妬・禁断・秘密・複数同時
    (52,8,0.85),(52,6,0.75),(52,1,0.7),(52,37,0.6),(52,24,0.5),
    # 友人の彼女・人妻(53): 禁断・秘密・裏切り・嫉妬・日常
    (53,1,0.9),(53,37,0.85),(53,8,0.8),(53,6,0.6),(53,18,0.6),
    # 双子・クローン(54): 複数同時・3人以上・秘密・体が違う
    (54,24,0.8),(54,16,0.7),(54,37,0.6),(54,11,0.45),(54,5,0.4),
    # 公開羞恥・露出(55): 受け身・力関係・禁断・恐怖・拘束
    (55,3,0.85),(55,0,0.75),(55,1,0.75),(55,7,0.6),(55,22,0.5),
    # 媚薬・薬物(56): 思考コントロール・受け身・力関係・所有物・禁断
    (56,23,0.85),(56,3,0.8),(56,0,0.75),(56,4,0.55),(56,1,0.6),
    # 夢・異空間(57): 超常・秘密・変身・禁断・ファンタジー
    (57,33,0.85),(57,37,0.65),(57,25,0.45),(57,1,0.5),(57,38,0.5),
    # 前世・輪廻転生(58): 永遠の命・幼い頃から・超常・甘い・禁断
    (58,34,0.85),(58,14,0.75),(58,33,0.7),(58,5,0.55),(58,1,0.45),
    # 牢獄・監禁(59): 拘束・力関係・受け身・所有物・禁断
    (59,22,0.95),(59,0,0.85),(59,3,0.8),(59,4,0.75),(59,1,0.6),
    # 時間停止(60): 超常・受け身・力関係・所有物・拘束
    (60,33,0.9),(60,3,0.85),(60,0,0.8),(60,4,0.65),(60,22,0.5),
    # 縮小・巨大化(61): 体格差・体が違う・超常・力関係
    (61,30,0.95),(61,11,0.75),(61,33,0.8),(61,0,0.6),(61,10,0.35),
    # 分身・複数存在(62): 複数同時・3人以上・変身・超常・秘密
    (62,24,0.85),(62,16,0.75),(62,25,0.65),(62,33,0.7),(62,37,0.4),
    # ゲーム世界転移(63): 異世界・チート・超常・変身・力関係
    (63,17,0.9),(63,19,0.75),(63,33,0.65),(63,25,0.45),(63,0,0.4),
    # 熟女(64): 年上・強い女性・甘い・男性向け
    (64,12,0.95),(64,31,0.75),(64,5,0.55),(64,0,0.3),(64,64,0.7),
    # 同棲・ルームシェア(65): 日常・甘い・精神的繋がり・一対一
    (65,18,0.9),(65,5,0.8),(65,61,0.65),(65,70,0.75),
    # 記憶喪失(66): 精神的繋がり・一方通行・幼い頃からの縁
    (66,61,0.8),(66,55,0.7),(66,14,0.4),(66,45,0.35),
    # 入れ替わり(67): 体が変化・立場逆転・精神的繋がり・性別曖昧
    (67,25,0.9),(67,59,0.85),(67,61,0.65),(67,15,0.45),
    # 格差婚・シンデレラ(68): 力関係・禁断・立場逆転・秘密・最初は弱い
    (68,0,0.75),(68,1,0.65),(68,59,0.7),(68,37,0.6),(68,32,0.7),
    # 魔王×勇者(69): 対立から惹かれ・異世界・力関係・禁断・超常
    (69,20,0.95),(69,17,0.9),(69,33,0.8),(69,0,0.75),(69,1,0.65),
    # 王族・貴族(70): 異世界・力関係・禁断・秘密・雇用関係
    (70,17,0.75),(70,0,0.7),(70,1,0.6),(70,37,0.55),(70,27,0.5),
    # お嬢様・令嬢(71): 甘い・献身・日常・禁断
    (71,5,0.65),(71,36,0.55),(71,18,0.5),(71,1,0.45),(71,27,0.4),
    # 巫女・神社(72): 超常・禁断・秘密・非人間との関係・堕ちる
    (72,33,0.85),(72,1,0.7),(72,37,0.6),(72,10,0.6),(72,57,0.5),
    # ギャル(73): 日常・甘い・対立から・刺激好き
    (73,18,0.9),(73,5,0.7),(73,20,0.5),(73,73,0.75),
    # アイドル・推し活(74): 一方通行・執着・秘密・嫉妬・日常
    (74,55,0.85),(74,2,0.65),(74,37,0.7),(74,6,0.55),(74,18,0.6),
    # 陰キャ・オタク男子(75): 最初は弱い・日常・甘い・一人でいる時間
    (75,32,0.7),(75,18,0.7),(75,5,0.6),(75,85,0.8),
    # 天使(76): 非人間・超常・禁断・精神的繋がり・甘い
    (76,10,0.9),(76,33,0.8),(76,1,0.65),(76,61,0.65),(76,5,0.6),
    # 竜・ドラゴン(77): 非人間・異種族共存・超常・力関係・体の形が違う
    (77,10,0.9),(77,38,0.85),(77,33,0.75),(77,11,0.75),(77,0,0.65),
    # 妖怪・物の怪(78): 非人間・超常・禁断・永遠の命・秘密
    (78,10,0.9),(78,33,0.75),(78,1,0.7),(78,34,0.65),(78,37,0.6),
    # フタナリ・両性具有(79): 性別曖昧・体の変化・欲望・受け身
    (79,15,0.9),(79,25,0.7),(79,62,0.6),(79,3,0.5),
    # 呪い・祟り(80): 超常・共依存・執着・秘密・非人間
    (80,33,0.8),(80,60,0.85),(80,2,0.6),(80,37,0.55),(80,10,0.5),
    # 武道・格闘(81): 力関係・対立から・命がけ・強い女性・格好いい
    (81,0,0.8),(81,20,0.7),(81,58,0.9),(81,31,0.6),(81,68,0.75),
    # VTuber・配信者(82): 一方通行・秘密・日常・未来SF好き
    (82,55,0.8),(82,37,0.75),(82,18,0.55),(82,82,0.65),
]

PSEUDO = 20

# 関連性癖マップ（包含・重複関係）
FETISH_RELATIONS = {
    0:  [20],          # NTR → 百合NTR
    1:  [20],          # 百合 → 百合NTR
    3:  [18, 32, 33],  # SM → 調教・感覚遮断・人格支配
    4:  [14, 29],      # ケモノ → モンスター娘・エルフ
    6:  [24],          # 年上攻め → お姉さん
    7:  [25],          # 年下攻め → ロリ
    8:  [30],          # 義兄妹 → 近親相姦
    10: [17],          # ヤンデレ → 溺愛
    11: [19],          # TSF → 女装
    12: [13],          # ハーレム → 逆ハーレム
    13: [12],          # 逆ハーレム → ハーレム
    14: [4, 29],       # モンスター娘 → ケモノ・エルフ
    17: [10],          # 溺愛 → ヤンデレ
    18: [3, 33],       # 調教 → SM・人格支配
    19: [11],          # 女装 → TSF
    20: [0, 1],        # 百合NTR → NTR・百合
    21: [29],          # 異世界転生 → エルフ
    24: [6],           # お姉さん → 年上攻め
    25: [7],           # ロリ → 年下攻め
    29: [4, 14, 21],   # エルフ → ケモノ・モンスター娘・異世界転生
    30: [8],           # 近親相姦 → 義兄妹
    32: [3, 18],       # 感覚遮断 → SM・調教
    33: [18, 32],      # 人格支配 → 調教・感覚遮断
    34: [18, 33],      # 催眠術 → 調教・人格支配
    35: [3, 17],       # オメガバース → SM・溺愛
    36: [21, 22],      # 悪役令嬢 → 異世界転生・復讐
    37: [24, 41],      # 女騎士 → お姉さん・強引な女性
    38: [17, 35],      # 孕ませ → 溺愛・オメガバース
    39: [9, 6],        # 後輩×先輩 → 師弟・年上攻め
    40: [25, 7],       # メスガキ → ロリ・年下攻め
    41: [13, 37],      # 強引な女性 → 逆ハーレム・女騎士
    42: [9, 6],        # 職場恋愛 → 師弟・年上攻め
    43: [11, 25],      # 魔法少女 → TSF・ロリ
    44: [17, 27],      # 聖女 → 溺愛・メイド
    45: [12, 13],      # 乱交 → ハーレム・逆ハーレム
    46: [7, 25, 19],   # ショタ → 年下攻め・ロリ・女装
    47: [4, 27],       # 獣耳メイド → ケモノ・メイド
    48: [15, 3],       # 堕天使 → 吸血鬼・SM
    49: [15, 34],      # ゾンビ → 吸血鬼・永遠の命(催眠)
    50: [14, 29],      # 人魚 → モンスター娘・エルフ
    51: [0, 16],       # 幼なじみNTR → NTR・幼馴染
    52: [0, 20],       # 寝取らせ → NTR・百合NTR
    53: [0, 42],       # 人妻 → NTR・職場恋愛
    54: [45, 12],      # 双子 → 乱交・ハーレム
    55: [32, 3],       # 公開羞恥 → 感覚遮断・SM
    56: [34, 18],      # 媚薬 → 催眠術・調教
    57: [21, 58],      # 夢 → 異世界転生・前世
    58: [16, 57],      # 前世 → 幼馴染・夢
    59: [32, 3],       # 監禁 → 感覚遮断・SM
    60: [34, 59],      # 時間停止 → 催眠術・監禁
    61: [26, 14],      # 縮小巨大化 → 身長差・モンスター娘
    62: [45, 54],      # 分身 → 乱交・双子
    63: [21, 28],      # ゲーム世界 → 異世界転生・アンドロイド
    64: [6, 24],       # 熟女 → 年上攻め・お姉さん
    65: [16, 17],      # 同棲 → 幼馴染・溺愛
    66: [58, 16],      # 記憶喪失 → 前世・幼馴染
    67: [11, 59],      # 入れ替わり → TSF・立場逆転（時間停止）
    68: [70, 71],      # 格差婚 → 王族・貴族・お嬢様
    69: [37, 81],      # 魔王×勇者 → 女騎士・武道
    70: [68, 71],      # 王族・貴族 → 格差婚・お嬢様
    71: [70, 68, 24],  # お嬢様 → 王族・格差婚・お姉さん
    72: [78, 76],      # 巫女 → 妖怪・天使
    73: [23, 75],      # ギャル → ツンデレ・陰キャ
    74: [82],          # アイドル → VTuber
    75: [73, 23],      # 陰キャ → ギャル・ツンデレ
    76: [48, 72],      # 天使 → 堕天使・巫女
    77: [4, 14, 69],   # 竜 → ケモノ・モンスター娘・魔王×勇者
    78: [15, 72, 80],  # 妖怪 → 吸血鬼・巫女・呪い
    79: [11, 19],      # フタナリ → TSF・女装
    80: [78, 72],      # 呪い → 妖怪・巫女
    81: [69, 37],      # 武道 → 魔王×勇者・女騎士
    82: [74, 28],      # VTuber → アイドル・アンドロイド
}

# 各性癖の相対的な出現頻度（事前確率の重み）。未登録は 1.0
FETISH_PRIOR_WEIGHTS = {
    # 非常に人気（3倍）
    0: 3.0, 10: 3.0, 23: 3.0,
    # 人気（2〜2.5倍）
    1: 2.0, 2: 2.0, 3: 2.0, 8: 2.0, 12: 2.0, 15: 2.0, 16: 2.5,
    17: 2.5, 18: 2.0, 21: 2.5, 22: 2.0, 25: 2.0, 36: 2.0,
    # やや人気（1.5〜1.8倍）
    5: 1.8, 6: 1.8, 7: 1.8, 9: 1.8, 11: 1.8, 13: 1.8, 24: 1.8,
    27: 1.8, 35: 1.8, 37: 1.8, 40: 1.8, 47: 1.8, 64: 1.8, 65: 1.5,
    73: 1.8, 74: 1.5, 81: 1.5,
    # ニッチ（0.5〜0.7倍）
    32: 0.5, 33: 0.6, 49: 0.5, 50: 0.6, 61: 0.5, 62: 0.5, 79: 0.6, 82: 0.6,
}

# 質問軸ごとの間接性ボーナス（情報利得が同程度なら間接的な軸を優先）
AXIS_INDIRECT_BONUS = {'content': 1.0, 'abstract': 1.01, 'personality': 1.02}


def _use_db():
    return bool(DATABASE_URL) and HAS_PSYCOPG2


def _get_conn():
    return _get_pool().getconn()

def _put_conn(conn):
    _get_pool().putconn(conn)


def _build_initial_matrix(nf, nq):
    alpha = 2.0
    yes   = [[alpha]       * nq for _ in range(nf)]
    total = [[alpha * 2.0] * nq for _ in range(nf)]
    for f, q, p in DOMAIN_PRIORS:
        yes[f][q]   = p * PSEUDO
        total[f][q] = float(PSEUDO)
    return yes, total


class Engine:
    def __init__(self):
        self._lock = threading.Lock()
        self.questions = self._load_json('questions.json')
        if _use_db():
            self._ensure_db()
            self.fetishes = self._load_fetishes_from_db()
            self.matrix   = self._load_from_db()
        else:
            self.fetishes = self._load_json('fetishes.json')
            self.matrix   = self._load_matrix_file()

    # ── JSON ローカル ──────────────────────────────────────
    def _load_json(self, fname):
        with open(os.path.join(DATA_DIR, fname), encoding='utf-8') as f:
            return json.load(f)

    def _load_matrix_file(self):
        path = os.path.join(DATA_DIR, 'matrix.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                m = json.load(f)
            nf = len(self.fetishes)
            nq = len(self.questions)
            if len(m.get('yes', [])) == nf and nf > 0 and len(m['yes'][0]) == nq:
                return m
            os.remove(path)
        return self._init_matrix_file()

    def _init_matrix_file(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        yes, total = _build_initial_matrix(nf, nq)
        m = {'yes': yes, 'total': total}
        self.matrix = m
        self._save_matrix_file()
        return m

    def _atomic_write(self, path, data, **kwargs):
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix='.tmp')
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, **kwargs)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _save_matrix_file(self):
        self._atomic_write(os.path.join(DATA_DIR, 'matrix.json'), self.matrix)

    def _save_fetishes_file(self):
        self._atomic_write(
            os.path.join(DATA_DIR, 'fetishes.json'),
            self.fetishes,
            ensure_ascii=False, indent=2,
        )

    # ── PostgreSQL ─────────────────────────────────────────
    def _ensure_db(self):
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS fetishes (
                        id   INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        "desc" TEXT NOT NULL
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS matrix (
                        fetish_id   INTEGER,
                        question_id INTEGER,
                        yes_count   REAL NOT NULL,
                        total_count REAL NOT NULL,
                        PRIMARY KEY (fetish_id, question_id)
                    )
                ''')
                cur.execute('SELECT COUNT(*) FROM fetishes')
                if cur.fetchone()[0] == 0:
                    seed_fetishes = self._load_json('fetishes.json')
                    psycopg2.extras.execute_values(
                        cur,
                        'INSERT INTO fetishes (id, name, "desc") VALUES %s',
                        [(f['id'], f['name'], f['desc']) for f in seed_fetishes]
                    )
                cur.execute('SELECT COUNT(*) FROM matrix')
                if cur.fetchone()[0] == 0:
                    seed_fetishes = self._load_json('fetishes.json')
                    self._seed_db(cur, seed_fetishes)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS stats (
                        key   TEXT PRIMARY KEY,
                        value INTEGER NOT NULL DEFAULT 0
                    )
                ''')
                for k in ('learn_count', 'play_count'):
                    cur.execute(
                        "INSERT INTO stats (key, value) VALUES (%s, 0) ON CONFLICT DO NOTHING", (k,)
                    )
                # 新しい性癖を fetishes.json から差分追加（マイグレーション）
                cur.execute('SELECT id FROM fetishes')
                existing_ids = {r[0] for r in cur.fetchall()}
                if existing_ids is not None:
                    seed = self._load_json('fetishes.json')
                    new_f = [f for f in seed if f['id'] not in existing_ids]
                    if new_f:
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO fetishes (id, name, "desc") VALUES %s ON CONFLICT DO NOTHING',
                            [(f['id'], f['name'], f['desc']) for f in new_f]
                        )
                        nq = len(self.questions)
                        nf_total = len(seed)
                        full_yes, full_total = _build_initial_matrix(nf_total, nq)
                        new_rows = [
                            (f['id'], q, full_yes[f['id']][q], full_total[f['id']][q])
                            for f in new_f for q in range(nq)
                        ]
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                            new_rows
                        )
                    # 既存性癖の名前・説明を fetishes.json と同期
                    for f in seed:
                        cur.execute(
                            'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                            (f['name'], f['desc'], f['id'])
                        )
                # 新しい質問を matrix に差分追加
                nq = len(self.questions)
                cur.execute('SELECT MAX(question_id) FROM matrix')
                max_qid = cur.fetchone()[0]
                if max_qid is not None and max_qid < nq - 1:
                    cur.execute('SELECT id FROM fetishes')
                    all_fids = [row[0] for row in cur.fetchall()]
                    alpha = 2.0
                    new_q_rows = [
                        (fid, q, alpha, alpha * 2.0)
                        for fid in all_fids
                        for q in range(max_qid + 1, nq)
                    ]
                    if new_q_rows:
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s ON CONFLICT DO NOTHING',
                            new_q_rows
                        )
        finally:
            _put_conn(conn)

    def _load_fetishes_from_db(self):
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT id, name, "desc" FROM fetishes ORDER BY id')
            return [{'id': r[0], 'name': r[1], 'desc': r[2]} for r in cur.fetchall()]
        finally:
            _put_conn(conn)

    def _seed_db(self, cur, fetishes=None):
        if fetishes is None:
            fetishes = self.fetishes
        nq = len(self.questions)
        alpha = 2.0
        rows = [
            (f['id'], q, alpha, alpha * 2.0)
            for f in fetishes for q in range(nq)
        ]
        psycopg2.extras.execute_values(
            cur,
            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
            rows
        )

    def _load_from_db(self):
        nf = len(self.fetishes)
        nq = len(self.questions)
        id_to_idx = {f['id']: i for i, f in enumerate(self.fetishes)}
        yes   = [[0.0] * nq for _ in range(nf)]
        total = [[0.0] * nq for _ in range(nf)]
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT fetish_id, question_id, yes_count, total_count FROM matrix')
            for f_id, q, y, t in cur.fetchall():
                idx = id_to_idx.get(f_id)
                if idx is not None and 0 <= q < nq:
                    yes[idx][q]   = y
                    total[idx][q] = t
        finally:
            _put_conn(conn)
        return {'yes': yes, 'total': total}

    def _increment_stat(self, key):
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value = stats.value + 1",
                        (key,)
                    )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats.json')
            try:
                with open(path, encoding='utf-8') as f:
                    s = json.load(f)
            except (OSError, json.JSONDecodeError):
                s = {}
            s[key] = s.get(key, 0) + 1
            self._atomic_write(path, s)

    def _increment_learn_count(self):
        self._increment_stat('learn_count')

    def increment_play_count(self):
        self._increment_stat('play_count')

    def get_stats(self):
        keys = ('play_count', 'learn_count')
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT key, value FROM stats WHERE key = ANY(%s)", (list(keys),))
                result = dict(cur.fetchall())
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats.json')
            try:
                with open(path, encoding='utf-8') as f:
                    result = json.load(f)
            except (OSError, json.JSONDecodeError):
                result = {}
        return {k: result.get(k, 0) for k in keys}

    def _save_to_db(self, all_updates):
        if not all_updates:
            return
        rows = [
            (self.fetishes[fetish_idx]['id'], q_idx, delta_yes, delta_total)
            for fetish_idx, updates in all_updates.items()
            for q_idx, delta_yes, delta_total in updates
            if fetish_idx < len(self.fetishes)
        ]
        conn = _get_conn()
        try:
            with conn:
                cur = conn.cursor()
                cur.executemany('''
                    INSERT INTO matrix (fetish_id, question_id, yes_count, total_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (fetish_id, question_id) DO UPDATE
                    SET yes_count   = matrix.yes_count   + EXCLUDED.yes_count,
                        total_count = matrix.total_count + EXCLUDED.total_count
                ''', rows)
        finally:
            _put_conn(conn)

    # ── 推論 ───────────────────────────────────────────────
    def _prob(self, f, q):
        y = self.matrix['yes'][f][q]
        t = self.matrix['total'][f][q]
        if t == 0:
            return 0.5
        return max(min(y / t, 0.999), 0.001)

    def posteriors(self, answers):
        nf = len(self.fetishes)
        nq = len(self.questions)
        log_p = [math.log(FETISH_PRIOR_WEIGHTS.get(self.fetishes[f]['id'], 1.0))
                 for f in range(nf)]
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if ans == 0 or not (0 <= q < nq):
                continue
            weight = abs(ans)
            for f in range(nf):
                p = self._prob(f, q)
                log_p[f] += weight * (math.log(p) if ans > 0 else math.log(1 - p))
        mx = max(log_p)
        probs = [math.exp(lp - mx) for lp in log_p]
        s = sum(probs)
        return [p / s for p in probs]

    def _question_axis(self, q):
        for name, r in QUESTION_AXES:
            if q in r:
                return name
        return None

    def best_question(self, answers, asked, idk_streak=0):
        probs      = self.posteriors(answers)
        h0         = self._entropy(probs)
        nf         = len(self.fetishes)
        asked_list = list(asked)

        asked_axes = {self._question_axis(qa) for qa in asked_list}
        asked_axes.discard(None)
        all_axis_names = {name for name, _ in QUESTION_AXES}

        # 軸フィルタリング: idk連続なら抽象/パーソナリティへ、序盤は未カバーの軸を優先
        if idk_streak >= 2:
            axis_filter = {'abstract', 'personality'}
        elif len(asked_list) < 3 and (all_axis_names - asked_axes):
            axis_filter = all_axis_names - asked_axes
        else:
            axis_filter = None

        q_vecs = {}
        for qa in asked_list:
            q_vecs[qa] = [self._prob(f, qa) for f in range(nf)]

        best_filtered_q, best_filtered_s = None, -1.0
        best_any_q,      best_any_s      = None, -1.0

        for q in range(len(self.questions)):
            if q in asked:
                continue
            p_yes = sum(probs[f] * self._prob(f, q) for f in range(nf))
            p_no  = 1.0 - p_yes
            if p_yes < 0.01 or p_no < 0.01:
                continue
            py = [probs[f] * self._prob(f, q) for f in range(nf)]
            sy = sum(py); py = [v / sy for v in py]
            pn = [probs[f] * (1 - self._prob(f, q)) for f in range(nf)]
            sn = sum(pn); pn = [v / sn for v in pn]
            score = h0 - (p_yes * self._entropy(py) + p_no * self._entropy(pn))
            # 識別力ペナルティ: P(yes|f) が全性癖で 0.5 に集中している質問を弱化
            disc = sum(abs(self._prob(f, q) - 0.5) for f in range(nf)) / nf
            score *= min(1.0, max(0.2, disc / 0.08))
            if asked_list:
                v_q = [self._prob(f, q) for f in range(nf)]
                n_q = math.sqrt(sum(a**2 for a in v_q))
                max_sim = 0.0
                for qa, v_qa in q_vecs.items():
                    if n_q == 0:
                        sim = 0.0
                    else:
                        n_qa = math.sqrt(sum(a**2 for a in v_qa))
                        sim = sum(a * b for a, b in zip(v_q, v_qa)) / (n_q * n_qa) if n_qa else 0.0
                    if sim > max_sim:
                        max_sim = sim
                score *= (1.0 - 0.4 * max_sim)
            axis_name = self._question_axis(q)
            weighted = score * AXIS_INDIRECT_BONUS.get(axis_name, 1.0)
            if axis_filter is None or axis_name in axis_filter:
                if weighted > best_filtered_s:
                    best_filtered_s = weighted
                    best_filtered_q = q
            if weighted > best_any_s:
                best_any_s = weighted
                best_any_q = q

        # 軸フィルタで該当が無ければ全体ベストにフォールバック
        return best_filtered_q if best_filtered_q is not None else best_any_q

    def get_learning_stats(self):
        nq = len(self.questions)
        prior_qs = {}
        for f, q, _ in DOMAIN_PRIORS:
            prior_qs.setdefault(f, set()).add(q)
        stats = []
        for f, fetish in enumerate(self.fetishes):
            n_prior  = len(prior_qs.get(f, set()))
            baseline = n_prior * float(PSEUDO) + (nq - n_prior) * 4.0
            data_weight = sum(self.matrix['total'][f]) - baseline
            stats.append({
                'id':          f,
                'name':        fetish['name'],
                'data_weight': round(data_weight, 1),
            })
        return sorted(stats, key=lambda x: x['data_weight'])

    def get_question_stats(self):
        """各質問の識別力を返す（識別力 = 各性癖でP(yes)が0.5からどれだけ離れているかの平均）。"""
        nf = len(self.fetishes)
        result = []
        for q, qdata in enumerate(self.questions):
            probs = [self._prob(f, q) for f in range(nf)]
            disc  = sum(abs(p - 0.5) for p in probs) / nf  # 0〜0.5; 高いほど識別力あり
            result.append({
                'id':   q,
                'text': qdata['text'],
                'disc': round(disc, 3),
            })
        return sorted(result, key=lambda x: x['disc'])

    def top_guess(self, answers, n=1):
        probs   = self.posteriors(answers)
        ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
        top     = ranked[:n]
        if n == 1:
            return top[0], probs[top[0]]
        return [(f, probs[f]) for f in top]

    def learn(self, answers, fetish_idx):
        neg_weight = 0.3
        all_updates = {}

        with self._lock:
            nf = len(self.fetishes)
            nq = len(self.questions)
            if not (0 <= fetish_idx < nf):
                return
            for q_str, ans in answers.items():
                try:
                    q = int(q_str)
                except (ValueError, TypeError):
                    continue
                if ans == 0 or not (0 <= q < nq):
                    continue
                strength = abs(ans)
                # 蓄積データが多いほど1セッションの影響を小さくする（汚染対策）
                scale = min(1.0, PSEUDO / max(self.matrix['total'][fetish_idx][q], PSEUDO))
                effective = strength * scale

                delta_yes = effective if ans > 0 else 0.0
                self.matrix['total'][fetish_idx][q] += effective
                self.matrix['yes'][fetish_idx][q]   += delta_yes
                all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))

                for f in range(nf):
                    if f == fetish_idx:
                        continue
                    w = neg_weight * effective
                    neg_yes = w * (0.0 if ans > 0 else 1.0)
                    self.matrix['total'][f][q] += w
                    self.matrix['yes'][f][q]   += neg_yes
                    all_updates.setdefault(f, []).append((q, neg_yes, w))

            if not _use_db():
                self._save_matrix_file()

        if _use_db():
            self._save_to_db(all_updates)

        self._increment_learn_count()

    def learn_negative(self, answers, fetish_idx):
        """fetish_idx が外れだった弱いネガティブ更新。learn() の約1/5の強度。"""
        neg_str = 0.2
        all_updates = {}
        with self._lock:
            nf = len(self.fetishes)
            nq = len(self.questions)
            if not (0 <= fetish_idx < nf):
                return
            for q_str, ans in answers.items():
                try:
                    q = int(q_str)
                except (ValueError, TypeError):
                    continue
                if ans == 0 or not (0 <= q < nq):
                    continue
                strength = abs(ans) * neg_str
                scale = min(1.0, PSEUDO / max(self.matrix['total'][fetish_idx][q], PSEUDO))
                effective = strength * scale
                # yes回答 → このfetishはyesしにくい方向: total++, yes据え置き
                # no回答  → このfetishはnoしにくい方向: yes++, total++
                dy = 0.0 if ans > 0 else effective
                self.matrix['yes'][fetish_idx][q]   += dy
                self.matrix['total'][fetish_idx][q] += effective
                all_updates.setdefault(fetish_idx, []).append((q, dy, effective))
            if not _use_db():
                self._save_matrix_file()
        if _use_db():
            self._save_to_db(all_updates)

    def _learn_silent(self, answers, fetish_idx, cold_start=False):
        """learn() without incrementing learn_count (used for initial boost).
        cold_start=True で蓄積データによる減衰を無効化（新規追加性癖の cold start 対応）。"""
        neg_weight = 0.3
        all_updates = {}

        with self._lock:
            nf = len(self.fetishes)
            nq = len(self.questions)
            if not (0 <= fetish_idx < nf):
                return
            for q_str, ans in answers.items():
                try:
                    q = int(q_str)
                except (ValueError, TypeError):
                    continue
                if ans == 0 or not (0 <= q < nq):
                    continue
                strength = abs(ans)
                if cold_start:
                    scale = 1.0
                else:
                    scale = min(1.0, PSEUDO / max(self.matrix['total'][fetish_idx][q], PSEUDO))
                effective = strength * scale

                delta_yes = effective if ans > 0 else 0.0
                self.matrix['total'][fetish_idx][q] += effective
                self.matrix['yes'][fetish_idx][q]   += delta_yes
                all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))

                for f in range(nf):
                    if f == fetish_idx:
                        continue
                    w = neg_weight * effective
                    neg_yes = w * (0.0 if ans > 0 else 1.0)
                    self.matrix['total'][f][q] += w
                    self.matrix['yes'][f][q]   += neg_yes
                    all_updates.setdefault(f, []).append((q, neg_yes, w))

            if not _use_db():
                self._save_matrix_file()

        if _use_db():
            self._save_to_db(all_updates)

    def add_fetish(self, name, desc, answers):
        """新しい性癖をDBに登録する（学習はしない）。返り値は (array_idx, db_id)。
        学習は完了確定時に boost_learn_new() を別途呼ぶ。"""
        nq = len(self.questions)
        alpha = 2.0

        # 現在の回答から最も確率の高い既存性癖をテンプレートに自動選択
        probs = self.posteriors(answers)
        auto_template = int(max(range(len(probs)), key=lambda i: probs[i])) if probs else None

        with self._lock:
            array_idx = len(self.fetishes)
            if auto_template is not None and 0 <= auto_template < array_idx:
                new_yes   = list(self.matrix['yes'][auto_template])
                new_total = list(self.matrix['total'][auto_template])
            else:
                new_yes   = [alpha] * nq
                new_total = [alpha * 2.0] * nq

            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute(
                            'SELECT COALESCE(MAX(id), %s - 1) + 1 FROM fetishes WHERE id >= %s',
                            (PLAYER_FETISH_BASE_ID, PLAYER_FETISH_BASE_ID)
                        )
                        db_id = max(cur.fetchone()[0], PLAYER_FETISH_BASE_ID)
                        cur.execute(
                            'INSERT INTO fetishes (id, name, "desc") VALUES (%s, %s, %s)',
                            (db_id, name, desc)
                        )
                        rows = [(db_id, q, new_yes[q], new_total[q]) for q in range(nq)]
                        psycopg2.extras.execute_values(
                            cur,
                            'INSERT INTO matrix (fetish_id, question_id, yes_count, total_count) VALUES %s',
                            rows
                        )
                finally:
                    _put_conn(conn)
            else:
                player_ids = [f['id'] for f in self.fetishes if f['id'] >= PLAYER_FETISH_BASE_ID]
                db_id = max(player_ids) + 1 if player_ids else PLAYER_FETISH_BASE_ID

            self.fetishes.append({'id': db_id, 'name': name, 'desc': desc})
            self.matrix['yes'].append(new_yes)
            self.matrix['total'].append(new_total)

            if not _use_db():
                self._save_fetishes_file()

        return array_idx, db_id

    def boost_learn_new(self, fetish_idx, answers):
        """新規追加時の初期ブースト：cold_start で _learn_silent × 5 + learn × 1。
        cold_start=True により蓄積データの減衰を無視し、回答済みの質問の値を確実に動かす。"""
        for _ in range(5):
            self._learn_silent(answers, fetish_idx, cold_start=True)
        self.learn(answers, fetish_idx)

    def index_of(self, db_id):
        """DB id から配列インデックスを取得する。見つからなければ None。"""
        return next((i for i, f in enumerate(self.fetishes) if f['id'] == db_id), None)

    def delete_fetish(self, fetish_id):
        """プレイヤー追加性癖（ID >= PLAYER_FETISH_BASE_ID）を削除する。"""
        with self._lock:
            idx = next((i for i, f in enumerate(self.fetishes) if f['id'] == fetish_id), None)
            if idx is None or self.fetishes[idx]['id'] < PLAYER_FETISH_BASE_ID:
                return False
            self.fetishes.pop(idx)
            self.matrix['yes'].pop(idx)
            self.matrix['total'].pop(idx)
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('DELETE FROM fetishes WHERE id = %s', (fetish_id,))
                        cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (fetish_id,))
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
                self._save_matrix_file()
        return True

    def get_related(self, fetish_id):
        related_ids = FETISH_RELATIONS.get(fetish_id, [])
        out = []
        for fid in related_ids:
            idx = self.index_of(fid)
            if idx is not None:
                out.append({'fetish_id': fid, 'fetish_name': self.fetishes[idx]['name']})
        return out

    def _entropy(self, probs):
        return -sum(p * math.log2(p) for p in probs if p > 1e-10)
