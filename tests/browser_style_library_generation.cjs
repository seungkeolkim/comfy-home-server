const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

/** 그림체 안의 생성 창·확인·카드 갱신과 기존 주소·프로젝트 초안의 연결을 검증합니다. */
async function verifyStyleLibraryGeneration() {
  const baseUrl = 'http://127.0.0.1:18388';
  const directory = 'runtime/verification/style-library-generation';
  filesystem.mkdirSync(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const settings = {
      name: '그림체 생성 통합', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
      artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
      promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
      componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
    };
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings, operationIdentifier: crypto.randomUUID() } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const otherResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings: { ...settings, name: '다른 프로젝트' }, operationIdentifier: crypto.randomUUID() } });
    const otherProject = await otherResponse.json();
    const initialJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    await context.addInitScript(identifier => sessionStorage.setItem('comfy-home-style-workspace-session-v1', JSON.stringify({ currentProjectIdentifier: identifier, screen: 'generation' })), project.identifier);
    const page = await context.newPage();
    const mutations = [];
    const resultQueries = [];
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => {
      if (request.method() !== 'GET') mutations.push(request.url());
      if (new URL(request.url()).pathname.endsWith('/generation-results')) resultQueries.push(new URL(request.url()).searchParams.get('summary'));
    });
    await page.goto(`${baseUrl}/style#generation`);
    await expect(page).toHaveURL(/#candidates$/);
    await expect(page.locator('#preview-content h1')).toHaveText('그림체');
    await expect(page.locator('#preview-mobile-navigation button')).toHaveCount(4);
    assert.deepEqual(await page.locator('#preview-mobile-navigation button').evaluateAll(elements => elements.map(element => element.dataset.screen)), ['projects', 'candidates', 'compare', 'evolution']);
    await expect(page.locator('#style-generation-random-count')).toHaveCount(0);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    const generator = page.locator('#style-generation-dialog');
    const confirmation = page.locator('#style-generation-confirmation-dialog');
    await expect(generator).toBeVisible();
    await expect(page.locator('#style-generation-random-count')).toBeEnabled();
    await expect(page.locator('#style-generation-random-count')).toHaveValue('50');
    await page.locator('#style-generation-random-count').fill('3');
    await page.keyboard.press('Escape');
    await expect(generator).not.toBeVisible();
    await expect(page.locator('.page-heading [data-generation-action=open-generator]')).toBeFocused();
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(page.locator('#style-generation-random-count')).toHaveValue('3');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.ok(await generator.evaluate(element => element.scrollWidth <= element.clientWidth));
      await page.screenshot({ path: `${directory}/generator-${width}.png` });
    }
    assert.deepEqual(mutations, []);
    await page.locator('[data-generation-action=generate-random]').click();
    await expect(confirmation).toContainText('9장');
    await confirmation.locator('[value=cancel]').click();
    await expect(confirmation).not.toBeVisible();
    await expect(generator).not.toHaveAttribute('inert', '');
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, initialJobCount);
    await page.locator('[data-generation-action=generate-random]').click();
    await expect(confirmation).toBeVisible();
    await confirmation.locator('[value=confirm]').click();
    await expect(generator).not.toBeVisible();
    await expect(page.locator('.style-library-card')).toHaveCount(3, { timeout: 20000 });
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(9, { timeout: 20000 });
    await expect(page.locator('.generation-result')).toHaveCount(0);
    await page.locator('.style-card-heading').first().click();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('1 / 3');
    await page.locator('[data-style-library-action=next]').click();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('2 / 3');
    await page.keyboard.press('Escape');

    const resultsEndpoint = `${baseUrl}/api/style-projects/${project.identifier}/generation-results?summary=true`;
    let displayedStatus = 'running';
    await page.route(resultsEndpoint, async route => {
      const response = await route.fetch();
      const results = await response.json();
      if (displayedStatus !== 'completed') {
        const render = results.candidates[0].renders.at(-1);
        render.files = [];
        render.status = displayedStatus;
        render.error = displayedStatus === 'failed' ? '검증 오류 <script>throw new Error("unsafe")</script>' : null;
      }
      await route.fulfill({ response, json: results });
    });
    await page.evaluate(() => refreshStyleGenerationResults());
    await expect(page.locator('.style-library-generation-progress')).toContainText('1장 생성 중');
    await expect(page.locator('.style-thumbnail-status')).toContainText(['생성 중']);
    let cancellationRequested = false;
    await page.route('**/api/jobs/*/cancel', async route => {
      cancellationRequested = true;
      displayedStatus = 'failed';
      await route.fulfill({ status: 200, json: {} });
    }, { times: 1 });
    await page.locator('[data-generation-action=cancel]').click();
    await expect(page.locator('.style-library-generation-progress')).toHaveCount(0);
    assert.equal(cancellationRequested, true);
    await page.locator('.style-card-generation-errors summary').click();
    await expect(page.locator('.style-card-generation-errors')).toContainText('검증 오류 <script>');
    await expect(page.locator('.style-card-generation-errors script')).toHaveCount(0);
    let retryFailedOnly = false;
    await page.route('**/generation-plans/*/submit', async route => {
      retryFailedOnly = route.request().postDataJSON().retryFailedOnly;
      displayedStatus = 'completed';
      await route.fulfill({ status: 200, json: {} });
    }, { times: 1 });
    await page.locator('[data-generation-action=retry]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(9);
    assert.equal(retryFailedOnly, true);
    await expect(page.locator('[data-generation-action=retry]')).toHaveCount(0);
    await page.unroute(resultsEndpoint);

    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await generator.locator('summary').filter({ hasText: '직접 조합 지정' }).click();
    await page.locator('[data-generation-action=prepare]').click();
    await expect(page.locator('.generation-component')).toHaveCount(2);
    await page.locator('[data-generation-strength]').first().fill('0.3');
    await page.locator('[data-generation-strength]').last().fill('0.7');
    await page.locator('[data-generation-component]').first().uncheck();
    await expect(page.locator('[data-generation-strength]').first()).toBeDisabled();
    await page.locator('[data-generation-component]').first().check();
    await page.locator('[data-generation-strength]').first().fill('0.3');
    await page.locator('#style-generation-count').selectOption('1');
    await expect(page.locator('.generation-component')).toHaveCount(1);
    await page.locator('#style-generation-count').selectOption('2');
    await page.locator('[data-generation-strength]').last().fill('0.7');
    await page.locator('[data-generation-action=preview]').click();
    await expect(confirmation).toContainText('6장');
    await confirmation.locator('[value=confirm]').click();
    await expect(generator).not.toBeVisible();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(15, { timeout: 20000 });
    await page.locator('#candidate-sort-order').selectOption('matches');
    await page.locator('.style-card-selection input').first().check();
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await page.locator('#style-generation-random-count').fill('7');
    await generator.locator('[data-generation-action=close-generator]').click();
    await expect(page.locator('#candidate-sort-order')).toHaveValue('matches');
    await expect(page.locator('.style-card-selection input:checked')).toHaveCount(1);
    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(page.locator('#style-generation-random-count')).toHaveValue('50');
    await page.evaluate(() => { location.hash = 'evolution'; });
    await expect(generator).not.toBeVisible();
    await page.locator('#preview-content [data-generation-action=open-generator]').first().click();
    await expect(page).toHaveURL(/#candidates$/);
    await expect(generator).toBeVisible();
    await page.keyboard.press('Escape');
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(page.locator('#style-generation-random-count')).toHaveValue('7');
    await page.keyboard.press('Escape');
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.screenshot({ path: `${directory}/library-${width}.png` });
    }
    assert.ok(resultQueries.length > 0 && resultQueries.every(value => value === 'true'), JSON.stringify(resultQueries));
    assert.deepEqual(browserErrors, []);
    filesystem.writeFileSync(`${directory}/browser.json`, JSON.stringify({ widths: [320, 390, 768, 1280], fourTabs: true, legacyAddressAndSession: true, navigationDoesNotGenerate: true, explicitConfirmation: true, randomAndManualGeneration: true, progressAndCancellation: true, escapedGenerationErrors: true, failedOnlyRetry: true, projectDraftsAndSelectionPreserved: true, summaryOnly: true, browserErrors }, null, 2));
    console.log('Style library generation Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleLibraryGeneration().catch(error => { console.error(error); process.exitCode = 1; });
