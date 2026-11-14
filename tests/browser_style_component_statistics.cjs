const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

const baseUrl = 'http://127.0.0.1:18388';

/** 격리 서버에만 두 성분의 실제 이미지와 승패가 다른 프로젝트를 준비합니다. */
async function prepareComponentStatisticsScenario(context) {
  const workspace = await (await context.request.get(`${baseUrl}/api/style-workspace`)).json();
  for (const name of ['score-alpha', 'score-beta']) {
    if (!workspace.globalSettings.additionalArtists.some(artist => artist.name === name)) {
      workspace.globalSettings.additionalArtists.push({ identifier: `artist:${name}`, name, kind: '작가' });
    }
  }
  const globalResponse = await context.request.put(`${baseUrl}/api/style-settings`, { data: workspace.globalSettings });
  assert.equal(globalResponse.status(), 200, await globalResponse.text());
  const settings = { name: `성분 통계 ${Date.now()}`, width: 64, height: 96, steps: 3,
    promptCases: [{ identifier: 'portrait', name: '인물', prompt: 'portrait' }, { identifier: 'garden', name: '정원', prompt: 'garden' }],
    componentPolicies: {
      'artist:score-alpha': { enabled: true, minimumStrength: 0.4, maximumStrength: 0.9 },
      'artist:score-beta': { enabled: true, minimumStrength: 0.4, maximumStrength: 0.9 },
      'lora:example.safetensors': { enabled: true, minimumStrength: 0.4, maximumStrength: 0.9 },
    } };
  const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings, operationIdentifier: crypto.randomUUID() } });
  assert.equal(projectResponse.status(), 201, await projectResponse.text());
  const project = await projectResponse.json();
  const planResponse = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/generation-plans`, { data: {
    expectedRevision: project.revision, operationIdentifier: crypto.randomUUID(), combinations: [
      { components: [{ identifier: 'artist:score-alpha', strength: 0.7 }] },
      { components: [{ identifier: 'artist:score-beta', strength: 0.6 }, { identifier: 'lora:example.safetensors', strength: 0.8 }] },
    ],
  } });
  assert.equal(planResponse.status(), 201, await planResponse.text());
  const plan = await planResponse.json();
  const submitResponse = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/generation-plans/${plan.planIdentifier}/submit`, { data: { operationIdentifier: crypto.randomUUID() } });
  assert.equal(submitResponse.status(), 200, await submitResponse.text());
  await expect.poll(async () => {
    const results = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-results?summary=true`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }).toBe(4);
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier, clientIdentifier: 'component-browser-0123456789' });
  const selection = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/selection?${parameters}`)).json();
  const winnerIdentifier = plan.candidates[1].identifier;
  const voted = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/votes`, { data: {
    evaluationIdentifier: project.evaluationIdentifier, clientIdentifier: 'component-browser-0123456789',
    operationIdentifier: crypto.randomUUID(), expectedRevision: selection.revision, matchToken: selection.match.token,
    choice: selection.match.a === winnerIdentifier ? 'a' : 'b',
  } });
  assert.equal(voted.status(), 200, await voted.text());
  const otherResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
    settings: { ...settings, name: `${settings.name} 빈 프로젝트` }, operationIdentifier: crypto.randomUUID(),
  } });
  assert.equal(otherResponse.status(), 201, await otherResponse.text());
  return { project, otherProject: await otherResponse.json() };
}

/** 실제 통계·모바일 배치·정렬·지연 응답 중 입력 보존·프로젝트 격리를 확인합니다. */
async function verifyComponentStatistics() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  const mutations = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const { project, otherProject } = await prepareComponentStatisticsScenario(context);
    await context.addInitScript(identifier => sessionStorage.setItem('comfy-home-style-workspace-session-v1',
      JSON.stringify({ currentProjectIdentifier: identifier, screen: 'project-settings' })), project.identifier);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (request.method() !== 'GET') mutations.push(request.url()); });
    await page.goto(`${baseUrl}/style#project-settings`);
    const loraStatistics = page.locator('[data-project-component-statistics="lora:example.safetensors"]');
    await expect(loraStatistics).toContainText('1승 0패');
    await expect(loraStatistics).toContainText('100%');
    await expect(loraStatistics.locator('dd').first()).toHaveText(/^\+/);
    await expect(page.locator('[data-project-component-statistics="artist:score-alpha"]')).toContainText('0승 1패');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      await loraStatistics.scrollIntoViewIfNeeded();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.ok(await loraStatistics.evaluate(element => element.scrollWidth <= element.clientWidth));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-component-statistics-sort=artist]').selectOption('score');
    await expect(page.locator('[data-settings-kind=artist] .settings-component').first()).toHaveAttribute('data-policy-component', 'artist:score-beta');
    const strengthInput = page.locator('[data-settings-component="lora:example.safetensors"][data-settings-policy=minimumStrength]');
    await strengthInput.fill('0.45');
    await page.route('**/component-statistics?**', async route => {
      await new Promise(resolve => setTimeout(resolve, 800));
      await route.continue();
    });
    const responsePromise = page.waitForResponse(response => response.url().includes('/component-statistics?'));
    await page.locator('[data-component-statistics-refresh]').click();
    await strengthInput.focus();
    await responsePromise;
    await expect(page.locator('#style-component-statistics-status')).toBeEmpty();
    await expect(strengthInput).toBeFocused();
    await expect(strengthInput).toHaveValue('0.45');
    await loraStatistics.scrollIntoViewIfNeeded();
    await page.screenshot({ path: 'runtime/verification/style-component-statistics-mobile.png' });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-component-statistics-desktop.png' });
    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await expect(loraStatistics).toContainText('0승 0패');
    await expect(loraStatistics.locator('dd').first()).toHaveText('—');
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await expect(loraStatistics).toContainText('1승 0패');
    await expect(strengthInput).toHaveValue('0.45');
    assert.deepEqual(mutations, []);
    assert.deepEqual(errors, []);
    filesystem.writeFileSync('runtime/verification/style-component-statistics-browser.json', JSON.stringify({
      widths: [320, 390, 768, 1280], projectIsolation: true, preferenceSorting: true, delayedInputPreserved: true, mutations, errors,
    }, null, 2));
    console.log('Style component statistics Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyComponentStatistics().catch(error => { console.error(error); process.exitCode = 1; });
