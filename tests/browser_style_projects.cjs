const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const verificationBaseUrl = process.env.STYLE_PROJECT_TEST_URL || 'http://127.0.0.1:18388';
const browserErrors = [];
const generationRequests = [];

/** 검증용 서버에만 로그인하며 실제 서버 비밀번호는 사용하지 않습니다. */
async function openStyleWorkspace(context, width = 1280) {
  const page = await context.newPage();
  page.on('pageerror', error => browserErrors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/(batches|generate)|\/(candidate-generation-plans|generation-plans|random-generation-plans|evolution-plans|votes)(\/|\?|$)/.test(request.url())) generationRequests.push(request.url());
  });
  await page.setViewportSize({ width, height: 1000 });
  await page.goto(`${verificationBaseUrl}/style`);
  await page.locator('#preview-password').fill('test');
  await page.locator('#preview-login-form button[type=submit]').click();
  await expect(page.locator('#preview-application')).toBeVisible();
  await expect(page.locator('#preview-content h1')).toHaveText('프로젝트');
  await expect(page.locator('#preview-mobile-navigation button')).toHaveCount(5);
  return page;
}

/** 실제 저장 완료 응답을 기다려 연타나 네트워크 타이밍과 독립적으로 확인합니다. */
async function saveProjectForm(page, createProject = false) {
  const savedResponse = page.waitForResponse(response => response.url().includes('/api/style-projects') && response.request().method() === (createProject ? 'POST' : 'PUT'));
  await page.locator('form.settings-form button[type=submit]').click();
  const response = await savedResponse;
  assert.equal(response.status(), createProject ? 201 : 200, await response.text());
  await expect(page.locator('form.settings-form button[type=submit]')).toBeEnabled();
  return response.json();
}

/** 여러 Prompt·성분 범위가 있는 프로젝트를 실제 Form으로 저장합니다. */
async function createProject(page, projectName, positivePrompt) {
  await page.locator('#preview-sidebar [data-screen=projects]').click();
  await page.locator('#preview-content [data-screen=create]').first().click();
  await page.locator('#settings-project-name').fill(projectName);
  await page.locator('#settings-project-purpose').fill('Browser 검증용 프로젝트');
  await page.locator('#settings-case-prompt-0').fill(positivePrompt);
  await page.locator('[data-settings-action=add-prompt]').click();
  await page.locator('#settings-case-prompt-1').fill('garden, flowers, {artist}');
  await page.locator('#settings-negative-prompt').fill('low quality');
  await page.locator('#settings-project-aspectRatio').selectOption('custom');
  await page.locator('#settings-project-width').fill('640');
  await page.locator('#settings-project-height').fill('960');
  await page.locator('#settings-project-steps').fill('7');
  await page.locator('[data-settings-component="artist:alpha"][data-settings-policy=enabled]').check();
  await page.locator('[data-settings-component="artist:alpha"][data-settings-policy=minimumStrength]').fill('0.4');
  await page.locator('[data-settings-component="artist:alpha"][data-settings-policy=maximumStrength]').fill('0.4');
  return saveProjectForm(page, true);
}

/** Desktop·Mobile·새 Session에서 저장·초안·충돌·일반 생성 입력 보존을 확인합니다. */
async function verifyPersistentStyleProjects() {
  if (!verificationBaseUrl.includes('127.0.0.1:18388')) throw new Error('별도 검증 서버에서만 실행하세요.');
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  try {
    const desktopContext = await browser.newContext();
    const desktopPage = await openStyleWorkspace(desktopContext);
    await expect(desktopPage.locator('#preview-content img')).toHaveCount(0);
    await desktopPage.locator('#preview-sidebar [data-screen=global-settings]').click();
    await desktopPage.locator('#artist-bulk-input').fill('artist:alpha\n@beta\n123');
    await desktopPage.locator('#artist-bulk-register-button').click();
    await expect(desktopPage.locator('#artist-bulk-registration-result')).toContainText('서버에 등록');
    await expect(desktopPage.locator('#artist-bulk-input')).toHaveValue('123');
    await desktopPage.locator('[data-settings-field=artistMinimumStrength]').fill('0.7');
    await desktopPage.locator('[data-settings-field=artistMaximumStrength]').fill('0.7');
    const globalSaveResponse = desktopPage.waitForResponse(response => response.url().endsWith('/api/style-settings') && response.request().method() === 'PUT');
    await desktopPage.locator('#global-settings-form button[type=submit]').click();
    assert.equal((await globalSaveResponse).status(), 200);
    await expect(desktopPage.locator('#global-settings-form button[type=submit]')).toBeEnabled();
    const firstProject = await createProject(desktopPage, `검증 A ${Date.now()}`, 'portrait, window, {artist}');
    assert.equal(firstProject.candidateCount, 0);
    assert.equal(firstProject.settings.promptCases.length, 2);
    assert.equal(firstProject.settings.width, 640);
    assert.equal(firstProject.settings.componentPolicies['artist:alpha'].maximumStrength, 0.4);
    assert.equal(firstProject.settings.componentPolicies['artist:beta'].minimumStrength, 0.7);
    assert.equal(firstProject.settings.defaultsRevision, 3);
    const caseIdentifiers = firstProject.settings.promptCases.map(promptCase => promptCase.identifier);
    await desktopPage.locator('#settings-project-name').fill(`${firstProject.name} 변경`);
    const renamedProject = await saveProjectForm(desktopPage);
    assert.equal(renamedProject.evaluationIdentifier, firstProject.evaluationIdentifier);
    assert.ok(renamedProject.storageBinding.project_folder.startsWith(renamedProject.name));
    await desktopPage.locator('#settings-project-purpose').fill('A의 미저장 초안');
    const secondProject = await createProject(desktopPage, `검증 B ${Date.now()}`, 'landscape, {artist}');
    await desktopPage.locator('#preview-sidebar [data-screen=projects]').click();
    await expect(desktopPage.locator('[data-project-card]')).toHaveCount(2);
    await expect(desktopPage.locator(`[data-project-card="${secondProject.identifier}"]`)).toHaveAttribute('aria-current', 'true');
    await desktopPage.locator(`[data-action=open-project][data-project="${firstProject.identifier}"]`).click();
    await expect(desktopPage.locator('#preview-content h1')).toHaveText('이미지 생성');
    await expect(desktopPage.locator('#active-project-picker')).toHaveValue(firstProject.identifier);
    await desktopPage.locator('.phase-badge[data-screen=project-settings]').click();
    await expect(desktopPage.locator('#settings-project-purpose')).toHaveValue('A의 미저장 초안');
    await desktopPage.reload();
    await expect(desktopPage.locator('#settings-project-purpose')).toHaveValue('A의 미저장 초안');
    await expect(desktopPage.locator('#settings-project-width')).toHaveValue('640');
    const mobileContext = await browser.newContext({ isMobile: true, hasTouch: true });
    const mobilePage = await openStyleWorkspace(mobileContext, 390);
    await mobilePage.locator(`[data-action=open-project][data-project="${firstProject.identifier}"]`).click();
    await expect(mobilePage.locator('#active-project-picker')).toHaveValue(firstProject.identifier);
    await mobilePage.locator('.phase-badge[data-screen=project-settings]').click();
    await expect(mobilePage.locator('#settings-project-purpose')).toHaveValue('Browser 검증용 프로젝트');
    await mobilePage.locator('#settings-project-purpose').fill('다른 기기에서 저장');
    await mobilePage.locator('#preview-mobile-navigation [data-screen=projects]').click();
    await expect(mobilePage.locator('#preview-mobile-navigation [data-screen=projects]')).toHaveClass('active');
    await expect(mobilePage.locator('[data-project-card]')).toHaveCount(2);
    await expect(mobilePage.locator(`[data-project-card="${firstProject.identifier}"] .project-current-indicator`)).toHaveText('현재 프로젝트');
    await mobilePage.locator(`[data-action=open-project][data-project="${secondProject.identifier}"]`).click();
    await expect(mobilePage.locator('#active-project-picker')).toHaveValue(secondProject.identifier);
    await mobilePage.locator('#preview-mobile-navigation [data-screen=projects]').click();
    await mobilePage.locator(`[data-action=open-project][data-project="${firstProject.identifier}"]`).click();
    await mobilePage.locator('.phase-badge[data-screen=project-settings]').click();
    await expect(mobilePage.locator('#settings-project-purpose')).toHaveValue('다른 기기에서 저장');
    const mobileProject = await saveProjectForm(mobilePage);
    assert.deepEqual(mobileProject.settings.promptCases.map(promptCase => promptCase.identifier), caseIdentifiers);
    const conflictResponse = desktopPage.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/api/style-projects/'));
    await desktopPage.locator('#project-settings-form button[type=submit]').click();
    assert.equal((await conflictResponse).status(), 409);
    await expect(desktopPage.locator('#settings-form-error')).toContainText('다른 탭');
    await expect(desktopPage.locator('#settings-project-purpose')).toHaveValue('A의 미저장 초안');
    await desktopPage.locator('[data-persistent-action=reload]').click();
    await expect(desktopPage.locator('#preview-toast')).toContainText('다시 불러왔습니다');
    await desktopPage.locator('[data-settings-action=reset-draft]').click();
    await expect(desktopPage.locator('#settings-project-purpose')).toHaveValue('다른 기기에서 저장');
    await desktopPage.locator('#settings-case-prompt-0').fill('new prompt, {artist}');
    const changedProject = await saveProjectForm(desktopPage);
    assert.notEqual(changedProject.evaluationIdentifier, firstProject.evaluationIdentifier);
    for (const width of [320, 390, 768, 1280]) {
      await mobilePage.setViewportSize({ width, height: 1000 });
      await expect(mobilePage.locator('#project-settings-form')).toBeVisible();
      const dimensions = await mobilePage.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await mobilePage.setViewportSize({ width: 390, height: 844 });
    await mobilePage.screenshot({ path: 'runtime/verification/style-projects-mobile.png', fullPage: true });
    await desktopPage.screenshot({ path: 'runtime/verification/style-projects-desktop.png', fullPage: true });
    for (const width of [320, 390, 768, 1280]) {
      await mobilePage.setViewportSize({ width, height: 1000 });
      const navigationSelector = width > 700 ? '#preview-sidebar' : '#preview-mobile-navigation';
      await mobilePage.locator(`${navigationSelector} [data-screen=projects]`).click();
      await expect(mobilePage.locator('#preview-content h1')).toHaveText('프로젝트');
      await expect(mobilePage.locator('[data-project-card]')).toHaveCount(2);
      assert.ok(await mobilePage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      if (width === 390 || width === 1280) await mobilePage.screenshot({ path: `runtime/verification/style-project-navigation-${width}.png`, fullPage: true });
      if (width === 390) {
        for (const screen of ['generation', 'compare', 'evolution', 'candidates']) {
          await mobilePage.locator(`#preview-mobile-navigation [data-screen="${screen}"]`).click();
          await expect(mobilePage.locator(`#preview-mobile-navigation [data-screen="${screen}"]`)).toHaveClass('active');
          await mobilePage.locator('#preview-mobile-navigation [data-screen=projects]').click();
          await expect(mobilePage.locator(`[data-project-card="${firstProject.identifier}"]`)).toHaveAttribute('aria-current', 'true');
        }
      }
    }
    await desktopPage.locator('#preview-sidebar [data-screen=compare]').click();
    await expect(desktopPage.locator('#preview-content')).toContainText('아직 생성한 이미지가 없습니다');
    await expect(desktopPage.locator('#preview-content img')).toHaveCount(0);
    await desktopPage.goto(`${verificationBaseUrl}/`);
    await desktopPage.locator('#generate-anima-prompt').fill('일반 생성의 미저장 입력');
    await desktopPage.locator('[data-workspace-style]').click();
    await expect(desktopPage).toHaveURL(/\/style/);
    await desktopPage.locator('#general-workspace-link').click();
    await expect(desktopPage.locator('#generate-anima-prompt')).toHaveValue('일반 생성의 미저장 입력');
    assert.equal(desktopContext.pages().length, 1);
    const projectsResponse = await desktopContext.request.get(`${verificationBaseUrl}/api/style-projects`);
    assert.ok((await projectsResponse.json()).projects.some(project => project.identifier === secondProject.identifier));
    assert.equal((await (await desktopContext.request.get(`${verificationBaseUrl}/api/jobs`)).json()).total, 0);
    await desktopPage.goto(`${verificationBaseUrl}/style-preview`);
    await expect(desktopPage.locator('#preview-content')).toContainText('사용해 볼 예시 프로젝트');
    await desktopPage.locator('#preview-sidebar [data-screen=compare]').click();
    await expect(desktopPage.locator('.vote-buttons')).toBeVisible();
    assert.deepEqual(browserErrors, []);
    assert.deepEqual(generationRequests, []);
    fs.writeFileSync('runtime/verification/style-projects-browser-results.json', JSON.stringify({
      projectIdentifiers: [firstProject.identifier, secondProject.identifier],
      caseIdentifiers, widths: [320, 390, 768, 1280],
      projectTabRestored: true, explicitCardSelection: true, selectedProjectIndicator: true, fiveTabNavigation: true,
      crossDevicePersistence: true, unsavedDraftPreservation: true, revisionConflict: true,
      renameBinding: true, evaluationSnapshots: true, generalInputPreserved: true,
      previewStillAvailable: true, browserErrors, generationRequests,
    }, null, 2));
    console.log('Style project Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyPersistentStyleProjects().catch(error => { console.error(error); process.exitCode = 1; });
