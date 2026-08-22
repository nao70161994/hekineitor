import {expect, test} from '@playwright/test';

const question = {
  action: 'question',
  question_id: 7,
  question: '誰にも見せない選択ほど、自分らしさが出る？',
  axis: 'abstract',
  count: 7,
  progress_message: 'いくつかの傾向を比べています',
};

const result = {
  fetish_id: 65,
  fetish_name: '静かな共同生活',
  fetish_desc: '言葉よりも、日々の小さな積み重ねに惹かれる傾向です。',
  probability: 72,
  compound: [{fetish_id: 12, fetish_name: '穏やかな信頼', fetish_desc: '安心できる関係を大切にします。', probability: 63}],
  top_chart: [
    {fetish_id: 65, fetish_name: '静かな共同生活', probability: 72},
    {fetish_id: 12, fetish_name: '穏やかな信頼', probability: 63},
  ],
  profile: [{fetish_name: '日常の余韻', probability: 41}],
  related: [{fetish_id: 4, fetish_name: '日常の余韻'}],
  reasons: [{text: '静かな場所では、細かな変化に気づきやすい？', ans: 1}],
  works: [],
  cross_works: [],
};

test.beforeEach(async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.route('**/api/share_link', route => route.fulfill({status: 503, json: {}}));
  await page.route('**/api/gameplay_event', route => route.fulfill({json: {status: 'ok'}}));
  await page.route('**/api/share_event', route => route.fulfill({json: {status: 'ok'}}));
});

test('mobile start screen', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  await page.goto('/');
  await expect(page).toHaveScreenshot('start-mobile.png', {animations: 'disabled', fullPage: true});
});

test('mobile question screen', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expect(page).toHaveScreenshot('question-mobile.png', {animations: 'disabled', fullPage: true});
});

test('desktop result screen', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 900});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.route('**/api/answer', route => route.fulfill({json: result}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-prob')).toHaveText('推定一致度 72%');
  await expect(page).toHaveScreenshot('result-desktop.png', {animations: 'disabled', fullPage: true});
});
