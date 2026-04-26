import json
import math
import os
import random
import tempfile
import threading
import time

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
    ('abstract',    range(87, 93)),   # 87-92: 追加抽象軸（6問）
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
    # 御曹司・CEO(83): 力関係・禁断・日常・秘密・年上・雇用・格好いい好き・女性向け
    (83,0,0.75),(83,1,0.65),(83,18,0.8),(83,37,0.7),(83,12,0.6),(83,27,0.5),(83,63,0.75),(83,68,0.8),
    # ライバル・犬猿の仲(84): 対立から・嫉妬・命がけ・禁断・精神的繋がり・女性向け
    (84,20,0.95),(84,6,0.65),(84,58,0.7),(84,1,0.55),(84,61,0.6),(84,63,0.65),
    # 腹黒・二面性(85): 秘密・執着・独占欲・所有物・特別反応・女性向け
    (85,37,0.9),(85,2,0.85),(85,6,0.8),(85,4,0.7),(85,39,0.8),(85,5,0.4),(85,63,0.7),
    # 執事・従者男性(86): 雇用・献身・禁断・力関係・秘密・甘い・女性向け
    (86,27,0.95),(86,36,0.9),(86,1,0.7),(86,0,0.6),(86,37,0.65),(86,5,0.6),(86,63,0.75),
    # 軍人・騎士(87): 命がけ・力関係・禁断・異世界・体格差・献身・守られたい
    (87,58,0.9),(87,0,0.7),(87,1,0.6),(87,17,0.65),(87,30,0.55),(87,36,0.6),(87,63,0.7),(87,80,0.8),
    # 男装・男役(88): 性別曖昧・強い女性・秘密・立場逆転・女性向け・ズボン好き
    (88,15,0.7),(88,31,0.85),(88,37,0.75),(88,59,0.65),(88,63,0.8),(88,66,0.7),
    # 体育会系・スポーツ(89): 命がけ・日常・体格差・対立から・甘い・格好いい好き
    (89,58,0.7),(89,18,0.75),(89,30,0.6),(89,20,0.5),(89,5,0.55),(89,68,0.7),(89,63,0.55),
    # 幽霊・死者との恋(90): 非人間・永遠の命・禁断・精神的繋がり・超常・秘密・一方通行
    (90,10,0.9),(90,34,0.9),(90,1,0.8),(90,61,0.75),(90,33,0.7),(90,37,0.65),(90,55,0.6),
    # 過保護・甘やかし(91): 献身・甘い・執着・独占欲・力関係・守られたい
    (91,36,0.9),(91,5,0.9),(91,2,0.7),(91,6,0.7),(91,0,0.6),(91,63,0.65),(91,80,0.85),
    # 秘密の関係・不倫(92): 禁断・秘密・裏切り・嫉妬・日常・秘密の関係に惹かれる
    (92,1,0.9),(92,37,0.95),(92,8,0.8),(92,6,0.7),(92,18,0.75),(92,78,0.7),
    # 幼馴染BL(93): 同性・幼い頃からの縁・甘い・日常・秘密・女性向け
    (93,9,0.95),(93,14,0.9),(93,5,0.7),(93,18,0.7),(93,37,0.6),(93,63,0.8),
    # 転生悪役令嬢BL(94): 同性・異世界・悪役令嬢転生・対立から・禁断・女性向け
    (94,9,0.9),(94,17,0.85),(94,48,0.9),(94,20,0.7),(94,1,0.65),(94,63,0.85),
    # 年下男子・俺様系(95): 年下・力関係・日常・対立から・リードされたい
    (95,13,0.85),(95,0,0.8),(95,18,0.75),(95,20,0.6),(95,63,0.7),(95,67,0.75),
    # 囚われ×救出(96): 拘束・命がけ・禁断・力関係・精神的繋がり・監禁
    (96,22,0.85),(96,58,0.9),(96,1,0.7),(96,0,0.65),(96,61,0.7),(96,51,0.75),
    # 政略結婚・仮面夫婦(97): 禁断・秘密・日常・甘い・精神的繋がり・女性向け
    (97,1,0.7),(97,37,0.65),(97,18,0.75),(97,5,0.7),(97,61,0.75),(97,63,0.75),
    # 天才・変人(98): クール・特別反応・日常・精神的繋がり・甘い・女性向け
    (98,35,0.8),(98,39,0.8),(98,18,0.7),(98,61,0.7),(98,5,0.5),(98,63,0.65),

    # ── 追加抽象軸（Q87-92）の事前確率 ──────────────────────────────────
    # Q87「してはいけない」感覚が引力: 禁断系全般
    (0,87,0.9),(8,87,0.9),(9,87,0.8),(30,87,0.9),(1,87,0.5),(20,87,0.8),
    (51,87,0.85),(52,87,0.8),(53,87,0.85),(92,87,0.9),(42,87,0.6),(39,87,0.6),
    # Q88「守る・守られる」非対称: 保護系全般
    (87,88,0.95),(91,88,0.9),(15,88,0.8),(17,88,0.75),(86,88,0.85),(10,88,0.6),
    (27,88,0.7),(44,88,0.65),(96,88,0.85),(28,88,0.6),(77,88,0.65),
    # Q89「孤独と繋がり」: 孤独な存在・非人間系
    (28,89,0.9),(15,89,0.85),(78,89,0.85),(90,89,0.9),(76,89,0.8),(48,89,0.7),
    (31,89,0.75),(23,89,0.6),(75,89,0.7),(98,89,0.75),(77,89,0.7),
    # Q90「運命・必然」: 宿命系
    (58,90,0.95),(35,90,0.9),(16,90,0.8),(69,90,0.9),(93,90,0.75),(51,90,0.7),
    (80,90,0.75),(72,90,0.7),(78,90,0.65),
    # Q91「苦しいのに離れられない」: 苦痛+執着系
    (10,91,0.95),(80,91,0.9),(0,91,0.8),(59,91,0.85),(35,91,0.75),(90,91,0.8),
    (92,91,0.7),(18,91,0.65),(34,91,0.6),
    # Q92「痛み・苦しみが成長に繋がる」: 葛藤・成長系
    (3,92,0.8),(18,92,0.75),(84,92,0.85),(22,92,0.8),(43,92,0.75),(81,92,0.8),
    (89,92,0.7),(36,92,0.7),(85,92,0.65),(69,92,0.7),
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
    83: [68, 70, 42],  # 御曹司・CEO → 格差婚・王族・職場恋愛
    84: [23, 69, 81],  # ライバル → ツンデレ・魔王×勇者・武道
    85: [10, 31, 17],  # 腹黒 → ヤンデレ・クーデレ・溺愛
    86: [27, 70, 83],  # 執事（男性） → メイド主従・王族・御曹司
    87: [69, 37, 81],  # 軍人・騎士 → 魔王×勇者・女騎士・武道
    88: [11, 37, 19],  # 男装 → TSF・女騎士・女装
    89: [81, 84, 9],   # 体育会系 → 武道・ライバル・師弟
    90: [15, 78, 58],  # 幽霊・死者との恋 → 吸血鬼・妖怪・前世
    91: [17, 10, 86],  # 過保護・甘やかし → 溺愛・ヤンデレ・執事（男性）
    92: [0, 53, 42],   # 秘密の関係・不倫 → NTR・人妻・職場恋愛
    93: [2, 16, 65],   # 幼馴染BL → BL・幼馴染・同棲
    94: [2, 36, 63],   # 転生悪役令嬢BL → BL・悪役令嬢・ゲーム世界転移
    95: [7, 23, 84],   # 年下俺様 → 年下攻め・ツンデレ・ライバル
    96: [59, 87, 69],  # 囚われ×救出 → 監禁・軍人・魔王×勇者
    97: [68, 70, 65],  # 政略結婚 → 格差婚・王族・同棲
    98: [31, 85, 75],  # 天才・変人 → クーデレ・腹黒・陰キャ
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
    # 女性向け新規（83-98）
    83: 2.0, 84: 1.8, 85: 2.0, 86: 1.5, 87: 1.5, 88: 1.3, 89: 1.5, 90: 1.3,
    91: 1.8, 92: 1.5, 93: 2.0, 94: 1.5, 95: 1.8, 96: 1.3, 97: 1.8, 98: 1.5,
}

# 質問軸ごとの間接性ボーナス（情報利得が同程度なら間接的な軸を優先）
AXIS_INDIRECT_BONUS = {'content': 1.0, 'abstract': 1.01, 'personality': 1.02}

# 終盤モード: top_p がこの値を超えたら上位 N 件に絞った情報利得を使う
FOCUS_THRESHOLD = 0.40
FOCUS_TOP_N     = 6

# 序盤ランダム性: 最初の N 問は上位 K 件からランダムに選ぶ（毎ゲームの多様性確保）
EARLY_RANDOM_DEPTH = 3
EARLY_RANDOM_TOP_K = 5

# UCB探索ボーナス: 使用回数が少ない質問に加算（一度も試されない質問を防ぐ）
UCB_EXPLORE_C = 0.05


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


_MATRIX_RELOAD_INTERVAL  = 5.0   # 複数worker対応: DBからmatrixをリロードする間隔(秒)
_DYNAMIC_PRIOR_INTERVAL  = 60.0  # 動的事前確率キャッシュの更新間隔(秒)

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
        self.disabled_questions    = self._load_disabled_questions()
        self._matrix_last_loaded   = time.monotonic()
        self._dynamic_prior_cache  = {}
        self._dynamic_prior_time   = 0.0
        self._disc_cache           = []   # [disc_value per question]
        self._disc_cache_time      = 0.0
        self.config                = self._load_config()

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
        # キャプチャ済みの学習priorがあれば DOMAIN_PRIORS より優先して上書き
        lp_path = os.path.join(DATA_DIR, 'learned_priors.json')
        if os.path.exists(lp_path):
            try:
                with open(lp_path, encoding='utf-8') as f:
                    learned = json.load(f)
                id_to_idx = {fobj['id']: i for i, fobj in enumerate(self.fetishes)}
                for fid_str, row in learned.items():
                    fi = id_to_idx.get(int(fid_str))
                    if fi is None:
                        continue
                    for q_str, p in row.items():
                        q = int(q_str)
                        if 0 <= q < nq:
                            yes[fi][q]   = float(p) * PSEUDO
                            total[fi][q] = float(PSEUDO)
            except Exception:
                pass
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
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS fetish_log (
                        fetish_id INTEGER PRIMARY KEY,
                        guessed   INTEGER NOT NULL DEFAULT 0,
                        correct   INTEGER NOT NULL DEFAULT 0,
                        wrong     INTEGER NOT NULL DEFAULT 0
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        data       TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS config (
                        key   TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS stats_history (
                        date  TEXT NOT NULL,
                        key   TEXT NOT NULL,
                        value INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (date, key)
                    )
                ''')
                # 新しい性癖を fetishes.json から差分追加（マイグレーション）
                cur.execute('SELECT id FROM fetishes')
                existing_ids = {r[0] for r in cur.fetchall()}
                if existing_ids is not None:
                    seed = [f for f in self._load_json('fetishes.json')
                            if f['id'] < PLAYER_FETISH_BASE_ID]
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

    def _record_daily_stat(self, key):
        from datetime import date as _date
        today = _date.today().isoformat()
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO stats_history (date, key, value) VALUES (%s, %s, 1) "
                        "ON CONFLICT (date, key) DO UPDATE SET value = stats_history.value + 1",
                        (today, key)
                    )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            try:
                with open(path, encoding='utf-8') as f:
                    h = json.load(f)
            except (OSError, json.JSONDecodeError):
                h = {}
            day = h.setdefault(today, {})
            day[key] = day.get(key, 0) + 1
            self._atomic_write(path, h)

    def _increment_learn_count(self):
        self._increment_stat('learn_count')
        self._record_daily_stat('learn')

    def increment_play_count(self):
        self._increment_stat('play_count')
        self._record_daily_stat('play')

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

    def get_stats_history(self, days=30):
        """過去N日間の日別プレイ・学習回数を [{date, play, learn}, ...] で返す。"""
        from datetime import date as _date, timedelta
        today = _date.today()
        date_range = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT date, key, value FROM stats_history WHERE date >= %s",
                    (date_range[0],)
                )
                raw = {}
                for d, k, v in cur.fetchall():
                    raw.setdefault(d, {})[k] = v
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'stats_history.json')
            try:
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError):
                raw = {}
        return [{'date': d, 'play': raw.get(d, {}).get('play', 0),
                 'learn': raw.get(d, {}).get('learn', 0)} for d in date_range]

    # ── 質問無効化フラグ ───────────────────────────────────
    def _load_disabled_questions(self):
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT key FROM stats WHERE key LIKE 'disabled_q_%'")
                return {int(r[0][len('disabled_q_'):]) for r in cur.fetchall()}
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'question_flags.json')
            try:
                with open(path, encoding='utf-8') as f:
                    return set(json.load(f).get('disabled', []))
            except (OSError, json.JSONDecodeError):
                return set()

    def _save_disabled_questions(self):
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM stats WHERE key LIKE 'disabled_q_%'")
                    for q_id in self.disabled_questions:
                        cur.execute(
                            "INSERT INTO stats (key, value) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE SET value=1",
                            (f'disabled_q_{q_id}',)
                        )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'question_flags.json')
            self._atomic_write(path, {'disabled': sorted(self.disabled_questions)})

    def toggle_question_disabled(self, q_id):
        """無効化/有効化を切り替え。True=無効化後の状態を返す。"""
        with self._lock:
            if q_id in self.disabled_questions:
                self.disabled_questions.discard(q_id)
                result = False
            else:
                self.disabled_questions.add(q_id)
                result = True
        self._save_disabled_questions()
        return result

    # ── 診断ログ ──────────────────────────────────────────
    def _increment_fetish_log(self, fetish_db_id, col):
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(f'''
                        INSERT INTO fetish_log (fetish_id, {col}) VALUES (%s, 1)
                        ON CONFLICT (fetish_id) DO UPDATE SET {col} = fetish_log.{col} + 1
                    ''', (fetish_db_id,))
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'fetish_log.json')
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = {}
            key = str(fetish_db_id)
            entry = data.get(key, {'guessed': 0, 'correct': 0, 'wrong': 0})
            entry[col] = entry.get(col, 0) + 1
            data[key] = entry
            self._atomic_write(path, data)

    def log_guessed(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'guessed')

    def log_correct(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'correct')

    def log_wrong(self, fetish_db_id):
        self._increment_fetish_log(fetish_db_id, 'wrong')

    def get_fetish_log(self):
        """全性癖のログを {fetish_db_id: {guessed, correct, wrong}} で返す。"""
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute('SELECT fetish_id, guessed, correct, wrong FROM fetish_log')
                return {r[0]: {'guessed': r[1], 'correct': r[2], 'wrong': r[3]}
                        for r in cur.fetchall()}
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'fetish_log.json')
            try:
                with open(path, encoding='utf-8') as f:
                    raw = json.load(f)
                return {int(k): v for k, v in raw.items()}
            except (OSError, json.JSONDecodeError):
                return {}


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

    # ── パラメータ設定 ────────────────────────────────────
    _CONFIG_DEFAULTS = {
        'guess_threshold': 0.75,
        'compound_ratio':  0.55,
        'triple_ratio':    0.45,
        'ucb_explore_c':   0.05,
        'focus_threshold': 0.40,
    }

    def _load_config(self):
        defaults = dict(self._CONFIG_DEFAULTS)
        if _use_db():
            conn = _get_conn()
            try:
                cur = conn.cursor()
                cur.execute('SELECT key, value FROM config')
                for k, v in cur.fetchall():
                    if k in defaults:
                        defaults[k] = float(v)
            except Exception:
                pass
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'config.json')
            try:
                with open(path, encoding='utf-8') as f:
                    stored = json.load(f)
                for k, v in stored.items():
                    if k in defaults:
                        defaults[k] = float(v)
            except (OSError, json.JSONDecodeError):
                pass
        return defaults

    def set_config(self, key, value):
        if key not in self._CONFIG_DEFAULTS:
            raise ValueError(f'未知のパラメータ: {key}')
        fval = float(value)
        self.config[key] = fval
        if _use_db():
            conn = _get_conn()
            try:
                with conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO config (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (key, str(fval))
                    )
            finally:
                _put_conn(conn)
        else:
            path = os.path.join(DATA_DIR, 'config.json')
            try:
                with open(path, encoding='utf-8') as f:
                    stored = json.load(f)
            except (OSError, json.JSONDecodeError):
                stored = {}
            stored[key] = fval
            self._atomic_write(path, stored)

    # ── disc キャッシュ（学習重みスケーリング用） ──────────
    _DISC_CACHE_TTL = 120.0  # 2分ごとに再計算

    def _get_disc_scales(self):
        now = time.monotonic()
        if self._disc_cache and now - self._disc_cache_time < self._DISC_CACHE_TTL:
            return self._disc_cache
        nf = len(self.fetishes)
        nq = len(self.questions)
        discs = [
            sum(abs(self._prob(f, q) - 0.5) for f in range(nf)) / max(nf, 1)
            for q in range(nq)
        ]
        mean_disc = sum(discs) / max(len(discs), 1) or 1e-9
        # 0.5〜2.0 にクランプして正規化（識別力が高い質問を最大2倍重く学習）
        scales = [max(0.5, min(2.0, d / mean_disc)) for d in discs]
        self._disc_cache      = scales
        self._disc_cache_time = now
        return scales

    # ── 複数Worker対応: DBからmatrixをTTLリロード ──────────
    def _reload_matrix_if_stale(self):
        if not _use_db():
            return
        now = time.monotonic()
        if now - self._matrix_last_loaded < _MATRIX_RELOAD_INTERVAL:
            return
        with self._lock:
            if time.monotonic() - self._matrix_last_loaded < _MATRIX_RELOAD_INTERVAL:
                return
            self.matrix = self._load_from_db()
            self._matrix_last_loaded = time.monotonic()

    # ── 動的事前確率（診断ログから自動更新） ──────────────
    def _get_dynamic_prior_weights(self):
        now = time.monotonic()
        if now - self._dynamic_prior_time < _DYNAMIC_PRIOR_INTERVAL:
            return self._dynamic_prior_cache
        log = self.get_fetish_log()
        if not log:
            self._dynamic_prior_time = now
            return self._dynamic_prior_cache
        # correct が多いほど重みを上げる（Laplace平滑: alpha=2）
        alpha = 2.0
        weights = {}
        for f in self.fetishes:
            fid = f['id']
            entry = log.get(fid, {})
            correct = entry.get('correct', 0)
            guessed = entry.get('guessed', 0)
            # 実績重み: 正解率 + ラプラス平滑、静的重みとの幾何平均
            empirical = (correct + alpha) / (guessed + alpha * 2)
            static    = FETISH_PRIOR_WEIGHTS.get(fid, 1.0)
            # 実績データが少ない間は静的重みを重視（guessed で線形ブレンド）
            trust = min(guessed / 20.0, 1.0)
            blended = static * (1 - trust) + static * empirical * 2 * trust
            weights[fid] = max(blended, 0.1)
        self._dynamic_prior_cache = weights
        self._dynamic_prior_time  = now
        return weights

    def get_top_questions_per_fetish(self, top_n=5):
        """各性癖について P(yes) が高い/低い質問を返す（DOMAIN_PRIORS整備の参考用）。"""
        result = []
        nq = len(self.questions)
        for fi, f in enumerate(self.fetishes):
            probs = [(q, self._prob(fi, q)) for q in range(nq)]
            probs.sort(key=lambda x: x[1], reverse=True)
            high = [{'q_id': q, 'text': self.questions[q]['text'], 'p': round(p, 3)}
                    for q, p in probs[:top_n]]
            low  = [{'q_id': q, 'text': self.questions[q]['text'], 'p': round(p, 3)}
                    for q, p in probs[-top_n:]]
            result.append({'fetish_id': f['id'], 'fetish_name': f['name'],
                           'high': high, 'low': low})
        return result

    # ── 推論 ───────────────────────────────────────────────
    def _prob(self, f, q):
        y = self.matrix['yes'][f][q]
        t = self.matrix['total'][f][q]
        if t == 0:
            return 0.5
        return max(min(y / t, 0.999), 0.001)

    def posteriors(self, answers):
        self._reload_matrix_if_stale()
        nf = len(self.fetishes)
        nq = len(self.questions)
        dyn = self._get_dynamic_prior_weights()
        log_p = [math.log(dyn.get(self.fetishes[f]['id'],
                                  FETISH_PRIOR_WEIGHTS.get(self.fetishes[f]['id'], 1.0)))
                 for f in range(nf)]
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if not (0 <= q < nq):
                continue
            if ans == 0:
                # 「わからない」= その質問に馴染みがない → P(yes) が高い性癖を微弱に下げる
                for f in range(nf):
                    p = self._prob(f, q)
                    log_p[f] -= 0.05 * abs(p - 0.5)
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
        nf         = len(self.fetishes)
        asked_list = list(asked)

        # 終盤モード: 上位 FOCUS_TOP_N 件に絞った確率で情報利得を計算
        focus_threshold = self.config.get('focus_threshold', FOCUS_THRESHOLD)
        ucb_c           = self.config.get('ucb_explore_c',  UCB_EXPLORE_C)
        top_p = max(probs)
        if top_p >= focus_threshold:
            ranked = sorted(range(nf), key=lambda i: probs[i], reverse=True)
            focus  = set(ranked[:FOCUS_TOP_N])
            wp     = [probs[f] if f in focus else 0.0 for f in range(nf)]
            s      = sum(wp)
            wp     = [p / s for p in wp]
        else:
            wp = probs

        h0         = self._entropy(wp)
        asked_axes = {self._question_axis(qa) for qa in asked_list}
        asked_axes.discard(None)
        all_axis_names = {name for name, _ in QUESTION_AXES}

        # 軸フィルタリング: idk連続なら直近idkが集中している軸を避ける
        if idk_streak >= 2:
            recent_idk_axes = []
            for qa in reversed(asked_list):
                a = answers.get(str(qa))
                if a == 0:
                    ax = self._question_axis(qa)
                    if ax:
                        recent_idk_axes.append(ax)
                    if len(recent_idk_axes) >= idk_streak:
                        break
                else:
                    break
            if recent_idk_axes and len(set(recent_idk_axes)) == 1:
                axis_filter = all_axis_names - {recent_idk_axes[0]}
            else:
                axis_filter = {'abstract', 'personality'}
        elif len(asked_list) < 3 and (all_axis_names - asked_axes):
            axis_filter = all_axis_names - asked_axes
        else:
            axis_filter = None

        early_game = len(asked_list) < EARLY_RANDOM_DEPTH
        # 相関ペナルティ用: 中心化ベクトル (P - 0.5) を使用
        q_vecs = {}
        for qa in asked_list:
            v = [self._prob(f, qa) - 0.5 for f in range(nf)]
            n = math.sqrt(sum(a**2 for a in v)) or 1e-9
            q_vecs[qa] = (v, n)

        best_filtered_q, best_filtered_s = None, -1.0
        best_any_q,      best_any_s      = None, -1.0
        early_cands = []  # (weighted_score, q) — 序盤ランダム用

        for q in range(len(self.questions)):
            if q in asked or q in self.disabled_questions:
                continue
            p_yes = sum(wp[f] * self._prob(f, q) for f in range(nf))
            p_no  = 1.0 - p_yes
            if p_yes < 0.01 or p_no < 0.01:
                continue
            py = [wp[f] * self._prob(f, q) for f in range(nf)]
            sy = sum(py); py = [v / sy for v in py]
            pn = [wp[f] * (1 - self._prob(f, q)) for f in range(nf)]
            sn = sum(pn); pn = [v / sn for v in pn]
            score = h0 - (p_yes * self._entropy(py) + p_no * self._entropy(pn))
            if asked_list:
                v_q = [self._prob(f, q) - 0.5 for f in range(nf)]
                n_q = math.sqrt(sum(a**2 for a in v_q)) or 1e-9
                max_sim = 0.0
                for v_qa, n_qa in q_vecs.values():
                    sim = sum(a * b for a, b in zip(v_q, v_qa)) / (n_q * n_qa)
                    if sim > max_sim:
                        max_sim = sim
                score *= (1.0 - 0.4 * max_sim)
            ask_count = sum(self.matrix['total'][f][q] for f in range(nf))
            score += ucb_c / math.sqrt(ask_count / max(nf, 1) + 1)
            axis_name = self._question_axis(q)
            weighted = score * AXIS_INDIRECT_BONUS.get(axis_name, 1.0)
            if axis_filter is None or axis_name in axis_filter:
                if weighted > best_filtered_s:
                    best_filtered_s = weighted
                    best_filtered_q = q
                if early_game:
                    early_cands.append((weighted, q))
            if weighted > best_any_s:
                best_any_s = weighted
                best_any_q = q

        # 序盤: 上位 K 件からランダムに選んで毎ゲームの多様性を確保
        if early_game and early_cands:
            early_cands.sort(reverse=True)
            pool = [q for _, q in early_cands[:EARLY_RANDOM_TOP_K]]
            return random.choice(pool)

        # 軸フィルタで該当が無ければ全体ベストにフォールバック
        return best_filtered_q if best_filtered_q is not None else best_any_q

    def get_matrix_heatmap(self, n_fetishes=20, n_questions=20):
        """上位N性癖×上位N質問の P(yes) ヒートマップデータを返す。"""
        nf = len(self.fetishes)
        nq = len(self.questions)
        weights = [sum(self.matrix['total'][fi]) for fi in range(nf)]
        top_fi = sorted(range(nf), key=lambda i: -weights[i])[:n_fetishes]
        discs  = [sum(abs(self._prob(f, q) - 0.5) for f in range(nf)) / max(nf, 1)
                  for q in range(nq)]
        top_qi = sorted(sorted(range(nq), key=lambda q: -discs[q])[:n_questions])
        rows = [{'name': self.fetishes[fi]['name'][:12], 'id': self.fetishes[fi]['id'],
                 'cells': [round(self._prob(fi, qi), 2) for qi in top_qi]}
                for fi in top_fi]
        q_labels = [f"Q{qi}" for qi in top_qi]
        q_texts  = [self.questions[qi]['text'][:18] for qi in top_qi]
        return {'rows': rows, 'q_labels': q_labels, 'q_texts': q_texts}

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
                'id':      q,
                'text':    qdata['text'],
                'disc':    round(disc, 3),
                'disabled': q in self.disabled_questions,
            })
        return sorted(result, key=lambda x: x['disc'])

    def get_correlation_stats(self, top_n=30):
        """質問ベクトル間のコサイン類似度を計算し、上位ペアを返す。"""
        import math
        nf = len(self.fetishes)
        nq = len(self.questions)
        vecs = []
        for q in range(nq):
            v = [self._prob(f, q) - 0.5 for f in range(nf)]
            norm = math.sqrt(sum(x*x for x in v)) or 1e-9
            vecs.append((v, norm))

        pairs = []
        for i in range(nq):
            for j in range(i+1, nq):
                vi, ni = vecs[i]
                vj, nj = vecs[j]
                cos = sum(a*b for a, b in zip(vi, vj)) / (ni * nj)
                pairs.append({
                    'q1_id': i, 'q1_text': self.questions[i]['text'],
                    'q2_id': j, 'q2_text': self.questions[j]['text'],
                    'cos': round(cos, 3),
                })
        pairs.sort(key=lambda x: -abs(x['cos']))
        return pairs[:top_n]

    def top_guess(self, answers, n=1):
        probs   = self.posteriors(answers)
        ranked  = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
        top     = ranked[:n]
        if n == 1:
            return top[0], probs[top[0]]
        return [(f, probs[f]) for f in top]

    def learn(self, answers, fetish_idx, strength_factor=1.0):
        """strength_factor: 確信度が低いほど大きく（最大2.0）、高いほど小さく（最小0.5）。"""
        neg_weight  = 0.3
        disc_scales = self._get_disc_scales()
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
                # 識別力が高い質問ほど学習に重みを付ける（disc スケーリング）
                effective = strength * scale * strength_factor * disc_scales[q]

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

    def learn_cooccurrence(self, answers, idx_a, idx_b, factor=0.25):
        """共起した2性癖を互いに相手の回答パターンで弱く強化する。"""
        nf = len(self.fetishes)
        nq = len(self.questions)
        if not (0 <= idx_a < nf and 0 <= idx_b < nf and idx_a != idx_b):
            return
        all_updates = {}
        with self._lock:
            for q_str, ans in answers.items():
                try:
                    q = int(q_str)
                except (ValueError, TypeError):
                    continue
                if ans == 0 or not (0 <= q < nq):
                    continue
                for target, src in ((idx_a, idx_b), (idx_b, idx_a)):
                    # target の矩陣を src のパターン方向に弱く引き寄せる
                    p_src = self._prob(src, q)
                    synthetic_ans = 1.0 if p_src >= 0.5 else -1.0
                    if synthetic_ans * ans < 0:  # 方向が逆なら skip
                        continue
                    scale = min(1.0, PSEUDO / max(self.matrix['total'][target][q], PSEUDO))
                    eff = abs(p_src - 0.5) * factor * scale
                    if eff < 0.005:
                        continue
                    dy = eff if synthetic_ans > 0 else 0.0
                    self.matrix['yes'][target][q]   += dy
                    self.matrix['total'][target][q] += eff
                    all_updates.setdefault(target, []).append((q, dy, eff))
            if not _use_db():
                self._save_matrix_file()
        if _use_db():
            self._save_to_db(all_updates)

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

    def merge_fetishes(self, id_keep, id_remove, new_name=None, new_desc=None):
        """id_remove の性癖を id_keep にマージ（matrixを加算、id_remove を削除）。"""
        with self._lock:
            idx_keep = self.index_of(id_keep)
            idx_rm   = self.index_of(id_remove)
            if idx_keep is None or idx_rm is None or id_keep == id_remove:
                return False
            nq = len(self.questions)
            for q in range(nq):
                self.matrix['yes'][idx_keep][q]   += self.matrix['yes'][idx_rm][q]
                self.matrix['total'][idx_keep][q] += self.matrix['total'][idx_rm][q]
            if new_name:
                self.fetishes[idx_keep]['name'] = new_name
            if new_desc:
                self.fetishes[idx_keep]['desc'] = new_desc
            self.fetishes.pop(idx_rm)
            self.matrix['yes'].pop(idx_rm)
            self.matrix['total'].pop(idx_rm)
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE matrix AS m
                            SET yes_count   = m.yes_count   + rm.yes_count,
                                total_count = m.total_count + rm.total_count
                            FROM matrix rm
                            WHERE m.fetish_id = %s AND rm.fetish_id = %s
                              AND m.question_id = rm.question_id
                        ''', (id_keep, id_remove))
                        cur.execute('DELETE FROM fetishes WHERE id = %s', (id_remove,))
                        cur.execute('DELETE FROM matrix WHERE fetish_id = %s', (id_remove,))
                        cur.execute('''
                            INSERT INTO fetish_log (fetish_id, guessed, correct, wrong)
                            SELECT %s, guessed, correct, wrong FROM fetish_log WHERE fetish_id = %s
                            ON CONFLICT (fetish_id) DO UPDATE
                            SET guessed = fetish_log.guessed + EXCLUDED.guessed,
                                correct = fetish_log.correct + EXCLUDED.correct,
                                wrong   = fetish_log.wrong   + EXCLUDED.wrong
                        ''', (id_keep, id_remove))
                        cur.execute('DELETE FROM fetish_log WHERE fetish_id = %s', (id_remove,))
                        if new_name or new_desc:
                            cur.execute(
                                'UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                                (new_name or self.fetishes[idx_keep]['name'],
                                 new_desc or self.fetishes[idx_keep]['desc'], id_keep)
                            )
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
                self._save_matrix_file()
                log_path = os.path.join(DATA_DIR, 'fetish_log.json')
                try:
                    with open(log_path, encoding='utf-8') as f:
                        log = json.load(f)
                except (OSError, json.JSONDecodeError):
                    log = {}
                e_keep = log.get(str(id_keep), {'guessed': 0, 'correct': 0, 'wrong': 0})
                e_rm   = log.get(str(id_remove), {'guessed': 0, 'correct': 0, 'wrong': 0})
                log[str(id_keep)] = {k: e_keep.get(k, 0) + e_rm.get(k, 0)
                                     for k in ('guessed', 'correct', 'wrong')}
                log.pop(str(id_remove), None)
                self._atomic_write(log_path, log)
        return True

    def edit_fetish(self, fetish_id, name=None, desc=None):
        """性癖の名前・説明文を更新する。変更したフィールドのみ渡す。"""
        with self._lock:
            idx = self.index_of(fetish_id)
            if idx is None:
                return False
            if name is not None:
                self.fetishes[idx]['name'] = name
            if desc is not None:
                self.fetishes[idx]['desc'] = desc
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        if name is not None and desc is not None:
                            cur.execute('UPDATE fetishes SET name=%s, "desc"=%s WHERE id=%s',
                                        (name, desc, fetish_id))
                        elif name is not None:
                            cur.execute('UPDATE fetishes SET name=%s WHERE id=%s', (name, fetish_id))
                        else:
                            cur.execute('UPDATE fetishes SET "desc"=%s WHERE id=%s', (desc, fetish_id))
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
        return True

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

    def promote_fetish(self, old_id):
        """プレイヤー追加性癖（ID≥10000）をシード性癖に格上げ（次の空きIDを割り当て）。
        DB・matrix・fetish_log のIDを全て更新する。返り値は新ID、失敗時None。"""
        with self._lock:
            idx = self.index_of(old_id)
            if idx is None or self.fetishes[idx]['id'] < PLAYER_FETISH_BASE_ID:
                return None
            seed_ids = {f['id'] for f in self.fetishes if f['id'] < PLAYER_FETISH_BASE_ID}
            new_id = next(i for i in range(PLAYER_FETISH_BASE_ID) if i not in seed_ids)
            self.fetishes[idx]['id'] = new_id
            if _use_db():
                conn = _get_conn()
                try:
                    with conn:
                        cur = conn.cursor()
                        cur.execute('UPDATE fetishes  SET id = %s WHERE id = %s', (new_id, old_id))
                        cur.execute('UPDATE matrix    SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
                        cur.execute('UPDATE fetish_log SET fetish_id = %s WHERE fetish_id = %s', (new_id, old_id))
                finally:
                    _put_conn(conn)
            else:
                self._save_fetishes_file()
        return new_id

    def capture_learned_priors(self):
        """現在の P(yes) を learned_priors.json として保存する。
        matrix.json を削除して再初期化する際に DOMAIN_PRIORS の代替として使用される。"""
        nf = len(self.fetishes)
        nq = len(self.questions)
        snapshot = {}
        for fi in range(nf):
            fid = self.fetishes[fi]['id']
            row = {}
            for q in range(nq):
                p = self._prob(fi, q)
                if abs(p - 0.5) > 0.05:
                    row[str(q)] = round(p, 4)
            if row:
                snapshot[str(fid)] = row
        path = os.path.join(DATA_DIR, 'learned_priors.json')
        self._atomic_write(path, snapshot, ensure_ascii=False)

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
