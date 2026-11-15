const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

/** 생성 후 Prompt 추가·저장 실패·Refresh·새 Session과 고정 조합 재생성을 검증합니다. */
async function verifyStylePromptChanges() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const created = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `prompt-changes-${Date.now()}`, settings: {
        name: 'Prompt 저장 Browser 검증', width: 64, height: 96, seed: 42, steps: 3, cfg: 1,
        artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
        promptCases: [1, 2].map(index => ({ identifier: `case-${index}`, name: `장면 ${index}`, prompt: `scene ${index}` })),
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
      },
    } });
    assert.equal(created.status(), 201, await created.text());
    const project = await created.json();
    const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await page.locator('#style-generation-random-count').fill('2');
    await page.locator('[data-generation-action=generate-random]').click();
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(4);
    const before = await (await context.request.get(endpoint + '/generation-results')).json();
    await page.goto(`${baseUrl}/style#project-settings`);
    await page.locator('[data-settings-action=add-prompt]').click();
    await page.locator('#settings-case-name-2').fill('세 번째 장면');
    await page.locator('#settings-case-prompt-2').fill('night garden');
    assert.equal(await page.evaluate(() => validateSettingsPreview('project', settingsPreviewDraft('project'))), '');
    const invalidFields = await page.locator('#project-settings-form').evaluate(form => [...form.elements].filter(field => field.willValidate && !field.validity.valid).map(field => ({ id: field.id, message: field.validationMessage, value: field.value })));
    assert.deepEqual(invalidFields, []);
    const savedResponse = page.waitForResponse(response => response.url() === endpoint && response.request().method() === 'PUT');
    await page.locator('#project-settings-form button[type=submit]').click();
    if ((await page.locator('#settings-form-error').innerText()).trim()) throw new Error(await page.locator('#settings-form-error').innerText());
    const response = await savedResponse;
    assert.equal(response.status(), 200, `Third prompt was refused: ${await response.text()}`);
    await expect(page.locator('#style-settings-save-status')).toHaveText('저장됨');
    await page.reload();
    await expect(page.locator('#settings-case-prompt-2')).toHaveValue('night garden');
    await expect(page.locator('#settings-case-name-2')).toHaveValue('세 번째 장면');
    const freshContext = await browser.newContext();
    await freshContext.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const freshPage = await freshContext.newPage();
    await freshPage.goto(`${baseUrl}/style#project-settings`);
    await freshPage.locator('#active-project-picker').selectOption(project.identifier);
    await expect(freshPage.locator('#settings-case-prompt-2')).toHaveValue('night garden');
    await freshContext.close();
    await page.locator('[data-settings-action=add-prompt]').click();
    await page.locator('#settings-case-prompt-3').fill('fourth scene kept after failed save');
    await page.route(endpoint, route => route.request().method() === 'PUT' ? route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '검증용 저장 충돌' }) }) : route.continue());
    await page.locator('#project-settings-form button[type=submit]').click();
    await expect(page.locator('#settings-form-error')).toContainText('검증용 저장 충돌');
    await expect(page.locator('#style-settings-save-status')).toContainText('저장 실패');
    await page.reload();
    await expect(page.locator('#settings-case-prompt-3')).toHaveValue('fourth scene kept after failed save');
    assert.equal((await (await context.request.get(endpoint)).json()).settings.promptCases.length, 3);
    await page.unroute(endpoint);
    await page.locator('#project-settings-form button[type=submit]').click();
    await expect(page.locator('#style-settings-save-status')).toHaveText('저장됨');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(page.locator('#project-settings-form button[type=submit]')).toBeInViewport();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/prompt-settings-mobile.png' });
    await page.goto(`${baseUrl}/style#generation`);
    await expect(page.locator('[data-generation-action=regenerate-prompts]')).toBeVisible();
    await page.locator('[data-generation-action=regenerate-prompts]').click();
    await expect(page.locator('#style-generation-confirmation-dialog')).toContainText('8장');
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(12);
    const after = await (await context.request.get(endpoint + '/generation-results')).json();
    const regenerationPlan = after.plans.find(plan => plan.selection.mode === 'prompt-regeneration');
    assert.equal(regenerationPlan.cases.length, 4);
    assert.equal(regenerationPlan.generationNumber, 1);
    assert.deepEqual(regenerationPlan.candidates.map(candidate => candidate.components).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))), before.candidates.map(candidate => candidate.components).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
    for (const candidate of before.candidates) assert.deepEqual(after.candidates.find(current => current.identifier === candidate.identifier), candidate);
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('.comparison-result img')).toHaveCount(8);
    await expect(page.locator('.comparison-result img').first()).toHaveAttribute('src', /^\/media\//);
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    assert.equal(await page.locator('.comparison-result img').first().evaluate(image => image.getBoundingClientRect().top < 560), true);
    await expect(page.locator('.evolution-panel')).toHaveCount(0);
    await expect(page.locator('.preview-notice')).toBeHidden();
    await page.screenshot({ path: 'runtime/verification/prompt-compare-mobile.png' });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.reload();
    await expect(page.locator('.comparison-result img').first()).toHaveAttribute('src', /^\/media\//);
    await page.screenshot({ path: 'runtime/verification/prompt-compare-desktop.png' });
    assert.deepEqual(errors, []);
    filesystem.writeFileSync('runtime/verification/style-prompt-changes-browser.json', JSON.stringify({ thirdPromptSaved: true, freshSessionReadsServer: true, failedSaveDraftSurvivesRefresh: true, stickySaveWidths: [320, 390, 768, 1280], regenerationPreservesCombinations: true, allFourPromptsRendered: true, originalResultsPreserved: true, comparisonImageAboveFold: true, errors }, null, 2));
    console.log('Prompt save, refresh recovery, fixed combinations and compact comparison passed');
  } finally {
    await browser.close();
  }
}

verifyStylePromptChanges().catch(error => { console.error(error); process.exitCode = 1; });
