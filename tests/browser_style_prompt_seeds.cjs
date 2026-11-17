const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const filesystem = require('node:fs');

/** Prompt Seed의 수동 입력·랜덤·개별 확정·응답 유실·독립 초안을 검증합니다. */
async function verifyStylePromptSeeds() {
  const baseUrl = 'http://127.0.0.1:18388';
  const artifactDirectory = 'runtime/verification/style-prompt-seeds';
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  const browserErrors = [];
  const generationRequests = [];
  const requestIdentifiers = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const response = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `prompt-seed-browser-${Date.now()}`,
      settings: { name: 'Prompt별 Seed 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 123456,
        promptCases: [
          { identifier: 'portrait', name: '인물', prompt: 'portrait' },
          { identifier: 'garden', name: '정원', prompt: 'garden', seed: 777 },
        ], componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
      },
    } });
    assert.equal(response.status(), 201, await response.text());
    const project = await response.json();
    const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST' && /generation-plans|evolution-plans|\/submit|\/votes/.test(request.url())) generationRequests.push(request.url());
      if (request.method() === 'PUT' && request.url().endsWith('/prompt-cases/portrait/seed')) requestIdentifiers.push(request.postDataJSON().operationIdentifier);
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${baseUrl}/style#project-settings`);
    await expect(page.locator('#settings-case-seed-0')).toHaveValue('123456');
    await expect(page.locator('#settings-case-seed-1')).toHaveValue('777');
    await expect(page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-action=confirm]')).toBeDisabled();
    await page.locator('#settings-project-seed').fill('321');
    await expect(page.locator('#settings-case-seed-0')).toHaveValue('321');
    await expect(page.locator('#settings-case-seed-1')).toHaveValue('777');
    await page.locator('#settings-project-seed').fill('123456');
    await expect(page.locator('#settings-case-seed-0')).toHaveValue('123456');
    await page.locator('#settings-project-purpose').fill('서버에 저장하지 않은 메모');
    await page.locator('#settings-case-prompt-1').fill('');
    await page.locator('#settings-case-seed-0').fill('999');
    assert.equal((await (await context.request.get(endpoint)).json()).settings.promptCases[0].seed, null);
    await page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-action=random]').click();
    const randomSeed = await page.locator('#settings-case-seed-0').inputValue();
    assert.match(randomSeed, /^\d+$/);
    assert.ok(BigInt(randomSeed) >= 0n && BigInt(randomSeed) <= 18446744073709551615n && randomSeed !== '999');
    assert.equal((await (await context.request.get(endpoint)).json()).revision, project.revision);
    await page.reload();
    await expect(page.locator('#settings-case-seed-0')).toHaveValue(randomSeed);
    await expect(page.locator('#settings-project-purpose')).toHaveValue('서버에 저장하지 않은 메모');
    await expect(page.locator('#settings-case-prompt-1')).toHaveValue('');
    await page.locator('#settings-case-seed-0').fill('18446744073709551615');
    let droppedResponse = false;
    await page.route('**/prompt-cases/portrait/seed', async route => {
      if (!droppedResponse) {
        droppedResponse = true;
        const savedResponse = await route.fetch();
        assert.equal(savedResponse.status(), 200, await savedResponse.text());
        await route.abort('failed');
      } else {
        await route.continue();
      }
    });
    await page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-action=confirm]').click();
    await expect(page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-error]')).not.toHaveText('');
    await page.reload();
    await page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-action=confirm]').click();
    await expect(page.locator('[data-prompt-seed-row=portrait] [data-prompt-seed-action=confirm]')).toBeDisabled();
    let savedProject = await (await context.request.get(endpoint)).json();
    assert.equal(savedProject.revision, project.revision + 1);
    assert.equal(savedProject.settings.promptCases[0].seed, '18446744073709551615');
    assert.equal(savedProject.settings.promptCases[1].seed, 777);
    assert.equal(savedProject.settings.promptCases[1].prompt, 'garden');
    assert.equal(savedProject.settings.purpose, '');
    assert.equal(requestIdentifiers.length, 2);
    assert.equal(requestIdentifiers[0], requestIdentifiers[1]);
    await expect(page.locator('#settings-project-purpose')).toHaveValue('서버에 저장하지 않은 메모');
    await expect(page.locator('#settings-case-prompt-1')).toHaveValue('');
    await page.locator('#settings-case-prompt-1').fill('garden');
    await page.locator('#settings-case-seed-1').fill('123');
    await page.locator('#project-settings-form button[type=submit]').click();
    await expect(page.locator('#style-settings-save-status')).toHaveText('저장됨');
    savedProject = await (await context.request.get(endpoint)).json();
    assert.equal(savedProject.settings.purpose, '서버에 저장하지 않은 메모');
    assert.equal(savedProject.settings.promptCases[1].seed, 777);
    await page.reload();
    await expect(page.locator('#settings-case-seed-1')).toHaveValue('123');
    for (const invalidSeed of ['-1', '18446744073709551616', 'abc', '1.5']) {
      await page.locator('#settings-case-seed-1').fill(invalidSeed);
      await page.locator('[data-prompt-seed-row=garden] [data-prompt-seed-action=confirm]').click();
      await expect(page.locator('[data-prompt-seed-row=garden] [data-prompt-seed-error]')).toContainText('정수');
    }
    assert.equal((await (await context.request.get(endpoint)).json()).revision, savedProject.revision);
    await page.locator('#settings-case-seed-1').fill('0');
    await page.locator('#settings-case-seed-1').press('Enter');
    await expect(page.locator('[data-prompt-seed-row=garden] [data-prompt-seed-action=confirm]')).toBeDisabled();
    assert.equal((await (await context.request.get(endpoint)).json()).settings.promptCases[1].seed, 0);
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('#settings-case-seed-0').scrollIntoViewIfNeeded();
      const geometry = await page.locator('[data-prompt-seed-row=portrait] .prompt-seed-controls').evaluate(controls => {
        const children = Array.from(controls.children).map(element => {
          const bounds = element.getBoundingClientRect();
          return { left: bounds.left, right: bounds.right, top: bounds.top };
        });
        return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, children };
      });
      assert.ok(geometry.documentWidth <= geometry.width + 1, JSON.stringify(geometry));
      assert.ok(geometry.children[0].right <= geometry.children[1].left && geometry.children[1].right <= geometry.children[2].left);
      assert.ok(geometry.children.every(child => child.left >= 0 && child.right <= geometry.width + 1));
      if ([390, 1280].includes(width)) await page.screenshot({ path: `${artifactDirectory}/prompt-seeds-${width}.png`, fullPage: false });
    }
    await page.locator('[data-settings-action=add-prompt]').click();
    await page.locator('#settings-case-name-2').fill('세 번째');
    await page.locator('#settings-case-prompt-2').fill('forest');
    await page.locator('#settings-case-seed-2').fill('345');
    await page.locator('.prompt-editor').nth(2).locator('[data-prompt-seed-action=confirm]').click();
    assert.equal((await (await context.request.get(endpoint)).json()).settings.promptCases.length, 2);
    await page.locator('#project-settings-form button[type=submit]').click();
    await expect(page.locator('#style-settings-save-status')).toHaveText('저장됨');
    savedProject = await (await context.request.get(endpoint)).json();
    assert.equal(savedProject.settings.promptCases[2].seed, 345);
    await page.goto(`${baseUrl}/style#projects`);
    await page.locator('[data-action=navigate][data-screen=create]').first().click();
    await page.locator('#settings-case-seed-0').fill('0');
    await page.locator('.prompt-editor').first().locator('[data-prompt-seed-action=confirm]').click();
    await page.locator('#settings-project-name').fill('생성 전 개별 Seed');
    await page.locator('#settings-case-prompt-0').fill('new character');
    await page.locator('#persistent-project-form button[type=submit]').click();
    await expect(page.locator('#project-settings-form')).toBeVisible();
    const newProjectSeed = await page.locator('#settings-case-seed-0').inputValue();
    assert.equal(newProjectSeed, '0');
    await context.close();
    const freshContext = await browser.newContext();
    await freshContext.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const freshProject = await (await freshContext.request.get(endpoint)).json();
    assert.deepEqual(freshProject.settings.promptCases.map(promptCase => promptCase.seed), ['18446744073709551615', 0, 345]);
    assert.deepEqual(browserErrors, []);
    assert.deepEqual(generationRequests, []);
    filesystem.writeFileSync(`${artifactDirectory}/browser-results.json`, JSON.stringify({ widths: [320, 390, 768, 1280], manualEntry: true, randomRequiresConfirmation: true, maximumSeedExact: true, seedZeroSupported: true, unsavedSettingsPreserved: true, unconfirmedSeedExcludedFromGeneralSave: true, responseLossRecovered: droppedResponse, newPromptSupported: true, browserErrors, generationRequests }, null, 2));
    console.log('Style Prompt Seed Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStylePromptSeeds().catch(error => { console.error(error); process.exitCode = 1; });
