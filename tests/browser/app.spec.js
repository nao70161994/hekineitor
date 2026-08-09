import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {expect, test} from '@playwright/test';

const gameplayEventPath = resolve(process.cwd(), 'data/gameplay_events.jsonl');

function gameplayEventCount(eventName) {
  try {
    return readFileSync(gameplayEventPath, 'utf8')
      .split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line))
      .filter(event => event.event_name === eventName)
      .length;
  } catch {
    return 0;
  }
}

async function completeDiagnosis(page) {
  const result = page.locator('#result-screen');
  const question = page.locator('#question-text');
  const yesButton = page.getByRole('button', {name: 'はい', exact: true});
  for (let attempt = 0; attempt < 30 && !(await result.isVisible()); attempt += 1) {
    const previousQuestion = await question.textContent();
    await yesButton.click();
    await page.waitForFunction(
      previous => {
        const resultScreen = document.querySelector('#result-screen');
        const questionText = document.querySelector('#question-text');
        return !resultScreen?.classList.contains('hidden') || questionText?.textContent !== previous;
      },
      previousQuestion,
      {timeout: 10_000},
    );
  }
  await expect(result).toBeVisible();
}

test('completes a diagnosis in a real browser', async ({page}) => {
  await page.goto('/');

  await expect(page.getByRole('heading', {name: 'へきネイター'})).toBeVisible();
  await page.getByRole('button', {name: 'スタート'}).click();

  await expect(page.locator('#question-screen')).toBeVisible();
  await expect(page.locator('#question-text')).not.toHaveText('読み込み中…');

  const result = page.locator('#result-screen');
  const question = page.locator('#question-text');
  const yesButton = page.getByRole('button', {name: 'はい', exact: true});
  for (let attempt = 0; attempt < 30 && !(await result.isVisible()); attempt += 1) {
    const previousQuestion = await question.textContent();
    await yesButton.click();
    await page.waitForFunction(
      previous => {
        const resultScreen = document.querySelector('#result-screen');
        const questionText = document.querySelector('#question-text');
        return !resultScreen?.classList.contains('hidden') || questionText?.textContent !== previous;
      },
      previousQuestion,
      {timeout: 10_000},
    );
  }

  await expect(result).toBeVisible();
  await expect(page.locator('#result-name')).not.toBeEmpty();
});

test('serves install and offline resources', async ({page, request}) => {
  const manifest = await request.get('/manifest.json');
  expect(manifest.ok()).toBe(true);

  await page.goto('/offline');
  await expect(page.locator('body')).toContainText('オフライン');
});


test('covers continue, feedback, history, and mobile transitions', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  const guess = {
    fetish_id: 0,
    fetish_name: 'NTR（寝取られ）',
    fetish_desc: 'テスト用の診断結果',
    probability: 82,
    compound: [],
    top_chart: [{fetish_id: 0, fetish_name: 'NTR（寝取られ）', probability: 82}],
    profile: [],
    related: [],
    reasons: [],
    works: [1, 2, 3, 4, 5].map(id => ({
      title: `作品${id}`,
      url: `https://example.test/${id}`,
      reason: `理由${id}`,
      work_id: `wrk_${id}`,
      edition_id: `wed_${id}`,
    })),
    cross_works: [],
  };
  let answerCount = 0;
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '最初の質問', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', route => {
    answerCount += 1;
    return route.fulfill({json: guess});
  });
  await page.route('**/api/continue', route => route.fulfill({json: {
    action: 'question', question_id: 1, question: '追加の質問', count: 20, total: 30,
  }}));
  await page.route('**/api/confirm', route => route.fulfill({json: {status: 'learned'}}));
  await page.route('**/api/share_link', route => route.fulfill({status: 503, json: {}}));
  await page.route('**/api/share_event', route => route.fulfill({json: {status: 'ok'}}));
  const gameplayEvents = [];
  await page.route('**/api/gameplay_event', route => {
    gameplayEvents.push(route.request().postDataJSON());
    return route.fulfill({json: {status: 'ok'}});
  });
  const revealFeaturedImpressions = async expectedOccurrences => {
    const cards = page.locator('.work-recommendation.featured');
    await expect(cards).toHaveCount(3);
    for (let index = 0; index < 3; index += 1) {
      await cards.nth(index).scrollIntoViewIfNeeded();
      await expect(cards.nth(index)).toBeInViewport();
      await expect.poll(() => gameplayEvents.filter(event => event.work_id === `wrk_${index + 1}`).length).toBe(expectedOccurrences);
    }
  };

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await expect(page.locator('#question-text')).toHaveText('最初の質問');
  await expect(page.locator('#question-text')).toBeInViewport();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-name')).toHaveText('NTR（寝取られ）');
  await expect(page.locator('#result-name')).toBeInViewport();
  const featuredWorks = page.locator('.work-recommendation.featured');
  await expect(featuredWorks).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await featuredWorks.nth(index).scrollIntoViewIfNeeded();
    await expect(featuredWorks.nth(index)).toBeInViewport();
    await expect.poll(() => gameplayEvents.some(event => event.work_id === `wrk_${index + 1}`)).toBe(true);
  }
  await expect.poll(() => gameplayEvents.filter(event => event.event_name === 'work_impression').length).toBe(3);
  expect(gameplayEvents.filter(event => event.event_name === 'work_impression')
    .map(event => [event.work_id, event.edition_id]).sort())
    .toEqual([['wrk_1', 'wed_1'], ['wrk_2', 'wed_2'], ['wrk_3', 'wed_3']]);
  expect(gameplayEvents.some(event => event.work_id === 'wrk_4')).toBe(false);
  await expect(page.locator('.works-more')).toBeHidden();
  await page.getByRole('button', {name: 'ほか2作品を見る'}).click();
  await expect(page.locator('.works-more')).toBeVisible();
  const moreWorks = page.locator('.works-more .work-recommendation');
  await expect(moreWorks).toHaveCount(2);
  for (let index = 0; index < 2; index += 1) {
    await moreWorks.nth(index).scrollIntoViewIfNeeded();
    await expect(moreWorks.nth(index)).toBeInViewport();
    await expect.poll(() => gameplayEvents.some(event => event.work_id === `wrk_${index + 4}`)).toBe(true);
  }
  await expect.poll(() => gameplayEvents.filter(event => event.event_name === 'work_impression').length).toBe(5);
  expect(gameplayEvents.filter(event => event.event_name === 'work_impression').map(event => event.work_id).sort())
    .toEqual(['wrk_1', 'wrk_2', 'wrk_3', 'wrk_4', 'wrk_5']);

  await page.getByRole('button', {name: '追加質問で精度を上げる'}).click();
  await expect(page.locator('#question-text')).toHaveText('追加の質問');
  await expect(page.locator('#question-stage-label')).toHaveText('追加質問 1/10');
  const savedPairs = await page.evaluate(() => JSON.parse(localStorage.getItem('heki_draft')).pairs);
  expect(savedPairs).toEqual([{q_id: 0, answer: 1}]);

  await page.getByRole('button', {name: 'はい', exact: true}).click();
  expect(answerCount).toBe(2);
  await revealFeaturedImpressions(2);
  await expect.poll(() => gameplayEvents.filter(event => event.event_name === 'work_impression').length).toBe(8);
  await page.getByRole('button', {name: '当たってる'}).click();
  await expect(page.locator('#quick-feedback-status')).toContainText('正解として学習しました');

  await page.getByRole('button', {name: 'タイトルに戻る'}).click();
  await page.getByRole('button', {name: /診断履歴/}).click();
  await expect(page.locator('#history-panel')).toContainText('NTR（寝取られ）');
  await page.locator('.history-item').filter({hasText: 'NTR（寝取られ）'}).first().getByRole('button', {name: '結果を見る'}).click();
  await expect(page.locator('#result-name')).toHaveText('NTR（寝取られ）');
  await revealFeaturedImpressions(3);
  await expect.poll(() => gameplayEvents.filter(event => event.event_name === 'work_impression').length).toBe(11);
  expect(gameplayEvents.filter(event => event.event_name === 'history_reopened')).toHaveLength(1);
});

const compoundGuess = {
  fetish_id: 1,
  fetish_name: '本命',
  fetish_desc: 'テスト用の複合結果',
  probability: 78,
  runner_up: {fetish_id: 4, fetish_name: '対抗候補', probability: 70, gap_points: 8},
  contrastive_reasons: [{text: '対抗候補との差になった決め手', ans: 1}],
  compound_explanation: '本命と二つの要素が同時に表れました。',
  compound: [
    {fetish_id: 2, fetish_name: '要素A', probability: 69, reasons: [{text: '要素Aの決め手', ans: 1}]},
    {fetish_id: 3, fetish_name: '要素B', probability: 64, reasons: [{text: '要素Bの決め手', ans: -0.5}]},
  ],
  top_chart: [{fetish_id: 1, fetish_name: '本命', probability: 78}],
  profile: [],
  related: [],
  reasons: [{text: '本命の決め手', ans: 1}],
  works: [{title: '通常作品', url: 'https://example.test/normal'}],
  cross_works: [{title: '複合作品', url: 'https://example.test/cross'}],
  work_recommendations: [{reason: '複合要素が重なる理由'}, {reason: '本命に関連する理由'}],
};

async function routeSingleQuestion(page, guess = compoundGuess) {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '最初の質問', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', route => route.fulfill({json: guess}));
}


test('retries an ambiguous answer with the same client request id', async ({page}) => {
  const payloads = [];
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '最初の質問', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', async route => {
    payloads.push(route.request().postDataJSON());
    if (payloads.length === 1) {
      await route.abort('failed');
      return;
    }
    await route.fulfill({json: {
      action: 'question', question_id: 1, question: '次の質問', count: 1, total: 20,
    }});
  });

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#question-text')).toHaveText('次の質問');
  await expect.poll(() => payloads.length).toBe(2);
  expect(payloads[0].answer_request_id).toBeTruthy();
  expect(payloads[1].answer_request_id).toBe(payloads[0].answer_request_id);
});
test('shows answer progress and locks an ambiguously failed answer for reconciliation', async ({page}) => {
  let answerCount = 0;
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '遅延確認', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', async route => {
    answerCount += 1;
    if (answerCount === 1) {
      await new Promise(resolve => setTimeout(resolve, 2500));
      await route.fulfill({json: {
        action: 'question', question_id: 1, question: '失敗確認', count: 1, total: 20,
      }});
      return;
    }
    await route.abort('failed');
  });

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  const yes = page.getByRole('button', {name: 'はい', exact: true});
  await yes.click();
  await expect(yes).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#genie')).toHaveClass(/thinking/);
  await expect(page.locator('#answer-status')).toContainText('まだ考えています');
  await expect(page.locator('#question-text')).toHaveText('失敗確認');

  const no = page.getByRole('button', {name: 'いいえ', exact: true});
  await no.click();
  await expect(page.locator('#answer-status')).toContainText('回答済みか確認できません');
  await expect(no).toBeDisabled();
  await expect(page.locator('#answer-reconcile')).toBeVisible();
  await expect(page.locator('#genie')).not.toHaveClass(/thinking/);
});


test('saves exclusions with title return and clears them only on discard', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '保存前の質問', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', route => route.fulfill({json: {
    action: 'question', question_id: 1, question: '保存後の質問', count: 1, total: 20,
  }}));

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.evaluate(() => window.HekiState.setExcludedIds([4, 7]));
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await page.getByRole('button', {name: 'タイトルへ'}).click();
  await expect(page.locator('#modal-restart-desc')).toContainText('除外リスト（2件）も失われます');
  await page.getByRole('button', {name: '保存してタイトルへ'}).click();
  await expect(page.locator('#resume-banner')).toBeVisible();
  const saved = await page.evaluate(() => ({
    draft: JSON.parse(localStorage.getItem('heki_draft')),
    excludedIds: window.HekiState.getExcludedIds(),
  }));
  expect(saved.draft.exclude_ids).toEqual([4, 7]);
  expect(saved.excludedIds).toEqual([4, 7]);

  await page.getByRole('button', {name: '破棄する'}).click();
  const discarded = await page.evaluate(() => ({
    draft: localStorage.getItem('heki_draft'),
    excludedIds: window.HekiState.getExcludedIds(),
  }));
  expect(discarded).toEqual({draft: null, excludedIds: []});
});
test('resumes a saved diagnosis and excludes every shown result on retry', async ({page}) => {
  const now = Date.now();
  await page.addInitScript(({savedAt}) => {
    localStorage.setItem('heki_draft', JSON.stringify({
      pairs: [{q_id: 4, answer: 0.5}], exclude_ids: [8, 9], ts: savedAt, expires_at: savedAt + 7 * 24 * 3600 * 1000,
    }));
  }, {savedAt: now});
  let resumeBody = null;
  await page.route('**/api/resume', route => {
    resumeBody = route.request().postDataJSON();
    return route.fulfill({json: {
    action: 'question', question_id: 5, question: '復帰後の質問', count: 1, total: 20,
    }});
  });
  await page.route('**/api/answer', route => route.fulfill({json: compoundGuess}));
  let retryBody = null;
  await page.route('**/api/start', route => {
    retryBody = route.request().postDataJSON();
    return route.fulfill({json: {
      action: 'question', question_id: 6, question: '除外後の質問', count: 0, total: 20,
    }});
  });

  await page.goto('/');
  await expect(page.locator('#resume-banner')).toBeVisible();
  await expect(page.locator('#resume-count')).toHaveText('1');
  await expect(page.locator('#resume-updated-at')).not.toBeEmpty();
  await expect(page.locator('#resume-expires-at')).not.toBeEmpty();
  await page.getByRole('button', {name: '続行する'}).click();
  await expect(page.locator('#question-text')).toHaveText('復帰後の質問');
  expect(resumeBody.exclude_ids).toEqual([8, 9]);
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-name')).toHaveText('本命 × 要素A × 要素B');
  await page.getByRole('button', {name: '当て直す'}).click();
  await expect(page.locator('#question-text')).toHaveText('除外後の質問');
  expect(retryBody.exclude_ids.sort((a, b) => a - b)).toEqual([1, 2, 3, 8, 9]);
});

test('stages compound detail feedback and finalizes one atomic batch', async ({page}) => {
  let confirmBody = null;
  let finalizeBody = null;
  const shareEvents = [];
  await routeSingleQuestion(page);
  await page.route('**/api/confirm', route => {
    confirmBody = route.request().postDataJSON();
    return route.fulfill({json: {
      status: 'wrong',
      atomic: true,
      processed_count: 3,
      fetishes: [{id: 11, name: '訂正候補', desc: '複合結果に近い候補'}],
    }});
  });
  await page.route('**/api/finalize_added', route => {
    finalizeBody = route.request().postDataJSON();
    return route.fulfill({json: {
      status: 'done', atomic: true, feedback_outcome: 'mixed', correction_count: 1,
    }});
  });
  await page.route('**/api/share_event', route => {
    shareEvents.push(route.request().postDataJSON());
    return route.fulfill({json: {status: 'ok'}});
  });

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('.result-icon')).toBeInViewport();
  await expect(page.locator('#result-name')).toBeInViewport();
  await expect(page.getByRole('region', {name: '対抗候補「対抗候補」との差になった回答'}))
    .toContainText('対抗候補との差になった決め手');
  await expect(page.locator('#result-rival')).toContainText('対抗候補「対抗候補」');
  await expect(page.locator('#result-desc')).toContainText('本命と二つの要素が同時に表れました。');
  await expect(page.locator('#compound-reasons-section')).toContainText('要素Aの決め手');
  await expect(page.locator('.work-recommendation').first()).toContainText('複合要素が重なる理由');
  await page.evaluate(() => document.addEventListener('click', event => {
    if (event.target.closest('a[data-work-title]')) event.preventDefault();
  }));
  await page.locator('a[data-work-title="複合作品"]').click();
  await expect.poll(() => shareEvents.some(event => event.event_name === 'work_click' && event.work_title === '複合作品')).toBe(true);

  await page.getByRole('button', {name: '詳細に○△×を付ける'}).click();
  await page.getByRole('button', {name: '本命: 当たっている'}).click();
  await page.getByRole('button', {name: '要素A: 惜しい'}).click();
  await page.getByRole('button', {name: '要素B: 違う'}).click();
  await page.getByRole('button', {name: '確定して学習'}).click();

  await expect(page.locator('#teach-screen')).toBeVisible();
  await page.getByRole('button', {name: '訂正候補'}).click();
  await page.getByRole('button', {name: '1件を学習する'}).click();
  await expect(page.locator('#done-screen')).toBeVisible();
  expect(confirmBody).toMatchObject({
    fetish_id: 1, compound_ids: [2, 3], correct_ids: [1], maybe_ids: [2], wrong_ids: [3],
  });
  expect(finalizeBody).toEqual({items: [{id: 11, is_new: false}]});
});

test('offers three near-miss corrections first and saves one correction atomically', async ({page}) => {
  let confirmBody = null;
  let finalizeBody = null;
  await routeSingleQuestion(page, {...compoundGuess, compound: []});
  await page.route('**/api/confirm', route => {
    confirmBody = route.request().postDataJSON();
    return route.fulfill({json: {
      status: 'wrong',
      atomic: true,
      fetishes: [11, 12, 13, 14, 15].map(id => ({id, name: `候補${id}`, desc: `説明${id}`, prob: 10})),
    }});
  });
  await page.route('**/api/finalize_added', route => {
    finalizeBody = route.request().postDataJSON();
    return route.fulfill({json: {
      status: 'done', atomic: true, feedback_outcome: 'maybe', correction_count: 1,
    }});
  });

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await page.getByRole('button', {name: '惜しい'}).click();

  await expect(page.locator('#teach-screen')).toBeVisible();
  await expect(page.locator('#fetish-list .fetish-item')).toHaveCount(5);
  await expect(page.locator('#fetish-list .candidate-extra.hidden')).toHaveCount(2);
  await page.getByRole('button', {name: 'ほかの候補を見る'}).click();
  await expect(page.locator('#fetish-list .candidate-extra.hidden')).toHaveCount(0);
  await page.getByRole('button', {name: /候補11/}).click();
  await page.getByRole('button', {name: /候補12/}).click();
  await expect(page.getByRole('button', {name: /候補11/})).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', {name: /候補12/})).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', {name: '1件を学習する'}).click();

  await expect(page.locator('#done-screen')).toBeVisible();
  expect(confirmBody).toMatchObject({
    correct: false, fetish_id: 1, defer_learning: true, maybe_ids: [], wrong_ids: [],
  });
  expect(finalizeBody).toEqual({items: [{id: 12, is_new: false}]});
});

test('records feedback completion and a normal non-exclusion retry', async ({page}) => {
  const feedbackBefore = gameplayEventCount('feedback_completed');
  const retryBefore = gameplayEventCount('retry_started');

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await completeDiagnosis(page);
  await page.getByRole('button', {name: '当たってる'}).click();
  await expect(page.locator('#quick-feedback-status')).toContainText('正解として学習しました');
  await expect.poll(() => gameplayEventCount('feedback_completed')).toBeGreaterThan(feedbackBefore);

  await page.getByRole('button', {name: 'タイトルに戻る'}).click();
  const retryRequest = page.waitForRequest(request => (
    request.url().endsWith('/api/start') && request.method() === 'POST'
  ));
  await page.getByRole('button', {name: 'スタート'}).click();
  const request = await retryRequest;
  expect(request.postData()).toBeNull();
  await expect(page.locator('#question-screen')).toBeVisible();
  await expect.poll(() => gameplayEventCount('retry_started')).toBeGreaterThan(retryBefore);
});

test('falls back to selectable share text and reaches the bottom on narrow layouts', async ({page}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'share', {
      configurable: true,
      value: () => Promise.reject(Object.assign(new Error('blocked'), {name: 'NotAllowedError'})),
    });
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {writeText: () => Promise.reject(new Error('denied'))},
    });
  });
  await routeSingleQuestion(page);
  await page.route('**/api/share_link', route => route.fulfill({status: 503, json: {}}));
  await page.route('**/api/share_event', route => route.fulfill({json: {status: 'ok'}}));

  await page.setViewportSize({width: 320, height: 568});
  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await page.getByRole('button', {name: '友達にも試してもらう'}).click();
  await expect(page.locator('#modal-share-fallback')).toBeVisible();
  await expect(page.locator('#share-fallback-text')).toHaveValue(/本命 × 要素A × 要素B/);
  await page.getByRole('button', {name: '閉じる'}).click();
  const home = page.getByRole('button', {name: 'タイトルに戻る'}).first();
  await home.scrollIntoViewIfNeeded();
  await expect(home).toBeInViewport();

  await page.setViewportSize({width: 667, height: 375});
  await home.scrollIntoViewIfNeeded();
  await expect(home).toBeInViewport();
});
