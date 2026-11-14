const { chromium } = require('playwright');
const { expect } = require('playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

/** Prompt 개수가 다른 실제 임시 생성 데이터를 격리 서버에만 준비합니다. */
async function createStyleLibraryScenario(context, baseUrl, promptCount) {
  const operationPrefix = `library-${Date.now()}-${promptCount}`;
  const scenarioSizes = { 1: { width: 512, height: 768 }, 3: { width: 640, height: 640 }, 5: { width: 768, height: 512 } };
  const promptCases = [];
  for (let index = 0; index < promptCount; index += 1) promptCases.push({ identifier: `case-${index}`, name: `Prompt ${index + 1}`, prompt: `scene ${index + 1}` });
  const projectResponse = await context.request.post(`${baseUrl}/api/style-projects`, { data: {
    operationIdentifier: `${operationPrefix}-project`, settings: {
      name: `${promptCount}개 Prompt 카드 검증`, promptCases, ...scenarioSizes[promptCount], steps: 3,
      componentPolicies: { 'lora:example.safetensors': { enabled: true, minimumStrength: 0.2, maximumStrength: 0.9 } },
    },
  } });
  assert.equal(projectResponse.status(), 201, await projectResponse.text());
  const project = await projectResponse.json();
  const planResponse = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/generation-plans`, { data: {
    expectedRevision: project.revision, operationIdentifier: `${operationPrefix}-plan`,
    combinations: [0.4, 0.8].map(strength => ({ components: [{ identifier: 'lora:example.safetensors', strength }] })),
  } });
  assert.equal(planResponse.status(), 201, await planResponse.text());
  const plan = await planResponse.json();
  const submitted = await context.request.post(`${baseUrl}/api/style-projects/${project.identifier}/generation-plans/${plan.planIdentifier}/submit`, { data: { operationIdentifier: `${operationPrefix}-submit` } });
  assert.equal(submitted.status(), 200, await submitted.text());
  await expect.poll(async () => {
    const results = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-results`)).json();
    return results.candidates.flatMap(candidate => candidate.renders).filter(render => render.status === 'completed').length;
  }, { timeout: 15000 }).toBe(promptCount * 2);
  return { ...project, candidateIdentifiers: plan.candidates.map(candidate => candidate.identifier) };
}

/** 실제 CSS 색상의 상대 명도를 계산해 선택 버튼의 텍스트 대비를 확인합니다. */
function relativeLuminance(color) {
  const channels = color.match(/\d+/g).slice(0, 3).map(Number).map(channel => {
    const normalized = channel / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

/** 이미지의 실제 비율과 테두리 크기가 같아 잘림이나 카드 안 여백이 없는지 확인합니다. */
async function verifyComparisonCardFit(page) {
  await expect.poll(() => page.locator('.comparison-result:visible img').evaluateAll(images => images.length > 0 && images.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
  const measurements = await page.locator('.comparison-result:visible .image-button').evaluateAll(buttons => buttons.map(button => {
    const image = button.querySelector('img');
    const imageBounds = image.getBoundingClientRect();
    const buttonBounds = button.getBoundingClientRect();
    return { imageWidth: imageBounds.width, imageHeight: imageBounds.height, buttonWidth: buttonBounds.width, buttonHeight: buttonBounds.height, naturalRatio: image.naturalWidth / image.naturalHeight };
  }));
  for (const measurement of measurements) {
    assert.ok(measurement.imageWidth > 0 && measurement.imageHeight > 0, JSON.stringify(measurement));
    assert.ok(Math.abs(measurement.imageWidth / measurement.imageHeight - measurement.naturalRatio) < 0.01, JSON.stringify(measurement));
    assert.ok(Math.abs(measurement.buttonWidth - measurement.imageWidth) <= 3, JSON.stringify(measurement));
    assert.ok(Math.abs(measurement.buttonHeight - measurement.imageHeight) <= 3, JSON.stringify(measurement));
  }
}

/** 화면의 남는 높이를 이미지에 배정하고 탐색 버튼이 잘리지 않는지 확인합니다. */
async function verifyViewerImageSpace(page) {
  const dialog = page.locator('#illustration-dialog');
  await expect(dialog.locator('[data-style-candidate-action], .style-card-statistics')).toHaveCount(0);
  await expect.poll(() => page.locator('.style-viewer-image').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
  await expect(page.locator('#style-viewer-image-status')).toBeEmpty();
  const measurements = await dialog.evaluate(element => {
    const dialogBounds = element.getBoundingClientRect();
    const imageFrameBounds = element.querySelector('.style-viewer-image-frame').getBoundingClientRect();
    const toolbarBounds = element.querySelector('.style-viewer-toolbar').getBoundingClientRect();
    return {
      dialogHeight: dialogBounds.height,
      imageHeight: imageFrameBounds.height,
      toolbarBottom: toolbarBounds.bottom,
      dialogBottom: dialogBounds.bottom,
      viewportHeight: innerHeight,
      maximumChromeHeight: innerWidth <= 600 ? 190 : 150,
      noOverflow: element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight,
    };
  });
  assert.ok(measurements.imageHeight >= measurements.dialogHeight - measurements.maximumChromeHeight, JSON.stringify(measurements));
  assert.ok(measurements.toolbarBottom <= measurements.dialogBottom && measurements.dialogBottom <= measurements.viewportHeight, JSON.stringify(measurements));
  assert.ok(measurements.noOverflow, JSON.stringify(measurements));
}

/** 작은 Mobile 화면에서도 위·아래 Backdrop을 실제로 눌러 닫을 수 있는지 확인합니다. */
async function verifyMobileViewerBackdrop(page, opener, width, height) {
  await page.setViewportSize({ width, height });
  const dialog = page.locator('#illustration-dialog');
  for (const backdropSide of ['top', 'bottom']) {
    await opener.click();
    await expect(dialog).toBeVisible();
    await expect.poll(() => page.locator('.style-viewer-image').evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
    await verifyViewerImageSpace(page);
    const bounds = await dialog.boundingBox();
    assert.ok(bounds.y >= 44 && height - bounds.y - bounds.height >= 44, JSON.stringify({ width, height, bounds }));
    assert.ok(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth));
    if (backdropSide === 'top' && height === 844) {
      await page.locator('.style-viewer-image').click();
      await expect(dialog).toBeVisible();
      const imageBounds = await page.locator('.style-viewer-image').boundingBox();
      await page.mouse.move(imageBounds.x + imageBounds.width / 2, imageBounds.y + imageBounds.height / 2);
      await page.mouse.down();
      await page.mouse.move(width / 2, bounds.y / 2);
      await page.mouse.up();
      await expect(dialog).toBeVisible();
    }
    const backdropY = backdropSide === 'top' ? bounds.y / 2 : (bounds.y + bounds.height + height) / 2;
    await page.touchscreen.tap(width / 2, backdropY);
    await expect(dialog).not.toBeVisible();
  }
}

/** 세 가지 이미지 비율·1/3/5개 Prompt·카드 Fit·Backdrop 닫기를 함께 검증합니다. */
async function verifyStyleLibrary() {
  const baseUrl = 'http://127.0.0.1:18388';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const browserErrors = [];
  const scenarios = [];
  try {
    const context = await browser.newContext({ hasTouch: true });
    await context.request.post(`${baseUrl}/api/login`, { data: { password: 'test' } });
    const page = await context.newPage();
    page.on('pageerror', error => browserErrors.push(error.message));
    for (const promptCount of [1, 3, 5]) {
      const project = await createStyleLibraryScenario(context, baseUrl, promptCount);
      await page.setViewportSize({ width: 1280, height: 1000 });
      await page.goto(`${baseUrl}/style#candidates`);
      await page.reload();
      await page.locator('#active-project-picker').selectOption(project.identifier);
      await expect(page.locator('.style-library-card')).toHaveCount(2, { timeout: 10000 });
      const firstCard = page.locator(`.style-library-card[data-style-candidate="${project.candidateIdentifiers[0]}"]`);
      await expect(firstCard).toBeVisible();
      await expect(firstCard.locator('.style-card-thumbnail')).toHaveCount(promptCount);
      await expect(page.locator('.generation-result-grid')).toHaveCount(0);
      await expect(firstCard.locator('img').first()).toBeVisible();
      const thumbnailWidth = await firstCard.locator('img').first().evaluate(image => image.getBoundingClientRect().width);
      assert.ok(thumbnailWidth > 0 && thumbnailWidth < 120, String(thumbnailWidth));
      await firstCard.locator('.style-card-heading').click();
      await verifyViewerImageSpace(page);
      await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText(`1 / ${promptCount}`);
      await expect(page.locator('[data-style-library-action=previous]')).toBeDisabled();
      if (promptCount === 1) await expect(page.locator('[data-style-library-action=next]')).toBeDisabled();
      else {
        const candidateIdentifier = await firstCard.getAttribute('data-style-candidate');
        const results = await (await context.request.get(`${baseUrl}/api/style-projects/${project.identifier}/generation-results`)).json();
        const candidate = results.candidates.find(item => item.identifier === candidateIdentifier);
        const candidatePaths = candidate.renders.flatMap(render => render.files.map(file => file.path));
        for (let index = 1; index < promptCount; index += 1) {
          await page.locator('[data-style-library-action=next]').click();
          await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText(`${index + 1} / ${promptCount}`);
          const imageSource = await page.locator('.style-viewer-image').getAttribute('src');
          assert.ok(candidatePaths.some(path => decodeURIComponent(imageSource).endsWith(path)), imageSource);
        }
        await expect(page.locator('[data-style-library-action=next]')).toBeDisabled();
        await page.keyboard.press('ArrowLeft');
        await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText(`${promptCount - 1} / ${promptCount}`);
      }
      await page.keyboard.press('Escape');
      await expect(page.locator('#illustration-dialog')).not.toBeVisible();
      await firstCard.locator('[data-library-case-index]').last().click();
      await expect(page.locator('.style-viewer-navigation [role=status]')).toHaveText(`${promptCount} / ${promptCount}`);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: `runtime/verification/style-library-viewer-${promptCount}-mobile.png`, fullPage: true });
      await page.locator('[data-style-library-action=close]').click();
      for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 640 }, { width: 390, height: 560 }, { width: 768, height: 390 }]) {
        await verifyMobileViewerBackdrop(page, firstCard.locator('.style-card-heading'), viewport.width, viewport.height);
      }
      for (const width of [320, 390, 768, 1280]) {
        await page.setViewportSize({ width, height: 1000 });
        const dimensions = await page.evaluate(() => ({ width: innerWidth, contentWidth: document.documentElement.scrollWidth }));
        assert.ok(dimensions.contentWidth <= dimensions.width, JSON.stringify(dimensions));
      }
      if (promptCount === 5) {
        await page.screenshot({ path: 'runtime/verification/style-library-desktop.png', fullPage: true });
        await page.setViewportSize({ width: 390, height: 844 });
        await page.screenshot({ path: 'runtime/verification/style-library-mobile.png', fullPage: true });
      }
      await page.goto(`${baseUrl}/style#compare`);
      await expect(page.locator('.case-section:visible')).toHaveCount(promptCount, { timeout: 10000 });
      for (const width of [320, 390, 768, 1280]) {
        await page.setViewportSize({ width, height: 1000 });
        await verifyComparisonCardFit(page);
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator('[data-action=image-layout]').click();
      await verifyComparisonCardFit(page);
      await page.locator('[data-action=image-layout]').click();
      await expect(page.locator('[data-action=switch-case]')).toHaveCount(0);
      await expect(page.locator('.case-tabs')).toHaveCount(0);
      await page.locator('.case-section').last().scrollIntoViewIfNeeded();
      await expect(page.locator('.case-section').last()).toContainText(`Prompt ${promptCount}`);
      if (promptCount === 5) {
        const sectionHandle = await page.locator('.case-section').last().elementHandle();
        const previousScroll = await page.evaluate(() => scrollY);
        await page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/generation-results'));
        assert.ok(await sectionHandle.evaluate(section => section.isConnected));
        assert.ok(Math.abs((await page.evaluate(() => scrollY)) - previousScroll) <= 1);
      }
      const buttonColors = await page.locator('.vote-choice').evaluateAll(buttons => buttons.map(button => {
        const style = getComputedStyle(button);
        return { background: style.backgroundColor, foreground: style.color, opacity: style.opacity };
      }));
      assert.notEqual(buttonColors[0].background, buttonColors[1].background);
      for (const colors of buttonColors) {
        const luminances = [relativeLuminance(colors.background), relativeLuminance(colors.foreground)].sort((first, second) => second - first);
        assert.ok((luminances[0] + 0.05) / (luminances[1] + 0.05) >= 4.5, JSON.stringify(colors));
        assert.equal(colors.opacity, '1');
      }
      await page.locator('.case-section .image-button').first().click();
      await expect(page.locator('#illustration-dialog')).toBeVisible();
      await expect(page.locator('.style-viewer-navigation')).toHaveCount(1);
      await expect(page.locator('#style-viewer-original-toggle')).toBeChecked({ checked: await page.evaluate(() => innerWidth >= 801) });
      await page.locator('[data-style-library-action=close]').click();
      scenarios.push({ promptCount, cardCount: 2, thumbnailWidth, buttonColors });
    }
    await page.goto(`${baseUrl}/style-preview#compare`);
    await expect(page.locator('.case-section:visible')).toHaveCount(2);
    await expect(page.locator('[data-action=switch-case]')).toHaveCount(0);
    assert.deepEqual(browserErrors, []);
    fs.writeFileSync('runtime/verification/style-library-browser-results.json', JSON.stringify({ scenarios, browserErrors, viewerBoundaries: true, keyboardNavigation: true, comparisonScroll: true }, null, 2));
    console.log('Style library and comparison scrolling Browser verification passed');
  } finally {
    await browser.close();
  }
}

verifyStyleLibrary().catch(error => { console.error(error); process.exitCode = 1; });
