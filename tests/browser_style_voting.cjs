const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 서버가 확정한 A/B와 실제 수치를 Browser 식별자로 읽습니다. */
async function readBrowserSelection(context, project, clientIdentifier) {
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier, clientIdentifier });
  const response = await context.request.get(`http://127.0.0.1:18388/api/style-projects/${project.identifier}/selection?${parameters}`);
  assert.equal(response.status(), 200, await response.text());
  return response.json();
}

/** 생성→한 표→순위→Skip→Undo를 실제 임시 PNG와 여러 Browser에서 검증합니다. */
async function verifyStyleVoting() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `voting-browser-create-${Date.now()}`,
      settings: {
        name: '선별 한 사이클 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
        artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
        promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
      },
    } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('[data-generation-action=random-start]').click();
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.generation-result img')).toHaveCount(12, { timeout: 20000 });
    await page.goto(`${baseUrl}/style#compare`);
    const firstChoice = page.locator('[data-style-voting-choice=a]');
    const undoButton = page.locator('[data-style-voting-action=undo]');
    await expect(firstChoice).toBeEnabled();
    await expect(undoButton).toBeDisabled();
    await expect(page.locator('.case-section')).toHaveCount(3);
    const clientIdentifier = await page.evaluate(() => styleVotingClientIdentifier());
    const initialSelection = await readBrowserSelection(context, project, clientIdentifier);
    let voteRequestCount = 0;
    page.on('request', request => { if (request.url().endsWith(`/${project.identifier}/votes`)) voteRequestCount += 1; });
    await firstChoice.evaluate(button => { button.click(); button.click(); });
    await expect(undoButton).toBeEnabled();
    assert.equal(voteRequestCount, 1);
    const afterVote = await readBrowserSelection(context, project, clientIdentifier);
    assert.equal(afterVote.rankings.find(entry => entry.identifier === initialSelection.match.a).rating, 10160);
    assert.equal(afterVote.rankings.find(entry => entry.identifier === initialSelection.match.b).rating, 9840);
    assert.notEqual(afterVote.match.token, initialSelection.match.token);
    await expect(firstChoice).toBeEnabled();
    await page.goto(`${baseUrl}/style#candidates`);
    const winnerCard = page.locator(`.style-library-card[data-style-candidate="${initialSelection.match.a}"]`);
    await expect(winnerCard).toContainText('1위');
    await expect(winnerCard).toContainText('10,160');
    await expect(winnerCard).toContainText('1승 0패');
    await expect(page.locator('.style-library-card').first()).toHaveAttribute('data-style-candidate', initialSelection.match.a);
    await page.locator('#candidate-sort-order').selectOption('creation');
    await page.locator('#candidate-sort-order').selectOption('elo');
    await winnerCard.locator('.style-card-heading').click();
    await expect(page.locator('#illustration-dialog')).toContainText('10,160');
    await page.keyboard.press('Escape');
    await page.goto(`${baseUrl}/style#compare`);
    await expect(firstChoice).toBeEnabled();
    const beforeSkip = await readBrowserSelection(context, project, clientIdentifier);
    await page.locator('[data-style-voting-choice=similar]').click();
    await expect.poll(async () => (await readBrowserSelection(context, project, clientIdentifier)).revision).toBeGreaterThan(beforeSkip.revision);
    const afterSkip = await readBrowserSelection(context, project, clientIdentifier);
    for (const original of beforeSkip.rankings) {
      const updated = afterSkip.rankings.find(entry => entry.identifier === original.identifier);
      for (const field of ['rating', 'matches', 'wins', 'losses']) assert.equal(updated[field], original[field]);
    }
    await undoButton.click();
    await expect.poll(async () => (await readBrowserSelection(context, project, clientIdentifier)).rankings).toEqual(beforeSkip.rankings);
    await expect(undoButton).toBeEnabled();
    await undoButton.click();
    await expect(undoButton).toBeDisabled();
    await expect.poll(async () => (await readBrowserSelection(context, project, clientIdentifier)).rankings).toEqual(initialSelection.rankings);
    const undone = await readBrowserSelection(context, project, clientIdentifier);
    assert.deepEqual(undone.rankings, initialSelection.rankings);
    assert.deepEqual([undone.match.a, undone.match.b], [initialSelection.match.a, initialSelection.match.b]);
    await page.reload();
    await expect(firstChoice).toBeEnabled();
    const restored = await readBrowserSelection(context, project, clientIdentifier);
    assert.deepEqual(restored.match, undone.match);
    await firstChoice.click();
    await expect(undoButton).toBeEnabled();

    const otherContext = await browser.newContext();
    await otherContext.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const otherPage = await otherContext.newPage();
    otherPage.on('pageerror', error => browserErrors.push(error.message));
    await otherPage.goto(`${baseUrl}/style#compare`);
    await otherPage.locator('#active-project-picker').selectOption(project.identifier);
    await expect(otherPage.locator('[data-style-voting-choice=b]')).toBeEnabled();
    await expect(otherPage.locator('[data-style-voting-action=undo]')).toBeDisabled();
    await expect(otherPage.locator('[data-style-voting-action=undo]')).toHaveAttribute('title', /다른 Browser/);
    const staleSelection = await readBrowserSelection(context, project, clientIdentifier);
    await otherPage.locator('[data-style-voting-choice=b]').click();
    await expect(otherPage.locator('[data-style-voting-action=undo]')).toBeEnabled();
    const staleResponse = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/votes`, { data: {
      evaluationIdentifier: project.evaluationIdentifier, clientIdentifier, operationIdentifier: `stale-browser-vote-${Date.now()}`,
      expectedRevision: staleSelection.revision, matchToken: staleSelection.match.token, choice: 'a',
    } });
    assert.equal(staleResponse.status(), 409);
    await expect(undoButton).toBeDisabled({ timeout: 10000 });
    await otherContext.close();
    await page.reload();
    await expect(firstChoice).toBeEnabled();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-voting-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-voting-mobile.png', fullPage: true });
    await page.locator('[data-action=toggle-blind]').click();
    await expect(page.locator('.candidate-headings')).toContainText('그림체 숨김');
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(0);
    await page.locator('[data-ranking-action=reveal-candidates]').click();
    await expect(page.locator('.style-library-card')).toHaveCount(4);
    await page.screenshot({ path: 'runtime/verification/style-voting-rankings-mobile.png', fullPage: true });
    await page.goto(`${baseUrl}/style#compare`);
    await expect(firstChoice).toBeEnabled();
    const blockedImageSource = await page.locator('.persistent-comparison img').first().getAttribute('src');
    await page.route(`${baseUrl}${blockedImageSource}`, route => route.abort('failed'));
    await page.reload();
    await expect(firstChoice).toBeDisabled();
    await expect(page.locator('#style-voting-status')).toContainText('이미지를 불러오지 못했습니다.');
    await page.unroute(`${baseUrl}${blockedImageSource}`);
    await page.reload();
    await expect(firstChoice).toBeEnabled();
    assert.deepEqual(browserErrors, []);
    fs.writeFileSync('runtime/verification/style-voting-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, generatedImageCount: 12, voteRequestCount, multiplePromptsOneVote: true, skipPreservesElo: true, undoRestoresPair: true, persistedReload: true, otherBrowserUndoRejected: true, staleVoteStatus: 409, widths: [320, 390, 768, 1280], browserErrors }, null, 2));
    console.log('Style voting, rankings and Undo Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleVoting().catch(error => { console.error(error); process.exitCode = 1; });
