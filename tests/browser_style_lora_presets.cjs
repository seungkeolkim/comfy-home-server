const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

/** 실제 임시 PNG와 서로 다른 STR·고정 CLIP 1 조합을 격리 서버에만 생성합니다. */
async function createLoraRegistrationProject(context, baseUrl, name) {
  const settings = {
    name, width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
    artistMinimumCount: 0, artistMaximumCount: 1, loraMinimumCount: 0, loraMaximumCount: 1,
    promptCases: ['인물', '거리'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
    componentPolicies: {
      'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 },
      'artist:example': { enabled: true, minimumStrength: 0.4, maximumStrength: 0.8 },
    },
  };
  const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: { settings, operationIdentifier: crypto.randomUUID() } });
  assert.equal(projectResponse.status(), 201, await projectResponse.text());
  const project = await projectResponse.json();
  const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
  const combinationBatches = [
    [
      { components: [{ identifier: 'lora:example.safetensors', strength: 0.4, clip_strength: 0 }] },
      { components: [{ identifier: 'lora:example.safetensors', strength: 0.7 }] },
    ],
    [{ components: [{ identifier: 'artist:example', strength: 0.6 }] }],
  ];
  const candidates = [];
  for (const combinations of combinationBatches) {
    const preview = await context.request.post(`${endpoint}/generation-plans`, { data: {
      expectedRevision: project.revision, operationIdentifier: crypto.randomUUID(), combinations,
    } });
    assert.equal(preview.status(), 201, await preview.text());
    const plan = await preview.json();
    candidates.push(...plan.candidates);
    assert.equal((await context.request.post(`${endpoint}/generation-plans/${plan.planIdentifier}/submit`, { data: { operationIdentifier: crypto.randomUUID() } })).status(), 200);
  }
  await expect.poll(async () => {
    const results = await (await context.request.get(`${endpoint}/generation-results?summary=true`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }, { timeout: 20000 }).toBe(6);
  return { project, plan: { candidates }, endpoint };
}

/** 등록·교집합 필터·CHS 사용·원본 이동·양쪽 삭제와 오류 시 원본 보존을 검증합니다. */
async function verifyStyleLoraPresets() {
  const baseUrl = 'http://127.0.0.1:18388';
  const directory = 'runtime/verification/style-lora-presets';
  filesystem.mkdirSync(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  const report = { widths: [], browserErrors };
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 } });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const first = await createLoraRegistrationProject(context, baseUrl, '긴 프로젝트 이름에서도 원본과 세대 조합을 확인하는 LoRA 등록 테스트');
    const second = await createLoraRegistrationProject(context, baseUrl, '다른 프로젝트 LoRA 등록');
    const initialJobs = (await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total;
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    await page.goto(`${baseUrl}/style#candidates`);
    await page.locator('#active-project-picker').selectOption(first.project.identifier);
    const firstIdentifier = first.plan.candidates[0].identifier;
    const secondIdentifier = first.plan.candidates[1].identifier;
    const firstCard = page.locator(`[data-style-candidate="${firstIdentifier}"]`);
    const secondCard = page.locator(`[data-style-candidate="${secondIdentifier}"]`);
    const registrationButton = firstCard.locator('[data-style-lora-preset]');
    await expect(page.locator('.style-library-card')).toHaveCount(3);
    await expect(page.locator(`[data-style-lora-preset="${first.plan.candidates[2].identifier}"]`)).toBeDisabled();
    await firstCard.locator('img').first().evaluate(image => { window.styleRegistrationImageReference = image; });
    await registrationButton.click();
    await expect(registrationButton).toHaveAttribute('aria-pressed', 'true');
    assert.ok(await firstCard.locator('img').first().evaluate(image => image === window.styleRegistrationImageReference));
    let presets = await (await context.request.get(`${baseUrl}/api/loras/presets`)).json();
    const firstPreset = presets.find(preset => preset.style_source?.candidate_id === firstIdentifier);
    assert.deepEqual(firstPreset.loras, [{ name: 'example.safetensors', strength: 0.4, clip_strength: 1 }]);
    await secondCard.locator('[data-style-candidate-favorite]').click();
    await expect(secondCard.locator('[data-style-candidate-favorite]')).toHaveAttribute('aria-pressed', 'true');
    await page.locator('#style-library-lora-presets-only').check();
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    await page.locator('#style-library-favorites-only').check();
    await expect(page.locator('.style-library-card')).toHaveCount(0);
    await page.locator('#style-library-lora-presets-only').uncheck();
    await secondCard.locator('[data-style-lora-preset]').click();
    await expect(secondCard.locator('[data-style-lora-preset]')).toHaveAttribute('aria-pressed', 'true');
    await page.locator('#style-library-lora-presets-only').check();
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    await page.reload();
    await expect(page.locator('#style-library-lora-presets-only')).toBeChecked();
    await expect(page.locator('#style-library-favorites-only')).toBeChecked();
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    await page.locator('#style-library-favorites-only').uncheck();
    const resultsEndpoint = `${first.endpoint}/generation-results?summary=true`;
    await page.route(resultsEndpoint, async route => {
      const response = await route.fetch();
      const results = await response.json();
      results.candidates.find(candidate => candidate.identifier === firstIdentifier).lifecycle = 'retired';
      await route.fulfill({ response, json: results });
    });
    await page.reload();
    await expect(page.locator('.style-library-card')).toHaveCount(2);
    await expect(firstCard).toContainText('퇴역');
    await expect(page.locator('#style-library-lifecycle')).toHaveValue('all');
    await expect(page.locator('#style-library-lifecycle')).toBeDisabled();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      const bounds = await firstCard.locator('.style-card-composition-actions').evaluate(element => {
        const buttons = [...element.querySelectorAll('button')].map(button => button.getBoundingClientRect());
        return { firstRight: buttons[0].right, secondLeft: buttons[1].left, sameRow: Math.abs(buttons[0].top - buttons[1].top) < 1, height: buttons[1].height };
      });
      assert.ok(bounds.sameRow && bounds.firstRight < bounds.secondLeft && bounds.height >= 44, JSON.stringify(bounds));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: `${directory}/style-${width}.png` });
      report.widths.push(width);
    }
    await page.unroute(resultsEndpoint);
    const registrationEndpoint = `${first.endpoint}/candidates/${firstIdentifier}/lora-preset`;
    await page.route(registrationEndpoint, route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"저장 실패 검증"}' }), { times: 1 });
    await registrationButton.click();
    await expect(registrationButton).toBeEnabled();
    await expect(registrationButton).toHaveAttribute('aria-pressed', 'true');
    assert.ok((await (await context.request.get(`${baseUrl}/api/loras/presets`)).json()).some(preset => preset.preset_id === firstPreset.preset_id));
    await page.locator('#active-project-picker').selectOption(second.project.identifier);
    await expect(page.locator('#style-library-lora-presets-only')).not.toBeChecked();
    let finishHeldRegistration;
    let registrationReachedServer;
    const registrationHeld = new Promise(resolve => { finishHeldRegistration = resolve; });
    const registrationSaved = new Promise(resolve => { registrationReachedServer = resolve; });
    await page.route(`${second.endpoint}/candidates/${second.plan.candidates[0].identifier}/lora-preset`, async route => {
      const response = await route.fetch();
      registrationReachedServer();
      await registrationHeld;
      await route.fulfill({ response });
    }, { times: 1 });
    await page.locator(`[data-style-lora-preset="${second.plan.candidates[0].identifier}"]`).click();
    await registrationSaved;
    await page.locator('#active-project-picker').selectOption(first.project.identifier);
    await expect(registrationButton).toHaveAttribute('aria-pressed', 'true');
    finishHeldRegistration();
    await expect.poll(() => page.evaluate(identifier => currentStyleGenerationState(identifier).pendingLoraRegistrationCandidateIdentifiers.size, second.project.identifier)).toBe(0);
    await expect(page.locator('#active-project-picker')).toHaveValue(first.project.identifier);
    await page.locator('#active-project-picker').selectOption(second.project.identifier);
    await expect(page.locator(`[data-style-lora-preset="${second.plan.candidates[0].identifier}"]`)).toHaveAttribute('aria-pressed', 'true');
    await context.request.post(`${baseUrl}/api/loras/presets`, { data: { name: '직접 저장한 일반 조합', workflow: 'anima', loras: [{ name: 'example.safetensors', strength: 0.25, clip_strength: 1 }] } });
    await page.goto(`${baseUrl}/?view=lora-presets`);
    await expect(page.locator('.lora-preset-row')).toHaveCount(4);
    await expect(page.locator('.lora-preset-group')).toHaveCount(3);
    await page.locator('#lora-presets-style-only').check();
    await expect(page.locator('.lora-preset-row')).toHaveCount(3);
    await page.locator('#lora-preset-search').fill(first.project.name.slice(15));
    await expect(page.locator('.lora-preset-row')).toHaveCount(2);
    const presetRow = page.locator(`[data-lora-preset="${firstPreset.preset_id}"]`);
    await expect(presetRow).toContainText('스타일 구성 · 자동 등록');
    await presetRow.locator('[data-edit-lora-preset]').click();
    await expect(page.locator('#lora-preset-style-source')).toContainText(first.project.name);
    await page.locator('#lora-preset-name').fill('미저장 별칭 보존');
    await page.locator('#lora-preset-search').fill('example.safetensors');
    await expect(page.locator('#lora-preset-name')).toHaveValue('미저장 별칭 보존');
    for (const width of report.widths) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({ path: `${directory}/chs-${width}.png` });
    }
    await presetRow.locator('[data-use-lora-preset]').click();
    await expect(page.locator('#generate-lora-preset')).toHaveValue(firstPreset.preset_id);
    const actualLoras = await page.evaluate(() => applicationState.selectedLoras);
    assert.equal(actualLoras[0].strength, 0.4);
    assert.equal(actualLoras[0].clip_strength, 1);
    const option = page.locator(`#generate-lora-preset option[value="${firstPreset.preset_id}"]`);
    await expect(option).toContainText('001-01');
    assert.ok((await option.textContent()).includes('…'));
    await page.locator('[data-view=lora-presets]').first().click();
    await presetRow.getByRole('link', { name: '원본 그림체' }).click();
    await expect(page).toHaveURL(`${baseUrl}/style#candidates`);
    await expect(page.locator('#active-project-picker')).toHaveValue(first.project.identifier);
    await expect(firstCard.locator('.style-card-composition')).toBeFocused();
    await expect(registrationButton).toHaveAttribute('aria-pressed', 'true');
    await registrationButton.click();
    await expect(registrationButton).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('.style-library-card')).toHaveCount(3);
    presets = await (await context.request.get(`${baseUrl}/api/loras/presets`)).json();
    const secondPreset = presets.find(preset => preset.style_source?.candidate_id === secondIdentifier);
    await context.request.delete(`${baseUrl}/api/loras/presets/${secondPreset.preset_id}`);
    await page.reload();
    await expect(secondCard.locator('[data-style-lora-preset]')).toHaveAttribute('aria-pressed', 'false');
    await expect(secondCard.locator('[data-style-candidate-favorite]')).toHaveAttribute('aria-pressed', 'true');
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs?include_style=true`)).json()).total, initialJobs);
    assert.deepEqual(browserErrors, []);
    report.registrationAndUnregistration = true;
    report.intersectionAndProjectFilters = true;
    report.retiredAndSessionPersistence = true;
    report.chsGroupingSearchUseAndSourceNavigation = true;
    report.chsDeletionAndFailurePreserveOriginals = true;
    report.projectSwitchDuringRegistrationAndImageNodeReuse = true;
    filesystem.writeFileSync(`${directory}/browser.json`, JSON.stringify(report, null, 2));
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } finally { await browser.close(); }
}

verifyStyleLoraPresets().catch(error => { console.error(error); process.exitCode = 1; });
