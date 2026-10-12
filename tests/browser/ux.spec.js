import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

test.use({serviceWorkers: 'block'});

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
    await new Promise(resolve => setTimeout(resolve, 700));
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

test('desktop gameplay keeps the genie, question, and answers together; mobile keeps a full-size host', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '静かな余韻が長く残る方が好き？', count: 0, total: 24,
  }}));
  await page.route('**/api/answer', route => route.fulfill({json: {
    action: 'question', question_id: 1, question: '答え方に迷うときもある？', count: 1, total: 24,
  }}));
  for (const viewport of [{width: 1280, height: 900}, {width: 375, height: 812}]) {
    await page.setViewportSize(viewport);
    await page.goto('/', {waitUntil: 'domcontentloaded'});
    await page.locator('[data-action="start-game"]').click();
    await expect(page.locator('#genie')).toBeVisible();
    const composition = await page.evaluate(() => {
      const card = document.querySelector('.card').getBoundingClientRect();
      const genie = document.querySelector('#genie').getBoundingClientRect();
      const question = document.querySelector('#question-text').getBoundingClientRect();
      const answers = [...document.querySelectorAll('#question-screen .btn-group button')];
      return {
        cardContainsGenie: genie.left >= card.left && genie.right <= card.right,
        cardContainsQuestion: question.left >= card.left && question.right <= card.right,
        avatarHeight: genie.height,
        desktopSideBySide: innerWidth >= 900 ? genie.left < question.left && genie.right <= question.left + 24 : true,
        answerTargets: answers.map(button => button.getBoundingClientRect().height),
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });
    expect(composition.cardContainsGenie).toBe(true);
    expect(composition.cardContainsQuestion).toBe(true);
    expect(composition.avatarHeight).toBeGreaterThan(viewport.width >= 900 ? 200 : 100);
    expect(composition.desktopSideBySide).toBe(true);
    expect(composition.answerTargets.every(height => height >= 48)).toBe(true);
    expect(composition.overflow).toBeLessThanOrEqual(1);
    await page.getByRole('button', {name: 'はい', exact: true}).click();
    await expect(page.locator('#question-text')).toHaveText('答え方に迷うときもある？');
    await expect(page.locator('#genie')).toHaveClass(/acknowledge/);
  }
});

test('result reveal leaves feedback available and the genie celebrates a correct guess', async ({page}) => {
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question', question_id: 0, question: '静かな余韻が長く残る方が好き？', count: 0, total: 20,
  }}));
  await page.route('**/api/answer', route => route.fulfill({json: {
    fetish_id: 65, fetish_name: '静かな共同生活', fetish_desc: '日々の積み重ねに惹かれる傾向です。',
    probability: 72, compound: [], top_chart: [], profile: [], related: [],
    reasons: [{text: '静かな余韻が長く残る方が好き？', ans: 1}], works: [], cross_works: [],
  }}));
  await page.route('**/api/confirm', route => route.fulfill({json: {status: 'learned'}}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#genie')).toHaveClass(/reveal/);
  await expect(page.getByRole('button', {name: '当たってる'})).toBeEnabled();
  await expect(page.getByRole('button', {name: '共有する'})).toBeEnabled();
  await page.getByRole('button', {name: '当たってる'}).click();
  await expect(page.locator('#genie')).toHaveClass(/celebrate/);
  await expect(page.locator('#quick-feedback-status')).toContainText('正解として学習しました');
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
    const answers = [...document.querySelectorAll('#question-screen .btn-group button')].map(button => {
      const box = button.getBoundingClientRect();
      return {height: box.height, bottom: box.bottom};
    });
    return {
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      genieVisible: genie.bottom > 0 && genie.top < innerHeight,
      viewportHeight: innerHeight,
      questionHeight: document.querySelector('#question-text').getBoundingClientRect().height,
      answers,
    };
  });
  expect(layout.overflow).toBeLessThanOrEqual(1);
  expect(layout.genieVisible).toBe(true);
  expect(layout.questionHeight).toBeGreaterThan(80);
  // Layout engines return fractional CSS pixels; ignore subpixel rounding under 1px.
  expect(layout.answers.every(button => button.bottom <= layout.viewportHeight + 1), JSON.stringify(layout)).toBe(true);
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
    const enlargedLayout = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      overflowing: [...document.querySelectorAll('body *')]
        .map(element => ({tag: element.tagName, className: element.className?.baseVal ?? element.className, right: element.getBoundingClientRect().right}))
        .filter(element => element.right > innerWidth + 1)
        .slice(0, 8),
    }));
    expect(enlargedLayout.overflow, JSON.stringify(enlargedLayout)).toBeLessThanOrEqual(1);
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

test('result hierarchy explains the candidate score before offering share actions', async ({page}) => {
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
  await expect(page.locator('#result-score-note')).toBeVisible();
  await expect(page.locator('#result-prob')).toHaveAttribute('aria-describedby', 'result-score-note');
  await expect(page.getByText('回答傾向から算出した候補スコアです（正解の確率ではありません）。')).toBeVisible();
  const descriptionBox = await page.locator('#result-desc').boundingBox();
  const shareBox = await page.getByRole('button', {name: '共有する', exact: true}).boundingBox();
  const shareStyle = await page.getByRole('button', {name: '共有する', exact: true}).evaluate(button => ({
    backgroundImage: getComputedStyle(button).backgroundImage,
    boxShadow: getComputedStyle(button).boxShadow,
  }));
  expect(descriptionBox.y).toBeLessThan(shareBox.y);
  expect(shareStyle.backgroundImage).toBe('none');
  expect(shareStyle.boxShadow).toBe('none');
  await page.getByRole("button", {name: "結果を詳しく見る"}).click();
  await expect(page.getByText('候補スコアは回答傾向と最近の表示回数を順位づけに反映した値（100点満点）です。正解率や正解の確率ではありません。棒グラフは本命を100とした相対比較です。')).toBeVisible();
  await expect(page.locator('#top-chart .chart-value')).toHaveText(['72 / 100', '63 / 100']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expectNoSeriousAccessibilityViolations(page);
});
