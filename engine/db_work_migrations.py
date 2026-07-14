"""Recommended-work data normalization used by schema migrations."""

import json
import re
import unicodedata

DEFAULT_RECOMMENDED_WORKS_BY_NAME = {
    '激重感情': ['ハッピーシュガーライフ', '未来日記', '君に愛されて痛かった'],
    'ツンデレ優男ヤンキー': ['ヤンキー君と白杖ガール', '山田くんとLv999の恋をする', 'ひるなかの流星'],
    '人外/異形頭': ['魔法使いの嫁', 'とつくにの少女', '異形頭さんとニンゲンちゃん'],
    '共生関係': ['魔法使いの嫁', '宝石の国', '蟲師'],
    '離別': ['秒速5センチメートル', '四月は君の嘘', 'ラヴレター'],
    '制服': ['明日ちゃんのセーラー服', 'その着せ替え人形は恋をする', '響け！ユーフォニアム'],
}

DIRECT_WORK_URLS_BY_TITLE = {
    'ハッピーシュガーライフ': 'https://www.amazon.co.jp/dp/B015Z262MW?tag=hekinator-22',
    '君に愛されて痛かった': 'https://www.amazon.co.jp/dp/B0BKPTJN4S?tag=hekinator-22',
    'からかい上手の高木さん': 'https://www.amazon.co.jp/dp/B00N2QXHRW?tag=hekinator-22',
    '響け！ユーフォニアム': 'https://www.amazon.co.jp/dp/B07SZBJR55?tag=hekinator-22',
    '四月は君の嘘': 'https://www.amazon.co.jp/dp/B00AF5PJOM?tag=hekinator-22',
    '天気の子': 'https://www.amazon.co.jp/dp/B07TXN8GK1?tag=hekinator-22',
    'NANA': 'https://www.amazon.co.jp/dp/B00AMB4JCM?tag=hekinator-22',
    'リエゾン': 'https://www.amazon.co.jp/dp/B08B3JKJRS?tag=hekinator-22',
    'コウノドリ': 'https://www.amazon.co.jp/dp/B00F02CMZ4?tag=hekinator-22',
    'まじっく快斗': 'https://www.amazon.co.jp/dp/B00BH943D8?tag=hekinator-22',
    '怪盗セイント・テール': 'https://www.amazon.co.jp/dp/B00ARAGSBS?tag=hekinator-22',
    'ルパン三世': 'https://www.amazon.co.jp/dp/B019FPZ2JO?tag=hekinator-22',
    '桜蘭高校ホスト部': 'https://www.amazon.co.jp/dp/B00DMU9GQ4?tag=hekinator-22',
    '美少年探偵団': 'https://www.amazon.co.jp/dp/B015GW70N6?tag=hekinator-22',
    'NHKへようこそ！': 'https://www.amazon.co.jp/dp/B0093G7X20?tag=hekinator-22',
    'ぼっち・ざ・ろっく！': 'https://www.amazon.co.jp/dp/B07N3NRSKF?tag=hekinator-22',
    'Rozen Maiden': 'https://www.amazon.co.jp/dp/B00DGI5C06?tag=hekinator-22',
    '機動天使エンジェリックレイヤー': 'https://www.amazon.co.jp/dp/B0G6RL2N1T?tag=hekinator-22',
    '境界の彼方': 'https://www.amazon.co.jp/dp/4990581245?tag=hekinator-22',
    'Dr.STONE': 'https://www.amazon.co.jp/dp/B071VV14SF?tag=hekinator-22',
    'SPY×FAMILY': 'https://www.amazon.co.jp/dp/B07S5K4L4H?tag=hekinator-22',
    'ヤンキー君と白杖ガール': 'https://www.amazon.co.jp/dp/B07MSBK5BZ?tag=hekinator-22',
    '山田くんとLv999の恋をする': 'https://www.amazon.co.jp/dp/B084JHMGD8?tag=hekinator-22',
    'ひるなかの流星': 'https://www.amazon.co.jp/dp/B00AU3M82U?tag=hekinator-22',
    'とつくにの少女': 'https://www.amazon.co.jp/dp/B01C5M5W1M?tag=hekinator-22',
    '異形頭さんとニンゲンちゃん': 'https://www.amazon.co.jp/dp/B0D7C3CVBM?tag=hekinator-22',
    '宝石の国': 'https://www.amazon.co.jp/dp/B00DW4ZYBG?tag=hekinator-22',
    '蟲師': 'https://www.amazon.co.jp/dp/B009KYBN44?tag=hekinator-22',
    '花束みたいな恋をした': 'https://www.amazon.co.jp/dp/B091YSWXYG?tag=hekinator-22',
    '最後から二番目の恋': 'https://www.amazon.co.jp/dp/B0F5ZH2W18?tag=hekinator-22',
    '半分、青い。': 'https://www.amazon.co.jp/dp/B07CXM1XYH?tag=hekinator-22',
    'ロミオとジュリエット（宝塚版）': 'https://www.amazon.co.jp/dp/B08H5BS5JV?tag=hekinator-22',
    '恋はDeepに': 'https://www.amazon.co.jp/dp/B096VJ6P7J?tag=hekinator-22',
    'ラヴレター': 'https://www.amazon.co.jp/dp/B00QKD6LYU?tag=hekinator-22',
    '明日ちゃんのセーラー服': 'https://www.amazon.co.jp/dp/B06XPYX4V1?tag=hekinator-22',
    'その着せ替え人形は恋をする': 'https://www.amazon.co.jp/dp/B07JZNFJVD?tag=hekinator-22',
    '後宮の烏': 'https://www.amazon.co.jp/dp/B07DK8QHGV?tag=hekinator-22',
    '悪役令嬢後宮物語': 'https://www.amazon.co.jp/dp/B07MQCV562?tag=hekinator-22',
    'ループ7回目の悪役令嬢は、元敵国で自由に生きる': 'https://www.amazon.co.jp/dp/B096RNH7JZ?tag=hekinator-22',
    '時をかける少女': 'https://www.amazon.co.jp/dp/B009GPM8OQ?tag=hekinator-22',
    'スパイ教室': 'https://www.amazon.co.jp/dp/B083PRSFG5?tag=hekinator-22',
    '魔探偵ロキ': 'https://www.amazon.co.jp/dp/B009WNRLWQ?tag=hekinator-22',
    '逃げるは恥だが役に立つ': 'https://www.amazon.co.jp/dp/B00GWVP77W?tag=hekinator-22',
    '同期のサクラ': 'https://www.amazon.co.jp/dp/B07TJQRVF5?tag=hekinator-22',
    '左ききのエレン': 'https://www.amazon.co.jp/dp/B076HN94KS?tag=hekinator-22',
    '君に届け': 'https://www.amazon.co.jp/dp/B009PL81RE?tag=hekinator-22',
    '青のフラッグ': 'https://www.amazon.co.jp/dp/B06VXVPNFZ?tag=hekinator-22',
    'ハチミツとクローバー': 'https://www.amazon.co.jp/dp/B01JIC5TFG?tag=hekinator-22',
}

DIRECT_WORK_TITLE_ALIASES = {
    '未来日記': 'Future Diary',
    'CLANNAD': 'クラナド',
    'まじっく快斗（怪盗キッド）': 'まじっく快斗',
    '美少年探偵団（西尾維新）': '美少年探偵団',
    'SPY×FAMILY（漫画）': 'SPY×FAMILY',
    '薬屋のひとりごと（小説）': '薬屋のひとりごと',
    'ヤンキー君と白杖ガール（漫画）': 'ヤンキー君と白杖ガール',
    'ループ7回目の悪役令嬢は、元敵国で自由に生きる（漫画）': 'ループ7回目の悪役令嬢は、元敵国で自由に生きる',
    'スパイ教室（小説）': 'スパイ教室',
    '同期のサクラ（ドラマ小説）': '同期のサクラ',
    'からかい上手の高木さん（漫画）': 'からかい上手の高木さん',
}


RECOMMENDED_WORK_REPLACEMENTS_BY_TITLE = {
    '灰かぶり姫の幸運': {
        'title': 'わたしの幸せな結婚',
        'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22',
    },
    '私の夫は冷酷帝': {'title': 'わたしの幸せな結婚', 'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22'},
    '極道くんの甘い溺愛（漫画）': {
        'title': '来世は他人がいい',
        'url': 'https://www.amazon.co.jp/dp/B07796N6LJ?tag=hekinator-22',
    },
    '着せ恋（彼女、お借りします）': {
        'title': 'その着せ替え人形は恋をする',
        'url': 'https://www.amazon.co.jp/dp/B07JZNFJVD?tag=hekinator-22',
    },
    '薔薇のないフローリスト': {'title': '同級生', 'url': 'https://www.amazon.co.jp/dp/B074CF91MQ?tag=hekinator-22'},
    'ヤクザと花嫁（漫画）': {
        'title': '来世は他人がいい',
        'url': 'https://www.amazon.co.jp/dp/B07796N6LJ?tag=hekinator-22',
    },
    '兎と猛獣（漫画）': {'title': '贄姫と獣の王', 'url': 'https://www.amazon.co.jp/dp/B01MT8SP41?tag=hekinator-22'},
    '拾われた伯爵令嬢は騎士団長に溺愛される（漫画）': {
        'title': '魔法使いの嫁',
        'url': 'https://www.amazon.co.jp/dp/B0CVL3R7DW?tag=hekinator-22',
    },
    '捨て猫に似た恋をする（漫画）': {
        'title': 'フルーツバスケット',
        'url': 'https://www.amazon.co.jp/dp/B00DMU66SK?tag=hekinator-22',
    },
    '偽婚約者は本気で愛したい（漫画）': {
        'title': '誰かこの状況を説明してください！',
        'url': 'https://www.amazon.co.jp/dp/B07DL6G318?tag=hekinator-22',
    },
    '契約結婚のはずが、旦那様が本気になってしまいました（漫画）': {
        'title': '誰かこの状況を説明してください！',
        'url': 'https://www.amazon.co.jp/dp/B07DL6G318?tag=hekinator-22',
    },
    '偽りの花嫁（小説）': {
        'title': 'わたしの幸せな結婚',
        'url': 'https://www.amazon.co.jp/dp/B07X25T546?tag=hekinator-22',
    },
    '探偵は今夜も嘘をつく（小説）': {
        'title': '虚構推理',
        'url': 'https://www.amazon.co.jp/dp/B017GUUV0U?tag=hekinator-22',
    },
    '不良と優等生（漫画）': {
        'title': 'ヤンキー君と白杖ガール',
        'url': 'https://www.amazon.co.jp/dp/B07MSBK5BZ?tag=hekinator-22',
    },
    '極上の敵（漫画）': {'title': 'となりの怪物くん', 'url': 'https://www.amazon.co.jp/dp/B009KYBS3U?tag=hekinator-22'},
}


def default_recommended_works_for_name(name):
    return [{'title': title, 'url': ''} for title in DEFAULT_RECOMMENDED_WORKS_BY_NAME.get(str(name or '').strip(), [])]


def backfill_empty_recommended_works(cur):
    updated = 0
    for name, titles in DEFAULT_RECOMMENDED_WORKS_BY_NAME.items():
        works_json = json.dumps([{'title': title, 'url': ''} for title in titles], ensure_ascii=False)
        cur.execute(
            "UPDATE fetishes SET works=%s WHERE name=%s AND (works='' OR works='[]' OR works IS NULL)",
            (works_json, name),
        )
        updated += int(getattr(cur, 'rowcount', 0) or 0)
    return updated


def _canonical_work_title(title):
    title = unicodedata.normalize('NFKC', str(title or '')).strip().casefold()
    title = re.sub(r'[（(][^）)]*[）)]', '', title).strip()
    return re.sub(r'\s+', ' ', title)


def recommended_work_replacement_for_title(title):
    title = str(title or '').strip()
    replacement = RECOMMENDED_WORK_REPLACEMENTS_BY_TITLE.get(title)
    if replacement is not None:
        return replacement
    canonical_title = _canonical_work_title(title)
    for source_title, candidate in RECOMMENDED_WORK_REPLACEMENTS_BY_TITLE.items():
        if _canonical_work_title(source_title) == canonical_title:
            return candidate
    return None


def _is_search_work_url(url):
    url = str(url or '').strip()
    return 'amazon.co.jp/s?' in url or 'amazon.co.jp/s/' in url


def build_direct_work_url_lookup(seed_fetishes):
    lookup = {}
    for title, url in DIRECT_WORK_URLS_BY_TITLE.items():
        lookup.setdefault(title, url)
        lookup.setdefault(_canonical_work_title(title), url)
    for fetish in seed_fetishes:
        for work in fetish.get('works') or []:
            if not isinstance(work, dict):
                continue
            title = str(work.get('title') or '').strip()
            url = str(work.get('url') or '').strip()
            if not title or '/dp/' not in url:
                continue
            lookup.setdefault(title, url)
            lookup.setdefault(_canonical_work_title(title), url)
    for alias, target_title in DIRECT_WORK_TITLE_ALIASES.items():
        target_url = lookup.get(target_title) or lookup.get(_canonical_work_title(target_title))
        if not target_url:
            continue
        lookup.setdefault(alias, target_url)
        lookup.setdefault(_canonical_work_title(alias), target_url)
    return lookup


def _recommended_work_dict(work):
    if isinstance(work, dict):
        return dict(work)
    return {'title': str(work or ''), 'url': ''}


def backfill_recommended_work_urls(cur, seed_fetishes):
    """Fill missing/search work URLs from the checked seed direct-link map."""
    lookup = build_direct_work_url_lookup(seed_fetishes)
    if not lookup:
        return 0

    cur.execute('SELECT id, works FROM fetishes')
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        if len(row) < 2:
            continue
        fetish_id, works_raw = row[0], row[1]
        try:
            works = json.loads(works_raw) if works_raw else []
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(works, list):
            continue

        changed = False
        next_works = []
        for work in works:
            item = _recommended_work_dict(work)
            title = str(item.get('title') or '').strip()
            replacement = recommended_work_replacement_for_title(title)
            if replacement is not None:
                item['title'] = replacement['title']
                item['url'] = replacement['url']
                changed = True
                next_works.append(item)
                continue

            current_url = str(item.get('url') or '').strip()
            direct_url = lookup.get(title) or lookup.get(_canonical_work_title(title))
            if title and direct_url and (not current_url or _is_search_work_url(current_url)):
                item['url'] = direct_url
                changed = True
            next_works.append(item)
        if not changed:
            continue
        cur.execute(
            'UPDATE fetishes SET works=%s WHERE id=%s',
            (json.dumps(next_works, ensure_ascii=False), fetish_id),
        )
        updated += int(getattr(cur, 'rowcount', 0) or 0)
    return updated
