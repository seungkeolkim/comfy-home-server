const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 확인창·취소·계획 응답 유실·재전송과 4조합×3Prompt 결과를 Desktop/Mobile에서 검증합니다. */
async function verifyRandomStyleGeneration() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const settings = {
      name: 'Random 초기 조합 Browser 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
      artistMinimumCount: 1, artistMaximumCount: 2, loraMinimumCount: 1, loraMaximumCount: 1,
      promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}, {artist}` })),
      componentPolicies: {
        'artist:first': { enabled: true, minimumStrength: 0.4, maximumStrength: 0.8 },
        'artist:second': { enabled: true, minimumStrength: 0.5, maximumStrength: 0.5 },
        'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 },
      },
    };
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings, operationIdentifier: `random-browser-project-${Date.now()}` } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const previousJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await expect(page.locator('#style-random-image-count')).toContainText('12장');
    await page.locator('#style-random-combination-count').fill('0');
    await page.locator('[data-generation-action=random-start]').click();
    await expect(page.locator('#style-generation-error')).toContainText('1 ~ 32');
    await page.locator('#style-random-combination-count').fill('4');

    let lostPlan;
    let firstOperationIdentifier;
    const previewEndpoint = `${baseUrl}/api/style-projects/${project.identifier}/random-generation-plans`;
    await page.route(previewEndpoint, async route => {
      firstOperationIdentifier = route.request().postDataJSON().operationIdentifier;
      const response = await route.fetch();
      assert.equal(response.status(), 201);
      lostPlan = await response.json();
      await route.abort('failed');
    }, { times: 1 });
    await page.locator('[data-generation-action=random-start]').click();
    await expect(page.locator('#style-generation-error')).not.toBeEmpty();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount);
    const previewResponsePromise = page.waitForResponse(response => response.url() === previewEndpoint);
    await page.locator('[data-generation-action=random-start]').click();
    const previewResponse = await previewResponsePromise;
    assert.equal(previewResponse.request().postDataJSON().operationIdentifier, firstOperationIdentifier);
    const plan = await previewResponse.json();
    assert.equal(plan.planIdentifier, lostPlan.planIdentifier);
    const confirmationDialog = page.locator('#style-generation-confirmation-dialog');
    await expect(confirmationDialog).toBeVisible();
    await expect(confirmationDialog).toContainText('12장');
    await expect(confirmationDialog.locator('button')).toHaveCount(2);
    await expect(confirmationDialog).not.toContainText('STR');
    await expect(confirmationDialog).not.toContainText('artist:first');
    await expect(page.locator('.generation-plan-candidates')).toHaveCount(0);
    assert.equal(new Set(plan.candidates.map(candidate => JSON.stringify(candidate.components))).size, 4);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-random-confirmation-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-random-confirmation-mobile.png', fullPage: true });
    await confirmationDialog.locator('button[value=cancel]').click();
    await expect(confirmationDialog).not.toBeVisible();
    await expect(page.locator('#preview-content')).not.toHaveAttribute('inert', '');
    let additionalPlanRequests = 0;
    page.on('request', request => { if (request.url() === previewEndpoint) additionalPlanRequests += 1; });
    await page.locator('[data-generation-action=random-start]').click();
    await expect(confirmationDialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(confirmationDialog).not.toBeVisible();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount);
    await page.reload();
    await expect.poll(() => page.evaluate(() => currentStyleGenerationState().results?.plans.length || 0)).toBe(1);
    await expect(page.locator('[data-generation-action=open-plan]')).toHaveCount(0);
    await page.locator('[data-generation-action=random-start]').click();
    await expect(confirmationDialog).toBeVisible();
    assert.equal(additionalPlanRequests, 0);
    await confirmationDialog.locator('button[value=confirm]').click();
    await expect(confirmationDialog).not.toBeVisible();
    await expect(page.locator('.generation-result img')).toHaveCount(12, { timeout: 20000 });
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(4);
    await expect(page.locator('.style-card-thumbnail')).toHaveCount(12);
    await page.locator('.style-card-heading').last().click();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('1 / 3');
    await page.locator('[data-style-library-action=next]').click();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('2 / 3');
    await page.keyboard.press('Escape');
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('.case-section')).toHaveCount(3);
    await expect(page.locator('[data-comparison-candidate]')).toHaveCount(2);
    await page.locator('[data-comparison-candidate="0"]').selectOption(plan.candidates[2].identifier);
    await page.locator('[data-comparison-candidate="1"]').selectOption(plan.candidates[3].identifier);
    await expect(page.locator('.candidate-headings')).toContainText('조합 C');
    await expect(page.locator('.candidate-headings')).toContainText('조합 D');
    await page.locator('[data-action=open-differences]').click();
    await expect(page.locator('#component-dialog')).toBeVisible();
    await page.locator('[data-action=close-differences]').click();
    await page.locator('[data-action=toggle-blind]').click();
    await expect(page.locator('[data-comparison-candidate="0"]')).toBeDisabled();
    await expect(page.locator('.comparison-pair-picker')).not.toContainText('조합 C');
    await page.locator('[data-action=toggle-blind]').click();
    await expect(page.locator('[data-comparison-candidate="0"]')).toHaveValue(plan.candidates[2].identifier);
    await page.screenshot({ path: 'runtime/verification/style-random-comparison-mobile.png', fullPage: true });
    await page.reload();
    await expect(page.locator('.case-section')).toHaveCount(3);
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(4);
    const results = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-results`)).json();
    assert.equal(results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length, 12);
    assert.ok(results.candidates.flatMap(candidate => candidate.renders).every(render => render.settings.seed === 42));
    const baseOnlyResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `random-base-project-${Date.now()}`,
      settings: { ...settings, name: '가능한 조합 부족 검증', artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 0, loraMaximumCount: 0 },
    } });
    assert.equal(baseOnlyResponse.status(), 201, await baseOnlyResponse.text());
    const baseOnlyProject = await baseOnlyResponse.json();
    await page.goto(`${baseUrl}/style#generation`);
    await page.reload();
    await page.locator('#active-project-picker').selectOption(baseOnlyProject.identifier);
    await page.locator('[data-generation-action=random-start]').click();
    await expect(confirmationDialog).toContainText('4개 중 1개');
    await expect(confirmationDialog).toContainText('3장');
    await confirmationDialog.locator('button[value=cancel]').click();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount + 1);
    assert.deepEqual(browserErrors, []);
    fs.writeFileSync('runtime/verification/style-random-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, planIdentifier: plan.planIdentifier, imageCount: 12, widths: [320, 390, 768, 1280], lostPreviewRecovered: true, cancelAndEscapePreservePlan: true, browserErrors }, null, 2));
    console.log('Random style generation Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyRandomStyleGeneration().catch(error => { console.error(error); process.exitCode = 1; });
