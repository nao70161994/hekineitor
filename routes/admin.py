import urllib.parse
from datetime import date, timedelta

from flask import Blueprint

from routes.admin_sections import analytics as analytics_routes
from routes.admin_sections import matrix as matrix_routes
from routes.admin_sections import matrix_handlers
from routes.admin_sections import mutations as mutation_routes
from routes.admin_sections import operations as operations_routes
from routes.admin_sections import page as page_routes
from routes.admin_sections import works as works_routes
from services import context as context_service
from services import improvement_candidates as improvement_candidates_service
from services import inference as inference_service
from services import ogp as ogp_service
from services import question_events as question_events_service
from services import result_exposure as result_exposure_service
from services import share_events as share_events_service
from services import share_links as share_links_service
from services.csv_safety import csv_text
from services.works_links import build_work_catalog_report, collect_work_link_queue


def _date_arg(value):
    value = str(value or '')[:10]
    if len(value) == 10 and value[4] == '-' and value[7] == '-':
        year, month, day = value.split('-')
        if year.isdigit() and month.isdigit() and day.isdigit():
            return value
    return None


def _previous_period(since, until):
    try:
        start = date.fromisoformat(since)
        end = date.fromisoformat(until)
    except (TypeError, ValueError):
        return None, None
    if end < start:
        return None, None
    span = end - start
    previous_until = start - timedelta(days=1)
    previous_since = previous_until - span
    return previous_since.isoformat(), previous_until.isoformat()


def _parse_dry_run_answers(raw):
    answers = {}
    errors = []
    for item in str(raw or '').replace(';', ',').split(','):
        item = item.strip()
        if not item:
            continue
        if ':' in item:
            q_text, answer_text = item.split(':', 1)
        elif '=' in item:
            q_text, answer_text = item.split('=', 1)
        else:
            errors.append(f'invalid_pair:{item}')
            continue
        try:
            question_id = int(q_text.strip())
            answer_value = float(answer_text.strip())
        except (TypeError, ValueError):
            errors.append(f'invalid_value:{item}')
            continue
        if answer_value not in (1, 0.5, 0, -0.5, -1):
            errors.append(f'invalid_answer:{item}')
            continue
        answers[str(question_id)] = answer_value
    return answers, errors


def dry_run_guess(ctx):
    answers, errors = _parse_dry_run_answers(ctx.request.args.get('answers', ''))
    if errors:
        return ctx.jsonify(
            {'status': 'error', 'message': 'answers は q:answer のカンマ区切りで指定してください', 'errors': errors}
        ), 400
    if not answers:
        return ctx.jsonify({'status': 'error', 'message': 'answers が空です'}), 400
    invalid_ids = [
        int(question_id) for question_id in answers if not (0 <= int(question_id) < len(ctx.engine.questions))
    ]
    if invalid_ids:
        return ctx.jsonify(
            {'status': 'error', 'message': '不正な質問IDです', 'invalid_question_ids': invalid_ids[:20]}
        ), 400
    inference_ctx = context_service.build_inference_context(
        engine=ctx.engine,
        session={},
        work_title=ctx.work_title,
        get_compound_works=ctx.get_compound_works,
        profile_min_ratio=0.25,
        profile_min_prob=0.08,
        compound_ratio=ctx.engine.config.get('compound_ratio', 0.55),
        triple_ratio=ctx.engine.config.get('triple_ratio', 0.45),
        adjusted_score_provider=lambda probs, ranked: result_exposure_service.adjusted_scores(
            ctx.engine, probs, ranked
        ),
    )
    result = inference_service.compute_guess(inference_ctx, answers)
    return ctx.jsonify(
        {
            'status': 'ok',
            'mode': 'dry_run_no_record',
            'recorded': False,
            'answer_count': len(answers),
            'answers': answers,
            'result': result,
        }
    )


def share_event_query(ctx, *, default_limit=500):
    filters = {
        'limit': ctx.bounded_int(ctx.request.args.get('limit'), default_limit, 1, 5000),
        'since': _date_arg(ctx.request.args.get('since')),
        'until': _date_arg(ctx.request.args.get('until')),
        'days': None,
        'compare_since': _date_arg(ctx.request.args.get('compare_since')),
        'compare_until': _date_arg(ctx.request.args.get('compare_until')),
    }
    if ctx.request.args.get('days'):
        filters['days'] = ctx.bounded_int(ctx.request.args.get('days'), 0, 1, 366)
    if filters['since'] and filters['until'] and not filters['compare_since'] and not filters['compare_until']:
        filters['compare_since'], filters['compare_until'] = _previous_period(filters['since'], filters['until'])
    return filters


def share_event_query_string(filters):
    parts = []
    for key in ('limit', 'days', 'since', 'until', 'compare_since', 'compare_until'):
        value = filters.get(key)
        if value not in (None, ''):
            parts.append(f'{key}={value}')
    return '&'.join(parts)


def analysis_log_status(ctx, *, stats_history=None, share_events=None, question_events=None):
    stats_history = stats_history if stats_history is not None else ctx.engine.get_stats_history(days=30)
    share_events = share_events if share_events is not None else ctx.share_event_report(limit=1000)
    question_events = question_events if question_events is not None else ctx.question_event_report(limit=1000)
    share_count = ctx.share_event_count()
    question_count = ctx.question_event_count()
    share_storage = ctx.share_event_storage_status() if hasattr(ctx, 'share_event_storage_status') else {}
    question_storage = ctx.question_event_storage_status() if hasattr(ctx, 'question_event_storage_status') else {}
    stats_history_count = len(
        [
            row
            for row in stats_history
            if any(row.get(key, 0) for key in ('start', 'play', 'completion', 'learn', 'correct', 'wrong', 'dropoff'))
        ]
    )
    return {
        'stats_history_count': stats_history_count,
        'share_event_count': share_count,
        'question_event_count': question_count,
        'share_event_loaded': share_events.get('total', 0),
        'share_invalid_result_events': share_events.get('invalid_result_events', 0),
        'question_event_loaded': question_events.get('total', 0),
        'share_event_storage': share_storage,
        'question_event_storage': question_storage,
        'question_ready': question_count >= 50,
        'share_ready': share_count >= 20,
        'stats_ready': stats_history_count > 0,
        'sources': {
            'result_distribution': 'Engine stats_history / fetish_log',
            'feedback': 'Engine fetish_log / stats_history',
            'share_analytics': 'Postgres analytics_events'
            if share_storage.get('storage') == 'postgres'
            else 'JSONL share_events',
            'question_analytics': 'Postgres analytics_events'
            if question_storage.get('storage') == 'postgres'
            else 'JSONL question_events',
        },
    }


def test_play_audit_rows(rows, *, limit=8):
    items = []
    for row in rows:
        action = row.get('action')
        if action not in ('test_play_start', 'test_play_stop'):
            continue
        detail = row.get('detail') if isinstance(row.get('detail'), dict) else {}
        items.append(
            {
                'event_name': detail.get('event_name') or action,
                'timestamp': row.get('ts', ''),
                'mode': detail.get('mode') or ('learning_off' if action == 'test_play_start' else 'normal'),
            }
        )
    return items[:limit]


def admin_page(ctx):
    stats = ctx.engine.get_learning_stats()
    app_stats = ctx.engine.get_stats()
    player_fetishes = [f for f in ctx.engine.fetishes if f['id'] >= ctx.player_fetish_base_id]
    question_stats = ctx.engine.get_question_stats()
    corr_stats = ctx.engine.get_correlation_stats(top_n=30)
    fetish_log_rows = ctx.build_fetish_log_rows()
    fetish_log_page = ctx.paged_fetish_log_rows(fetish_log_rows, ctx.request.args)
    domain_suggestions = ctx.engine.get_top_questions_per_fetish(top_n=5)
    stats_history = ctx.engine.get_stats_history(days=30)
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    completion_metrics = ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary)
    matrix_heatmap = ctx.engine.get_matrix_heatmap(n_fetishes=20, n_questions=20)
    axis_stats = ctx.engine.get_axis_stats()
    quality = ctx.engine.get_quality_report()
    maintenance = ctx.build_admin_maintenance_checklist()
    share_event_filters = share_event_query(ctx, default_limit=1000)
    share_events = ctx.share_event_report(**share_event_filters)
    question_events = ctx.question_event_report(limit=1000)
    analysis_logs = analysis_log_status(
        ctx, stats_history=stats_history, share_events=share_events, question_events=question_events
    )
    share_notes = ctx.load_share_notes()
    audit_rows = ctx.recent_audit(50)
    return ctx.render_template(
        'admin.html',
        stats=stats,
        start_count=app_stats.get('start_count', 0),
        completion_count=app_stats.get('completion_count', 0),
        play_count=app_stats['play_count'],
        learn_count=app_stats['learn_count'],
        completion_metrics=completion_metrics,
        player_fetishes=player_fetishes,
        question_stats=question_stats,
        corr_stats=corr_stats,
        fetish_log_rows=fetish_log_rows,
        fetish_log_page=fetish_log_page,
        domain_suggestions=domain_suggestions,
        engine_config=ctx.engine.config,
        config_defaults=ctx.engine._CONFIG_DEFAULTS,
        stats_history=stats_history,
        matrix_heatmap=matrix_heatmap,
        axis_stats=axis_stats,
        quality_report=quality,
        maintenance_checklist=maintenance,
        share_events=share_events,
        question_events=question_events,
        analysis_logs=analysis_logs,
        share_notes=share_notes,
        share_event_filters=share_event_filters,
        share_event_query=share_event_query_string(share_event_filters),
        csrf_token=ctx.csrf_token(),
        csrf_expires_at=int(
            ctx.session.get('admin_csrf_issued_at', 0) + int(ctx.environ.get('ADMIN_CSRF_TTL_SECONDS', '7200'))
        ),
        audit_rows=audit_rows[:20],
        test_play_audit_rows=test_play_audit_rows(audit_rows),
        matrix_backups=ctx.list_matrix_import_backups(),
        test_play_active=ctx.is_test_play(),
    )


def start_test_play(ctx):
    ctx.enable_test_play()
    ctx.write_audit('test_play_start', 'ok', {'event_name': 'test_play_start', 'mode': 'learning_off'})
    return ctx.Response('', status=302, headers={'Location': '/'})


def stop_test_play(ctx):
    ctx.disable_test_play()
    ctx.write_audit('test_play_stop', 'ok', {'event_name': 'test_play_stop', 'mode': 'normal'})
    return ctx.Response('', status=302, headers={'Location': '/admin'})


def works_link_queue_payload(ctx, *, sample_limit=20):
    return collect_work_link_queue(ctx.engine.fetishes, sample_limit=sample_limit, associate_id=ctx.amazon_associate_id)


def _admin_work_url(ctx, work, title):
    raw_url = work.get('url', '') if isinstance(work, dict) else ''
    url = ctx.safe_work_url(raw_url)
    if raw_url and not url:
        return ''
    if not url and getattr(ctx, 'amazon_associate_id', '') and title:
        url = f'https://www.amazon.co.jp/s?k={urllib.parse.quote(str(title))}&tag={urllib.parse.quote(ctx.amazon_associate_id)}'
    elif url and getattr(ctx, 'amazon_associate_id', '') and 'tag=' not in url:
        separator = '&' if '?' in url else '?'
        url = url + f'{separator}tag={urllib.parse.quote(ctx.amazon_associate_id)}'
    return url


def _seed_fetish_works(ctx):
    rows = ctx.load_json_file('fetishes.json', default=[])
    return {int(row['id']): row.get('works') or [] for row in rows if isinstance(row, dict) and 'id' in row}


def seed_works_backfill_payload(ctx, *, sample_limit=50, apply=False):
    seed_works = _seed_fetish_works(ctx)
    candidates = []
    for fetish in ctx.engine.fetishes:
        fetish_id = fetish.get('id')
        if fetish_id is None or fetish_id >= ctx.player_fetish_base_id:
            continue
        current_works = fetish.get('works') or []
        replacement = seed_works.get(fetish_id) or []
        if current_works or not replacement:
            continue
        normalized = ctx.parse_works_list(replacement)
        if not normalized:
            continue
        candidates.append(
            {
                'id': fetish_id,
                'name': fetish.get('name', ''),
                'seed_work_count': len(normalized),
                'seed_titles': [ctx.work_title(work) for work in normalized[:5]],
            }
        )

    updated = 0
    if apply:
        confirm_error = ctx.require_confirm('BACKFILL_WORKS')
        if confirm_error:
            return confirm_error
        for row in candidates:
            if ctx.engine.edit_fetish(row['id'], works=ctx.parse_works_list(seed_works[row['id']])):
                updated += 1
        ctx.write_audit('works_seed_backfill', 'ok', {'updated_count': updated})

    return ctx.jsonify(
        {
            'status': 'ok',
            'mode': 'applied' if apply else 'dry_run',
            'candidate_count': len(candidates),
            'updated_count': updated,
            'required_confirm_text': 'BACKFILL_WORKS',
            'candidates': candidates[:sample_limit],
        }
    )


def export_log(ctx):
    log = ctx.engine.get_fetish_log()
    fetish_map = {fetish['id']: fetish['name'] for fetish in ctx.engine.fetishes}
    fieldnames = [
        'id',
        'name',
        'guessed',
        'correct',
        'wrong',
        'feedback_total',
        'feedback_accuracy',
        'unfeedback',
        'guess_confirm_rate',
    ]
    rows = []
    for fid, entry in sorted(log.items(), key=lambda item: -item[1].get('guessed', 0)):
        name = fetish_map.get(fid, str(fid))
        guessed = entry.get('guessed', 0)
        correct = entry.get('correct', 0)
        wrong = entry.get('wrong', 0)
        feedback_total = correct + wrong
        feedback_acc = f'{round(correct / feedback_total * 100, 1)}' if feedback_total else ''
        unfeedback = max(0, guessed - feedback_total)
        guess_confirm_rate = f'{round(correct / guessed * 100, 1)}' if guessed else ''
        rows.append(
            {
                'id': fid,
                'name': name,
                'guessed': guessed,
                'correct': correct,
                'wrong': wrong,
                'feedback_total': feedback_total,
                'feedback_accuracy': feedback_acc,
                'unfeedback': unfeedback,
                'guess_confirm_rate': guess_confirm_rate,
            }
        )
    return ctx.Response(
        csv_text(rows, fieldnames),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="fetish_log.csv"'},
    )


def fetish_history(ctx, fetish_id):
    days = ctx.bounded_int(ctx.request.args.get('days'), 30, 1, 90)
    return ctx.jsonify(ctx.engine.get_fetish_history(fetish_id, days=days))


def fetish_log_rows(ctx):
    return ctx.jsonify(
        {
            'status': 'ok',
            **ctx.paged_fetish_log_rows(ctx.build_fetish_log_rows(), ctx.request.args),
        }
    )


def low_exposure_fetishes(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 30, 1, 200)
    threshold = ctx.bounded_int(ctx.request.args.get('threshold'), 3, 0, 1000000)
    rows = ctx.build_fetish_log_rows()
    fetish_by_id = {fetish.get('id'): fetish for fetish in ctx.engine.fetishes}
    enriched = []
    for row in rows:
        fetish = fetish_by_id.get(row['id'], {})
        works = fetish.get('works') or []
        item = {
            'id': row['id'],
            'name': row['name'],
            'guessed': row['guessed'],
            'correct': row['correct'],
            'wrong': row['wrong'],
            'feedback_total': row['feedback_total'],
            'acc': row['acc'],
            'unfeedback': row['unfeedback'],
            'works_count': len(works),
            'has_works': bool(works),
            'is_player_fetish': row['id'] >= ctx.player_fetish_base_id,
            'detail_url': f'/fetish/{row["id"]}',
        }
        enriched.append(item)
    low_rows = sorted(
        [row for row in enriched if row['guessed'] <= threshold],
        key=lambda row: (row['guessed'], row['works_count'], row['id']),
    )
    zero_rows = [row for row in enriched if row['guessed'] == 0]
    no_work_low_rows = [row for row in low_rows if not row['has_works']]
    return ctx.jsonify(
        {
            'status': 'ok',
            'threshold': threshold,
            'total_fetishes': len(enriched),
            'zero_count': len(zero_rows),
            'low_count': len(low_rows),
            'no_work_low_count': len(no_work_low_rows),
            'summary': {
                'zero_share': round(len(zero_rows) / len(enriched) * 100, 1) if enriched else 0,
                'low_share': round(len(low_rows) / len(enriched) * 100, 1) if enriched else 0,
                'no_work_low_share': round(len(no_work_low_rows) / len(low_rows) * 100, 1) if low_rows else 0,
            },
            'rows': low_rows[:limit],
            'zero_rows': zero_rows[:limit],
            'no_work_low_rows': no_work_low_rows[:limit],
        }
    )


def performance(ctx):
    measurements = []

    def measure(name, fn):
        start = ctx.perf_counter()
        result = fn()
        elapsed = (ctx.perf_counter() - start) * 1000
        measurements.append({'name': name, 'ms': round(elapsed, 3)})
        return result

    measure('get_question_stats', ctx.engine.get_question_stats)
    measure('get_learning_stats', ctx.engine.get_learning_stats)
    measure('get_fetish_log', ctx.engine.get_fetish_log)
    measure('best_question_empty', lambda: ctx.best_question(ctx.engine, {}, set()))
    return ctx.jsonify({'status': 'ok', 'measurements': measurements})


def recent_fetish_ranking(ctx):
    days = ctx.bounded_int(ctx.request.args.get('days'), 7, 1, 90)
    top_n = ctx.bounded_int(ctx.request.args.get('top_n'), 10, 1, 50)
    end_date = (ctx.request.args.get('date') or ctx.request.args.get('until') or '').strip()[:10] or None
    ranking = ctx.engine.get_recent_fetish_ranking(days=days, top_n=top_n, end_date=end_date)
    source = ranking[0].get('source') if ranking else 'recent'
    return ctx.jsonify({'ranking': ranking, 'days': days, 'date': end_date, 'source': source})


def result_exposures_report(ctx):
    days = ctx.bounded_int(ctx.request.args.get('days'), 7, 1, 90)
    top_n = ctx.bounded_int(ctx.request.args.get('top_n'), 10, 1, 50)
    end_date = (ctx.request.args.get('date') or ctx.request.args.get('until') or '').strip()[:10] or None
    include_backfill = str(ctx.request.args.get('include_backfill') or '').lower() in ('1', 'true', 'yes')
    include_secondary = str(ctx.request.args.get('include_secondary') or '').lower() in ('1', 'true', 'yes')
    include_candidates = str(ctx.request.args.get('include_candidates') or '').lower() in ('1', 'true', 'yes')
    fetish_names = _current_fetish_names(ctx)
    report = result_exposure_service.ranking_report(
        environ=ctx.environ,
        limit=5000,
        days=days,
        date=end_date,
        top_n=top_n,
        include_backfill=include_backfill,
        fetish_names=fetish_names,
        include_secondary=include_secondary,
        include_candidates=include_candidates,
    )
    report['include_backfill'] = include_backfill
    report['include_secondary'] = include_secondary
    report['include_candidates'] = include_candidates
    return ctx.jsonify(report)


def _current_fetish_names(ctx):
    return {
        fetish.get('id'): fetish.get('name', '')
        for fetish in getattr(ctx.engine, 'fetishes', [])
        if fetish.get('id') is not None
    }


def result_exposure_trend(ctx):
    days = ctx.bounded_int(ctx.request.args.get('days'), 14, 1, 90)
    top_n = ctx.bounded_int(ctx.request.args.get('top_n'), 5, 1, 20)
    end_date = (ctx.request.args.get('date') or ctx.request.args.get('until') or '').strip()[:10] or None
    include_backfill = str(ctx.request.args.get('include_backfill') or '').lower() in ('1', 'true', 'yes')
    return ctx.jsonify(
        result_exposure_service.heavy_result_trend_report(
            environ=ctx.environ,
            limit=5000,
            days=days,
            date=end_date,
            top_n=top_n,
            include_backfill=include_backfill,
            fetish_names=_current_fetish_names(ctx),
        )
    )


def result_exposures_recent(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 20, 1, 100)
    include_backfill = str(ctx.request.args.get('include_backfill') or '').lower() in ('1', 'true', 'yes')
    return ctx.jsonify(
        result_exposure_service.recent_events_report(
            environ=ctx.environ,
            limit=limit,
            include_backfill=include_backfill,
        )
    )


def result_exposure_factors(ctx):
    top_n = ctx.bounded_int(ctx.request.args.get('top_n'), 30, 1, 200)
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 5000, 1, 50000)
    return ctx.jsonify(
        result_exposure_service.factor_report(
            ctx.engine.fetishes,
            environ=ctx.environ,
            limit=limit,
            top_n=top_n,
        )
    )


def result_exposures_backfill(ctx, *, apply=False):
    data = ctx.request.get_json(silent=True) or {}
    value = data.get('max_events') if apply else ctx.request.args.get('max_events')
    try:
        max_events = max(1, min(int(value or 1000), 5000))
    except (TypeError, ValueError):
        max_events = 1000
    force_value = data.get('force') if apply else ctx.request.args.get('force')
    force = str(force_value or '').lower() in ('1', 'true', 'yes')
    if apply:
        confirm_error = ctx.require_confirm(result_exposure_service.BACKFILL_CONFIRM_TEXT)
        if confirm_error:
            return confirm_error
    report = result_exposure_service.backfill_from_fetish_log(
        ctx.engine.fetishes,
        ctx.engine.get_fetish_log(),
        environ=ctx.environ,
        max_events=max_events,
        apply=apply,
        force=force,
    )
    if apply and report.get('inserted_count'):
        ctx.write_audit(
            'backfill_result_exposures',
            'ok',
            {
                'inserted_count': report.get('inserted_count'),
                'raw_total': report.get('raw_total'),
                'force': force,
            },
        )
    return ctx.jsonify(report)


def export_stats_history(ctx):
    history = ctx.engine.get_stats_history(days=90)
    fieldnames = ['date', 'start', 'completion', 'play', 'learn', 'correct', 'wrong', 'dropoff']
    rows = [
        {
            'date': row['date'],
            'start': row.get('start', 0),
            'completion': row.get('completion', 0),
            'play': row.get('play', 0),
            'learn': row.get('learn', 0),
            'correct': row.get('correct', 0),
            'wrong': row.get('wrong', 0),
            'dropoff': row.get('dropoff', 0),
        }
        for row in history
    ]
    return ctx.Response(
        csv_text(rows, fieldnames),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="stats_history.csv"'},
    )


def quality_report(ctx):
    return ctx.jsonify(ctx.engine.get_quality_report())


def share_events_report(ctx):
    return ctx.jsonify({'status': 'ok', **ctx.share_event_report(**share_event_query(ctx))})


def question_events_report(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 1000, 1, 50000)
    target_date = (ctx.request.args.get('date') or '').strip()[:10]
    exclude_suspicious = str(ctx.request.args.get('exclude_suspicious') or '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )
    return ctx.jsonify(
        {
            'status': 'ok',
            **ctx.question_event_report(limit=limit, date=target_date or None, exclude_suspicious=exclude_suspicious),
        }
    )


def question_events_csv(ctx, kind):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 5000, 1, 50000)
    target_date = (ctx.request.args.get('date') or '').strip()[:10]
    exclude_suspicious = str(ctx.request.args.get('exclude_suspicious') or '1').strip().lower() not in (
        '0',
        'false',
        'no',
        'off',
    )
    report = ctx.question_event_report(limit=limit, date=target_date or None, exclude_suspicious=exclude_suspicious)
    if kind == 'category':
        body = question_events_service.category_csv(report)
        filename = 'question_events_category.csv'
    else:
        body = question_events_service.question_csv(report)
        filename = 'question_events_questions.csv'
    return ctx.Response(
        body,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def share_events_csv(ctx, kind):
    filters = share_event_query(ctx)
    report = ctx.share_event_report(**filters)
    if kind == 'daily':
        body = share_events_service.daily_csv(report)
        filename = 'share_events_daily.csv'
    elif kind == 'comparison':
        body = share_events_service.comparison_csv(report)
        filename = 'share_events_comparison.csv'
    else:
        body = share_events_service.ranking_csv(report)
        filename = 'share_events_ranking.csv'
    return ctx.Response(
        body,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def share_notes(ctx):
    if ctx.request.method == 'GET':
        return ctx.jsonify({'status': 'ok', 'notes': ctx.load_share_notes()})
    data = ctx.request.get_json(silent=True) or {}
    result_name = data.get('result_name', '')
    note = data.get('note', '')
    try:
        saved = ctx.save_share_note(result_name, note)
    except ValueError as exc:
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    ctx.write_audit('share_note_update', 'ok', {'result_name': str(result_name or '')[:80]}, ctx.request)
    return ctx.jsonify({'status': 'ok', 'result_name': str(result_name or '')[:80], 'note': saved})


def maintenance_checklist(ctx):
    return ctx.jsonify(ctx.build_admin_maintenance_checklist())


def fetishes_snapshot(ctx):
    rows = []
    for fetish in ctx.engine.fetishes:
        works = fetish.get('works') or []
        rows.append(
            {
                'id': fetish.get('id'),
                'name': fetish.get('name', ''),
                'desc': fetish.get('desc', ''),
                'works_count': len(works),
                'works_titles': [ctx.work_title(work) for work in works[:5]],
                'is_player_fetish': fetish.get('id', 0) >= ctx.player_fetish_base_id,
                'detail_url': f'/fetish/{fetish.get("id")}',
            }
        )
    return ctx.jsonify(
        {
            'status': 'ok',
            'total': len(rows),
            'seed_count': len([row for row in rows if not row['is_player_fetish']]),
            'player_count': len([row for row in rows if row['is_player_fetish']]),
            'fetishes': rows,
        }
    )


def learning_stats(ctx):
    rows = ctx.engine.get_learning_stats()
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'rows': rows})


def question_stats(ctx):
    rows = ctx.engine.get_question_stats()
    categories = {}
    for row in rows:
        category = row.get('category') or 'unknown'
        bucket = categories.setdefault(category, {'count': 0, 'disabled': 0, 'avg_disc': 0.0, 'ask_count': 0})
        bucket['count'] += 1
        bucket['disabled'] += 1 if row.get('disabled') else 0
        bucket['avg_disc'] += float(row.get('disc') or 0)
        bucket['ask_count'] += int(row.get('ask_count') or 0)
    for bucket in categories.values():
        if bucket['count']:
            bucket['avg_disc'] = round(bucket['avg_disc'] / bucket['count'], 4)
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'categories': categories, 'rows': rows})


def works_health(ctx):
    maintenance = ctx.build_admin_maintenance_checklist().get('works', {})
    queue = works_link_queue_payload(ctx, sample_limit=50)
    seed_backfill = seed_works_backfill_payload(ctx, sample_limit=50, apply=False).get_json()
    catalog = build_work_catalog_report(
        ctx.engine.fetishes,
        compound_rows=ctx.list_compound_works(),
        sample_limit=50,
    )
    return ctx.jsonify(
        {
            'status': 'ok',
            'maintenance': maintenance,
            'link_queue': queue,
            'seed_backfill': seed_backfill,
            'catalog': catalog,
        }
    )


def matrix_health(ctx):
    yes_rows = ctx.engine.matrix.get('yes', [])
    total_rows = ctx.engine.matrix.get('total', [])
    expected_rows = len(ctx.engine.fetishes)
    expected_cols = len(ctx.engine.questions)
    row_lengths = [len(row) for row in yes_rows] + [len(row) for row in total_rows]
    ok = (
        len(yes_rows) == expected_rows
        and len(total_rows) == expected_rows
        and all(len(row) == expected_cols for row in yes_rows)
        and all(len(row) == expected_cols for row in total_rows)
    )
    return ctx.jsonify(
        {
            'status': 'ok' if ok else 'warning',
            'storage': 'postgres' if ctx.use_db() else 'local_json',
            'fetish_count': expected_rows,
            'question_count': expected_cols,
            'yes_rows': len(yes_rows),
            'total_rows': len(total_rows),
            'min_cols': min(row_lengths) if row_lengths else 0,
            'max_cols': max(row_lengths) if row_lengths else 0,
            'matrix_shape_ok': ok,
            'backups': ctx.list_matrix_import_backups(),
        }
    )


def funnel_metrics(ctx):
    include_details = str(ctx.request.args.get('include_details') or '').lower() in ('1', 'true', 'yes')
    app_stats = ctx.engine.get_stats()
    stats_history = ctx.engine.get_stats_history(days=30)
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    completion = ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary)
    payload = {
        'status': 'ok',
        'completion': completion,
        'dropoff_summary': dropoff_summary,
        'stats_history': stats_history,
        'details_included': include_details,
    }
    if include_details:
        share_report = ctx.share_event_report(limit=1000)
        question_report = ctx.question_event_report(limit=1000)
        payload.update(
            {
                'share_metrics': share_report.get('metrics', {}),
                'question_summary': question_report.get('summary', {}),
            }
        )
    return ctx.jsonify(payload)


def player_fetishes(ctx):
    rows = [
        {
            'id': fetish.get('id'),
            'name': fetish.get('name', ''),
            'desc': fetish.get('desc', ''),
            'works_count': len(fetish.get('works') or []),
        }
        for fetish in ctx.engine.fetishes
        if fetish.get('id', 0) >= ctx.player_fetish_base_id
    ]
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'player_fetishes': rows})


def added_fetishes(ctx):
    seed_rows = ctx.load_json_file('fetishes.json', default=[])
    seed_ids = {row.get('id') for row in seed_rows if isinstance(row, dict)}
    seed_names = {str(row.get('name') or '') for row in seed_rows if isinstance(row, dict)}
    rows = []
    for fetish in ctx.engine.fetishes:
        fetish_id = fetish.get('id')
        name = str(fetish.get('name') or '')
        if fetish_id in seed_ids and name in seed_names:
            continue
        if fetish_id in seed_ids and name:
            source = 'seed_name_changed'
        elif isinstance(fetish_id, int) and fetish_id >= ctx.player_fetish_base_id:
            source = 'player_added'
        elif fetish_id not in seed_ids:
            source = 'promoted_or_db_added'
        else:
            source = 'unknown_added'
        rows.append(
            {
                'id': fetish_id,
                'name': name,
                'source': source,
                'player_id': bool(isinstance(fetish_id, int) and fetish_id >= ctx.player_fetish_base_id),
                'seed_id_present': fetish_id in seed_ids,
                'seed_name_present': name in seed_names,
                'works_count': len(fetish.get('works') or []),
            }
        )
    rows.sort(key=lambda row: (0 if row['source'] == 'player_added' else 1, row.get('id') or 0, row.get('name') or ''))
    counts = {}
    for row in rows:
        counts[row['source']] = counts.get(row['source'], 0) + 1
    return ctx.jsonify({'status': 'ok', 'total': len(rows), 'counts': counts, 'added_fetishes': rows})


def promoted_fetish_history(ctx):
    rows = ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('limit'), 100, 1, 500))
    promotions = []
    repairs = []
    for row in rows:
        action = row.get('action')
        detail = row.get('detail') if isinstance(row.get('detail'), dict) else {}
        if action == 'promote_fetish':
            promotions.append(
                {
                    'timestamp': row.get('ts', ''),
                    'old_id': detail.get('old_id'),
                    'new_id': detail.get('new_id'),
                    'status': row.get('status', ''),
                }
            )
        elif action in ('repair_promoted_stats_history', 'move_stats_history'):
            repairs.append(
                {
                    'timestamp': row.get('ts', ''),
                    'action': action,
                    'status': row.get('status', ''),
                    'detail': detail,
                }
            )
    return ctx.jsonify({'status': 'ok', 'promotions': promotions, 'repairs': repairs})


def _safe_engine_config(ctx):
    defaults = getattr(ctx.engine, '_CONFIG_DEFAULTS', {}) or {}
    config = getattr(ctx.engine, 'config', {}) or {}
    keys = sorted(set(defaults) | set(config))
    rows = []
    for key in keys:
        rows.append(
            {
                'key': str(key),
                'value': config.get(key),
                'default': defaults.get(key),
                'overridden': config.get(key) != defaults.get(key),
            }
        )
    return rows


def _question_admin_rows(ctx):
    stats_by_id = {row.get('id'): row for row in ctx.engine.get_question_stats()}
    rows = []
    for question_id, question in enumerate(ctx.engine.questions):
        stats = stats_by_id.get(question_id, {})
        rows.append(
            {
                'id': question_id,
                'text': question.get('text', ''),
                'category': question.get('category') or 'unknown',
                'axis': question.get('axis') or '',
                'disabled': bool(question.get('disabled')),
                'disc': stats.get('disc'),
                'ask_count': stats.get('ask_count', 0),
                'variant_count': stats.get('variant_count', 0),
            }
        )
    return rows


def _compound_works_rows(ctx, *, limit=200):
    items = ctx.list_compound_works()[: max(1, int(limit or 200))]
    rows = []
    for item in items:
        idx_a = ctx.engine.index_of(item['id_a'])
        idx_b = ctx.engine.index_of(item['id_b'])
        rows.append(
            {
                **item,
                'name_a': ctx.engine.fetishes[idx_a]['name'] if idx_a is not None else f'id={item["id_a"]}',
                'name_b': ctx.engine.fetishes[idx_b]['name'] if idx_b is not None else f'id={item["id_b"]}',
                'works_count': len(item.get('works') or []),
                'works_titles': [ctx.work_title(work) for work in (item.get('works') or [])[:5]],
            }
        )
    return rows


def operations_snapshot(ctx):
    """Read-only bundle for Codex/ops analysis; excludes CSRF, secrets, sessions, and mutation payloads."""
    stats_history = ctx.engine.get_stats_history(days=30)
    app_stats = ctx.engine.get_stats()
    dropoff_summary = ctx.engine.get_dropoff_summary(days=30)
    question_events = ctx.question_event_report(limit=1000)
    share_events = ctx.share_event_report(**share_event_query(ctx, default_limit=1000))
    audit_rows = ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('audit_limit'), 50, 1, 200))
    return ctx.jsonify(
        {
            'status': 'ok',
            'scope': 'read_only_operations_snapshot',
            'counts': {
                'fetishes': len(ctx.engine.fetishes),
                'questions': len(ctx.engine.questions),
                'player_fetishes': len([f for f in ctx.engine.fetishes if f.get('id', 0) >= ctx.player_fetish_base_id]),
                'compound_works': len(ctx.list_compound_works()),
            },
            'engine_config': _safe_engine_config(ctx),
            'questions': _question_admin_rows(ctx),
            'question_categories': question_stats(ctx).get_json().get('categories', {}),
            'correlation_stats': ctx.engine.get_correlation_stats(top_n=30),
            'domain_suggestions': ctx.engine.get_top_questions_per_fetish(top_n=5),
            'matrix_heatmap': ctx.engine.get_matrix_heatmap(n_fetishes=20, n_questions=20),
            'axis_stats': ctx.engine.get_axis_stats(),
            'quality_report': ctx.engine.get_quality_report(),
            'completion': ctx.build_completion_metrics(app_stats, stats_history, dropoff_summary),
            'analysis_logs': analysis_log_status(
                ctx, stats_history=stats_history, share_events=share_events, question_events=question_events
            ),
            'share_events_summary': {
                'total': share_events.get('total', 0),
                'invalid_result_events': share_events.get('invalid_result_events', 0),
                'metrics': share_events.get('metrics', {}),
                'work_ranking': share_events.get('work_ranking', [])[:20],
            },
            'question_events_summary': {
                'total': question_events.get('total', 0),
                'raw_loaded': question_events.get('raw_loaded', question_events.get('total', 0)),
                'total_available': question_events.get('total_available', question_events.get('total', 0)),
                'quality': question_events.get('quality', {}),
                'summary': question_events.get('summary', {}),
                'cold_start_summary': question_events.get('cold_start_summary', {}),
                'cold_start_questions': question_events.get('cold_start_questions', []),
                'warnings': question_events.get('warnings', []),
            },
            'compound_works': _compound_works_rows(ctx, limit=200),
            'test_play_audit_rows': test_play_audit_rows(audit_rows, limit=20),
            'audit_recent': [_safe_audit_row(ctx, row) for row in audit_rows[:50]],
        }
    )


def admin_read_overview(ctx):
    logs = analysis_log_status(ctx, stats_history=ctx.engine.get_stats_history(days=90))
    question_report = ctx.question_event_report(limit=5000)
    exposure_events = result_exposure_service.read_events(environ=ctx.environ, limit=300)
    fetish_rows = ctx.build_fetish_log_rows()
    return ctx.jsonify(
        {
            'status': 'ok',
            'share_links_count': share_links_service.count_links(environ=ctx.environ),
            'improvement_candidates': improvement_candidates_service.build_candidates(
                question_report,
                exposure_events=exposure_events,
                fetish_rows=fetish_rows,
            ),
            'low_learning_candidates': improvement_candidates_service.low_learning_candidates(
                fetish_rows,
                exposure_events=exposure_events,
            ),
            'available_endpoints': [
                '/api/admin/preflight',
                '/api/admin/fetishes_snapshot',
                '/api/admin/learning_stats',
                '/api/admin/question_stats',
                '/api/admin/operations_snapshot',
                '/api/admin/quality_report',
                '/api/admin/works_health',
                '/api/admin/audit_log',
                '/api/admin/maintenance_checklist',
                '/api/admin/matrix_health',
                '/api/admin/funnel_metrics',
                '/api/admin/player_fetishes',
                '/api/admin/added_fetishes',
                '/api/admin/promoted_fetish_history',
                '/api/admin/fetish_log_rows',
                '/api/admin/low_exposure_fetishes',
                '/api/admin/recent_fetish_ranking',
                '/api/admin/dry_run_guess',
                '/api/admin/result_exposures',
                '/api/admin/result_exposures/recent',
                '/api/admin/result_exposure_trend',
                '/api/admin/result_exposure_factors',
                '/api/admin/result_exposures/backfill',
                '/api/admin/question_events',
                '/api/admin/share_events',
                '/api/admin/share_notes',
                '/api/admin/export_stats_history',
                '/api/admin/matrix_backups',
                '/api/admin/works_link_queue',
                '/api/admin/compound_works',
            ],
            'analysis_log_status': logs,
        }
    )


def _safe_audit_row(ctx, row):
    safe = {
        'ts': str(row.get('ts', '')),
        'action': row.get('action', ''),
        'status': row.get('status', ''),
        'detail': row.get('detail', {}) if isinstance(row.get('detail'), dict) else {},
    }
    if row.get('method'):
        safe['method'] = row.get('method', '')
    if row.get('path'):
        safe['path'] = row.get('path', '')
    return safe


def audit_log(ctx):
    rows = [
        _safe_audit_row(ctx, row)
        for row in ctx.recent_audit(ctx.bounded_int(ctx.request.args.get('limit'), 500, 1, 500))
    ]
    if ctx.request.args.get('format') == 'csv':
        fieldnames = ['ts', 'action', 'status', 'method', 'path', 'detail']
        csv_rows = []
        for row in rows:
            csv_rows.append(
                {
                    'ts': row['ts'],
                    'action': row['action'],
                    'status': row['status'],
                    'method': row.get('method', ''),
                    'path': row.get('path', ''),
                    'detail': ctx.json_dumps(row.get('detail', {}), ensure_ascii=False),
                }
            )
        return ctx.Response(
            csv_text(csv_rows, fieldnames),
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="admin_audit_log.csv"'},
        )
    return ctx.jsonify({'status': 'ok', 'audit_log': rows})


def preflight(ctx):
    checks = []

    def add_check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})

    add_check(
        'secret_key_configured',
        bool(ctx.environ.get('SECRET_KEY')),
        'configured' if ctx.environ.get('SECRET_KEY') else 'development fallback in use',
    )
    add_check(
        'admin_pass_configured',
        bool(ctx.environ.get('ADMIN_PASS')),
        'configured' if ctx.environ.get('ADMIN_PASS') else 'missing',
    )
    add_check('storage_available', True, 'postgres' if ctx.use_db() else 'local_json')
    yes_rows = ctx.engine.matrix.get('yes', [])
    total_rows = ctx.engine.matrix.get('total', [])
    expected_rows = len(ctx.engine.fetishes)
    expected_cols = len(ctx.engine.questions)
    matrix_ok = (
        len(yes_rows) == expected_rows
        and len(total_rows) == expected_rows
        and all(len(row) == expected_cols for row in yes_rows)
        and all(len(row) == expected_cols for row in total_rows)
    )
    add_check(
        'matrix_shape',
        matrix_ok,
        f'yes={len(yes_rows)} total={len(total_rows)} / fetishes={expected_rows} questions={expected_cols}',
    )
    backups = ctx.list_matrix_import_backups()
    backup_keep = ctx.bounded_int(ctx.environ.get('MATRIX_IMPORT_BACKUP_KEEP'), 20, 1, 1000)
    add_check(
        'matrix_backups_retained',
        len(backups) <= backup_keep,
        f'{len(backups)} import backups present / keep={backup_keep}',
    )
    ogp_font = ogp_service.cjk_font_status()
    add_check('ogp_cjk_font_available', ogp_font['available'], ogp_font['detail'])
    add_check('csrf_enabled', ctx.should_enforce_runtime_guard('csrf'), 'enabled for non-test runtime')
    logs = analysis_log_status(ctx, stats_history=ctx.engine.get_stats_history(days=90))
    add_check('analysis_stats_history_rows', True, f'{logs["stats_history_count"]} active stats_history days')
    share_storage = logs.get('share_event_storage') or {}
    question_storage = logs.get('question_event_storage') or {}
    share_storage_ok = bool(share_storage.get('parent_writable') and share_storage.get('file_writable'))
    question_storage_ok = bool(question_storage.get('parent_writable') and question_storage.get('file_writable'))
    add_check(
        'analysis_share_events_rows',
        share_storage_ok,
        f'{logs["share_event_count"]} share_events rows / {"ready" if logs["share_ready"] else "insufficient for analysis"} / path={share_storage.get("path", "unknown")} / writable={share_storage_ok}',
    )
    add_check(
        'analysis_question_events_rows',
        question_storage_ok,
        f'{logs["question_event_count"]} question_events rows / {"ready" if logs["question_ready"] else "insufficient for analysis"} / path={question_storage.get("path", "unknown")} / writable={question_storage_ok}',
    )
    add_check('rate_limit_enabled', ctx.should_enforce_runtime_guard('rate_limit'), 'enabled for non-test runtime')
    ok = all(check['ok'] for check in checks)
    return ctx.jsonify({'status': 'ok' if ok else 'warning', 'checks': checks})


def list_compound_works(ctx):
    items = ctx.list_compound_works()
    result = []
    for item in items:
        idx_a = ctx.engine.index_of(item['id_a'])
        idx_b = ctx.engine.index_of(item['id_b'])
        name_a = ctx.engine.fetishes[idx_a]['name'] if idx_a is not None else f'id={item["id_a"]}'
        name_b = ctx.engine.fetishes[idx_b]['name'] if idx_b is not None else f'id={item["id_b"]}'
        result.append({**item, 'name_a': name_a, 'name_b': name_b})
    return ctx.jsonify(result)


def set_compound_works(ctx):
    data = ctx.request.get_json(silent=True) or {}
    try:
        id_a = int(data['id_a'])
        id_b = int(data['id_b'])
    except (KeyError, ValueError, TypeError):
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    if id_a == id_b:
        return ctx.jsonify({'status': 'error', 'message': '同じIDは指定できません'}), 400
    if ctx.engine.index_of(id_a) is None or ctx.engine.index_of(id_b) is None:
        return ctx.jsonify({'status': 'error', 'message': '存在しない性癖IDです'}), 400
    raw = data.get('works', [])
    if isinstance(raw, str):
        raw = [work.strip() for work in raw.split(',') if work.strip()]
    works = ctx.parse_works_list(raw)
    if not works:
        return ctx.jsonify({'status': 'error', 'message': '作品を1件以上入力してください'}), 400
    if len(works) > 10:
        return ctx.jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    try:
        key = ctx.set_compound_works(id_a, id_b, works)
    except ValueError as exc:
        return ctx.jsonify({'status': 'error', 'message': str(exc)}), 400
    ctx.write_audit(
        'compound_works_update',
        'ok',
        {'id_a': min(id_a, id_b), 'id_b': max(id_a, id_b), 'work_count': len(works)},
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'key': key, 'works': works})


def delete_compound_works(ctx, key):
    parts = key.split(',')
    if len(parts) != 2:
        return ctx.jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    try:
        id_a, id_b = int(parts[0]), int(parts[1])
    except ValueError:
        return ctx.jsonify({'status': 'error', 'message': '不正なキーです'}), 400
    ok = ctx.delete_compound_works(id_a, id_b)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    ctx.write_audit(
        'compound_works_delete',
        'ok',
        {'id_a': min(id_a, id_b), 'id_b': max(id_a, id_b)},
        ctx.request,
    )
    return ctx.jsonify({'status': 'deleted', 'key': key})


def toggle_question(ctx, q_id):
    if q_id < 0 or q_id >= len(ctx.engine.questions):
        return ctx.jsonify({'status': 'error', 'message': '不正な質問IDです'}), 400
    disabled = ctx.engine.toggle_question_disabled(q_id)
    return ctx.jsonify({'status': 'ok', 'disabled': disabled})


def update_params(ctx):
    data = ctx.request.get_json(silent=True) or {}
    updated = {}
    errors = []
    for key, value in data.items():
        try:
            ctx.engine.set_config(key, value)
            updated[key] = ctx.engine.config[key]
        except (ValueError, KeyError) as exc:
            errors.append(str(exc))
    return ctx.jsonify({'status': 'ok', 'updated': updated, 'errors': errors})


def cleanup_sessions(ctx):
    deleted = ctx.cleanup_sessions()
    return ctx.jsonify({'status': 'ok', 'deleted': deleted})


def add_fetish(ctx):
    data = ctx.request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    desc = data.get('desc', '').strip()
    if not name:
        return ctx.jsonify({'status': 'error', 'message': '名前を入力してください'}), 400
    if len(name) > 100:
        return ctx.jsonify({'status': 'error', 'message': '名前は100文字以内'}), 400
    if len(desc) > 500:
        return ctx.jsonify({'status': 'error', 'message': '説明は500文字以内'}), 400
    existing = next((fetish for fetish in ctx.engine.fetishes if fetish['name'] == name), None)
    if existing:
        return ctx.jsonify({'status': 'exists', 'fetish_id': existing['id'], 'fetish_name': existing['name']})
    if not desc:
        desc = name
    _, db_id = ctx.engine.add_fetish(name, desc, {})
    return ctx.jsonify({'status': 'created', 'fetish_id': db_id, 'fetish_name': name})


def capture_priors(ctx):
    ctx.engine.capture_learned_priors()
    return ctx.jsonify({'status': 'ok'})


def lookup_fetish(ctx, fetish_id):
    for fetish in ctx.engine.fetishes:
        if fetish.get('id') == fetish_id:
            return ctx.jsonify(
                {
                    'status': 'ok',
                    'id': fetish_id,
                    'name': fetish.get('name', ''),
                    'is_player_fetish': fetish_id >= ctx.player_fetish_base_id,
                }
            )
    return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404


def promote_fetish(ctx, fetish_id):
    if fetish_id < ctx.player_fetish_base_id:
        return ctx.jsonify({'status': 'error', 'message': 'シード性癖は格上げ不要です'}), 400
    new_id = ctx.engine.promote_fetish(fetish_id)
    if new_id is None:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    promoted = next((fetish for fetish in ctx.engine.fetishes if fetish.get('id') == new_id), {})
    reassign_report = result_exposure_service.safe_reassign_fetish_id(
        fetish_id,
        new_id,
        fetish_name=promoted.get('name', ''),
        environ=ctx.environ,
    )
    ctx.write_audit(
        'promote_fetish',
        'ok',
        {
            'old_id': fetish_id,
            'new_id': new_id,
            'result_exposure_reassign': reassign_report,
        },
        ctx.request,
    )
    return ctx.jsonify(
        {
            'status': 'promoted',
            'old_id': fetish_id,
            'new_id': new_id,
            'result_exposure_reassign': reassign_report,
        }
    )


def _repair_mappings_from_request(ctx):
    data = ctx.request.get_json(silent=True) or {}
    raw = data.get('mappings') or []
    mappings = []
    if isinstance(raw, dict):
        raw = [{'old_id': key, 'new_id': value} for key, value in raw.items()]
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            old_id = int(item.get('old_id'))
            new_id = int(item.get('new_id'))
        except (TypeError, ValueError):
            continue
        if old_id >= ctx.player_fetish_base_id and 0 <= new_id < ctx.player_fetish_base_id:
            mappings.append((old_id, new_id))
    return mappings


def _manual_stats_history_mappings_from_request(ctx):
    data = ctx.request.get_json(silent=True) or {}
    raw = data.get('mappings') or []
    mappings = []
    seen_old = set()
    if isinstance(raw, dict):
        raw = [{'old_id': key, 'new_id': value} for key, value in raw.items()]
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            old_id = int(item.get('old_id'))
            new_id = int(item.get('new_id'))
        except (TypeError, ValueError):
            continue
        if old_id == new_id or old_id in seen_old:
            continue
        if 0 <= old_id < ctx.player_fetish_base_id and 0 <= new_id < ctx.player_fetish_base_id:
            mappings.append((old_id, new_id))
            seen_old.add(old_id)
    return mappings


def move_stats_history(ctx):
    data = ctx.request.get_json(silent=True) or {}
    mappings = _manual_stats_history_mappings_from_request(ctx)
    if not mappings:
        return ctx.jsonify(
            {
                'status': 'error',
                'message': 'mappings に正式ID同士の old_id/new_id を指定してください',
                'required_confirm_text': 'MOVE_STATS_HISTORY',
            }
        ), 400
    if data.get('dry_run') is True:
        report = ctx.engine.promoted_stats_history_repair_report(mappings)
        return ctx.jsonify({'status': 'ok', 'mode': 'dry_run', 'required_confirm_text': 'MOVE_STATS_HISTORY', **report})
    confirm_error = ctx.require_confirm('MOVE_STATS_HISTORY')
    if confirm_error:
        return confirm_error
    report = ctx.engine.repair_promoted_stats_history(mappings)
    ctx.write_audit(
        'move_stats_history',
        'ok',
        {
            'mapping_count': report.get('mapping_count', 0),
            'total_value': report.get('total_value', 0),
            'mappings': [{'old_id': old_id, 'new_id': new_id} for old_id, new_id in mappings],
        },
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'mode': 'applied', 'required_confirm_text': 'MOVE_STATS_HISTORY', **report})


def repair_promoted_stats_history(ctx):
    data = ctx.request.get_json(silent=True) or {}
    mappings = _repair_mappings_from_request(ctx)
    if not mappings:
        return ctx.jsonify(
            {
                'status': 'error',
                'message': 'mappings に old_id/new_id を指定してください',
                'required_confirm_text': 'REPAIR_PROMOTED_STATS',
            }
        ), 400
    if ctx.request.method == 'GET' or data.get('dry_run') is True:
        report = ctx.engine.promoted_stats_history_repair_report(mappings)
        return ctx.jsonify(
            {'status': 'ok', 'mode': 'dry_run', 'required_confirm_text': 'REPAIR_PROMOTED_STATS', **report}
        )
    confirm_error = ctx.require_confirm('REPAIR_PROMOTED_STATS')
    if confirm_error:
        return confirm_error
    report = ctx.engine.repair_promoted_stats_history(mappings)
    ctx.write_audit(
        'repair_promoted_stats_history',
        'ok',
        {
            'mapping_count': report.get('mapping_count', 0),
            'total_value': report.get('total_value', 0),
            'mappings': [{'old_id': old_id, 'new_id': new_id} for old_id, new_id in mappings],
        },
        ctx.request,
    )
    return ctx.jsonify({'status': 'ok', 'mode': 'applied', 'required_confirm_text': 'REPAIR_PROMOTED_STATS', **report})


def edit_question(ctx, q_idx):
    data = ctx.request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return ctx.jsonify({'status': 'error', 'message': 'text が必要です'}), 400
    if len(text) > 120:
        return ctx.jsonify({'status': 'error', 'message': '質問は120文字以内'}), 400
    ok = ctx.engine.edit_question(q_idx, text)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '不正なインデックスです'}), 404
    return ctx.jsonify({'status': 'ok', 'q_idx': q_idx, 'text': text})


def edit_fetish(ctx, fetish_id):
    data = ctx.request.get_json(silent=True) or {}
    name = data.get('name', '').strip() or None
    desc = data.get('desc', '').strip() if 'desc' in data else None
    works = None
    if 'works' in data:
        raw = data['works']
        if isinstance(raw, str):
            raw = [work.strip() for work in raw.split(',') if work.strip()]
        elif not isinstance(raw, list):
            return ctx.jsonify({'status': 'error', 'message': 'works はリストまたは文字列で指定してください'}), 400
        works = ctx.parse_works_list(raw)
    if name is not None and len(name) > 50:
        return ctx.jsonify({'status': 'error', 'message': '名前は50文字以内'}), 400
    if works is not None and len(works) > 10:
        return ctx.jsonify({'status': 'error', 'message': '作品は10件以内'}), 400
    ok = ctx.engine.edit_fetish(fetish_id, name=name, desc=desc, works=works)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '見つかりません'}), 404
    idx = ctx.engine.index_of(fetish_id)
    fetish = ctx.engine.fetishes[idx]
    ctx.write_audit(
        'fetish_update',
        'ok',
        {
            'fetish_id': fetish_id,
            'updated_fields': [
                field
                for field, value in (('name', name), ('desc', desc), ('works', works))
                if value is not None
            ],
            'work_count': len(works) if works is not None else None,
        },
        ctx.request,
    )
    return ctx.jsonify(
        {'status': 'ok', 'name': fetish['name'], 'desc': fetish['desc'], 'works': fetish.get('works', [])}
    )


def _export_player_fetishes_to_restore(ctx, exported_fetishes):
    return matrix_handlers._export_player_fetishes_to_restore(ctx, exported_fetishes)


def _missing_export_player_fetishes(ctx, exported_fetishes):
    return matrix_handlers._missing_export_player_fetishes(ctx, exported_fetishes)


def _backup_integer(value, label):
    return matrix_handlers._backup_integer(value, label)


def _matrix_backup_format_version(payload):
    return matrix_handlers._matrix_backup_format_version(payload)


def _adapt_matrix_rows_to_current_questions(ctx, rows, exported_questions, exported_fetishes, fetishes_to_restore):
    return matrix_handlers._adapt_matrix_rows_to_current_questions(
        ctx, rows, exported_questions, exported_fetishes, fetishes_to_restore
    )


def _import_validation_report(ctx, rows, fetishes_to_restore):
    return matrix_handlers._import_validation_report(ctx, rows, fetishes_to_restore)


def _matrix_import_completeness_error(ctx, report, expected_rows):
    return matrix_handlers._matrix_import_completeness_error(ctx, report, expected_rows)


def export_matrix(ctx):
    return matrix_handlers.export_matrix(ctx)


def import_matrix(ctx):
    return matrix_handlers.import_matrix(ctx)


def import_matrix_dry_run(ctx):
    return matrix_handlers.import_matrix_dry_run(ctx)


def matrix_backups(ctx):
    return matrix_handlers.matrix_backups(ctx)


def restore_matrix_backup(ctx, name):
    return matrix_handlers.restore_matrix_backup(ctx, name)


def merge_fetishes(ctx):
    data = ctx.request.get_json(silent=True) or {}
    id_keep = data.get('id_keep')
    id_remove = data.get('id_remove')
    new_name = (data.get('new_name') or '').strip() or None
    new_desc = (data.get('new_desc') or '').strip() or None
    if id_keep is None or id_remove is None:
        return ctx.jsonify({'status': 'error', 'message': 'id_keep と id_remove が必要です'}), 400
    try:
        id_keep = int(id_keep)
        id_remove = int(id_remove)
    except (TypeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'id_keep と id_remove は整数で指定してください'}), 400
    confirm_error = ctx.require_confirm('MERGE')
    if confirm_error:
        return confirm_error
    ok = ctx.engine.merge_fetishes(id_keep, id_remove, new_name=new_name, new_desc=new_desc)
    if not ok:
        return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    idx = ctx.engine.index_of(id_keep)
    name = ctx.engine.fetishes[idx]['name'] if idx is not None else '(unknown)'
    return ctx.jsonify({'status': 'merged', 'id_keep': id_keep, 'name': name})


def works_review(ctx):
    rows = []
    for fetish in ctx.engine.fetishes:
        for work in fetish.get('works', []):
            title = work['title'] if isinstance(work, dict) else work
            url = work.get('url', '') if isinstance(work, dict) else ''
            asin = ''
            url = _admin_work_url(ctx, work, title)
            if url:
                match = ctx.re_search(r'/dp/([A-Z0-9]{10})', url)
                asin = match.group(1) if match else ''
            rows.append((fetish['name'], title, asin, url))
    html = (
        """<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<title>作品リンク確認</title>
<style>
body{font-family:sans-serif;font-size:13px;background:#111;color:#ddd;padding:16px;}
table{border-collapse:collapse;width:100%;}
th{background:#222;padding:6px 10px;text-align:left;position:sticky;top:0;z-index:1;}
td{padding:5px 10px;border-bottom:1px solid #222;vertical-align:top;}
tr:hover td{background:#1a1a1a;}
a{color:#7af0a0;}
.no-url{color:#e94560;}
input{background:#222;color:#ddd;border:1px solid #444;padding:4px 8px;border-radius:4px;margin-bottom:10px;width:300px;}
</style></head><body>
<h2>作品リンク確認（"""
        + str(len(rows))
        + """件）</h2>
<input type="text" id="q" placeholder="性癖名や作品名で絞り込み...">
<table id="tbl">
<tr><th>性癖</th><th>作品タイトル</th><th>ASIN</th><th>リンク</th></tr>"""
    )
    for fetish_name, title, asin, url in rows:
        fetish_name_e = ctx.html_escape(str(fetish_name))
        title_e = ctx.html_escape(str(title))
        asin_e = ctx.html_escape(str(asin))
        if url:
            url_e = ctx.html_escape(str(url), quote=True)
            link = f'<a href="{url_e}" target="_blank" rel="noopener">Kindle</a>'
        else:
            link = '<span class="no-url">URLなし</span>'
        html += f'<tr><td>{fetish_name_e}</td><td>{title_e}</td><td>{asin_e}</td><td>{link}</td></tr>'
    html += """</table>
<script>
document.getElementById("q").addEventListener("input", () => {
  const q = document.getElementById("q").value.toLowerCase();
  document.querySelectorAll("#tbl tr:not(:first-child)").forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
</script>
</body></html>"""
    return ctx.Response(html, mimetype='text/html')


def fetish_similarity(ctx):
    data = ctx.request.get_json(silent=True) or {}
    id_a = data.get('id_a')
    id_b = data.get('id_b')
    if id_a is None or id_b is None:
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b が必要です'}), 400
    try:
        id_a = int(id_a)
        id_b = int(id_b)
    except (TypeError, ValueError):
        return ctx.jsonify({'status': 'error', 'message': 'id_a と id_b は整数で指定してください'}), 400
    result = ctx.engine.fetish_similarity(id_a, id_b)
    if result is None:
        return ctx.jsonify({'status': 'error', 'message': '性癖が見つかりません'}), 404
    return ctx.jsonify({'status': 'ok', **result})


def create_blueprint(ctx_factory, require_admin, require_admin_or_read=None):
    bp = Blueprint('admin_routes', __name__)
    require_admin_or_read = require_admin_or_read or require_admin

    matrix_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        export_matrix=lambda ctx: export_matrix(ctx),
        import_matrix=lambda ctx: import_matrix(ctx),
        import_matrix_dry_run=lambda ctx: import_matrix_dry_run(ctx),
        matrix_backups=lambda ctx: matrix_backups(ctx),
        restore_matrix_backup=lambda ctx, name: restore_matrix_backup(ctx, name),
    )

    works_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        list_compound_works=lambda ctx: list_compound_works(ctx),
        set_compound_works=lambda ctx: set_compound_works(ctx),
        delete_compound_works=lambda ctx, key: delete_compound_works(ctx, key),
        works_review=lambda ctx: works_review(ctx),
        works_link_queue_payload=lambda ctx, **kwargs: works_link_queue_payload(ctx, **kwargs),
        seed_works_backfill_payload=lambda ctx, **kwargs: seed_works_backfill_payload(ctx, **kwargs),
    )

    analytics_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals()[name],
    )

    operations_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals()[name],
    )

    page_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        resolve_handler=lambda name: globals()[name],
    )

    mutation_routes.register_routes(
        bp,
        ctx_factory=ctx_factory,
        require_admin=require_admin,
        require_admin_or_read=require_admin_or_read,
        resolve_handler=lambda name: globals()[name],
    )

    return bp
