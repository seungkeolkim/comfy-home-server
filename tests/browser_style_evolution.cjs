const { chromium } = require('playwright');
const { expect } = require('playwright/test');
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
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    const prepare = page.locator('[data-style-evolution-action=prepare]');
    await expect(prepare).toBeDisabled();
    await expect(page.locator('.evolution-panel')).toContainText('평가된 그림체 10개');
    await page.locator('#style-random-combination-count').fill('10');
    await page.locator('[data-generation-action=random-start]').click();
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
    await expect(prepare).toBeEnabled();
    const source = await readEvolutionSelection(context, project, clientIdentifier);
    const previousJobCount = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    await page.locator('#style-evolution-child-count').fill('3');
    await prepare.click();
    const dialog = page.locator('#style-generation-confirmation-dialog');
    await expect(dialog).toContainText('9장');
    await expect(dialog).not.toContainText('safetensors');
    await dialog.locator('button[value=cancel]').click();
    await expect(prepare).toBeEnabled();
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, previousJobCount);
    await prepare.click();
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('[data-style-evolution-action=cancel]')).toBeVisible();
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    selection = await readEvolutionSelection(context, project, clientIdentifier);
    assert.equal(selection.match.kind, 'select');
    await expect(page.locator('#style-voting-status')).toContainText('부모의 Elo·전적은 유지');
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
    for (let index = 0; index < 60; index += 1) {
      evolution = await (await context.request.get(`${endpoint}/evolution?evaluationIdentifier=${project.evaluationIdentifier}`)).json();
      if (evolution.batch.canConfirm) break;
      selection = await readEvolutionSelection(context, project, clientIdentifier);
      await clickEvolutionVote(page, children.has(selection.match.a) ? 'a' : 'b');
      const current = await readEvolutionSelection(context, project, clientIdentifier);
      for (const candidate of source.rankings) {
        const updated = current.rankings.find(entry => entry.identifier === candidate.identifier);
        for (const field of ['rating', 'matches', 'wins', 'losses', 'skips']) assert.equal(updated[field], candidate[field]);
      }
    }
    await expect(confirm).toBeEnabled();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
      assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.screenshot({ path: 'runtime/verification/style-evolution-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-evolution-mobile.png', fullPage: true });
    await confirm.click();
    await expect(dialog).toContainText('이미지와 이력은 보존');
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('.evolution-panel')).toContainText('현재 2세대');
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
    await page.locator('#style-evolution-child-count').fill('1');
    await prepare.click();
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('[data-style-evolution-action=cancel]')).toBeVisible();
    await page.locator('[data-style-evolution-action=cancel]').click();
    await dialog.locator('button[value=confirm]').click();
    await expect(page.locator('.evolution-panel')).toContainText('현재 2세대');
    await page.goto(`${baseUrl}/style#candidates`);
    await page.locator('#style-library-lifecycle').selectOption('cancelled');
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    assert.deepEqual(errors, []);
    fs.writeFileSync('runtime/verification/style-evolution-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, sourceImages: 30, children: 3, caseCount: 3, generation: 2, activeCount: 10, retiredCount: 3, fixedParents: true, selectionUndo: true, persistedReload: true, cancelledPlansNoJobs: true, cancelledChildrenPreserved: true, widths: [320, 390, 768, 1280], errors }, null, 2));
    console.log('Style evolution Browser cycle passed');
  } finally {
    await browser.close();
  }
}

verifyStyleEvolution().catch(error => { console.error(error); process.exitCode = 1; });
