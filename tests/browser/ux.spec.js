import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

async function expectNoSeriousAccessibilityViolations(page) {
  const results = await new AxeBuilder({page})
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

test('start experience is understandable, keyboard reachable, and accessible', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question',
    question_id: 0,
    question: '誰にも見せない選択ほど、自分らしさが出る？',
    count: 0,
    total: 30,
  }}));
  await page.goto('/');

  const startHeading = page.getByRole('heading', {name: 'あなたの「好き」、見抜けるかも'});
  const startIntro = page.locator('.start-intro');
  await expect(startHeading).toBeVisible();
  await expect(startIntro).toBeVisible();
  const headingBox = await startHeading.boundingBox();
  const introBox = await startIntro.boundingBox();
  expect(introBox.y).toBeGreaterThan(headingBox.y + headingBox.height);
  await expect(page.getByRole('button', {name: '診断をはじめる'})).toBeVisible();
  await expect(page.getByText('20〜30問・約3〜5分')).toBeVisible();
  await expect(page.getByRole('link', {name: 'データの扱い', exact: true})).toHaveAttribute('href', '/privacy');
  await expectNoSeriousAccessibilityViolations(page);

  await page.keyboard.press('Tab');
  const skipLink = page.getByRole('link', {name: '診断へ移動'});
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeInViewport();
  await page.keyboard.press('Enter');
  await expect(page.locator('#app-main')).toBeFocused();

  await page.getByRole('button', {name: '診断をはじめる'}).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#question-text')).toBeFocused();
  await expect(page.locator('#question-stage-label')).toHaveText('質問 1');
  await expect(page.locator('#question-answer-frame')).toHaveCount(0);
  await expectNoSeriousAccessibilityViolations(page);
});

test('question host frames the answer, acknowledges the choice, and tracks progress', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question',
    question_id: 0,
    question: 'この関係性の変化に惹かれる？',
    count: 0,
    total: 20,
    answer_frame: '作品・設定の好みとして',
    progress_message: '最初の手がかりを見つけたよ',
  }}));
  await page.route('**/api/answer', async route => {
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({json: {
      action: 'question',
      question_id: 1,
      question: 'ふたりの距離が近づく展開が好き？',
      count: 1,
      total: 20,
      answer_frame: '人物・関係性の好みとして',
      progress_message: '少しずつ輪郭が見えてきたよ',
    }});
  });

  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expect(page.getByText('今回の視点：作品・設定の好みとして')).toBeVisible();
  await expect(page.locator('#question-progress')).toHaveAttribute('aria-valuetext', '質問 1 / 20');
  await expect(page.getByText('最初の手がかりを見つけたよ')).toBeVisible();

  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#genie')).toHaveClass(/thinking/);
  await expect(page.locator('#question-text')).toHaveText('ふたりの距離が近づく展開が好き？');
  await expect(page.locator('#question-progress')).toHaveAttribute('aria-valuetext', '質問 2 / 20');
  await expect(page.getByText('今回の視点：人物・関係性の好みとして')).toBeVisible();
  await expect(page.locator('#genie')).toHaveClass(/acknowledge/);
  await expect(page.locator('#answer-status')).toHaveText('「はい」を手がかりに加えたよ。次の質問だね。');
});

test('long questions stay readable in landscape without hiding the genie or causing horizontal overflow', async ({page}) => {
  const longQuestion = '物語のなかで、立場や価値観の違う人物たちが時間をかけて理解し合い、少しずつ信頼を深めていく展開に惹かれる？';
  await page.setViewportSize({width: 812, height: 375});
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question',
    question_id: 0,
    question: longQuestion,
    count: 0,
    total: 20,
    answer_frame: '作品・設定の好みとして',
  }}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expect(page.locator('#question-text')).toHaveText(longQuestion);
  await expect(page.getByRole('button', {name: 'どちらかといえばいいえ'})).toBeVisible();

  const layout = await page.evaluate(() => {
    const genie = document.querySelector('#genie').getBoundingClientRect();
    return {
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      genieVisible: genie.bottom > 0 && genie.top < innerHeight,
      questionHeight: document.querySelector('#question-text').getBoundingClientRect().height,
      answersFit: [...document.querySelectorAll('#question-screen .btn-group button')]
        .every(button => button.getBoundingClientRect().bottom <= innerHeight),
    };
  });
  expect(layout.overflow).toBeLessThanOrEqual(1);
  expect(layout.genieVisible).toBe(true);
  expect(layout.questionHeight).toBeGreaterThan(80);
  expect(layout.answersFit).toBe(true);
});

test('public pages fit small screens and enlarged Japanese text', async ({page}) => {
  for (const viewport of [
    {width: 320, height: 568},
    {width: 375, height: 812},
    {width: 768, height: 900},
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const startButtonBox = await page.getByRole('button', {name: '診断をはじめる'}).boundingBox();
    expect(startButtonBox.height).toBeGreaterThanOrEqual(48);
  }

  for (const scale of ['200%', '400%']) {
    await page.setViewportSize({width: 320, height: 568});
    await page.goto('/');
    await page.evaluate(value => { document.documentElement.style.fontSize = value; }, scale);
    const enlargedOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(enlargedOverflow).toBeLessThanOrEqual(1);
  }

  await page.goto('/privacy');
  await expect(page.getByRole('heading', {name: 'データの扱い'})).toBeVisible();
  await expectNoSeriousAccessibilityViolations(page);
});

test('restart dialog traps keyboard focus, hides the background, and restores the trigger', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '静かな場所では、細かな変化に気づきやすい？', count: 0,
  }}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  const trigger = page.getByRole('button', {name: '中断', exact: true});
  await trigger.click();

  const dialog = page.getByRole('dialog', {name: 'タイトルへ戻りますか？'});
  await expect(dialog).toBeFocused();
  await expect(page.locator('#app-main')).toHaveAttribute('aria-hidden', 'true');
  await expectNoSeriousAccessibilityViolations(page);

  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', {name: 'キャンセル'})).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByRole('button', {name: '破棄してタイトルへ'})).toBeFocused();
  await page.keyboard.press('Escape');

  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(page.locator('#app-main')).not.toHaveAttribute('aria-hidden');
});

test('result hierarchy explains confidence before offering share actions', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '静かな余韻が長く残る方が好き？', count: 0, total: 30,
  }}));
  await page.route('**/api/answer', route => route.fulfill({json: {
    fetish_id: 65,
    fetish_name: '静かな共同生活',
    fetish_desc: '言葉よりも日々の積み重ねに惹かれる傾向です。',
    probability: 72,
    compound: [],
    top_chart: [
      {fetish_id: 65, fetish_name: '静かな共同生活', probability: 72},
      {fetish_id: 12, fetish_name: '穏やかな信頼', probability: 63},
    ],
    profile: [], related: [], reasons: [{text: '静かな余韻が長く残る方が好き？', ans: 1}], works: [], cross_works: [],
  }}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();

  await expect(page.getByRole('heading', {name: '静かな共同生活'})).toBeFocused();
  await expect(page.locator("#result-details")).toBeHidden();
  const descriptionBox = await page.locator('#result-desc').boundingBox();
  const shareBox = await page.getByRole('button', {name: '共有する', exact: true}).boundingBox();
  expect(descriptionBox.y).toBeLessThan(shareBox.y);
  await page.getByRole("button", {name: "結果を詳しく見る"}).click();
  await expect(page.getByText("一致度は回答との近さを表す参考値です。表示結果の偏りを抑える調整も行っています。")).toBeVisible();
  await expectNoSeriousAccessibilityViolations(page);
});
