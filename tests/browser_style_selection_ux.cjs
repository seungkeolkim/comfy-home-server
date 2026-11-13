const { chromium } = require('playwright');
const { expect: browserExpect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

const expect = browserExpect.configure({ timeout: 15000 });
const baseUrl = 'http://127.0.0.1:18388';

/** 격리 서버에서 실제 임시 PNG를 만들어 다중 Prompt 선별 자료를 준비합니다. */
async function prepareSelectionProject(context, name, combinationCount) {
  const response = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
    operationIdentifier: `selection-ux-project-${crypto.randomUUID()}`,
    settings: {
      name, width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
      artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
      promptCases: ['낮 거리', '실내 서재'].map((name, index) => ({ identifier: `selection-case-${index}`, name, prompt: `safe scene ${index}` })),
      componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 1.9 } },
    },
  } });
  assert.equal(response.status(), 201, await response.text());
  const project = await response.json();
  const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const planResponse = await context.request.post(`${endpoint}/random-generation-plans`, { data: {
    expectedRevision: project.revision, operationIdentifier: `selection-ux-plan-${crypto.randomUUID()}`, combinationCount,
  } });
  assert.equal(planResponse.status(), 201, await planResponse.text());
  const plan = await planResponse.json();
  const submitResponse = await context.request.post(`${endpoint}/generation-plans/${plan.planIdentifier}/submit`, { data: {
    operationIdentifier: `selection-ux-submit-${crypto.randomUUID()}`, retryFailedOnly: false,
  } });
  assert.equal(submitResponse.status(), 200, await submitResponse.text());
  await expect.poll(async () => {
    const results = await (await context.request.get(`${endpoint}/generation-results`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }).toBe(combinationCount * 2);
  return project;
}

/** 현재 Browser 소유의 Match와 Revision을 서버에서 읽습니다. */
async function readSelection(context, project, clientIdentifier) {
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier, clientIdentifier });
  const response = await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/selection?${parameters}`);
  assert.equal(response.status(), 200, await response.text());
  return response.json();
}

/** 준비 과정의 미평가 후보를 평가해 일반 리그의 Elo 피드백을 관찰할 수 있게 합니다. */
async function finishInitialSelection(context, project, clientIdentifier) {
  for (let comparisonIndex = 0; comparisonIndex < 100; comparisonIndex += 1) {
    const selection = await readSelection(context, project, clientIdentifier);
    if (selection.rankings.every(candidate => candidate.rated) && selection.match?.kind === 'league' && !selection.match.metadata.fresh) return;
    assert.ok(selection.match);
    const response = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/votes`, { data: {
      evaluationIdentifier: project.evaluationIdentifier, clientIdentifier, operationIdentifier: crypto.randomUUID(),
      expectedRevision: selection.revision, matchToken: selection.match.token,
      choice: selection.match.kind === 'tie' ? 'similar' : 'a',
    } });
    assert.equal(response.status(), 200, await response.text());
  }
  throw new Error('Initial selection did not settle');
}

/** 모든 Prompt의 이미지가 준비되고 결과 공개가 끝난 다음 조작을 시작합니다. */
async function waitForSelectionReady(page) {
  await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
  await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', '');
}

/** 표를 보낼 수 없는 Focus·Keyboard 상황에서 서버 요청이 생기지 않는지 확인합니다. */
async function verifyKeyboardGuards(page, voteRequests) {
  const originalCount = voteRequests.length;
  await page.locator('[data-style-comparison-action=rename-prompt]').first().click();
  await page.locator('#style-prompt-display-name').focus();
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('Backspace');
  await page.keyboard.press('Escape');
  await page.locator('.comparison-result .image-button').first().click();
  await expect(page.locator('#illustration-dialog')).toBeVisible();
  await page.locator('#illustration-dialog').evaluate(dialog => { dialog.tabIndex = -1; dialog.focus(); });
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Backspace');
  assert.equal(voteRequests.length, originalCount);
  await page.keyboard.press('Escape');
  await page.evaluate(() => document.activeElement?.blur());
  await page.evaluate(() => {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', code: 'ArrowLeft', bubbles: true, repeat: true }));
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', code: 'ArrowRight', bubbles: true, isComposing: true }));
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', code: 'ArrowLeft', bubbles: true, ctrlKey: true }));
  });
  await page.keyboard.press('Shift+ArrowRight');
  assert.equal(voteRequests.length, originalCount);
}

/** 투표 응답이 지연돼도 화면 이동은 허용하되 같은 프로젝트의 동시 변경을 막습니다. */
async function verifyPendingVoteMutationGuards(page, project, otherProject) {
  await page.setViewportSize({ width: 1280, height: 1000 });
  if (await page.locator('[data-action=toggle-blind]').getAttribute('aria-pressed') === 'true') {
    await page.locator('[data-action=toggle-blind]').click();
    await waitForSelectionReady(page);
  }
  const projectEndpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const voteEndpoint = `${projectEndpoint}/votes`;
  const otherMutationRequests = [];
  /** 현재 프로젝트의 투표 이외 변경 요청만 집계합니다. */
  function recordOtherMutation(request) {
    if (request.method() === 'POST' && request.url().startsWith(projectEndpoint) && request.url() !== voteEndpoint) otherMutationRequests.push(request.url());
  }
  page.on('request', recordOtherMutation);
  let releaseVoteRequest;
  let markVoteIntercepted;
  const voteRelease = new Promise(resolve => { releaseVoteRequest = resolve; });
  const voteIntercepted = new Promise(resolve => { markVoteIntercepted = resolve; });
  await page.route(voteEndpoint, async route => {
    markVoteIntercepted();
    await voteRelease;
    await route.continue();
  }, { times: 1 });
  try {
    await page.locator('[data-style-voting-choice=a]').click();
    await voteIntercepted;
    await page.locator('#preview-sidebar [data-screen=generation]').click();
    await page.locator('[data-generation-action=generate-random]').click();
    await expect(page.locator('#style-generation-confirmation-dialog')).not.toBeVisible();
    await expect(page.locator('.toast')).toContainText('선택 결과를 처리하고 있습니다.');

    await page.locator('#preview-sidebar [data-screen=candidates]').click();
    await page.locator('.style-card-actions [data-style-candidate-action=rating]').first().click();
    await expect(page.locator('#component-dialog')).not.toBeVisible();
    await page.locator('.style-card-actions [data-style-candidate-action=delete]').first().click();
    await expect(page.locator('#component-dialog')).not.toBeVisible();
    assert.deepEqual(otherMutationRequests, []);

    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await page.locator('.style-card-actions [data-style-candidate-action=rating]').first().click();
    await expect(page.locator('#component-dialog')).toBeVisible();
    await expect(page.locator('#component-dialog')).toContainText('Elo 수정');
    await page.locator('#component-dialog button[value=cancel]').click();
  } finally {
    releaseVoteRequest();
    page.off('request', recordOtherMutation);
  }
  await expect.poll(() => page.evaluate(identifier => Boolean(currentStyleGenerationState(identifier).votingCommandBusy), project.identifier)).toBe(false);
  await expect(page.locator('#active-project-picker')).toHaveValue(otherProject.identifier);
  await page.locator('#active-project-picker').selectOption(project.identifier);
  await page.locator('#preview-sidebar [data-screen=compare]').click();
  await waitForSelectionReady(page);
}

/** 선택 강조·동일 Pair 공개·단축키·Mode 전환을 실제 격리 API와 Browser에서 검증합니다. */
async function verifySelectionUserExperience() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const project = await prepareSelectionProject(context, '선별 피드백·Keyboard 검증', 10);
    const otherProject = await prepareSelectionProject(context, '선별 프로젝트 이동 검증', 2);
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(`${baseUrl}/style#compare`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    const clientIdentifier = await page.evaluate(() => styleVotingClientIdentifier());
    await finishInitialSelection(context, project, clientIdentifier);
    await page.reload();
    await waitForSelectionReady(page);
    const voteEndpoint = `${baseUrl}/api/style-projects/${project.identifier}/votes`;
    const voteRequests = [];
    page.on('request', request => {
      if (request.method() === 'POST' && request.url() === voteEndpoint) voteRequests.push(request.postDataJSON());
    });
    await verifyKeyboardGuards(page, voteRequests);

    const originalSelection = await readSelection(context, project, clientIdentifier);
    const originalSources = await page.locator('.comparison-result img').evaluateAll(images => images.map(image => image.getAttribute('src')));
    await page.locator('[data-action=toggle-blind]').click();
    await waitForSelectionReady(page);
    await expect(page.locator('.candidate-headings')).toContainText('그림체 숨김');
    await page.route(voteEndpoint, async route => {
      await new Promise(resolve => setTimeout(resolve, 300));
      await route.continue();
    }, { times: 1 });
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('ArrowLeft');
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'selecting');
    await expect(page.locator('.comparison-result.comparison-picked')).toHaveCount(2);
    await expect(page.locator('.comparison-result.comparison-dimmed')).toHaveCount(2);
    await expect(page.locator('.comparison-picked .image-button').first()).toHaveCSS('opacity', '1');
    await expect(page.locator('.candidate-headings')).toContainText('그림체 숨김');
    await page.keyboard.press('ArrowRight');
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'reveal');
    const revealStarted = Date.now();
    assert.equal(voteRequests.length, 1);
    assert.equal(voteRequests[0].choice, 'a');
    assert.deepEqual(await page.locator('.comparison-result img').evaluateAll(images => images.map(image => image.getAttribute('src'))), originalSources);
    await expect(page.locator('.candidate-headings')).not.toContainText('그림체 숨김');
    await expect(page.locator('.comparison-rating-delta')).toHaveCount(2);
    await page.evaluate(() => refreshStyleGenerationResults());
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'reveal');
    await page.screenshot({ path: 'runtime/verification/style-selection-feedback-desktop.png', fullPage: true });
    await waitForSelectionReady(page);
    assert.ok(Date.now() - revealStarted >= 700, 'The result must remain visible for about one second');
    await expect(page.locator('.candidate-headings')).toContainText('그림체 숨김');
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Backspace');
    await waitForSelectionReady(page);
    const restoredSelection = await readSelection(context, project, clientIdentifier);
    assert.deepEqual(restoredSelection.rankings, originalSelection.rankings);
    assert.deepEqual([restoredSelection.match.a, restoredSelection.match.b], [originalSelection.match.a, originalSelection.match.b]);
    assert.deepEqual(await page.locator('.comparison-result img').evaluateAll(images => images.map(image => image.getAttribute('src'))), originalSources);

    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Enter');
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'reveal');
    await expect(page.locator('.comparison-rating-delta')).toHaveText(['+0', '+0']);
    await expect(page.locator('.comparison-result.comparison-even')).toHaveCount(4);
    await waitForSelectionReady(page);
    await page.locator('[data-style-voting-choice=a]').focus();
    await page.keyboard.press('Enter');
    await waitForSelectionReady(page);
    assert.equal(voteRequests.at(-1).choice, 'a', 'Focused A button Enter must activate A, not similar');
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Numpad6');
    await waitForSelectionReady(page);
    assert.equal(voteRequests.at(-1).choice, 'b');
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Numpad4');
    await waitForSelectionReady(page);
    assert.equal(voteRequests.at(-1).choice, 'a');

    const beforeMode = await readSelection(context, project, clientIdentifier);
    const modeEndpoint = `${baseUrl}/api/style-projects/${project.identifier}/selection-mode`;
    let modeRequestCount = 0;
    await page.route(modeEndpoint, async route => {
      modeRequestCount += 1;
      await new Promise(resolve => setTimeout(resolve, 250));
      await route.continue();
    });
    await page.locator('[data-style-selection-mode=top]').evaluate(button => {
      button.click();
      document.querySelector('[data-style-selection-mode=league]').click();
    });
    await expect(page.locator('[data-style-selection-mode=top]')).toHaveAttribute('aria-pressed', 'true');
    await waitForSelectionReady(page);
    assert.equal(modeRequestCount, 1);
    let modeSelection = await readSelection(context, project, clientIdentifier);
    assert.equal(modeSelection.mode, 'top');
    assert.deepEqual(modeSelection.rankings, beforeMode.rankings);
    await page.reload();
    await waitForSelectionReady(page);
    await expect(page.locator('[data-style-selection-mode=top]')).toHaveAttribute('aria-pressed', 'true');
    await page.locator('[data-style-selection-mode=league]').click();
    await expect(page.locator('[data-style-selection-mode=league]')).toHaveAttribute('aria-pressed', 'true');
    await waitForSelectionReady(page);
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Backspace');
    await waitForSelectionReady(page);
    assert.equal((await readSelection(context, project, clientIdentifier)).mode, 'league', 'Undo must preserve explicitly selected mode');
    await page.unroute(modeEndpoint);

    await page.route(modeEndpoint, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '검증용 Mode 충돌' }) }), { times: 1 });
    await page.locator('[data-style-selection-mode=top]').click();
    await expect(page.locator('#style-voting-status')).toContainText('검증용 Mode 충돌');
    await expect(page.locator('[data-style-selection-mode=league]')).toHaveAttribute('aria-pressed', 'true');
    await waitForSelectionReady(page);

    const beforeFailure = await readSelection(context, project, clientIdentifier);
    await page.route(voteEndpoint, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '검증용 투표 충돌' }) }), { times: 1 });
    await page.locator('[data-style-voting-choice=b]').click();
    await expect(page.locator('#style-voting-status')).toContainText('검증용 투표 충돌');
    await waitForSelectionReady(page);
    assert.deepEqual((await readSelection(context, project, clientIdentifier)).rankings, beforeFailure.rankings);
    await expect(page.locator('.comparison-picked, .comparison-dimmed')).toHaveCount(0);

    for (const viewportWidth of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width: viewportWidth, height: 844 });
      const measuredLayout = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
      assert.ok(measuredLayout.content <= measuredLayout.viewport, JSON.stringify(measuredLayout));
      const modeRows = await page.locator('[data-style-selection-mode]').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().top));
      assert.equal(new Set(modeRows).size, 1, 'Selection modes must remain on one readable row');
      const modeLayout = await page.locator('.comparison-selection-modes').evaluate(group => ({
        groupWidth: group.getBoundingClientRect().width,
        toolbarWidth: group.closest('.comparison-toolbar').getBoundingClientRect().width,
        buttonsFit: [...group.querySelectorAll('button')].every(button => button.scrollWidth <= button.clientWidth),
      }));
      assert.equal(modeLayout.buttonsFit, true, JSON.stringify(modeLayout));
      if (viewportWidth <= 700) assert.ok(Math.abs(modeLayout.groupWidth - modeLayout.toolbarWidth) <= 1, JSON.stringify(modeLayout));
      if (viewportWidth === 320) await page.screenshot({ path: 'runtime/verification/style-selection-controls-320.png', fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('[data-action=image-layout]').click();
    await expect(page.locator('.comparison-result:visible')).toHaveCount(2);
    await page.locator('[data-style-voting-choice=similar]').click();
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'reveal');
    await page.screenshot({ path: 'runtime/verification/style-selection-feedback-mobile.png', fullPage: true });
    await waitForSelectionReady(page);
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
    assert.ok(dimensions.content <= dimensions.viewport, JSON.stringify(dimensions));
    const modeRows = await page.locator('[data-style-selection-mode]').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().top));
    assert.equal(new Set(modeRows).size, 1, 'Mobile selection modes must remain on one readable row');

    await verifyPendingVoteMutationGuards(page, project, otherProject);

    await page.locator('[data-style-voting-choice=a]').click();
    await expect(page.locator('.persistent-comparison')).toHaveAttribute('data-voting-feedback', 'reveal');
    await page.locator('#active-project-picker').selectOption(otherProject.identifier);
    await waitForSelectionReady(page);
    await expect(page.locator('#active-project-picker')).toHaveValue(otherProject.identifier);
    await page.waitForTimeout(1100);
    await expect(page.locator('#active-project-picker')).toHaveValue(otherProject.identifier);
    assert.equal(await page.evaluate(() => currentPersistentComparison().voting.projectIdentifier), otherProject.identifier);
    await expect(page.locator('.comparison-rating-delta')).toHaveCount(0);
    assert.deepEqual(browserErrors, []);
    filesystem.writeFileSync('runtime/verification/style-selection-ux-browser-results.json', JSON.stringify({
      projectIdentifier: project.identifier, otherProjectIdentifier: otherProject.identifier,
      selectionFeedback: true, blindRevealThenRemask: true, samePairHeld: true, eloDeltaIncludesZero: true,
      keyboardAndFocusGuards: true, keyboardUndoRestoresPair: true, modeRoundTripAndPersistence: true,
      modeAndVoteErrorsRecover: true, mobileMultiplePrompts: true, projectSwitchDuringReveal: true, browserErrors,
      pendingVoteBlocksSameProjectMutations: true, pendingVoteAllowsOtherProjectDialogs: true,
      viewportWidths: [320, 390, 768, 1280],
    }, null, 2));
    console.log('Style selection UX Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifySelectionUserExperience().catch(error => { console.error(error); process.exitCode = 1; });
