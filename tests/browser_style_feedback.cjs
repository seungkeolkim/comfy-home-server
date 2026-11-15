const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 실제 Form 저장 응답을 기다려 초안·낮은 Revision 덮어쓰기를 함께 확인합니다. */
async function saveStyleFeedbackForm(page, formIdentifier, method) {
  const savedResponse = page.waitForResponse(response => response.request().method() === method && /\/api\/style-(projects|settings)/.test(response.url()));
  await page.locator(`${formIdentifier} button[type=submit]`).click();
  const response = await savedResponse;
  assert.equal(response.status(), method === 'POST' ? 201 : 200, await response.text());
  if (formIdentifier === '#style-prompt-name-form') await expect(page.locator('#component-dialog')).not.toBeVisible();
  else await expect(page.locator(`${method === 'POST' ? '#project-settings-form' : formIdentifier} button[type=submit]`)).toBeEnabled();
  return response.json();
}

/** 검토한 목업의 조작과 다섯 수정 요구를 실제 임시 생성 결과로 검증합니다. */
async function verifyStyleFeedback() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const workspace = await (await context.request.get(`${baseUrl}/api/style-workspace`)).json();
    const globalSettings = workspace.globalSettings;
    for (const name of ['feedback_alpha', 'feedback_beta']) {
      if (!globalSettings.additionalArtists.some(artist => artist.name === name)) globalSettings.additionalArtists.push({ identifier: `artist:${name}`, name, kind: '작가' });
      globalSettings.availableComponents[`artist:${name}`] = true;
    }
    globalSettings.availableComponents['lora:example.safetensors'] = true;
    const globalResponse = await context.request.put(`${baseUrl}/api/style-settings`, { data: globalSettings });
    assert.equal(globalResponse.status(), 200, await globalResponse.text());
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(`${baseUrl}/style#global-settings`);
    await page.locator('#settings-global-artistMinimumCount').fill('1');
    await page.locator('#settings-global-artistMaximumCount').fill('2');
    await page.locator('#settings-global-loraMinimumCount').fill('0');
    await page.locator('#settings-global-loraMaximumCount').fill('1');
    await saveStyleFeedbackForm(page, '#global-settings-form', 'PUT');
    await page.locator('#preview-sidebar [data-screen=projects]').click();
    await page.locator('#preview-content [data-screen=create]').first().click();
    await expect(page.locator('#settings-project-artistMinimumCount')).toHaveValue('1');
    await expect(page.locator('#settings-project-artistMaximumCount')).toHaveValue('2');
    await page.locator('#settings-project-name').fill(`피드백 검증 ${Date.now()}`);
    await page.locator('#settings-case-prompt-0').fill('portrait, {artist}');
    await page.locator('[data-settings-action=add-prompt]').click();
    await page.locator('#settings-case-prompt-1').fill('garden, {artist}');
    await page.locator('#settings-project-aspectRatio').selectOption('custom');
    await page.locator('#settings-project-width').fill('64');
    await page.locator('#settings-project-height').fill('96');
    await page.locator('#settings-project-steps').fill('3');
    await page.locator('#settings-project-seed').fill('18446744073709551615');
    await page.locator('#settings-project-artistMaximumCount').fill('1');
    for (const checkbox of await page.locator('[data-settings-policy=enabled]').all()) {
      const identifier = await checkbox.getAttribute('data-settings-component');
      await checkbox.setChecked(['artist:feedback_alpha', 'artist:feedback_beta', 'lora:example.safetensors'].includes(identifier));
    }
    const project = await saveStyleFeedbackForm(page, '#persistent-project-form', 'POST');
    assert.equal(project.settings.artistMaximumCount, 1);
    assert.equal(project.settings.seed, '18446744073709551615');
    await page.locator('#preview-sidebar [data-screen=candidates]').click();
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await page.getByText('직접 조합 지정', { exact: true }).click();
    await page.locator('[data-generation-action=prepare]').click();
    await page.locator('[data-generation-component="artist:feedback_alpha"][data-generation-combination="1"]').uncheck();
    await page.locator('[data-generation-component="artist:feedback_beta"][data-generation-combination="1"]').check();
    await page.locator('[data-generation-strength="lora:example.safetensors"][data-generation-combination="0"]').fill('0.4');
    await page.locator('[data-generation-strength="lora:example.safetensors"][data-generation-combination="1"]').fill('0.8');
    await page.locator('[data-generation-action=preview]').click();
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(4, { timeout: 15000 });
    await page.goto(`${baseUrl}/style#project-settings`);
    await page.locator('#settings-project-purpose').fill('선별 왕복 후에도 남아야 하는 미저장 메모');
    await page.locator('#preview-sidebar [data-screen=compare]').click();
    await expect(page.locator('.persistent-comparison img')).toHaveCount(4, { timeout: 10000 });
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    const originalSources = await page.locator('.persistent-comparison img').evaluateAll(elements => elements.map(element => element.getAttribute('src')));
    await expect(page.locator('#preview-content')).not.toContainText('성분·실제 생성 조건');
    await page.locator('[data-action=open-differences]').click();
    await expect(page.locator('#component-dialog .difference-row')).toHaveCount(3);
    await expect(page.locator('#component-dialog')).toContainText('A에만 있음');
    await expect(page.locator('#component-dialog')).toContainText('B에만 있음');
    await expect(page.locator('#component-dialog')).toContainText('강도 변경');
    await expect(page.locator('#component-dialog')).not.toContainText('CLIP');
    const toggleComponent = page.locator('[data-style-comparison-action=toggle-component][data-component="artist:feedback_alpha"]');
    await toggleComponent.click();
    await expect(toggleComponent).toContainText('제외 설정됨');
    const excludedProject = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}`)).json();
    assert.equal(excludedProject.settings.componentPolicies['artist:feedback_alpha'].enabled, false);
    await toggleComponent.click();
    await expect(toggleComponent).toContainText('앞으로 새 조합에서 제외');
    await page.locator('[data-action=close-differences]').click();
    await page.locator('[data-action=toggle-blind]').click();
    await expect(page.locator('[data-action=open-differences]')).toBeDisabled();
    await page.locator('[data-action=toggle-blind]').click();
    await page.locator('[data-style-comparison-action=rename-prompt]').first().click();
    await page.locator('#style-prompt-display-name').fill('이름을 바꾼 인물');
    await saveStyleFeedbackForm(page, '#style-prompt-name-form', 'PUT');
    await expect(page.locator('.case-heading').first()).toContainText('이름을 바꾼 인물');
    assert.deepEqual(await page.locator('.persistent-comparison img').evaluateAll(elements => elements.map(element => element.getAttribute('src'))), originalSources);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.case-section:visible')).toHaveCount(2);
    await expect(page.locator('[data-action=switch-case]')).toHaveCount(0);
    await page.locator('.case-section').last().scrollIntoViewIfNeeded();
    await expect(page.locator('.case-section').last()).toContainText('Prompt 2');
    await page.locator('[data-action=image-layout]').click();
    await expect(page.locator('.case-section:visible .comparison-result:visible')).toHaveCount(2);
    await page.locator('[data-action=switch-side]').click();
    await expect(page.locator('.case-section .comparison-result.visible-side').last()).toBeVisible();
    await page.screenshot({ path: 'runtime/verification/style-feedback-mobile.png', fullPage: true });
    await page.locator('.phase-badge[data-screen=project-settings]').click();
    await expect(page.locator('#settings-project-purpose')).toHaveValue('선별 왕복 후에도 남아야 하는 미저장 메모');
    await expect(page.locator('#settings-case-name-0')).toHaveValue('이름을 바꾼 인물');
    await expect(page.locator('#settings-project-seed')).toHaveValue('18446744073709551615');
    await page.locator('#settings-project-seed').fill('99999');
    const updated = await saveStyleFeedbackForm(page, '#project-settings-form', 'PUT');
    assert.notEqual(updated.evaluationIdentifier, project.evaluationIdentifier);
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('.persistent-comparison img')).toHaveCount(4, { timeout: 10000 });
    assert.equal(await page.evaluate(() => String(currentPersistentComparison().plan.sampling.seed)), '18446744073709551615');
    await page.reload();
    await expect(page.locator('.persistent-comparison img')).toHaveCount(4, { timeout: 10000 });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-feedback-desktop.png', fullPage: true });
    const options = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-options`)).json();
    assert.equal(options.settings.seed, 99999);
    assert.equal(options.settings.artistMaximumCount, 1);
    const globalsAfter = (await (await context.request.get(`${baseUrl}/api/style-workspace`)).json()).globalSettings;
    assert.equal(globalsAfter.artistMaximumCount, 2);
    assert.deepEqual(errors, []);
    fs.writeFileSync('runtime/verification/style-feedback-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, inheritedCounts: true, independentProjectCounts: true, promptRenameWithoutRegeneration: true, largeSeedExact: true, oldImagesPreserved: true, componentDifferences: true, mobileCaseScroll: true, singleImage: true, widths: [320, 390, 768, 1280], errors }, null, 2));
    console.log('Style feedback Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleFeedback().catch(error => { console.error(error); process.exitCode = 1; });
