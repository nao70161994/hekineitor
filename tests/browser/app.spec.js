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
    works: [],
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

  await page.getByRole('button', {name: 'もう少し続ける'}).click();
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
});
