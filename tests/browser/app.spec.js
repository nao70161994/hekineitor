import {expect, test} from '@playwright/test';

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
    works: [1, 2, 3, 4, 5].map(id => ({title: `作品${id}`, url: `https://example.test/${id}`, reason: `理由${id}`})),
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

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await expect(page.locator('#question-text')).toHaveText('最初の質問');
  await expect(page.locator('#question-text')).toBeInViewport();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-name')).toHaveText('NTR（寝取られ）');
  await expect(page.locator('#result-name')).toBeInViewport();
  await expect(page.locator('.work-recommendation.featured')).toHaveCount(3);
  await expect(page.locator('.works-more')).toBeHidden();
  await page.getByRole('button', {name: 'ほか2作品を見る'}).click();
  await expect(page.locator('.works-more')).toBeVisible();

  await page.getByRole('button', {name: '追加質問で精度を上げる'}).click();
  await expect(page.locator('#question-text')).toHaveText('追加の質問');
  await expect(page.locator('#question-stage-label')).toHaveText('追加質問 1/10');
  const savedPairs = await page.evaluate(() => JSON.parse(localStorage.getItem('heki_draft')).pairs);
  expect(savedPairs).toEqual([{q_id: 0, answer: 1}]);

  await page.getByRole('button', {name: 'はい', exact: true}).click();
  expect(answerCount).toBe(2);
  await page.getByRole('button', {name: '当たってる'}).click();
  await expect(page.locator('#quick-feedback-status')).toContainText('正解として学習しました');

  await page.getByRole('button', {name: 'タイトルに戻る'}).click();
  await page.getByRole('button', {name: /診断履歴/}).click();
  await expect(page.locator('#history-panel')).toContainText('NTR（寝取られ）');
  await page.locator('.history-item').filter({hasText: 'NTR（寝取られ）'}).first().getByRole('button', {name: '結果を見る'}).click();
  await expect(page.locator('#result-name')).toHaveText('NTR（寝取られ）');
});

const compoundGuess = {
  fetish_id: 1,
  fetish_name: '本命',
  fetish_desc: 'テスト用の複合結果',
  probability: 78,
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

test('shows answer progress, a delay message, and safely recovers after failure', async ({page}) => {
  let answerCount = 0;
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '遅延確認', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', async route => {
    answerCount += 1;
    if (answerCount === 1) {
      await new Promise(resolve => setTimeout(resolve, 1200));
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
  await expect(page.locator('#answer-status')).toContainText('送信できませんでした');
  await expect(no).toBeEnabled();
  await expect(page.locator('#genie')).not.toHaveClass(/thinking/);
});

test('resumes a saved diagnosis and excludes every shown result on retry', async ({page}) => {
  const now = Date.now();
  await page.addInitScript(({savedAt}) => {
    localStorage.setItem('heki_draft', JSON.stringify({
      pairs: [{q_id: 4, answer: 0.5}], ts: savedAt, expires_at: savedAt + 7 * 24 * 3600 * 1000,
    }));
  }, {savedAt: now});
  await page.route('**/api/resume', route => route.fulfill({json: {
    action: 'question', question_id: 5, question: '復帰後の質問', count: 1, total: 20,
  }}));
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
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-name')).toHaveText('本命 × 要素A × 要素B');
  await page.getByRole('button', {name: '当て直す'}).click();
  await expect(page.locator('#question-text')).toHaveText('除外後の質問');
  expect(retryBody.exclude_ids.sort()).toEqual([1, 2, 3]);
});

test('submits compound detail feedback atomically and tracks a work click', async ({page}) => {
  let confirmBody = null;
  const shareEvents = [];
  await routeSingleQuestion(page);
  await page.route('**/api/confirm', route => {
    confirmBody = route.request().postDataJSON();
    return route.fulfill({json: {status: 'learned'}});
  });
  await page.route('**/api/share_event', route => {
    shareEvents.push(route.request().postDataJSON());
    return route.fulfill({json: {status: 'ok'}});
  });

  await page.goto('/');
  await page.getByRole('button', {name: 'スタート'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
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
  await expect(page.locator('#done-screen')).toBeVisible();
  expect(confirmBody).toMatchObject({
    fetish_id: 1, compound_ids: [2, 3], correct_ids: [1], maybe_ids: [2], wrong_ids: [3],
  });
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
