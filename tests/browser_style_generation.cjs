const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 격리 서버에서 실제 Form 제출·결과 Polling·일반 화면 필터를 검증합니다. */
async function verifyStyleGeneration() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.setViewportSize({ width: 1280, height: 1000 });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const response = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `browser-${Date.now()}-create`, settings: {
        name: `Browser 생성 ${Date.now()}`, pipelineIdentifier: 'anima', width: 64, height: 96, steps: 3, cfg: 1,
        promptCases: [{ identifier: 'portrait', name: '인물', prompt: 'portrait, {artist}' }, { identifier: 'garden', name: '정원', prompt: 'garden, {artist}' }],
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.8 } },
      },
    } });
    assert.equal(response.status(), 201, await response.text());
    const project = await response.json();
    await page.goto(`${baseUrl}/style#generation`);
    await expect(page.locator('#preview-application')).toBeVisible();
    if (await page.locator('#active-project-picker').count()) await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.goto(`${baseUrl}/style#generation`);
    await page.getByText('고정 A/B 조합 직접 확인', { exact: true }).click();
    await page.locator('[data-generation-action=prepare]').click();
    await expect(page.locator('.generation-component')).toHaveCount(2);
    await page.locator('[data-generation-strength]').first().fill('0.3');
    await page.locator('[data-generation-strength]').last().fill('0.7');
    await page.locator('[data-generation-action=preview]').click();
    await expect(page.locator('#style-generation-confirmation-dialog')).toContainText('4장');
    const beforeJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    const submittedResponse = page.waitForResponse(response => response.url().endsWith('/submit') && response.request().method() === 'POST');
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    const submitted = await submittedResponse;
    assert.equal(submitted.status(), 200, await submitted.text());
    await expect(page.locator('.generation-result img')).toHaveCount(4, { timeout: 15000 });
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-generation-mobile.png', fullPage: true });
    await page.locator('[data-generation-action=enlarge]').first().click();
    await expect(page.locator('#illustration-dialog')).toBeVisible();
    await expect(page.locator('#style-viewer-original-toggle')).not.toBeChecked();
    await page.locator('[data-style-library-action=close]').click();
    await page.reload();
    await expect(page.locator('.generation-result img')).toHaveCount(4, { timeout: 10000 });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-generation-desktop.png', fullPage: true });
    await page.goto(`${baseUrl}/?view=jobs`);
    await expect(page.locator('#include-style-jobs')).toBeVisible();
    await expect(page.locator('[data-move-job-folder]')).toHaveCount(0);
    await page.locator('#include-style-jobs').check();
    await expect(page.locator('[data-move-job-folder]')).toHaveCount(beforeJobCount + 1);
    await expect(page.locator('[data-move-job-folder]').first()).toBeDisabled();
    await page.goto(`${baseUrl}/?view=outputs`);
    await expect(page.locator('#include-style-outputs')).toBeVisible();
    await expect(page.locator('.output-card')).toHaveCount(0);
    await page.locator('#include-style-outputs').check();
    await expect(page.locator('.output-card')).toHaveCount((beforeJobCount + 1) * 4);
    await expect(page.locator('[data-move-output]').first()).toBeDisabled();
    await page.locator('#include-style-outputs').uncheck();
    await expect(page.locator('.output-card')).toHaveCount(0);
    assert.deepEqual(browserErrors, []);
    fs.writeFileSync('runtime/verification/style-generation-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, imageCount: 4, widths: [320, 390, 768, 1280], browserErrors }, null, 2));
    console.log('Style generation Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleGeneration().catch(error => { console.error(error); process.exitCode = 1; });
