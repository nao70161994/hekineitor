"""Analytics and report handlers for the administrative API."""

from datetime import date, timedelta

from services import context as context_service
from services import gameplay_events as gameplay_events_service
from services import inference as inference_service
from services import question_events as question_events_service
from services import result_exposure as result_exposure_service
from services import share_events as share_events_service
from services.csv_safety import csv_text


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
        return (
            ctx.jsonify(
                {'status': 'error', 'message': 'answers は q:answer のカンマ区切りで指定してください', 'errors': errors}
            ),
            400,
        )
    if not answers:
        return ctx.jsonify({'status': 'error', 'message': 'answers が空です'}), 400
    invalid_ids = [
        int(question_id) for question_id in answers if not (0 <= int(question_id) < len(ctx.engine.questions))
    ]
    if invalid_ids:
        return (
            ctx.jsonify({'status': 'error', 'message': '不正な質問IDです', 'invalid_question_ids': invalid_ids[:20]}),
            400,
        )
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
            'share_analytics': (
                'Postgres analytics_events' if share_storage.get('storage') == 'postgres' else 'JSONL share_events'
            ),
            'question_analytics': (
                'Postgres analytics_events'
                if question_storage.get('storage') == 'postgres'
                else 'JSONL question_events'
            ),
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
    works_by_fetish = ctx.engine.recommended_works_snapshot()
    enriched = []
    for row in rows:
        works = works_by_fetish.get(int(row['id']), [])
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


def gameplay_events_report(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 5000, 1, 50000)
    return ctx.jsonify({'status': 'ok', **ctx.gameplay_event_report(limit=limit)})


def gameplay_events_csv(ctx):
    limit = ctx.bounded_int(ctx.request.args.get('limit'), 5000, 1, 50000)
    report = ctx.gameplay_event_report(limit=limit)
    return ctx.Response(
        gameplay_events_service.summary_csv(report),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="gameplay_summaries_v2.csv"'},
    )


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
        works = ctx.engine.get_recommended_works(fetish['id'])
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
