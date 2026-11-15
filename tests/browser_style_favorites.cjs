const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

/** 임시 PNG가 있는 세 조합을 만들어 카드·Viewer의 같은 좋아요를 확인합니다. */
async function createFavoriteProject(context, baseUrl) {
  const settings = {
    name: '그림체 즐겨찾기 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
    artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
    promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
    componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
  };
  const created = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings, operationIdentifier: crypto.randomUUID() } });
  assert.equal(created.status(), 201, await created.text());
  const project = await created.json();
  const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const preview = await context.request.post(`${endpoint}/random-generation-plans`, { data: { expectedRevision: project.revision, operationIdentifier: crypto.randomUUID(), combinationCount: 3 } });
  assert.equal(preview.status(), 201, await preview.text());
  const plan = await preview.json();
  assert.equal((await context.request.post(`${endpoint}/generation-plans/${plan.planIdentifier}/submit`, { data: { operationIdentifier: crypto.randomUUID() } })).status(), 200);
  await expect.poll(async () => {
    const results = await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }, { timeout: 20000 }).toBe(9);
  return { project, plan, settings, endpoint };
}

/** 좋아요 모아보기·퇴역·Reload·오류·동시 Polling·프로젝트 전환·폐기를 검증합니다. */
async function verifyStyleFavorites() {
  const baseUrl = 'http://127.0.0.1:18388';
  const directory = 'runtime/verification/style-favorites';
  filesystem.mkdirSync(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 1000 } });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const { project, plan, settings, endpoint } = await createFavoriteProject(context, baseUrl);
    const identifiers = plan.candidates.map(candidate => candidate.identifier);
    for (const identifier of identifiers.slice(0, 2)) assert.equal((await context.request.put(`${endpoint}/candidates/${identifier}/favorite`, { data: { isFavorite: true } })).status(), 200);
    const otherResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings: { ...settings, name: '다른 프로젝트' }, operationIdentifier: crypto.randomUUID() } });
    const otherProject = await otherResponse.json();
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    const resultsEndpoint = `${endpoint}/generation-results?summary=true`;
    await page.route(resultsEndpoint, async route => {
      const response = await route.fetch();
      const results = await response.json();
      const retired = results.candidates.find(candidate => candidate.identifier === identifiers[1]);
      if (retired) retired.lifecycle = 'retired';
      await route.fulfill({ response, json: results });
    });
    await page.goto(`${baseUrl}/style#candidates`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await expect(page.locator('.style-library-card')).toHaveCount(2);
    await expect(page.locator('#style-library-favorite-count')).toHaveText('2');
    await page.locator('#style-library-favorites-only').check();
    await expect(page.locator('.style-library-card')).toHaveCount(2);
    await expect(page.locator('#style-library-lifecycle')).toHaveValue('all');
    await expect(page.locator('#style-library-lifecycle')).toBeDisabled();
    const retiredCard = page.locator(`[data-style-candidate="${identifiers[1]}"]`);
    await expect(retiredCard).toContainText('퇴역');
    await retiredCard.locator('.style-card-open').click();
    const viewer = page.locator('#illustration-dialog');
    const viewerFavorite = viewer.locator('[data-style-candidate-favorite]');
    await viewerFavorite.click();
    await expect(viewerFavorite).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    await expect(viewer).toBeVisible();
    await viewerFavorite.click();
    await expect(viewerFavorite).toHaveAttribute('aria-pressed', 'true');
    await page.keyboard.press('Escape');
    await page.reload();
    await expect(page.locator('#style-library-favorites-only')).toBeChecked();
    await expect(page.locator('.style-library-card')).toHaveCount(2);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const favoriteButton = page.locator('.style-card-actions [data-style-candidate-favorite]').first();
      const dimensions = await favoriteButton.boundingBox();
      assert.ok(dimensions.width >= 44 && dimensions.height >= 44);
      await page.screenshot({ path: `${directory}/favorites-${width}.png` });
    }
    await page.locator('#style-library-favorites-only').uncheck();
    await expect(page.locator('#style-library-lifecycle')).toHaveValue('active');
    await expect(page.locator('#style-library-lifecycle')).toBeEnabled();
    const thirdCard = page.locator(`[data-style-candidate="${identifiers[2]}"]`);
    await thirdCard.scrollIntoViewIfNeeded();
    const previousScroll = await page.evaluate(() => scrollY);
    await page.evaluate(identifier => { window.favoriteThumbnailReference = document.querySelector(`[data-style-candidate="${identifier}"] img`); }, identifiers[2]);
    await thirdCard.locator('[data-style-candidate-favorite]').click();
    await expect(thirdCard.locator('[data-style-candidate-favorite]')).toHaveAttribute('aria-pressed', 'true');
    assert.equal(await page.evaluate(identifier => window.favoriteThumbnailReference === document.querySelector(`[data-style-candidate="${identifier}"] img`), identifiers[2]), true);
    assert.equal(await page.evaluate(() => scrollY), previousScroll);
    await expect(viewer).not.toBeVisible();

    await page.evaluate(async () => { clearTimeout(styleGenerationViewState.timer); await currentStyleGenerationState().resultRefreshPromise; });
    const firstFavorite = page.locator(`.style-card-actions [data-style-candidate-favorite="${identifiers[0]}"]`);
    const favoriteEndpoint = `${endpoint}/candidates/${identifiers[0]}/favorite`;
    await page.route(favoriteEndpoint, route => route.fulfill({ status: 503, json: { detail: '좋아요 저장 오류 검증' } }), { times: 1 });
    await firstFavorite.click();
    await expect(page.locator('.toast')).toContainText('좋아요 저장 오류 검증');
    await expect(firstFavorite).toHaveAttribute('aria-pressed', 'true');
    await expect(firstFavorite).toBeEnabled();
    await page.route(favoriteEndpoint, async route => {
      assert.equal((await route.fetch()).status(), 200);
      await route.abort('failed');
    }, { times: 1 });
    await firstFavorite.click();
    await expect(firstFavorite).toBeEnabled();
    assert.equal((await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json()).candidates[0].isFavorite, false);
    const retriedFavorite = page.waitForRequest(request => request.url() === favoriteEndpoint && request.method() === 'PUT');
    await firstFavorite.click();
    assert.equal((await retriedFavorite).postDataJSON().isFavorite, false);
    await expect(firstFavorite).toHaveAttribute('aria-pressed', 'false');

    let releaseOldResults;
    let oldResultsStarted;
    const oldResultsStartedPromise = new Promise(resolve => { oldResultsStarted = resolve; });
    const oldResultsRelease = new Promise(resolve => { releaseOldResults = resolve; });
    await page.route(resultsEndpoint, async route => {
      const response = await route.fetch();
      oldResultsStarted();
      await oldResultsRelease;
      await route.fulfill({ response });
    }, { times: 1 });
    await page.evaluate(() => { window.pendingFavoriteRefresh = refreshStyleGenerationResults(); });
    await oldResultsStartedPromise;
    await thirdCard.locator('[data-style-candidate-favorite]').click();
    await expect(thirdCard.locator('[data-style-candidate-favorite]')).toHaveAttribute('aria-pressed', 'false');
    releaseOldResults();
    await page.evaluate(() => window.pendingFavoriteRefresh);
    await expect(thirdCard.locator('[data-style-candidate-favorite]')).toHaveAttribute('aria-pressed', 'false');

    let releaseFavorite;
    let favoriteStarted;
    const favoriteStartedPromise = new Promise(resolve => { favoriteStarted = resolve; });
    const favoriteRelease = new Promise(resolve => { releaseFavorite = resolve; });
    await page.route(favoriteEndpoint, async route => {
      const response = await route.fetch();
      favoriteStarted();
      await favoriteRelease;
      await route.fulfill({ response });
    }, { times: 1 });
    await firstFavorite.click();
    await favoriteStartedPromise;
    await expect(firstFavorite).toBeDisabled();
    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await expect(page.locator('#style-library-favorite-count')).toHaveText('0');
    await expect(page.locator('#style-library-favorites-only')).not.toBeChecked();
    releaseFavorite();
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await expect(firstFavorite).toHaveAttribute('aria-pressed', 'true');

    const freshContext = await browser.newContext({ storageState: await context.storageState() });
    const freshPage = await freshContext.newPage();
    await freshPage.goto(`${baseUrl}/style#candidates`);
    await freshPage.locator('#active-project-picker').selectOption(project.identifier);
    await expect(freshPage.locator(`.style-card-actions [data-style-candidate-favorite="${identifiers[0]}"]`)).toHaveAttribute('aria-pressed', 'true');
    await freshContext.close();
    await page.locator('#style-library-favorites-only').check();
    await retiredCard.locator('[data-style-candidate-action=delete]').click();
    await page.locator('#component-dialog button[value=confirm]').click();
    await expect(retiredCard).toHaveCount(0);
    await expect(page.locator('#style-library-favorite-count')).toHaveText('1');
    assert.deepEqual(browserErrors, []);
    filesystem.writeFileSync(`${directory}/browser.json`, JSON.stringify({ widths: [320, 390, 768, 1280], favoriteStarAndViewer: true, retiredIncluded: true, filterAndSessionPreserved: true, freshSessionPersistence: true, imageNodesAndScrollPreserved: true, failedSaveRecovery: true, lostResponseIdempotency: true, stalePollingGuard: true, projectSwitchDuringSave: true, deletedFavoriteRemoved: true, browserErrors }, null, 2));
    console.log('Style favorites Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleFavorites().catch(error => { console.error(error); process.exitCode = 1; });
