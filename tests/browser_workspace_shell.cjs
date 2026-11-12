const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');
const path = require('node:path');

const verificationBaseUrl = process.env.WORKSPACE_SHELL_TEST_URL || 'http://127.0.0.1:18388';
const verificationDirectory = path.resolve(__dirname, '..', 'runtime', 'verification');
const generalPrompt = 'workspace roundtrip, [SHELL_SCENE]';
const generalNegativePrompt = 'workspace negative prompt, low quality';
const projectDraftPurpose = '일반 생성으로 이동해도 유지할 스타일 초안';
const projectDraftPrompt = 'unsaved style prompt, {artist}';

/** 실제 서버와 분리된 localhost Fixture에서만 검증하도록 제한합니다. */
function requireIsolatedVerificationServer() {
  const verificationUrl = new URL(verificationBaseUrl);
  assert.equal(verificationUrl.origin, 'http://127.0.0.1:18388');
  assert.equal(verificationUrl.pathname, '/');
}

/** 운영 데이터 없이 프로젝트와 태그 선택을 검증할 최소 Fixture를 만듭니다. */
async function prepareWorkspaceFixtures(browserContext) {
  const projectResponse = await browserContext.request.post(`${verificationBaseUrl}/api/style-projects`, {
    data: {
      operationIdentifier: `workspace-shell-${Date.now()}`,
      settings: {
        name: 'Workspace shell 검증',
        purpose: '저장된 프로젝트 메모',
        pipelineIdentifier: 'anima',
        promptCases: [{ identifier: 'shell-case', name: '인물', prompt: 'portrait, {artist}', negativePrompt: '' }],
        negativePrompt: 'low quality',
        width: 576,
        height: 864,
        steps: 12,
        cfg: 1,
        componentPolicies: {},
      },
    },
  });
  assert.equal(projectResponse.status(), 201, await projectResponse.text());
  const project = await projectResponse.json();
  const tagsResponse = await browserContext.request.get(`${verificationBaseUrl}/api/tags`);
  const tags = await tagsResponse.json();
  let group = tags.groups.find(candidate => candidate.tag_key === 'SHELL_SCENE');
  if (!group) {
    const groupResponse = await browserContext.request.post(`${verificationBaseUrl}/api/tags/groups`, {
      data: { name: 'Workspace shell 태그', tag_key: 'SHELL_SCENE' },
    });
    assert.equal(groupResponse.status(), 201, await groupResponse.text());
    group = await groupResponse.json();
  }
  const existingTag = tags.entries.find(candidate => candidate.group_id === group.group_id);
  if (existingTag) return { project, tag: existingTag };
  const tagResponse = await browserContext.request.post(`${verificationBaseUrl}/api/tags/entries`, {
    data: { group_id: group.group_id, name: '검증용 장면', content: 'window, daylight', weight: 1 },
  });
  assert.equal(tagResponse.status(), 201, await tagResponse.text());
  return { project, tag: await tagResponse.json() };
}

/** 스타일 직접 주소에서도 일반 생성의 공통 로그인 화면으로 인증합니다. */
async function signInThroughSharedLogin(page) {
  await expect(page).toHaveURL(destination => destination.pathname === '/');
  await expect(page.locator('#login-screen')).toBeVisible();
  await expect(page.locator('#login-form')).toHaveCount(1);
  await expect(page.locator('#preview-login-form')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('#login-screen')).toBeVisible();
  await page.locator('#login-password').fill('test');
  await page.locator('#login-form button[type=submit]').click();
  await expect(page).toHaveURL(/\/style(?:[?#]|$)/);
  await expect(page.locator('#preview-application')).toBeVisible();
}

/** 실제 computed style과 위치에서 두 작업 공간의 공통 Shell 모양을 읽습니다. */
async function readWorkspaceShellAppearance(page, workspaceName) {
  return page.evaluate(workspace => {
    const sidebar = document.querySelector(workspace === 'general' ? '#application > .sidebar' : '#style-workspace-sidebar');
    const topbar = document.querySelector(workspace === 'general' ? '.topbar' : '.workspace-topbar');
    const workspaceSwitch = document.querySelector('.workspace-switch');
    const currentWorkspace = workspaceSwitch.querySelector('[aria-current=page]');
    const workspaceLink = workspaceSwitch.querySelector('a:not([aria-current=page])');
    const brandMark = sidebar.querySelector(workspace === 'general' ? '.brand-mark' : '.workspace-brand-mark');
    const sidebarStyle = getComputedStyle(sidebar);
    const topbarRectangle = topbar.getBoundingClientRect();
    const currentStyle = getComputedStyle(currentWorkspace);
    const linkStyle = getComputedStyle(workspaceLink);
    const brandStyle = getComputedStyle(brandMark);
    return {
      sidebarWidth: sidebar.getBoundingClientRect().width,
      sidebarBackground: sidebarStyle.backgroundColor,
      sidebarBorder: sidebarStyle.borderRightColor,
      topbarLeft: topbarRectangle.left,
      titleFont: getComputedStyle(topbar.querySelector('h1')).fontSize,
      brandWidth: brandMark.getBoundingClientRect().width,
      brandHeight: brandMark.getBoundingClientRect().height,
      brandBackground: brandStyle.backgroundImage,
      brandText: brandMark.textContent.trim(),
      toggleFont: currentStyle.fontFamily,
      toggleFontSize: currentStyle.fontSize,
      togglePadding: currentStyle.padding,
      toggleRadius: currentStyle.borderRadius,
      toggleBackground: currentStyle.backgroundColor,
      toggleLinkPadding: linkStyle.padding,
      toggleLinkRadius: linkStyle.borderRadius,
      toggleLinkColor: linkStyle.color,
      bodyBackground: getComputedStyle(document.documentElement).backgroundColor,
    };
  }, workspaceName);
}

/** 일반 생성의 Prompt·Negative·LoRA·태그·기본 옵션을 실제 Form으로 작성합니다. */
async function fillGeneralGenerationDraft(page, selectedTagIdentifier) {
  await page.locator('#generate-anima-prompt').fill(generalPrompt);
  await page.locator('#generate-negative').fill(generalNegativePrompt);
  await page.locator('#generate-count').fill('3');
  await page.locator('#anima-steps').fill('17');
  await page.locator('#available-loras').selectOption('example.safetensors');
  await page.locator('#add-lora-button').click();
  await page.locator('#selected-loras [data-lora-field=strength]').fill('0.65');
  await page.locator('#selected-loras [data-lora-field=clip_strength]').fill('0.2');
  await page.locator('#expand-generate-tag-groups-button').click();
  await page.locator(`[data-select-tag="${selectedTagIdentifier}"]`).check();
}

/** 작업 공간을 왕복한 뒤 일반 생성의 편집 내용과 선택 상태를 확인합니다. */
async function expectGeneralGenerationDraft(page, selectedTagIdentifier) {
  await expect(page.locator('#generate-anima-prompt')).toHaveValue(generalPrompt);
  await expect(page.locator('#generate-negative')).toHaveValue(generalNegativePrompt);
  await expect(page.locator('#generate-count')).toHaveValue('3');
  await expect(page.locator('#anima-steps')).toHaveValue('17');
  await expect(page.locator('#selected-loras .selected-lora')).toHaveCount(1);
  await expect(page.locator('#selected-loras [data-lora-field=strength]')).toHaveValue('0.65');
  await expect(page.locator('#selected-loras [data-lora-field=clip_strength]')).toHaveValue('0.2');
  await expect(page.locator(`[data-select-tag="${selectedTagIdentifier}"]`)).toBeChecked();
}

/** 서버에 저장하지 않은 스타일 설정 초안과 선택한 프로젝트를 확인합니다. */
async function expectStyleSettingsDraft(page, projectIdentifier) {
  await expect(page.locator('#active-project-picker')).toHaveValue(projectIdentifier);
  await expect(page.locator('#settings-project-purpose')).toHaveValue(projectDraftPurpose);
  await expect(page.locator('#settings-case-prompt-0')).toHaveValue(projectDraftPrompt);
}

/** 작은 화면에서도 공통 Toggle과 콘텐츠가 가로로 넘치지 않는지 확인합니다. */
async function verifyWorkspaceViewport(page, workspaceName, viewportWidth) {
  await expect(page.locator('.workspace-switch')).toBeVisible();
  await expect(page.locator('.workspace-switch [aria-current=page]')).toHaveText(workspaceName === 'general' ? '일반 생성' : '스타일 구성');
  const dimensions = await page.evaluate(() => {
    const toggleRectangle = document.querySelector('.workspace-switch').getBoundingClientRect();
    return {
      viewportWidth: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      toggleLeft: toggleRectangle.left,
      toggleRight: toggleRectangle.right,
    };
  });
  assert.ok(dimensions.documentWidth <= dimensions.viewportWidth, JSON.stringify({ workspaceName, ...dimensions }));
  assert.ok(dimensions.toggleLeft >= 0 && dimensions.toggleRight <= dimensions.viewportWidth, JSON.stringify(dimensions));
  if ([390, 1280].includes(viewportWidth)) {
    await page.screenshot({ path: path.join(verificationDirectory, `workspace-shell-${workspaceName}-${viewportWidth}.png`), fullPage: true });
  }
}

/** 실제 API 응답을 받은 뒤 Browser에 전달하는 시점만 제어합니다. */
function createResponseGate() {
  let releaseResponse;
  let markResponseCaptured;
  const responseReleased = new Promise(resolve => { releaseResponse = resolve; });
  const responseCaptured = new Promise(resolve => { markResponseCaptured = resolve; });
  return { responseReleased, responseCaptured, releaseResponse, markResponseCaptured };
}

/** 별도 Context의 프로젝트에서 새로고침과 설정 저장의 동시 실행 차단을 검증합니다. */
async function verifyWorkspaceRefreshExclusion(browser) {
  const browserContext = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
  const refreshResponseGate = createResponseGate();
  const saveResponseGate = createResponseGate();
  const browserErrors = [];
  const mutationRequests = [];
  let workspaceReadCount = 0;
  try {
    const loginResponse = await browserContext.request.post(`${verificationBaseUrl}/api/login`, { data: { password: 'test' } });
    assert.equal(loginResponse.status(), 200);
    const { project } = await prepareWorkspaceFixtures(browserContext);
    const projectEndpoint = `${verificationBaseUrl}/api/style-projects/${project.identifier}`;
    const page = await browserContext.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => {
      const requestPath = new URL(request.url()).pathname;
      if (requestPath === '/api/style-workspace' && request.method() === 'GET') workspaceReadCount += 1;
      if (requestPath.startsWith('/api/') && request.method() !== 'GET') mutationRequests.push(`${request.method()} ${requestPath}`);
    });
    await page.goto(`${verificationBaseUrl}/style`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('#preview-sidebar [data-screen=project-settings]').click();
    await page.locator('#settings-project-purpose').fill(projectDraftPurpose);
    await page.locator('#settings-case-prompt-0').fill(projectDraftPrompt);

    await page.route('**/api/style-workspace', async route => {
      const workspaceResponse = await route.fetch();
      refreshResponseGate.markResponseCaptured();
      await refreshResponseGate.responseReleased;
      await route.fulfill({ response: workspaceResponse });
    }, { times: 1 });
    const readsBeforeRefresh = workspaceReadCount;
    await page.locator('#workspace-refresh-button').click();
    await refreshResponseGate.responseCaptured;
    await expect(page.locator('#workspace-refresh-button')).toBeDisabled();
    for (const containerIdentifier of ['#preview-content', '#project-context', '#preview-sidebar', '#preview-mobile-navigation']) {
      await expect(page.locator(containerIdentifier)).toHaveAttribute('inert', '');
    }
    await page.evaluate(() => savePersistentStyleSettings(document.querySelector('#project-settings-form')));
    assert.deepEqual(mutationRequests, []);
    assert.equal(workspaceReadCount, readsBeforeRefresh + 1);
    refreshResponseGate.releaseResponse();
    await expect(page.locator('#workspace-refresh-button')).toBeEnabled();
    for (const containerIdentifier of ['#preview-content', '#project-context', '#preview-sidebar', '#preview-mobile-navigation']) {
      await expect(page.locator(containerIdentifier)).not.toHaveAttribute('inert', '');
    }
    await expectStyleSettingsDraft(page, project.identifier);

    await page.route(projectEndpoint, async route => {
      const savedProjectResponse = await route.fetch();
      saveResponseGate.markResponseCaptured();
      await saveResponseGate.responseReleased;
      await route.fulfill({ response: savedProjectResponse });
    }, { times: 1 });
    await page.locator('#project-settings-form button[type=submit]').click();
    await saveResponseGate.responseCaptured;
    await expect(page.locator('#workspace-refresh-button')).toBeDisabled();
    const readsDuringSave = workspaceReadCount;
    await page.evaluate(() => refreshStyleWorkspace());
    assert.equal(workspaceReadCount, readsDuringSave);
    saveResponseGate.releaseResponse();
    await expect(page.locator('#workspace-refresh-button')).toBeEnabled();
    await expect(page.locator('#style-settings-save-status')).toHaveText('저장됨');
    await expectStyleSettingsDraft(page, project.identifier);
    assert.deepEqual(mutationRequests, [`PUT /api/style-projects/${project.identifier}`]);
    const savedProject = await (await browserContext.request.get(projectEndpoint)).json();
    assert.equal(savedProject.settings.purpose, projectDraftPurpose);
    assert.equal(savedProject.settings.promptCases[0].prompt, projectDraftPrompt);
    assert.deepEqual(browserErrors, []);
    return { refreshBlocksSave: true, saveBlocksRefresh: true, refreshRestoresInteractivity: true, browserErrors };
  } finally {
    refreshResponseGate.releaseResponse();
    saveResponseGate.releaseResponse();
    await browserContext.close();
  }
}

/** 공통 로그인·Shell·왕복 초안·모바일 화면을 GPU 요청 없이 검증합니다. */
async function verifySharedWorkspaceShell() {
  requireIsolatedVerificationServer();
  filesystem.mkdirSync(verificationDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  const browserMutationRequests = [];
  const loginRequests = [];
  const logoutRequests = [];
  try {
    const browserContext = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
    const page = await browserContext.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => {
      const requestPath = new URL(request.url()).pathname;
      if (request.method() === 'GET' || !requestPath.startsWith('/api/')) return;
      if (requestPath === '/api/login') loginRequests.push(requestPath);
      else if (requestPath === '/api/logout') logoutRequests.push(requestPath);
      else browserMutationRequests.push(`${request.method()} ${requestPath}`);
    });

    await page.goto(`${verificationBaseUrl}/style`);
    await signInThroughSharedLogin(page);
    assert.equal(loginRequests.length, 1);
    const { project, tag } = await prepareWorkspaceFixtures(browserContext);
    await page.reload();
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('#preview-sidebar [data-screen=project-settings]').click();
    await page.locator('#settings-project-purpose').fill(projectDraftPurpose);
    await page.locator('#settings-case-prompt-0').fill(projectDraftPrompt);
    await expectStyleSettingsDraft(page, project.identifier);
    const styleAppearance = await readWorkspaceShellAppearance(page, 'style');

    await page.locator('#general-workspace-link').click();
    await expect(page.locator('#application')).toBeVisible();
    await expect(page.locator('#login-screen')).toBeHidden();
    const generalAppearance = await readWorkspaceShellAppearance(page, 'general');
    assert.deepEqual(styleAppearance, generalAppearance);
    assert.equal(generalAppearance.sidebarWidth, 236);
    assert.equal(generalAppearance.brandText, 'CH');
    await fillGeneralGenerationDraft(page, tag.tag_id);

    for (const viewportWidth of [1280, 390, 320]) {
      await page.setViewportSize({ width: viewportWidth, height: 1000 });
      await expectGeneralGenerationDraft(page, tag.tag_id);
      await verifyWorkspaceViewport(page, 'general', viewportWidth);
      await page.locator('[data-workspace-style]').click();
      await expect(page.locator('#preview-application')).toBeVisible();
      await expectStyleSettingsDraft(page, project.identifier);
      await verifyWorkspaceViewport(page, 'style', viewportWidth);
      await page.locator('#workspace-refresh-button').click();
      await expectStyleSettingsDraft(page, project.identifier);
      await page.locator('#general-workspace-link').click();
      await expect(page.locator('#application')).toBeVisible();
      await expectGeneralGenerationDraft(page, tag.tag_id);
    }
    assert.equal(loginRequests.length, 1, 'Workspace toggle은 추가 로그인을 요구하지 않아야 합니다.');
    assert.equal(browserContext.pages().length, 1);
    const storedProject = await (await browserContext.request.get(`${verificationBaseUrl}/api/style-projects/${project.identifier}`)).json();
    assert.equal(storedProject.settings.purpose, '저장된 프로젝트 메모');
    assert.equal(storedProject.settings.promptCases[0].prompt, 'portrait, {artist}');
    const storedJobs = await (await browserContext.request.get(`${verificationBaseUrl}/api/jobs`)).json();
    assert.equal(storedJobs.total, 0);

    await page.locator('[data-workspace-style]').click();
    await expect(page.locator('#preview-application')).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 1000 });
    let initialWorkspaceUnauthorizedCount = 0;
    await page.route('**/api/style-workspace', async route => {
      initialWorkspaceUnauthorizedCount += 1;
      await browserContext.clearCookies();
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: '로그인이 필요합니다.' }) });
    }, { times: 1 });
    await page.reload();
    await signInThroughSharedLogin(page);
    assert.equal(initialWorkspaceUnauthorizedCount, 1);
    await expectStyleSettingsDraft(page, project.identifier);
    assert.equal(loginRequests.length, 2);

    await page.locator('#workspace-logout-button').click();
    await expect(page.locator('#login-screen')).toBeVisible();
    assert.equal(new URL(page.url()).pathname, '/');
    assert.equal(logoutRequests.length, 1);
    assert.deepEqual(await (await browserContext.request.get(`${verificationBaseUrl}/api/session`)).json(), { authenticated: false });
    await page.goto(`${verificationBaseUrl}/style`);
    await signInThroughSharedLogin(page);
    await expectStyleSettingsDraft(page, project.identifier);
    assert.equal(loginRequests.length, 3);
    await browserContext.clearCookies();
    const expiredRefreshResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/style-workspace');
    await page.locator('#workspace-refresh-button').click();
    assert.equal((await expiredRefreshResponse).status(), 401);
    await signInThroughSharedLogin(page);
    await expectStyleSettingsDraft(page, project.identifier);
    assert.equal(loginRequests.length, 4);
    await browserContext.clearCookies();
    const expiredLogoutResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/logout');
    await page.locator('#workspace-logout-button').click();
    assert.equal((await expiredLogoutResponse).status(), 401);
    await signInThroughSharedLogin(page);
    await expectStyleSettingsDraft(page, project.identifier);
    assert.equal(logoutRequests.length, 2);
    assert.equal(loginRequests.length, 5);
    assert.deepEqual(browserMutationRequests, []);
    assert.deepEqual(browserErrors, []);
    const refreshExclusion = await verifyWorkspaceRefreshExclusion(browser);

    filesystem.writeFileSync(path.join(verificationDirectory, 'workspace-shell-browser-results.json'), JSON.stringify({
      sharedLogin: true,
      directStyleReturn: true,
      shellAppearance: generalAppearance,
      generalDraftPreserved: true,
      styleDraftPreserved: true,
      refreshPreservesDraft: true,
      styleLogout: true,
      expiredSessionRecovery: true,
      initialWorkspaceUnauthorizedDraftRecovery: true,
      expiredSessionLogoutRecovery: true,
      loginReloadReturn: true,
      viewportWidths: [1280, 390, 320],
      refreshExclusion,
      browserMutationRequests,
      browserErrors,
    }, null, 2));
    console.log('Passed: shared login, matching Shell, roundtrip drafts, refresh, mobile layout, logout and no generation requests.');
  } finally {
    await browser.close();
  }
}

verifySharedWorkspaceShell().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
