const { chromium } = require('playwright');
const { expect: browserExpect } = require('playwright/test');
const expect = browserExpect.configure({ timeout: 15000 });
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 현재 Browser의 서버 Match·Undo·Revision을 다시 조회합니다. */
async function readEvolutionSelection(context, project, clientIdentifier) {
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier, clientIdentifier });
  const response = await context.request.get(`http://127.0.0.1:18388/api/style-projects/${project.identifier}/selection?${parameters}`);
  assert.equal(response.status(), 200, await response.text());
  return response.json();
}

/** 한 클릭의 서버 응답과 후속 Polling·이미지 로드를 모두 기다립니다. */
async function clickEvolutionVote(page, choice) {
  const button = page.locator(`[data-style-voting-choice=${choice}]`);
  await expect(button).toBeEnabled();
  const response = page.waitForResponse(response => response.url().endsWith('/votes') && response.request().method() === 'POST');
  await button.click();
  assert.equal((await response).status(), 200);
  await expect(page.locator('#preview-content')).not.toHaveAttribute('inert', '');
}

/** 초기 10조합→투표→자녀 생성→Selection→확정·취소를 실제 이미지로 검증합니다. */
async function verifyStyleEvolution() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `evolution-browser-create-${Date.now()}`,
      settings: {
        name: '진화 한 세대 Browser 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
        artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
        promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
      },
    } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
    const page = await context.newPage();
    const mutationRequests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST' && request.url().startsWith(endpoint)) mutationRequests.push(request.url());
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    const prepare = page.locator('[data-generation-action=generate-candidates]');
    await expect(prepare).toBeEnabled();
    await expect(page.locator('.evolution-panel')).toContainText('1세대 초기 후보');
    await page.locator('#style-generation-candidate-count').fill('10');
    await page.locator('[data-generation-action=generate-candidates]').click();
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.generation-result img')).toHaveCount(30, { timeout: 20000 });
    await page.goto(`${baseUrl}/style#compare`);
    const clientIdentifier = await page.evaluate(() => styleVotingClientIdentifier());
    let selection = await readEvolutionSelection(context, project, clientIdentifier);
    for (let index = 0; index < 40; index += 1) {
      const evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
      if (evolution.canPrepare) break;
      await clickEvolutionVote(page, selection.match.kind === 'tie' ? 'similar' : 'a');
      selection = await readEvolutionSelection(context, project, clientIdentifier);
    }
    await page.goto(`${baseUrl}/style#generation`);
    await expect(prepare).toBeEnabled();
    const source = await readEvolutionSelection(context, project, clientIdentifier);
    const previousJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    await page.locator('#style-generation-candidate-count').fill('3');
    await prepare.click();
    const dialog = page.locator('#style-generation-confirmation-dialog');
    await expect(dialog).toContainText('9장');
    await expect(dialog).not.toContainText('safetensors');
    await dialog.locator('button[value=cancel]').click();
    await expect(prepare).toBeEnabled();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount);
    await prepare.click();
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('.evolution-secondary-actions')).toBeVisible();
    await page.locator('#style-evolution-controls [data-screen=compare]').click();
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    selection = await readEvolutionSelection(context, project, clientIdentifier);
    assert.equal(selection.match.kind, 'select');
    await expect(page.locator('#style-voting-status')).toContainText('자동 선별');
    await expect(page.locator('.candidate-placement-status')).toContainText('평가 중');
    let evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    const children = new Set(evolution.batch.plan.candidates.map(candidate => candidate.identifier));
    const firstPair = { ...selection.match };
    await clickEvolutionVote(page, 'similar');
    await page.locator('[data-style-voting-action=undo]').click();
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    selection = await readEvolutionSelection(context, project, clientIdentifier);
    assert.deepEqual([selection.match.a, selection.match.b], [firstPair.a, firstPair.b]);
    await page.reload();
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    const confirm = page.locator('[data-style-evolution-action=confirm]');
    const comparisonsByChild = new Map([...children].map(identifier => [identifier, 0]));
    let comparedNewcomers = false;
    for (let index = 0; index < 60; index += 1) {
      evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
      if (evolution.batch.canConfirm) break;
      selection = await readEvolutionSelection(context, project, clientIdentifier);
      if (children.has(selection.match.a) && children.has(selection.match.b)) {
        comparedNewcomers = true;
        await expect(page.locator('.candidate-placement-status')).toHaveCount(2);
        await expect(page.locator('#style-voting-status')).toContainText('신규 조합끼리 비교');
        await page.screenshot({ path: 'runtime/verification/style-automatic-placement-newcomers-mobile.png' });
      }
      await clickEvolutionVote(page, children.has(selection.match.a) ? 'a' : 'b');
      const current = await readEvolutionSelection(context, project, clientIdentifier);
      for (const identifier of [selection.match.a, selection.match.b]) {
        if (!children.has(identifier)) continue;
        comparisonsByChild.set(identifier, comparisonsByChild.get(identifier) + 1);
        if (comparisonsByChild.get(identifier) === 1) {
          const statistics = current.rankings.find(candidate => candidate.identifier === identifier);
          assert.equal(statistics.placementPending, true);
          assert.equal(statistics.rated, false);
          assert.equal(statistics.rank, null);
          assert.equal(evolution.batch.canConfirm, false);
        }
      }
      for (const candidate of source.rankings) {
        const updated = current.rankings.find(entry => entry.identifier === candidate.identifier);
        for (const field of ['rating', 'matches', 'wins', 'losses', 'skips']) assert.equal(updated[field], candidate[field]);
      }
    }
    assert.equal(comparedNewcomers, true);
    assert.ok([...comparisonsByChild.values()].every(count => count > 1));
    await page.goto(`${baseUrl}/style#evolution`);
    await expect(confirm).toBeEnabled();
    await expect(page.locator('.evolution-candidate-group').first().locator('.style-library-card')).toHaveCount(3);
    await expect(page.locator('.evolution-candidate-group').nth(1).locator('.style-library-card')).toHaveCount(3);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-evolution-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-evolution-mobile.png', fullPage: true });
    await expect(page.locator('[data-generation-action=generate-candidates]')).toHaveCount(0);
    const beforeConfirmationJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    const beforeConfirmationRequestCount = mutationRequests.length;
    await confirm.click();
    await expect(dialog).toContainText('이미지와 이력은 보존');
    await expect(dialog).toContainText('다음 세대 이미지는 확정 후 별도로 생성');
    await dialog.locator('button[value=cancel]').click();
    await expect(confirm).toBeEnabled();
    assert.equal(mutationRequests.length, beforeConfirmationRequestCount);
    await confirm.click();
    await dialog.locator('button[value=confirm]').click();
    await expect.poll(async () => (await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json()).currentGeneration).toBe(2);
    await expect(page.locator('.generation-current-badge')).toContainText('2세대');
    await expect(page.locator('.evolution-panel')).toContainText('2세대 확정 완료');
    await expect(page.locator('.evolution-panel')).toContainText('다음 단계: 3세대 후보 이미지 생성');
    assert.deepEqual(mutationRequests.slice(beforeConfirmationRequestCount).map(url => url.split('/').at(-1)), ['confirm']);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeConfirmationJobCount);
    evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    assert.equal(evolution.batch, null);
    const afterConfirmationRequestCount = mutationRequests.length;
    await page.reload();
    await expect(page.locator('.evolution-panel')).toContainText('2세대 확정 완료');
    assert.equal(mutationRequests.length, afterConfirmationRequestCount);
    await page.screenshot({ path: 'runtime/verification/style-evolution-confirmed-mobile.png', fullPage: true });
    await expect(page.locator('.evolution-history')).toBeVisible();
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('[data-style-voting-action=undo]')).toBeDisabled();
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(10);
    await page.locator('#style-library-lifecycle').selectOption('retired');
    await expect(page.locator('.style-library-card')).toHaveCount(3);
    await expect(page.locator('.style-library-card').first()).toContainText('퇴역');
    await page.locator('.style-card-heading').first().click();
    await expect(page.locator('#illustration-dialog img')).toBeVisible();
    await page.keyboard.press('Escape');
    await page.locator('#style-library-lifecycle').selectOption('all');
    await expect(page.locator('.style-library-card')).toHaveCount(13);
    await page.screenshot({ path: 'runtime/verification/style-evolution-archive-mobile.png', fullPage: true });
    await page.goto(`${baseUrl}/style#generation`);
    await expect(prepare).toBeEnabled();
    await page.locator('#style-generation-candidate-count').fill('2');
    await prepare.click();
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('.evolution-secondary-actions')).toBeVisible();
    await page.goto(`${baseUrl}/style#compare`);
    evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    const thirdGenerationChildren = new Set(evolution.batch.candidateIdentifiers);
    await expect.poll(async () => Boolean((await readEvolutionSelection(context, project, clientIdentifier)).match)).toBe(true);
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    for (let index = 0; index < 60; index += 1) {
      await expect.poll(async () => {
        selection = await readEvolutionSelection(context, project, clientIdentifier);
        evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
        return Boolean(selection.match) || evolution.batch.canConfirm;
      }).toBe(true);
      if (evolution.batch.canConfirm) break;
      await clickEvolutionVote(page, thirdGenerationChildren.has(selection.match.a) ? 'a' : 'b');
    }
    await page.goto(`${baseUrl}/style#evolution`);
    await expect(confirm).toBeEnabled();
    const thirdGenerationBatch = evolution.batch;
    const beforeNextJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    const beforeThirdConfirmationRequests = mutationRequests.length;
    await page.route(`${endpoint}/evolution-batches/*/confirm`, async route => {
      const response = await route.fetch();
      assert.equal(response.status(), 200, await response.text());
      await route.abort('failed');
    }, { times: 1 });
    await confirm.click();
    await dialog.locator('button[value=confirm]').click();
    await expect.poll(() => page.evaluate(() => styleGenerationViewState.busy)).toBe(false);
    await expect(page.locator('#style-generation-error')).not.toBeEmpty();
    await expect(page.locator('.evolution-panel')).toContainText('3세대 확정 완료');
    assert.deepEqual(mutationRequests.slice(beforeThirdConfirmationRequests).map(url => url.split('/').at(-1)), ['confirm']);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeNextJobCount);
    await page.evaluate(({ projectIdentifier, batchIdentifier, planOperationIdentifier, projectRevision, votingRevision }) => {
      const storedSession = JSON.parse(sessionStorage.getItem(STYLE_WORKSPACE_SESSION_KEY));
      storedSession.evolutionContinuations = { [projectIdentifier]: { batchIdentifier, candidateCount: 2 } };
      storedSession.candidateGenerationRequests[projectIdentifier] = {
        operationIdentifier: planOperationIdentifier, expectedProjectRevision: projectRevision, expectedVotingRevision: votingRevision, candidateCount: 2,
      };
      sessionStorage.setItem(STYLE_WORKSPACE_SESSION_KEY, JSON.stringify(storedSession));
    }, { projectIdentifier: project.identifier, batchIdentifier: thirdGenerationBatch.identifier,
      planOperationIdentifier: thirdGenerationBatch.plan.operationIdentifier, projectRevision: evolution.projectRevision, votingRevision: evolution.votingRevision });
    const beforeReloadRequests = mutationRequests.length;
    await page.reload();
    await expect(page.locator('.evolution-panel')).toContainText('3세대 확정 완료');
    await expect(page.locator('[data-style-evolution-action=resume-next]')).toHaveCount(0);
    assert.equal(mutationRequests.length, beforeReloadRequests);
    evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    assert.equal(evolution.currentGeneration, 3);
    assert.equal(evolution.batch, null);
    if (!evolution.canPrepare) {
      await page.goto(`${baseUrl}/style#compare`);
      for (let index = 0; index < 20; index += 1) {
        evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
        if (evolution.canPrepare) break;
        selection = await readEvolutionSelection(context, project, clientIdentifier);
        assert.equal(selection.match.kind, 'tie');
        await clickEvolutionVote(page, 'similar');
      }
      await page.goto(`${baseUrl}/style#evolution`);
    }
    await expect(prepare).toBeEnabled();
    await page.locator('#style-generation-candidate-count').fill('2');
    await prepare.click();
    await expect(dialog).toContainText('6장');
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeNextJobCount);
    await page.reload();
    await expect(page.locator('[data-style-evolution-action=resume]')).toBeVisible();
    let acceptedNextPlanIdentifier;
    await page.route(`${endpoint}/generation-plans/*/submit`, async route => {
      acceptedNextPlanIdentifier = route.request().url().split('/').at(-2);
      const response = await route.fetch();
      assert.equal(response.status(), 200, await response.text());
      await route.abort('failed');
    }, { times: 1 });
    await page.locator('[data-style-evolution-action=resume]').click();
    await expect(dialog).toContainText('6장');
    await dialog.locator('button[value=confirm]').click();
    await expect.poll(() => page.evaluate(() => styleGenerationViewState.busy), { timeout: 20000 }).toBe(false);
    await expect(page.locator('#style-generation-error')).not.toBeEmpty();
    assert.ok(acceptedNextPlanIdentifier, 'Response loss route must accept the next plan');
    evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    assert.equal(evolution.batch.targetGeneration, 4);
    assert.equal(evolution.batch.childCount, 2);
    const nextCandidateIdentifiers = evolution.batch.candidateIdentifiers;
    assert.equal(evolution.batch.plan.planIdentifier, acceptedNextPlanIdentifier);
    assert.equal(evolution.batch.plan.selection.mode, 'evolution');
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeNextJobCount + 1);
    const afterSubmissionRequestCount = mutationRequests.length;
    await page.reload();
    await expect(page.locator('.evolution-secondary-actions')).toBeVisible();
    await expect(page.locator('[data-style-evolution-action=resume]')).toHaveCount(0);
    assert.equal(mutationRequests.length, afterSubmissionRequestCount);
    evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
    assert.equal(evolution.currentGeneration, 3);
    assert.deepEqual(evolution.batch.candidateIdentifiers, nextCandidateIdentifiers);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, beforeNextJobCount + 1);
    await expect(page.locator('.evolution-candidate-group').first().locator('.style-library-card')).toHaveCount(2);
    await page.screenshot({ path: 'runtime/verification/style-evolution-continuation-mobile.png', fullPage: true });
    await page.locator('.evolution-secondary-actions summary').click();
    await page.locator('[data-style-evolution-action=cancel]').click();
    await dialog.locator('button[value=confirm]').click();
    await expect.poll(async () => (await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json()).currentGeneration).toBe(3);
    await expect.poll(() => page.evaluate(() => styleGenerationViewState.busy), { timeout: 20000 }).toBe(false);
    await expect.poll(async () => (await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json()).batch).toBeNull();
    await expect(page.locator('.generation-current-badge')).toContainText('3세대');
    await page.goto(`${baseUrl}/style#candidates`);
    await page.locator('#style-library-lifecycle').selectOption('cancelled');
    await expect(page.locator('.style-library-card')).toHaveCount(2);
    assert.deepEqual(errors, []);
    fs.writeFileSync('runtime/verification/style-evolution-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, sourceImages: 30, children: 3, caseCount: 3, generation: 3, activeCount: 10, retiredCount: 3, nextGeneration: 4, confirmationAndGenerationSeparated: true, confirmationResponseLossRecovered: true, responseLossAndReloadRecovered: true, noDuplicateJobs: true, fixedParents: true, selectionUndo: true, persistedReload: true, cancelledPlansNoJobs: true, cancelledChildrenPreserved: true, widths: [320, 390, 768, 1280], errors }, null, 2));
    console.log('Style evolution Browser cycle passed');
  } finally {
    await browser.close();
  }
}

verifyStyleEvolution().catch(error => { console.error(error); process.exitCode = 1; });
