const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 실제 확정 세대가 있는 격리 서버에서 폐기 후 즉시 승격·새로고침·선별 반영을 확인합니다. */
async function verifyStylePopulationReplenishment() {
  const baseUrl = 'http://127.0.0.1:18388';
  const artifactDirectory = 'runtime/verification/style-active-refill';
  const fixture = JSON.parse(fs.readFileSync(`${artifactDirectory}/fixture-manifest.json`, 'utf8'));
  const project = fixture.project;
  const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  const deletionResults = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.goto(`${baseUrl}/style#candidates`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await expect(page.locator('.style-library-card')).toHaveCount(10);
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const before = await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json();
      const retired = before.candidates.filter(candidate => candidate.lifecycle === 'retired');
      retired.sort((first, second) => second.statistics.rating - first.statistics.rating);
      const expectedCandidate = retired[0];
      const targetIdentifier = await page.locator('.style-library-card').first().getAttribute('data-style-candidate');
      const targetDeleteButton = page.locator(`[data-style-candidate="${targetIdentifier}"] [data-style-candidate-action=delete]`);
      await targetDeleteButton.click();
      if (width === 390) {
        await page.locator('#component-dialog button[value=cancel]').click();
        await expect(page.locator('.style-library-card')).toHaveCount(10);
        await targetDeleteButton.click();
      }
      const deletionResponsePromise = page.waitForResponse(response => response.url().endsWith('/candidate-deletions') && response.request().method() === 'POST');
      await page.locator('#component-dialog button[value=confirm]').click();
      const deletionResponse = await deletionResponsePromise;
      assert.equal(deletionResponse.status(), 200, await deletionResponse.text());
      const deletion = await deletionResponse.json();
      assert.deepEqual(deletion.promotedCandidateIdentifiers, [expectedCandidate.identifier]);
      await expect(page.locator(`[data-style-candidate="${expectedCandidate.identifier}"]`)).toBeVisible();
      await expect(page.locator(`[data-style-candidate="${targetIdentifier}"]`)).toHaveCount(0);
      await expect(page.locator('.style-library-card')).toHaveCount(10);
      const after = await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json();
      const promotedCandidate = after.candidates.find(candidate => candidate.identifier === expectedCandidate.identifier);
      assert.equal(promotedCandidate.lifecycle, 'active');
      for (const field of ['rating', 'matches', 'wins', 'losses', 'placed']) {
        assert.equal(promotedCandidate.statistics[field], expectedCandidate.statistics[field]);
      }
      assert.equal(after.candidates.filter(candidate => candidate.lifecycle === 'active').length, 10);
      await page.reload();
      await expect(page.locator('.style-library-card')).toHaveCount(10);
      await expect(page.locator(`[data-style-candidate="${expectedCandidate.identifier}"]`)).toBeVisible();
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
      await page.screenshot({ path: `${artifactDirectory}/replenishment-${width}.png`, fullPage: true });
      await page.goto(`${baseUrl}/style#compare`);
      await page.waitForFunction(identifier => currentPersistentComparison()?.allCandidates.some(candidate => candidate.identifier === identifier), expectedCandidate.identifier);
      await page.goto(`${baseUrl}/style#candidates`);
      await expect(page.locator('.style-library-card')).toHaveCount(10);
      deletionResults.push({ width, deletedIdentifier: targetIdentifier, promotedIdentifier: expectedCandidate.identifier, activeCount: 10 });
    }
    assert.deepEqual(browserErrors, []);
    fs.writeFileSync(`${artifactDirectory}/browser-results.json`, JSON.stringify({ deletionResults, browserErrors }, null, 2));
    console.log('Style population replenishment Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStylePopulationReplenishment().catch(error => { console.error(error); process.exitCode = 1; });
