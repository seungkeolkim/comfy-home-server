/** Prompt 관리의 저장 대상·버전·생성 화면 독립성과 모바일 탐색을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");
const screenshotDirectory = path.join(projectDirectory, "runtime", "prompt-manager-inspection");

/** 운영 데이터에 접근하지 않는 서로 다른 Workflow의 Prompt와 버전 이력을 만듭니다. */
function createPromptFixtures() {
  const savedAt = "2026-10-20T01:00:00Z";
  const presets = [
    { preset_id: "portrait", name: "인물 Template", workflow: "anima", version: 2,
      body: { prompt: "portrait, daylight, latest", negative: "blur" }, updated_at: savedAt },
    { preset_id: "landscape", name: "풍경 Template", workflow: "anima", version: 1,
      body: { prompt: "mountains, landscape", negative: "text" }, updated_at: savedAt },
    { preset_id: "motion", name: "영상 Template", workflow: "minimax_h3", version: 1,
      body: { prompt: "A camera moves through a forest." }, updated_at: savedAt },
  ];
  const versions = new Map(presets.map(preset => [preset.preset_id,
    [{ version: preset.version, body: structuredClone(preset.body), saved_at: savedAt }]]));
  versions.get("portrait").push({ version: 1, body: { prompt: "portrait, earlier", negative: "old negative" }, saved_at: savedAt });
  return { presets, versions, mutations: [], rejectSave: false, saveGate: null,
    rejectVersions: false, versionGates: new Map(), versionReads: [] };
}

/** 실제 UI 파일과 격리된 Prompt API를 연결하고 저장 실패와 지연을 제어합니다. */
function createPromptHandler(fixtures) {
  return async function handlePromptRequest(route) {
    const requestPath = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (await handleJobFolderReadRequest(route)) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const fileName = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({ contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[fileName],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", fileName), "utf8") });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/jobs") response = { items: [], total: 0, total_pages: 1, active_count: 0 };
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/loras/presets") response = [];
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/presets" && method === "GET") response = fixtures.presets;
    else if (requestPath === "/api/presets" && method === "POST") {
      const payload = route.request().postDataJSON();
      fixtures.mutations.push(payload);
      if (fixtures.saveGate) await fixtures.saveGate;
      if (fixtures.rejectSave) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "저장 실패 테스트" }) });
        return;
      }
      const existingIndex = fixtures.presets.findIndex(preset => preset.preset_id === payload.preset_id);
      const existingPreset = fixtures.presets[existingIndex];
      response = { ...payload, preset_id: payload.preset_id || `new-prompt-${fixtures.mutations.length}`,
        version: existingPreset ? existingPreset.version + 1 : 1, updated_at: "2026-10-20T02:00:00Z" };
      if (existingIndex >= 0) fixtures.presets.splice(existingIndex, 1);
      fixtures.presets.unshift(response);
      const previousVersions = fixtures.versions.get(response.preset_id) || [];
      fixtures.versions.set(response.preset_id, [{ version: response.version, body: response.body, saved_at: response.updated_at }, ...previousVersions]);
    } else if (/^\/api\/presets\/[^/]+\/versions$/.test(requestPath)) {
      const presetIdentifier = requestPath.split("/")[3];
      fixtures.versionReads.push(presetIdentifier);
      if (fixtures.versionGates.has(presetIdentifier)) await fixtures.versionGates.get(presetIdentifier);
      if (fixtures.rejectVersions) {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "버전 조회 실패 테스트" }) });
        return;
      }
      response = fixtures.versions.get(presetIdentifier) || [];
    } else throw new Error(`Unexpected request: ${method} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 현재 모바일 상세를 목록으로 돌려 같은 선택 동작을 Desktop과 공유합니다. */
async function openPromptFromList(page, presetIdentifier, versions = false) {
  if (await page.locator("#prompt-list-back").isVisible()) await page.locator("#prompt-list-back").click();
  await page.locator(`[${versions ? "data-show-versions" : "data-load-preset"}="${presetIdentifier}"]`).click();
}

/** 잘못된 대상 저장과 입력 손실을 막고 버전·생성·모바일 흐름을 함께 확인합니다. */
async function verifyPromptManager(browser, viewport) {
  const fixtures = createPromptFixtures();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createPromptHandler(fixtures));
  const navigationSelector = viewport.width <= 800 ? ".mobile-nav" : ".sidebar";
  try {
    await page.goto("http://prompt-manager.test/?view=prompts");
    await page.locator('[data-load-preset="portrait"]').waitFor();
    assert.equal(await page.locator("[data-load-preset]").count(), 3);
    await page.locator("#preset-search").fill("mountains");
    assert.equal(await page.locator("[data-load-preset]").count(), 1);
    await page.locator("#preset-search").fill("");
    await page.locator("#preset-workflow-filter").selectOption("minimax_h3");
    assert.equal(await page.locator("[data-load-preset]").count(), 1);
    await page.locator("#preset-workflow-filter").selectOption("");

    await openPromptFromList(page, "portrait");
    assert.equal(await page.locator("#preset-workflow").isDisabled(), true);
    assert.equal(await page.locator("#save-preset-button").isDisabled(), true);
    assert.match(await page.locator("#preset-version").textContent(), /v2 편집 중/);
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "");
    await page.locator("#preset-history-tab").click();
    await page.locator('[data-preview-version="1"]').waitFor();
    assert.match(await page.locator("#preset-history-title").textContent(), /인물 Template/);
    if (viewport.width <= 800) {
      await page.locator("#prompt-list-back").click();
      await page.locator('[data-show-versions="portrait"]').click();
      assert.equal(await page.locator("#preset-history-panel").isVisible(), true);
    }
    await page.locator('[data-preview-version="1"]').click();
    assert.equal(await page.locator("#preset-preview-prompt").textContent(), "portrait, earlier");
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, daylight, latest");
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "");
    await page.locator("#load-preset-version-button").click();
    assert.match(await page.locator("#preset-version").textContent(), /v1에서 시작 · 최신 v2/);
    assert.equal(await page.locator("#save-preset-button").textContent(), "v3으로 저장");
    assert.equal(await page.locator("#save-preset-button").isEnabled(), true);
    await page.locator("#use-preset-button").click();
    assert.match(await page.locator("#generate-prompt-status").textContent(), /v1 사용 중 · 최신 v2/);
    assert.match(await page.locator("#generate-preset option:checked").textContent(), /v1 사용 중 · 최신 v2/);
    await page.locator("#generate-anima-prompt").fill("portrait, edited generation");
    assert.match(await page.locator("#generate-prompt-status").textContent(), /v1에서 수정됨/);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, earlier");
    await page.locator("#edit-preset-button").click();
    assert.match(await page.locator("#preset-version").textContent(), /변경됨/);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, edited generation");

    await page.locator(`${navigationSelector} [data-view="tags"]`).click();
    await page.locator(`${navigationSelector} [data-view="prompts"]`).click();
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, edited generation");
    page.once("dialog", dialog => dialog.dismiss());
    await page.locator("#new-preset-detail-button").click();
    assert.equal(await page.locator("#preset-name").inputValue(), "인물 Template");
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#new-preset-detail-button").click();
    assert.equal(await page.locator("#preset-name").inputValue(), "");
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "");
    assert.equal(await page.locator("#preset-workflow").isEnabled(), true);
    assert.equal(await page.locator("#preset-history-tab").isDisabled(), true);
    assert.equal(await page.locator("#preset-version-history").textContent(), "");

    await page.locator("#preset-name").fill("새 Prompt 확인");
    await page.locator("#preset-anima-prompt").fill("<img src=x onerror=alert(1)> new prompt");
    await page.locator("#preset-negative").fill("new negative");
    fixtures.rejectSave = true;
    await page.locator("#save-preset-button").click();
    await page.locator("#preset-editor-error").filter({ hasText: "저장 실패 테스트" }).waitFor();
    assert.equal(fixtures.mutations.at(-1).preset_id, null);
    assert.equal(await page.locator("#preset-name").inputValue(), "새 Prompt 확인");
    assert.equal(await page.locator("#save-preset-button").isEnabled(), true);
    fixtures.rejectSave = false;
    let releaseSave;
    fixtures.saveGate = new Promise(resolve => { releaseSave = resolve; });
    await page.locator("#save-preset-button").click();
    await page.waitForFunction(() => document.getElementById("preset-name").disabled);
    assert.equal(await page.locator("#new-preset-detail-button").isDisabled(), true);
    assert.equal(await page.locator("#use-preset-button").isDisabled(), true);
    const requestCount = fixtures.mutations.length;
    await page.evaluate(() => savePreset());
    assert.equal(fixtures.mutations.length, requestCount);
    releaseSave();
    fixtures.saveGate = null;
    await page.waitForFunction(() => document.getElementById("preset-version").textContent === "v1 편집 중");
    assert.match(await page.locator("#preset-save-message").textContent(), /새 Prompt 확인 v1을 저장/);
    assert.equal(fixtures.presets.find(preset => preset.preset_id === "portrait").version, 2);
    assert.equal(await page.locator("#save-preset-button").isDisabled(), true);
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "portrait, edited generation");
    assert.equal(await page.locator("#preset-edit-panel img").count(), 0);
    const newPresetIdentifier = fixtures.presets[0].preset_id;
    await page.locator("#preset-name").fill("새 Prompt 이름 수정");
    await page.locator("#save-preset-button").click();
    await page.waitForFunction(() => document.getElementById("preset-version").textContent === "v2 편집 중");
    assert.equal(fixtures.mutations.at(-1).preset_id, newPresetIdentifier);
    assert.match(await page.locator("#prompt-editor-title").textContent(), /이름 수정/);

    await page.locator("#copy-preset-button").click();
    assert.equal(await page.locator("#preset-name").inputValue(), "새 Prompt 이름 수정 복사");
    assert.match(await page.locator("#preset-version").textContent(), /새 Prompt/);
    assert.equal(await page.locator("#save-preset-button").textContent(), "새 Prompt 저장");
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#new-preset-detail-button").click();

    await page.locator(`${navigationSelector} [data-view="generate"]`).click();
    await page.locator("#generate-preset").selectOption("");
    await page.locator("#edit-preset-button").click();
    assert.equal(await page.locator("#preset-name").inputValue(), "");
    assert.match(await page.locator("#preset-version").textContent(), /새 Prompt/);
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#new-preset-detail-button").click();

    fixtures.rejectVersions = true;
    await openPromptFromList(page, "portrait", true);
    await page.locator("#retry-preset-versions").waitFor();
    fixtures.rejectVersions = false;
    await page.locator("#retry-preset-versions").click();
    await page.locator('[data-preview-version="1"]').waitFor();
    let releaseVersions;
    fixtures.versionGates.set("portrait", new Promise(resolve => { releaseVersions = resolve; }));
    await page.locator("#preset-edit-tab").click();
    await page.locator("#preset-history-tab").click();
    await page.waitForFunction(() => document.getElementById("preset-history-status").textContent.includes("불러오는 중"));
    await openPromptFromList(page, "motion", true);
    await page.locator("#preset-preview-prompt").filter({ hasText: "camera" }).waitFor();
    const delayedResponse = page.waitForResponse(response => response.url().endsWith("/portrait/versions"));
    releaseVersions();
    fixtures.versionGates.delete("portrait");
    await delayedResponse;
    assert.match(await page.locator("#preset-history-title").textContent(), /영상 Template/);
    assert.equal(await page.locator("[data-preview-version]").count(), 1);
    assert.equal(await page.locator("#preset-preview-negative-section").isVisible(), false);
    await page.locator("#load-preset-version-button").click();
    assert.equal(await page.locator("#preset-minimax-prompt").inputValue(), "A camera moves through a forest.");
    assert.equal(await page.locator("#generate-workflow").inputValue(), "anima");
    await page.locator("#save-preset-button").scrollIntoViewIfNeeded();
    if (viewport.width <= 800) {
      const saveBounds = await page.locator("#save-preset-button").boundingBox();
      const navigationBounds = await page.locator(".mobile-nav").boundingBox();
      assert.ok(saveBounds.y + saveBounds.height <= navigationBounds.y, "저장 버튼이 모바일 하단 메뉴에 가려지면 안 됩니다.");
      assert.equal(await page.locator("#save-preset-button").evaluate(button => {
        const bounds = button.getBoundingClientRect();
        return document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2) === button;
      }), true);
    }
    await page.screenshot({ path: path.join(screenshotDirectory, `editor-${viewport.width}.png`), fullPage: true });
    await page.screenshot({ path: path.join(screenshotDirectory, `viewport-${viewport.width}.png`) });

    if (viewport.width <= 800) {
      await page.locator("#prompt-list-back").click();
      await page.locator("#preset-search").fill("Template");
      await page.locator("#preset-workflow-filter").selectOption("anima");
      const listPosition = await page.evaluate(() => scrollY);
      await openPromptFromList(page, "landscape");
      await page.locator("#prompt-list-back").click();
      assert.equal(await page.locator("#preset-search").inputValue(), "Template");
      assert.equal(await page.locator("#preset-workflow-filter").inputValue(), "anima");
      assert.equal(await page.evaluate(() => scrollY), listPosition);
      await page.screenshot({ path: path.join(screenshotDirectory, `list-${viewport.width}.png`), fullPage: true });
    }
    await openPromptFromList(page, "portrait", true);
    await page.locator('[data-preview-version="1"]').waitFor();
    await page.locator('[data-preview-version="1"]').click();
    await page.locator("#load-preset-version-button").click();
    await page.locator("#save-preset-button").click();
    await page.waitForFunction(() => document.getElementById("preset-version").textContent === "v3 편집 중");
    assert.equal(fixtures.mutations.at(-1).preset_id, "portrait");
    assert.equal(fixtures.presets.find(preset => preset.preset_id === "portrait").body.prompt, "portrait, earlier");
    assert.deepEqual(fixtures.versions.get("portrait").map(version => version.version), [3, 2, 1]);
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "portrait, edited generation");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const reloadRequestIdentifiers = [];
    for (let reloadIndex = 0; reloadIndex < 2; reloadIndex += 1) {
      const reloadRequestPromise = page.waitForRequest(request => request.isNavigationRequest() &&
        new URL(request.url()).searchParams.get("reload_assets") === "true");
      const documentLoadedPromise = page.waitForEvent("domcontentloaded");
      await page.locator("#reload-web-assets-button").click();
      const reloadRequestUrl = new URL((await reloadRequestPromise).url());
      reloadRequestIdentifiers.push(reloadRequestUrl.searchParams.get("reload_request"));
      assert.equal(reloadRequestUrl.searchParams.get("view"), "prompts");
      await documentLoadedPromise;
      await page.locator('[data-load-preset="portrait"]').waitFor();
      assert.equal(await page.locator("#application").isVisible(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    }
    assert.ok(reloadRequestIdentifiers.every(Boolean));
    assert.notEqual(reloadRequestIdentifiers[0], reloadRequestIdentifiers[1]);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** Desktop과 좁은 모바일에서 동일한 저장·버전·상태 보호 계약을 확인합니다. */
async function main() {
  filesystem.mkdirSync(screenshotDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyPromptManager(browser, { width: 1440, height: 1000 });
    await verifyPromptManager(browser, { width: 320, height: 844 });
    console.log("Passed: prompt create/update/copy, contextual version preview, stale response protection, dirty/failure/pending safety, independent generation state, mobile navigation and repeated web asset reload.");
  } finally {
    await browser.close();
  }
}

module.exports = { createPromptFixtures, createPromptHandler };
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
