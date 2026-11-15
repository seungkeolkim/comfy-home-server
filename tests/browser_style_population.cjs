const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

const baseUrl = 'http://127.0.0.1:18388';

/** 여러 Prompt와 충분한 STR 범위를 가진 격리 프로젝트를 만듭니다. */
async function createPopulationProject(context, name) {
  const response = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
    operationIdentifier: crypto.randomUUID(),
    settings: {
      name, width: 64, height: 96, steps: 3, cfg: 1,
      artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
      promptCases: [{ identifier: 'portrait', name: '인물', prompt: 'portrait' }, { identifier: 'garden', name: '정원', prompt: 'garden' }],
      componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.1, maximumStrength: 1.9 } },
    },
  } });
  assert.equal(response.status(), 201, await response.text());
  return response.json();
}

/** 초기 10개 조합을 실제 임시 PNG로 준비합니다. */
async function prepareSmallPopulation(context, project) {
  const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const response = await context.request.post(`${endpoint}/random-generation-plans`, { data: {
    expectedRevision: project.revision, operationIdentifier: crypto.randomUUID(), combinationCount: 10,
  } });
  assert.equal(response.status(), 201, await response.text());
  const plan = await response.json();
  const submitted = await context.request.post(`${endpoint}/generation-plans/${plan.planIdentifier}/submit`, { data: { operationIdentifier: crypto.randomUUID() } });
  assert.equal(submitted.status(), 200, await submitted.text());
  await expect.poll(async () => {
    const results = await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }, { timeout: 15000 }).toBe(20);
}

/** 10→50 확장 입력·취소·실제 제출과 프로젝트별 수량 복원을 확인합니다. */
async function verifyPopulationControls() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const project = await createPopulationProject(context, '조합 규모 확장 검증');
    const otherProject = await createPopulationProject(context, '수량 독립 검증');
    await prepareSmallPopulation(context, project);
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    const countInput = page.locator('#style-generation-random-count');
    const expandButton = page.locator('[data-generation-action=expand-population]');
    await expect(countInput).toBeEnabled();
    await expect(countInput).toHaveValue('10');
    await expect(countInput).toHaveAttribute('max', '1000');
    await expect(page.locator('.random-population-summary')).toContainText('현재 10개');
    await expect(expandButton).toHaveText('50개까지 늘리기 (+40)');
    await page.evaluate(() => navigatePreview('compare'));
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    await page.evaluate(() => navigatePreview('candidates'));
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(countInput).toBeEnabled();
    const beforeJobs = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    await expandButton.click();
    await expect(countInput).toHaveValue('40');
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeJobs);
    await page.locator('[data-generation-action=generate-random]').click();
    const dialog = page.locator('#style-generation-confirmation-dialog');
    await expect(dialog).toContainText('40개 조합 × 2개 Prompt');
    await expect(dialog).toContainText('80장');
    await dialog.locator('[value=cancel]').click();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeJobs);
    const beforeSubmission = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-results?summary=true`)).json();
    assert.equal(beforeSubmission.generationSizing.randomCombinationCount, 10, 'Cancelled confirmation must not become the submitted default');
    await page.locator('[data-generation-action=generate-random]').click();
    await expect(dialog).toBeVisible();
    const submissionRequest = page.waitForRequest(request => request.method() === 'POST' && /\/generation-plans\/[^/]+\/submit$/.test(request.url()));
    await dialog.locator('[value=confirm]').click();
    await submissionRequest;
    assert.equal(await page.evaluate(() => Boolean(currentStyleGenerationState().votingEvaluations?.[currentProject().evaluationIdentifier])), false, 'New submission must invalidate the previous comparison');
    await expect(page.locator('#style-generation-dialog')).not.toBeVisible();
    await expect(page.locator('.style-library-card')).toHaveCount(50, { timeout: 15000 });
    await page.reload();
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(countInput).toBeEnabled();
    await expect(countInput).toHaveValue('40');
    await expect(expandButton).toHaveCount(0);
    await page.locator('[data-generation-action=close-generator]').click();
    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(countInput).toBeEnabled();
    await expect(countInput).toHaveValue('50');
    await page.locator('[data-generation-action=close-generator]').click();
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(countInput).toHaveValue('40');
    const newContext = await browser.newContext({ storageState: await context.storageState() });
    const secondPage = await newContext.newPage();
    await secondPage.goto(`${baseUrl}/style#generation`);
    await secondPage.locator('#active-project-picker').selectOption(project.identifier);
    await secondPage.locator('.page-heading [data-generation-action=open-generator]').click();
    await expect(secondPage.locator('#style-generation-random-count')).toBeEnabled();
    await expect(secondPage.locator('#style-generation-random-count')).toHaveValue('40');
    await secondPage.close();
    await newContext.close();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.evaluate(() => navigatePreview('evolution'));
    await expect(page.locator('#style-generation-candidate-count')).toHaveValue('12');
    await expect(page.locator('#style-generation-candidate-count')).toHaveAttribute('max', '60');
    await expect(page.locator('#style-evolution-controls')).toContainText('활성 50개');
    assert.deepEqual(browserErrors, []);
    filesystem.writeFileSync('runtime/verification/style-population-browser-results.json', JSON.stringify({
      projectIdentifier: project.identifier, otherProjectIdentifier: otherProject.identifier,
      expandedFrom: 10, expandedTo: 50, prompts: 2, defaultRandomCount: 50, defaultEvolutionCount: 12,
      cancelledConfirmationCreatesNoJob: true, projectCountsSurviveReloadAndNewBrowser: true,
      newSubmissionInvalidatesOldMatch: true,
      projectCountsRemainIndependent: true, viewportWidths: [320, 390, 768, 1280], browserErrors,
    }, null, 2));
    console.log('Style population size and persisted generation counts Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyPopulationControls().catch(error => { console.error(error); process.exitCode = 1; });
