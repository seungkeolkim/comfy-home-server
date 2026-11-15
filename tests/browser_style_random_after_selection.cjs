const { chromium } = require('playwright');
const { expect: browserExpect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

const expect = browserExpect.configure({ timeout: 15000 });

/** 준비된 초기 조합의 평가와 경계 Tie를 마쳐 진화 가능한 Pool을 만듭니다. */
async function finishInitialRandomSelection(context, project, endpoint, clientIdentifier) {
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier, clientIdentifier });
  for (let voteIndex = 0; voteIndex < 80; voteIndex += 1) {
    const evolutionResponse = await context.request.get(`${endpoint}/evolution?${parameters}`);
    const evolution = await evolutionResponse.json();
    if (evolution.canPrepare) return evolution;
    const selectionResponse = await context.request.get(`${endpoint}/selection?${parameters}`);
    assert.equal(selectionResponse.status(), 200, await selectionResponse.text());
    const selection = await selectionResponse.json();
    assert.ok(selection.match, 'Initial candidates must have a selectable match');
    const voteResponse = await context.request.post(`${endpoint}/votes`, { data: {
      evaluationIdentifier: project.evaluationIdentifier, clientIdentifier,
      operationIdentifier: `random-after-selection-${Date.now()}-${voteIndex}`,
      expectedRevision: selection.revision, matchToken: selection.match.token,
      choice: selection.match.kind === 'tie' ? 'similar' : 'a',
    } });
    assert.equal(voteResponse.status(), 200, await voteResponse.text());
  }
  throw new Error('Initial candidates did not finish selection within 80 votes');
}

/** 평가 Pool이 준비된 뒤에도 Random 추가가 세대 진화로 바뀌지 않는지 검증합니다. */
async function verifyRandomAfterSelection() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `random-after-selection-project-${Date.now()}`,
      settings: {
        name: '평가 후 독립 Random 추가 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
        artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
        promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 1.9 } },
      },
    } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await page.locator('#style-generation-random-count').fill('10');
    await page.locator('[data-generation-action=generate-random]').click();
    const confirmation = page.locator('#style-generation-confirmation-dialog');
    await expect(confirmation).toContainText('30장');
    await confirmation.locator('button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(30);
    const clientIdentifier = await page.evaluate(() => styleVotingClientIdentifier());
    const evolutionBefore = await finishInitialRandomSelection(context, project, endpoint, clientIdentifier);
    assert.equal(evolutionBefore.evaluatedCount, 10);
    assert.equal(evolutionBefore.batch, null);
    await page.goto(`${baseUrl}/style#evolution`);
    await expect(page.locator('[data-generation-action=generate-candidates]')).toBeEnabled();
    await page.locator('#preview-content [data-generation-action=open-generator]').click();
    await expect(page.locator('[data-generation-action=generate-random]')).toBeEnabled();
    await expect(page.locator('[data-generation-action=generate-candidates]')).toHaveCount(0);
    const resultsBefore = await (await context.request.get(`${endpoint}/generation-results`)).json();
    const mutationPaths = [];
    page.on('request', request => {
      if (request.method() === 'POST' && request.url().startsWith(endpoint)) mutationPaths.push(request.url());
    });
    await page.locator('#style-generation-random-count').fill('1');
    const planResponse = page.waitForResponse(response => response.url() === `${endpoint}/random-generation-plans`);
    await page.locator('[data-generation-action=generate-random]').click();
    const randomPlan = await (await planResponse).json();
    assert.equal(randomPlan.selection.mode, 'random');
    assert.equal(randomPlan.generationNumber, 1);
    await expect(confirmation).toContainText('1개 조합 × 3개 Prompt');
    await expect(confirmation).toContainText('3장');
    await confirmation.locator('button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(33);
    const evolutionAfter = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    assert.equal(evolutionAfter.currentGeneration, evolutionBefore.currentGeneration);
    assert.equal(evolutionAfter.batch, null);
    const resultsAfter = await (await context.request.get(`${endpoint}/generation-results`)).json();
    assert.equal(resultsAfter.candidates.length, 11);
    for (const candidate of resultsBefore.candidates) {
      const preserved = resultsAfter.candidates.find(current => current.identifier === candidate.identifier);
      assert.deepEqual(preserved.renders, candidate.renders);
      assert.deepEqual(preserved.components, candidate.components);
      assert.equal(preserved.lifecycle, 'active');
    }
    assert.ok(mutationPaths.every(path => !path.endsWith('/evolution-plans') && !path.endsWith('/candidate-generation-plans')));
    assert.deepEqual(browserErrors, []);
    filesystem.writeFileSync('runtime/verification/style-random-after-selection-results.json', JSON.stringify({ projectIdentifier: project.identifier, initialCount: 10, addedCount: 1, promptCount: 3, generationPreserved: true, noEvolutionBatch: true, browserErrors }, null, 2));
    console.log('Random addition after evaluated pool Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyRandomAfterSelection().catch(error => { console.error(error); process.exitCode = 1; });
