const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 실제 Fork 화면에서 설정 복사·응답 유실·이력 분리·모바일 배치를 검증합니다. */
async function verifyStyleProjectForks() {
  const baseUrl = 'http://127.0.0.1:18388';
  const artifactDirectory = 'runtime/verification/style-project-forks';
  const fixture = JSON.parse(fs.readFileSync(`${artifactDirectory}/fixture-manifest.json`, 'utf8'));
  const source = fixture.source;
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  const unexpectedMutationRequests = [];
  const createdProjects = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST' && /\/(votes|random-generation-plans|generation-plans|evolution-plans|submit)(?:[/?]|$)/.test(request.url())) {
        unexpectedMutationRequests.push(request.url());
      }
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#projects`);
    await expect(page.locator(`[data-project-fork="${source.identifier}"]`)).toBeVisible();
    await page.evaluate(identifier => {
      previewState.settingsDrafts.projects[identifier] = structuredClone(previewState.projects.find(project => project.identifier === identifier).settings);
      previewState.settingsDrafts.projects[identifier].promptCases[0].prompt = 'unsaved local prompt';
      persistPreviewSession();
    }, source.identifier);
    await page.locator(`[data-project-fork="${source.identifier}"]`).click();
    await expect(page.locator('#style-project-fork-source')).toBeEnabled();
    await expect(page.locator('#style-project-fork-statistics')).not.toBeChecked();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const geometry = await page.locator('#style-project-fork-dialog').evaluate(dialog => {
        const bounds = dialog.getBoundingClientRect();
        return { left: bounds.left, right: bounds.right, width: innerWidth, contentWidth: dialog.scrollWidth, clientWidth: dialog.clientWidth };
      });
      assert.ok(geometry.left >= 0 && geometry.right <= geometry.width + 1 && geometry.contentWidth <= geometry.clientWidth + 1, JSON.stringify(geometry));
    }
    await page.locator('[data-project-fork-cancel]').click();
    assert.equal((await (await context.request.get(`${baseUrl}/api/style-projects`)).json()).projects.length, 1);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator(`[data-project-fork="${source.identifier}"]`).click();
    await expect(page.locator('#style-project-fork-source')).toBeEnabled();
    await page.locator('#style-project-fork-name').fill('설정만 Fork');
    await page.screenshot({ path: `${artifactDirectory}/fork-mobile.png`, fullPage: true });
    let droppedResponse = false;
    await page.route('**/api/style-projects/*/forks', async route => {
      if (!droppedResponse) {
        droppedResponse = true;
        const response = await route.fetch();
        assert.equal(response.status(), 201, await response.text());
        await route.abort('failed');
      } else {
        await route.continue();
      }
    });
    await page.locator('#style-project-fork-form button[type=submit]').click();
    await expect(page.locator('#style-project-fork-error')).not.toHaveText('');
    await expect(page.locator('#style-project-fork-dialog')).toBeVisible();
    await page.locator('#style-project-fork-form button[type=submit]').click();
    await expect(page.locator('#style-project-fork-dialog')).not.toBeVisible();
    await expect(page.locator('#settings-project-name')).toHaveValue('설정만 Fork');
    let projects = (await (await context.request.get(`${baseUrl}/api/style-projects`)).json()).projects;
    assert.equal(projects.length, 2);
    const initialFork = projects.find(project => project.name === '설정만 Fork');
    assert.deepEqual(initialFork.settings, { ...source.settings, name: initialFork.name });
    assert.equal(initialFork.forkSource.generationNumber, 2);
    assert.equal(initialFork.generation, 0);
    assert.equal(initialFork.forkSource.includesComponentStatistics, false);
    const resetStatistics = await (await context.request.get(`${baseUrl}/api/style-projects/${initialFork.identifier}/component-statistics`)).json();
    assert.ok(Object.values(resetStatistics.components).every(value => value.score === 0 && value.matches === 0));
    const retainedDraft = await page.evaluate(identifier => previewState.settingsDrafts.projects[identifier].promptCases[0].prompt, source.identifier);
    assert.equal(retainedDraft, 'unsaved local prompt');
    createdProjects.push(initialFork.identifier);
    await page.goto(`${baseUrl}/style#projects`);
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.locator(`[data-project-fork="${source.identifier}"]`).click();
    await expect(page.locator('#style-project-fork-source')).toBeEnabled();
    await page.locator('#style-project-fork-source').selectOption(fixture.snapshotIdentifier);
    await page.locator('#style-project-fork-statistics').check();
    await expect(page.locator('#style-project-fork-summary')).toContainText('선호도·승패 포함');
    await page.locator('#style-project-fork-name').fill('확정 세대 Fork');
    await page.screenshot({ path: `${artifactDirectory}/fork-desktop.png`, fullPage: true });
    await page.locator('#style-project-fork-form button[type=submit]').click();
    await expect(page.locator('#style-project-fork-dialog')).not.toBeVisible();
    await expect(page.locator('#settings-project-name')).toHaveValue('확정 세대 Fork');
    await expect(page.locator('.component-inherited-statistics').first()).toContainText('새 비교 0회');
    projects = (await (await context.request.get(`${baseUrl}/api/style-projects`)).json()).projects;
    assert.equal(projects.length, 3);
    const historicalFork = projects.find(project => project.name === '확정 세대 Fork');
    assert.deepEqual(historicalFork.settings, { ...fixture.historicalSettings, name: historicalFork.name });
    assert.equal(historicalFork.forkSource.generationNumber, 1);
    assert.equal(historicalFork.generation, 0);
    assert.equal(historicalFork.forkSource.includesComponentStatistics, true);
    const inheritedStatistics = await (await context.request.get(`${baseUrl}/api/style-projects/${historicalFork.identifier}/component-statistics`)).json();
    for (const [identifier, original] of Object.entries(fixture.historicalStatistics)) {
      const inherited = inheritedStatistics.components[identifier];
      assert.equal(inherited.score, original.score);
      assert.equal(inherited.matches, original.matches);
      assert.equal(inherited.localScore, 0);
    }
    createdProjects.push(historicalFork.identifier);
    for (const identifier of createdProjects) {
      const results = await (await context.request.get(`${baseUrl}/api/style-projects/${identifier}/generation-results?summary=true`)).json();
      assert.deepEqual(results.candidates, []);
      assert.deepEqual(results.plans, []);
    }
    await page.reload();
    await expect(page.locator('#settings-project-name')).toHaveValue('확정 세대 Fork');
    await page.goto(`${baseUrl}/style#projects`);
    await expect(page.locator(`[data-project-card="${historicalFork.identifier}"] .project-fork-source`)).toContainText('1세대에서 Fork');
    await page.locator(`[data-project-fork="${source.identifier}"]`).click();
    await expect(page.locator('#style-project-fork-source')).toBeEnabled();
    await page.locator('#style-project-fork-source').selectOption(fixture.initialSnapshotIdentifier);
    await expect(page.locator('#style-project-fork-statistics')).not.toBeChecked();
    await page.locator('#style-project-fork-name').fill('0세대 설정 Fork');
    await page.locator('#style-project-fork-form button[type=submit]').click();
    await expect(page.locator('#style-project-fork-dialog')).not.toBeVisible();
    await expect(page.locator('#settings-project-name')).toHaveValue('0세대 설정 Fork');
    projects = (await (await context.request.get(`${baseUrl}/api/style-projects`)).json()).projects;
    assert.equal(projects.length, 4);
    const zeroFork = projects.find(project => project.name === '0세대 설정 Fork');
    assert.equal(zeroFork.generation, 0);
    assert.equal(zeroFork.forkSource.generationNumber, 0);
    assert.deepEqual(zeroFork.settings, { ...fixture.initialSettings, name: zeroFork.name });
    createdProjects.push(zeroFork.identifier);
    const currentSource = await (await context.request.get(`${baseUrl}/api/style-projects/${source.identifier}`)).json();
    assert.deepEqual(currentSource.settings, source.settings);
    assert.deepEqual(browserErrors, []);
    assert.deepEqual(unexpectedMutationRequests, []);
    fs.writeFileSync(`${artifactDirectory}/browser-results.json`, JSON.stringify({ widths: [320, 390, 768, 1280], createdProjects, responseLossRecovered: droppedResponse, browserErrors, unexpectedMutationRequests }, null, 2));
    console.log('Style project Fork Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleProjectForks().catch(error => { console.error(error); process.exitCode = 1; });
