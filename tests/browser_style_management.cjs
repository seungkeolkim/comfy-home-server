const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** 파일 규칙·Elo·폐기·공통 Viewer·고정 Vote Bar를 실제 임시 이미지로 확인합니다. */
async function verifyStyleManagement() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  const originalRequests = [];
  try {
    const context = await browser.newContext();
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
      operationIdentifier: `management-browser-${Date.now()}`,
      settings: { name: '조합 관리 Browser 검증', width: 64, height: 96, steps: 3, cfg: 1, seed: 42,
        artistMinimumCount: 0, artistMaximumCount: 0, loraMinimumCount: 1, loraMaximumCount: 1,
        promptCases: ['인물', '거리', '정원'].map((name, index) => ({ identifier: `case-${index}`, name, prompt: `scene ${index}` })),
        componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } } },
    } });
    assert.equal(projectResponse.status(), 201, await projectResponse.text());
    const project = await projectResponse.json();
    const endpoint = `${baseUrl}/api/style-projects/${project.identifier}`;
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/media/')) originalRequests.push(request.url()); });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(`${baseUrl}/style#generation`);
    await page.locator('#active-project-picker').selectOption(project.identifier);
    await page.locator('.page-heading [data-generation-action=open-generator]').click();
    await page.locator('#style-generation-random-count').fill('4');
    await page.locator('[data-generation-action=generate-random]').click();
    await page.locator('#style-generation-confirmation-dialog button[value=confirm]').click();
    await expect(page.locator('.style-card-thumbnail img')).toHaveCount(12, { timeout: 20000 });
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(4);
    const names = await page.locator('.style-card-heading strong').allTextContents();
    assert.deepEqual(names, ['세대001-조합01', '세대001-조합02', '세대001-조합03', '세대001-조합04']);
    assert.ok(!(await page.locator('#preview-content').innerText()).includes('번째 생성'));
    await page.locator('.style-card-heading').first().click();
    await expect(page.locator('#style-viewer-original-toggle')).toBeChecked();
    await expect(page.locator('.style-viewer-image')).toHaveAttribute('src', /^\/media\//);
    await page.screenshot({ path: 'runtime/verification/style-usability-viewer-desktop.png', fullPage: true });
    await page.locator('[data-style-library-action=close]').click();
    await page.setViewportSize({ width: 390, height: 844 });
    const beforeMobile = originalRequests.length;
    await page.locator('.style-card-heading').first().click();
    await expect(page.locator('#style-viewer-original-toggle')).not.toBeChecked();
    await expect(page.locator('.style-viewer-image')).toHaveAttribute('src', /^\/api\/outputs\/preview\//);
    await page.locator('[data-style-library-action=next]').click();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('2 / 3');
    assert.equal(originalRequests.length, beforeMobile);
    await page.locator('#style-viewer-original-toggle').check();
    await expect(page.locator('.style-viewer-image')).toHaveAttribute('src', /^\/media\//);
    await page.locator('[data-style-library-action=next]').click();
    await expect(page.locator('#style-viewer-original-toggle')).toBeChecked();
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('3 / 3');
    await page.keyboard.press('ArrowLeft');
    await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText('2 / 3');
    await page.locator('#style-viewer-original-toggle').uncheck();
    await expect(page.locator('#illustration-dialog [data-style-candidate-action]')).toHaveCount(0);
    await expect(page.locator('#illustration-dialog .style-card-statistics')).toHaveCount(0);
    await expect(page.locator('#style-viewer-title')).toHaveText(names[0]);
    await expect(page.locator('#style-viewer-case-name')).toHaveText('거리');
    await expect(page.locator('.style-viewer-image')).toHaveAttribute('src', /^\/api\/outputs\/preview\//);
    const viewerBounds = await page.locator('#illustration-dialog').boundingBox();
    const closeBounds = await page.locator('[data-style-library-action=close]').boundingBox();
    assert.ok(viewerBounds.y >= 0 && viewerBounds.y + viewerBounds.height <= 844);
    assert.ok(closeBounds.y >= viewerBounds.y && closeBounds.y + closeBounds.height <= 844);
    await page.screenshot({ path: 'runtime/verification/style-usability-viewer-mobile.png', fullPage: true });
    await page.locator('[data-style-library-action=close]').click();
    const ratingCandidateIdentifier = await page.locator('.style-library-card').first().getAttribute('data-style-candidate');
    await page.locator('.style-library-card [data-style-candidate-action=rating]').first().click();
    await expect(page.locator('#component-dialog')).toContainText('Elo 수정');
    await page.locator('#style-candidate-rating').fill('12345');
    await page.locator('#style-candidate-rating').press('Enter');
    await expect(page.locator(`[data-style-candidate="${ratingCandidateIdentifier}"] [data-style-rating]`)).toHaveText('12,345');
    const selectedIdentifiers = await page.locator('.style-library-card').evaluateAll(cards => cards.slice(0, 2).map(card => card.dataset.styleCandidate));
    for (const identifier of selectedIdentifiers) await page.locator(`[data-style-candidate-select="${identifier}"]`).check();
    await expect(page.locator('.style-candidate-selection-toolbar')).toContainText('2개 선택');
    await page.locator('.style-candidate-selection-toolbar [data-style-candidate-action=rating]').click();
    await page.locator('#style-candidate-rating').fill('15000');
    await page.locator('#component-dialog button[value=confirm]').click();
    for (const identifier of selectedIdentifiers) await expect(page.locator(`[data-style-candidate="${identifier}"] [data-style-rating]`)).toHaveText('15,000');
    await page.locator('[data-style-candidate-action=clear-selection]').click();
    const deletionTarget = page.locator('.style-library-card').last();
    const targetIdentifier = await deletionTarget.getAttribute('data-style-candidate');
    let beforeResults = await (await context.request.get(endpoint + '/generation-results')).json();
    const generationJobIdentifier = beforeResults.plans.find(plan => plan.jobIdentifiers.length).jobIdentifiers[0];
    const deletedPaths = beforeResults.candidates.find(candidate => candidate.identifier === targetIdentifier).renders.flatMap(render => render.files.map(file => file.path));
    await deletionTarget.locator('[data-style-candidate-action=delete]').click();
    await expect(page.locator('#component-dialog')).toContainText('모든 Prompt');
    await page.locator('#component-dialog button[value=cancel]').click();
    await expect(page.locator('.style-library-card')).toHaveCount(4);
    await page.locator(`[data-style-candidate="${targetIdentifier}"] [data-style-candidate-action=delete]`).click();
    await page.locator('#component-dialog button[value=confirm]').click();
    await expect(page.locator('.style-library-card')).toHaveCount(3);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs/${generationJobIdentifier}`)).json()).request_count, 9);
    for (const relativePath of deletedPaths) assert.equal((await context.request.get(`${baseUrl}/media/${relativePath}`)).status(), 404);
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('[data-style-voting-choice=a]')).toBeEnabled();
    const afterSelection = await (await context.request.get(`${endpoint}/selection?evaluationIdentifier=${project.evaluationIdentifier}&clientIdentifier=management-browser-inspection`)).json();
    assert.ok(!afterSelection.rankings.some(candidate => candidate.identifier === targetIdentifier));
    assert.ok(![afterSelection.match.a, afterSelection.match.b].includes(targetIdentifier));
    const cachedIdentifiers = await page.evaluate(() => currentPersistentComparison().allCandidates.map(candidate => candidate.identifier));
    assert.ok(!cachedIdentifiers.includes(targetIdentifier));
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const position of ['top', 'middle', 'bottom']) {
        await page.evaluate(position => window.scrollTo(0, position === 'top' ? 0 : position === 'middle' ? document.documentElement.scrollHeight / 2 : document.documentElement.scrollHeight), position);
        await expect.poll(async () => page.locator('.comparison-footer').evaluate(footer => {
          const rectangle = footer.getBoundingClientRect();
          const navigation = document.querySelector('#preview-mobile-navigation').getBoundingClientRect();
          return rectangle.top >= 0 && rectangle.left >= 0 && rectangle.right <= innerWidth && rectangle.bottom <= (navigation.height ? navigation.top - 4 : innerHeight);
        })).toBe(true);
      }
      assert.equal(await page.locator('.comparison-footer').evaluate(footer => getComputedStyle(footer).position), 'fixed');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: 'runtime/verification/style-usability-compare-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'runtime/verification/style-usability-compare-mobile.png', fullPage: true });
    await page.locator('.comparison-extra-controls summary').click();
    await page.locator('[data-style-candidate-action=delete][data-candidates]').click();
    await expect(page.locator('#component-dialog')).toContainText('2개 조합');
    await page.locator('#component-dialog button[value=confirm]').click();
    await page.goto(`${baseUrl}/style#candidates`);
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    await page.reload();
    await expect(page.locator('.style-library-card')).toHaveCount(1);
    assert.equal((await (await context.request.get(`${baseUrl}/api/jobs/${generationJobIdentifier}`)).json()).request_count, 3);
    await page.locator('.style-library-card [data-style-candidate-action=delete]').click();
    await page.locator('#component-dialog button[value=confirm]').click();
    await expect(page.locator('.style-library-card')).toHaveCount(0);
    assert.equal((await context.request.get(`${baseUrl}/api/jobs/${generationJobIdentifier}`)).status(), 404);
    await page.goto(`${baseUrl}/style#compare`);
    await expect(page.locator('#preview-content')).toContainText('아직 생성한 이미지가 없습니다.');
    await expect(page.locator('.comparison-result img')).toHaveCount(0);
    const emptySelection = await (await context.request.get(`${endpoint}/selection?evaluationIdentifier=${project.evaluationIdentifier}&clientIdentifier=management-browser-inspection`)).json();
    assert.equal(emptySelection.match, null);
    assert.deepEqual(emptySelection.rankings, []);
    assert.deepEqual(errors, []);
    fs.writeFileSync('runtime/verification/style-usability-browser-results.json', JSON.stringify({ projectIdentifier: project.identifier, names, mobileUsesPreview: true, desktopUsesOriginal: true, originalTogglePersistsAcrossPrompts: true, directAndBulkRating: true, deleteCancelled: true, wholeCombinationDeleted: true, deleteBothFromComparison: true, fixedVoteBarAtEveryScroll: true, widths: [320, 390, 768, 1280], errors }, null, 2));
    console.log('Style management, shared Viewer and fixed voting Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleManagement().catch(error => { console.error(error); process.exitCode = 1; });
