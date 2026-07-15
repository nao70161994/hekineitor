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
