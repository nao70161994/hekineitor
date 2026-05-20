def learn(engine, answers, fetish_idx, strength_factor=1.0, *, pseudo):
    neg_weight = 0.3
    disc_scales = engine._get_disc_scales()
    all_updates = {}
    idx_to_db_id = {}

    with engine._lock:
        nf = len(engine.fetishes)
        nq = len(engine.questions)
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
            scale = min(1.0, pseudo / max(engine.matrix['total'][fetish_idx][q], pseudo))
            effective = strength * scale * strength_factor * disc_scales[q]

            delta_yes = effective if ans > 0 else 0.0
            engine.matrix['total'][fetish_idx][q] += effective
            engine.matrix['yes'][fetish_idx][q] += delta_yes
            all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))

            for f in range(nf):
                if f == fetish_idx:
                    continue
                weight = neg_weight * effective
                neg_yes = weight * (0.0 if ans > 0 else 1.0)
                engine.matrix['total'][f][q] += weight
                engine.matrix['yes'][f][q] += neg_yes
                all_updates.setdefault(f, []).append((q, neg_yes, weight))

        idx_to_db_id = {i: fetish['id'] for i, fetish in enumerate(engine.fetishes)}

    engine._save_async(all_updates, idx_to_db_id)
    engine._increment_learn_count()


def learn_cooccurrence(engine, answers, idx_a, idx_b, factor=0.25, *, pseudo):
    nf = len(engine.fetishes)
    nq = len(engine.questions)
    if not (0 <= idx_a < nf and 0 <= idx_b < nf and idx_a != idx_b):
        return
    all_updates = {}
    idx_to_db_id = {}
    with engine._lock:
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if ans == 0 or not (0 <= q < nq):
                continue
            for target, src in ((idx_a, idx_b), (idx_b, idx_a)):
                p_src = engine._prob(src, q)
                synthetic_ans = 1.0 if p_src >= 0.5 else -1.0
                if synthetic_ans * ans < 0:
                    continue
                scale = min(1.0, pseudo / max(engine.matrix['total'][target][q], pseudo))
                effective = abs(p_src - 0.5) * factor * scale
                if effective < 0.005:
                    continue
                delta_yes = effective if synthetic_ans > 0 else 0.0
                engine.matrix['yes'][target][q] += delta_yes
                engine.matrix['total'][target][q] += effective
                all_updates.setdefault(target, []).append((q, delta_yes, effective))
        idx_to_db_id = {i: fetish['id'] for i, fetish in enumerate(engine.fetishes)}

    engine._save_async(all_updates, idx_to_db_id)


def learn_near_miss(engine, answers, fetish_idx, strength_factor=1.0, *, pseudo):
    near_strength = 0.35 * strength_factor
    disc_scales = engine._get_disc_scales()
    all_updates = {}
    idx_to_db_id = {}
    with engine._lock:
        nf = len(engine.fetishes)
        nq = len(engine.questions)
        if not (0 <= fetish_idx < nf):
            return
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if ans == 0 or not (0 <= q < nq):
                continue
            strength = abs(ans) * near_strength
            scale = min(1.0, pseudo / max(engine.matrix['total'][fetish_idx][q], pseudo))
            effective = strength * scale * disc_scales[q]
            delta_yes = effective if ans > 0 else 0.0
            engine.matrix['yes'][fetish_idx][q] += delta_yes
            engine.matrix['total'][fetish_idx][q] += effective
            all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))
        idx_to_db_id = {i: fetish['id'] for i, fetish in enumerate(engine.fetishes)}

    engine._save_async(all_updates, idx_to_db_id)
    engine._increment_learn_count()


def learn_negative(engine, answers, fetish_idx, strength_factor=1.0, *, pseudo):
    neg_strength = 0.2 * strength_factor
    all_updates = {}
    idx_to_db_id = {}
    with engine._lock:
        nf = len(engine.fetishes)
        nq = len(engine.questions)
        if not (0 <= fetish_idx < nf):
            return
        for q_str, ans in answers.items():
            try:
                q = int(q_str)
            except (ValueError, TypeError):
                continue
            if ans == 0 or not (0 <= q < nq):
                continue
            strength = abs(ans) * neg_strength
            scale = min(1.0, pseudo / max(engine.matrix['total'][fetish_idx][q], pseudo))
            effective = strength * scale
            delta_yes = 0.0 if ans > 0 else effective
            engine.matrix['yes'][fetish_idx][q] += delta_yes
            engine.matrix['total'][fetish_idx][q] += effective
            all_updates.setdefault(fetish_idx, []).append((q, delta_yes, effective))
        idx_to_db_id = {i: fetish['id'] for i, fetish in enumerate(engine.fetishes)}

    engine._save_async(all_updates, idx_to_db_id)
