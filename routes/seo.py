from flask import Blueprint
import html as _html
import urllib.parse


def index(ctx):
    base_url = ctx.public_base_url()
    public_fetish_count = len([f for f in ctx.engine.fetishes if f['id'] < ctx.player_fetish_base_id])
    return ctx.render_template(
        'index.html',
        display_version=ctx.display_version,
        amazon_associate_id=ctx.amazon_associate_id,
        base_url=base_url,
        public_fetish_count=public_fetish_count,
    )


def result_og_image_url(base_url, name, probability):
    return f"{base_url}/ogp.png?f={urllib.parse.quote(name or '')}&p={probability or ''}"


def fetish_og_image_url(base_url, fetish_name, probability=90):
    return f"{base_url}/ogp.png?f={urllib.parse.quote(fetish_name or '')}&p={probability}"


def ogp_cache_headers():
    return {'Cache-Control': 'public, max-age=3600'}


def fetish_index(ctx):
    base_url = ctx.public_base_url()
    fetish_log = ctx.engine.get_fetish_log()
    rows = []
    for fetish in ctx.engine.fetishes:
        if fetish['id'] >= ctx.player_fetish_base_id:
            continue
        works = [ctx.work_title(work) for work in fetish.get('works', [])][:3]
        log = fetish_log.get(fetish['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        rows.append({
            'id': fetish['id'],
            'name': fetish['name'],
            'desc': fetish['desc'],
            'works': works,
            'guessed': log.get('guessed', 0),
        })
    rows.sort(key=lambda row: (-row['guessed'], row['id']))
    page_url = f"{base_url}/fetishes"
    json_ld = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': '性癖一覧 - へきネイター',
        'description': 'へきネイターで診断できる性癖の一覧。各性癖の意味、関連作品、診断ページへの入口をまとめています。',
        'url': page_url,
        'mainEntity': {
            '@type': 'ItemList',
            'numberOfItems': len(rows),
            'itemListElement': [
                {'@type': 'ListItem', 'position': i + 1, 'url': f"{base_url}/fetish/{row['id']}", 'name': row['name']}
                for i, row in enumerate(rows[:50])
            ],
        },
    }
    return ctx.render_template(
        'fetishes.html',
        fetishes=rows,
        display_version=ctx.display_version,
        base_url=base_url,
        page_url=page_url,
        json_ld=json_ld,
    )



def fetish_detail(ctx, fetish_id):
    idx = ctx.engine.index_of(fetish_id)
    if idx is None:
        return ctx.error_page.format(
            title='見つかりません', emoji='🔍', code='404',
            message='その性癖は存在しないか、削除されました。'
        ), 404
    fetish = ctx.engine.fetishes[idx]

    related = []
    for related_id in ctx.fetish_relations.get(fetish_id, []):
        related_idx = ctx.engine.index_of(related_id)
        if related_idx is not None:
            related.append({'id': related_id, 'name': ctx.engine.fetishes[related_idx]['name']})

    works = []
    for work in fetish.get('works', []):
        title = ctx.work_title(work)
        url = work.get('url', '') if isinstance(work, dict) else ''
        url = ctx.safe_work_url(url)
        if url and ctx.amazon_associate_id and 'tag=' not in url:
            separator = '&' if '?' in url else '?'
            url = url + f'{separator}tag={urllib.parse.quote(ctx.amazon_associate_id)}'
        works.append({'title': title, 'url': url})

    char_qs = []
    if idx < len(ctx.engine.matrix['yes']):
        row_yes = ctx.engine.matrix['yes'][idx]
        row_total = ctx.engine.matrix['total'][idx]
        scores = []
        for question_idx in range(len(ctx.engine.questions)):
            probability = row_yes[question_idx] / row_total[question_idx] if row_total[question_idx] > 0 else 0.5
            if abs(probability - 0.5) > 0.08:
                scores.append((probability, question_idx))
        scores.sort(reverse=True)
        for probability, question_idx in scores[:5]:
            char_qs.append({'text': ctx.engine.questions[question_idx]['text'], 'p': round(probability * 100)})

    fetish_log = ctx.engine.get_fetish_log()
    log = fetish_log.get(fetish_id, {'guessed': 0, 'correct': 0, 'wrong': 0})
    accuracy = round(log['correct'] / log['guessed'] * 100) if log['guessed'] else None
    base_url = ctx.public_base_url()
    work_names = [work['title'] for work in works[:6]]
    seo_desc = f"{fetish['name']}とは、{fetish['desc']} へきネイターでこの性癖に当てはまるか診断できます。"[:155]
    page_url = f'{base_url}/fetish/{fetish_id}'
    json_ld = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        'headline': f"{fetish['name']}とは？性癖診断とおすすめ作品",
        'description': seo_desc,
        'url': page_url,
        'isPartOf': {'@type': 'WebSite', 'name': 'へきネイター', 'url': base_url},
        'about': {'@type': 'Thing', 'name': fetish['name'], 'description': fetish['desc']},
    }
    if work_names:
        json_ld['mentions'] = [{'@type': 'CreativeWork', 'name': title} for title in work_names]
    return ctx.render_template(
        'fetish.html',
        fetish=fetish,
        works=works,
        work_names=work_names,
        related=related,
        char_qs=char_qs,
        log=log,
        acc=accuracy,
        display_version=ctx.display_version,
        og_image=fetish_og_image_url(base_url, fetish['name'], 90),
        base_url=base_url,
        page_url=page_url,
        seo_desc=seo_desc,
        json_ld=json_ld,
    )


def result_share(ctx):
    name = ctx.request.args.get('f', '')[:60]
    probability = ctx.clean_probability(ctx.request.args.get('p', ''))
    desc = ctx.request.args.get('d', '')[:120]
    base_url = ctx.public_base_url()
    share_url = f"{base_url}/r?f={urllib.parse.quote(name)}&p={urllib.parse.quote(probability)}&d={urllib.parse.quote(desc)}"
    body = ctx.render_template(
        'result_share.html',
        fetish_name=name,
        probability=probability,
        desc=desc,
        display_version=ctx.display_version,
        og_image=result_og_image_url(base_url, name, probability),
        share_url=share_url,
        share_text=ctx.result_share_text(name, probability),
        result_tagline=ctx.result_tagline(name, probability),
    )
    return ctx.Response(body, headers={'X-Robots-Tag': 'noindex, follow'})


def ogp_png_image(ctx):
    name = ctx.request.args.get('f', '???')[:30]
    probability = ctx.clean_probability(ctx.request.args.get('p', ''))
    body = ctx.generate_ogp_png(name, probability)
    return ctx.Response(body, mimetype='image/png', headers=ogp_cache_headers())


def ogp_svg_image(ctx):
    name = ctx.request.args.get('f', '???')[:30]
    probability = ctx.request.args.get('p', '')[:5]
    body = ctx.render_ogp_svg(name, probability)
    return ctx.Response(body, mimetype='image/svg+xml', headers=ogp_cache_headers())


def stats_page(ctx):
    fetish_log = ctx.engine.get_fetish_log()
    stats = ctx.engine.get_stats()
    rows = []
    for fetish in ctx.engine.fetishes:
        if fetish['id'] >= ctx.player_fetish_base_id:
            continue
        log = fetish_log.get(fetish['id'], {'guessed': 0, 'correct': 0, 'wrong': 0})
        guessed, correct, wrong = log['guessed'], log['correct'], log['wrong']
        accuracy = round(correct / guessed * 100) if guessed else None
        rows.append({'id': fetish['id'], 'name': fetish['name'], 'guessed': guessed, 'correct': correct, 'wrong': wrong, 'acc': accuracy})
    rows.sort(key=lambda row: -row['guessed'])
    top10 = [row for row in rows if row['guessed'] > 0][:10]
    total_guessed = sum(row['guessed'] for row in rows)
    total_correct = sum(row['correct'] for row in rows)
    ranked = [row for row in rows if row['guessed'] >= 3 and row['acc'] is not None]
    base_url = ctx.public_base_url()
    return ctx.render_template(
        'stats.html',
        top10=top10,
        play_count=stats['play_count'],
        learn_count=stats['learn_count'],
        total_guessed=total_guessed,
        overall_acc=round(total_correct / total_guessed * 100) if total_guessed else None,
        top_acc=sorted(ranked, key=lambda row: -row['acc'])[:5],
        total_fetishes=len([f for f in ctx.engine.fetishes if f['id'] < ctx.player_fetish_base_id]),
        display_version=ctx.display_version,
        base_url=base_url,
        page_url=f"{base_url}/stats",
    )


def robots_txt(ctx):
    host = ctx.public_base_url()
    body = f"""User-agent: *
Disallow: /admin
Disallow: /api/
Allow: /
Sitemap: {host}/sitemap.xml
"""
    return ctx.Response(body, mimetype='text/plain')


def sitemap_xml(ctx):
    host = ctx.public_base_url()
    urls = [host + '/', host + '/fetishes', host + '/stats']
    for fetish in ctx.engine.fetishes:
        if fetish['id'] < 10000:
            urls.append(f"{host}/fetish/{fetish['id']}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        priority = '1.0' if url == host + '/' else ('0.8' if url in (host + '/fetishes', host + '/stats') else '0.6')
        lines.append(f'  <url><loc>{_html.escape(url, quote=True)}</loc><priority>{priority}</priority></url>')
    lines.append('</urlset>')
    return ctx.Response('\n'.join(lines), mimetype='application/xml')



def create_blueprint(ctx_factory):
    bp = Blueprint('seo', __name__)

    @bp.route('/')
    def index_route():
        return index(ctx_factory())

    @bp.route('/fetishes')
    def fetish_index_route():
        return fetish_index(ctx_factory())

    @bp.route('/r')
    def result_share_route():
        return result_share(ctx_factory())

    @bp.route('/ogp.png')
    def ogp_png_image_route():
        return ogp_png_image(ctx_factory())

    @bp.route('/ogp')
    def ogp_svg_image_route():
        return ogp_svg_image(ctx_factory())

    @bp.route('/fetish/<int:fetish_id>')
    def fetish_detail_route(fetish_id):
        return fetish_detail(ctx_factory(), fetish_id)

    @bp.route('/stats')
    def stats_page_route():
        return stats_page(ctx_factory())

    @bp.route('/robots.txt')
    def robots_txt_route():
        return robots_txt(ctx_factory())

    @bp.route('/sitemap.xml')
    def sitemap_xml_route():
        return sitemap_xml(ctx_factory())

    return bp
