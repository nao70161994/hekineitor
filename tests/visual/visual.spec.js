import {expect, test} from '@playwright/test';
import process from 'node:process';

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
  works: [{title: '星灯りの約束', work_id: 'visual-work-1'}],
  cross_works: [],
};

test.beforeEach(async ({page}) => {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.route('**/api/share_link', route => route.fulfill({status: 503, json: {}}));
  await page.route('**/api/gameplay_event', route => route.fulfill({json: {status: 'ok'}}));
  await page.route('**/api/share_event', route => route.fulfill({json: {status: 'ok'}}));
});

async function expectSkipLinkHidden(page) {
  const box = await page.locator('.skip-link').boundingBox();
  expect(box).not.toBeNull();
  expect(box.y + box.height).toBeLessThanOrEqual(0);
}

async function expectVisualSnapshot(page, name) {
  const options = {animations: 'disabled', fullPage: true};
  // CI runs Linux Chromium while local snapshots may come from Android Chromium.
  if (process.env.CI) options.maxDiffPixelRatio = 0.07;
  await expect(page).toHaveScreenshot(name, options);
}

test('mobile start screen', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  await page.goto('/');
  await expectVisualSnapshot(page, 'start-mobile.png');
});

test('mobile question screen', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expectSkipLinkHidden(page);
  await expectVisualSnapshot(page, 'question-mobile.png');
});

test('desktop question composition', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 900});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expect(page.locator('#question-text')).toBeVisible();
  await expectVisualSnapshot(page, 'question-desktop.png');
});

test('landscape question keeps the genie and all five answers in view', async ({page}) => {
  await page.setViewportSize({width: 812, height: 375});
  await page.route('**/api/start', route => route.fulfill({json: {
    action: 'question',
    question_id: 7,
    question: '物語のなかで、立場や価値観の違う人物たちが時間をかけて理解し合い、少しずつ信頼を深めていく展開に惹かれる？',
    axis: 'abstract',
    count: 0,
    total: 20,
    answer_frame: '作品・設定の好みとして',
    progress_message: '最初の手がかりを見つけたよ',
  }}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await expectVisualSnapshot(page, 'question-landscape.png');
});

test('desktop result screen', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 900});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.route('**/api/answer', route => route.fulfill({json: result}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-prob')).toHaveText('推定一致度 72%');
  await expectSkipLinkHidden(page);
  await expectVisualSnapshot(page, 'result-desktop.png');
});

test('mobile result screen', async ({page}) => {
  await page.setViewportSize({width: 375, height: 812});
  await page.route('**/api/start', route => route.fulfill({json: question}));
  await page.route('**/api/answer', route => route.fulfill({json: result}));
  await page.goto('/');
  await page.getByRole('button', {name: '診断をはじめる'}).click();
  await page.getByRole('button', {name: 'はい', exact: true}).click();
  await expect(page.locator('#result-prob')).toHaveText('推定一致度 72%');
  await expect(page.locator('.result-crystal')).toBeVisible();
  await expectSkipLinkHidden(page);
  await expectVisualSnapshot(page, 'result-mobile.png');
  await page.getByRole('button', {name: '結果を詳しく見る'}).click();
  await expect(page.locator('#works-section')).toBeVisible();
  await expectVisualSnapshot(page, 'result-mobile-details.png');
});
