/** Mock API를 사용하는 Edge에서 LoRA 조합의 전체 UI 흐름을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
const savedPresets = [];
const batchSubmissions = [];
let availableLoras = ["first.safetensors", "second.safetensors"];

/** 브라우저에 실제 앱 파일과 GPU 작업이 없는 독립된 API 응답을 제공합니다. */
async function handleBrowserRequest(route) {
  const request = route.request();
  const requestUrl = new URL(request.url());
  const requestPath = requestUrl.pathname;
  if (["/", "/app.css", "/app.js"].includes(requestPath)) {
    const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
    const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
    await route.fulfill({ contentType: contentTypes[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
    return;
  }
  let response = {};
  const method = request.method();
  if (requestPath === "/api/session") response = { authenticated: true };
  else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
  else if (requestPath === "/api/jobs" || requestPath === "/api/presets") response = [];
  else if (requestPath === "/api/outputs") response = { files: [], total: 0 };
  else if (requestPath === "/api/loras") response = {
    files: availableLoras,
    profiles: [{ name: "first.safetensors", workflow: "anima", settings: { strength: 0.75, clip_strength: 0.55 } }],
  };
  else if (requestPath === "/api/loras/presets" && method === "GET") response = savedPresets;
  else if (requestPath === "/api/loras/presets" && method === "POST") {
    response = { ...request.postDataJSON(), preset_id: `preset-${savedPresets.length + 1}` };
    savedPresets.push(structuredClone(response));
  } else if (requestPath.startsWith("/api/loras/presets/") && method === "PUT") {
    const presetIdentifier = requestPath.split("/").at(-1);
    const presetIndex = savedPresets.findIndex(preset => preset.preset_id === presetIdentifier);
    response = { ...request.postDataJSON(), preset_id: presetIdentifier };
    savedPresets[presetIndex] = structuredClone(response);
  } else if (requestPath.startsWith("/api/loras/presets/") && method === "DELETE") {
    const presetIdentifier = requestPath.split("/").at(-1);
    savedPresets.splice(savedPresets.findIndex(preset => preset.preset_id === presetIdentifier), 1);
    response = { deleted: true };
  } else if (requestPath === "/api/batches") {
    batchSubmissions.push(request.postDataJSON());
    response = { batch_id: "test-batch", request_ids: ["request-1", "request-2"] };
  } else if (requestPath === "/favicon.ico") {
    await route.fulfill({ status: 204 });
    return;
  } else throw new Error(`Unexpected request: ${method} ${requestPath}`);
  await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
}

/** 렌더링된 카드 값을 입력하고 input 이벤트가 상태에 반영되도록 합니다. */
async function setCardWeight(page, containerIdentifier, index, field, value) {
  await page.locator(`#${containerIdentifier} [data-lora-index="${index}"] [data-lora-field="${field}"]`).fill(String(value));
}

/** 비동기 저장과 화면 갱신이 끝날 때까지 preset 선택 목록을 확인합니다. */
async function waitForPreset(page, presetIdentifier) {
  await page.locator(`[data-edit-lora-preset="${presetIdentifier}"]`).waitFor();
}

/** 원본 보존, 복제, 갱신, workflow 전환과 mobile 배치를 검증합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/*", handleBrowserRequest);
    await page.goto("http://home-server.test/");
    await page.locator('#available-loras option[value="first.safetensors"]').waitFor({ state: "attached" });
    assert.deepEqual(
      await page.locator("#view-generate .form-grid > .panel .panel-heading h3").allTextContents(),
      ["기본 설정", "상황 선택", "LoRA", "Workflow 옵션"],
    );
    assert.equal(await page.locator("#generate-count-field").isVisible(), true);
    assert.equal(await page.locator("#generate-count-field + #submit-button").count(), 1);
    await page.locator("#generate-workflow").selectOption("minimax_h3");
    assert.equal(await page.locator("#generate-scenario-fields").isVisible(), false);
    assert.equal(await page.locator("#generate-count-field").isVisible(), false);
    assert.equal(await page.locator("#lora-step").textContent(), "02");
    assert.equal(await page.locator("#workflow-options-step").textContent(), "03");
    await page.locator("#generate-workflow").selectOption("anima");
    await page.locator('.sidebar [data-view="lora-presets"]').click();
    await page.locator("#lora-preset-name").fill("Portrait combination");
    await page.locator("#lora-preset-available-files").selectOption("first.safetensors");
    await page.locator("#add-lora-preset-entry-button").click();
    await setCardWeight(page, "lora-preset-selected-files", 0, "strength", 0.6);
    await setCardWeight(page, "lora-preset-selected-files", 0, "clip_strength", 0.4);
    await page.locator("#lora-preset-available-files").selectOption("second.safetensors");
    await page.locator("#add-lora-preset-entry-button").click();
    await page.locator("#create-lora-preset-button").click();
    await waitForPreset(page, "preset-1");
    assert.equal(savedPresets[0].loras.length, 2);
    assert.equal(savedPresets[0].loras[0].strength, 0.6);
    await page.locator('[data-use-lora-preset="preset-1"]').click();
    assert.equal(await page.locator('#selected-loras [data-lora-field="strength"]').first().inputValue(), "0.6");
    await setCardWeight(page, "selected-loras", 0, "strength", 0.85);
    assert.equal(savedPresets[0].loras[0].strength, 0.6);
    await page.locator("#generate-lora-preset").selectOption("preset-1");
    assert.equal(await page.locator('#selected-loras [data-lora-field="strength"]').first().inputValue(), "0.6");
    await setCardWeight(page, "selected-loras", 0, "strength", 0.85);
    await page.locator("#save-generation-lora-preset-button").click();
    await page.locator("#cancel-generation-lora-preset-button").click();
    await page.locator("#manage-lora-presets-button").click();
    assert.equal(await page.locator('#lora-preset-selected-files [data-lora-field="strength"]').first().inputValue(), "0.85");
    assert.equal(savedPresets[0].loras[0].strength, 0.6);
    await page.locator("#use-lora-preset-editor-button").click();
    await page.locator("#save-generation-lora-preset-button").click();
    await page.locator("#generation-lora-preset-name").fill("Portrait variant");
    await page.locator('#generation-lora-preset-form button[type="submit"]').click();
    await page.locator('#generation-lora-preset-form').waitFor({ state: "hidden" });
    assert.equal(savedPresets.length, 2);
    assert.equal(savedPresets[1].loras[0].strength, 0.85);
    await page.reload();
    await page.locator('#generate-lora-preset option[value="preset-2"]').waitFor({ state: "attached" });
    await page.locator("#generate-lora-preset").selectOption("preset-2");
    assert.equal(await page.locator('#selected-loras [data-lora-field="strength"]').first().inputValue(), "0.85");
    await page.locator('.sidebar [data-view="lora-presets"]').click();
    await page.locator('[data-edit-lora-preset="preset-1"]').click();
    await setCardWeight(page, "lora-preset-selected-files", 0, "strength", 0.9);
    await page.locator("#update-lora-preset-button").click();
    await page.locator("#update-lora-preset-button").waitFor({ state: "visible" });
    await page.waitForFunction(() => document.getElementById("update-lora-preset-button").disabled);
    assert.equal(savedPresets[0].loras[0].strength, 0.9);
    assert.equal(savedPresets[1].loras[0].strength, 0.85);
    await page.locator('[data-copy-lora-preset="preset-1"]').click();
    await page.locator('#lora-preset-selected-files [data-remove-lora="1"]').click();
    await page.locator("#create-lora-preset-button").click();
    await waitForPreset(page, "preset-3");
    assert.equal(savedPresets[2].loras.length, 1);
    page.once("dialog", dialog => dialog.accept());
    await page.locator('[data-delete-lora-preset="preset-3"]').click();
    await page.locator('[data-edit-lora-preset="preset-3"]').waitFor({ state: "detached" });
    await page.locator("#new-lora-preset-button").click();
    await page.locator("#lora-preset-workflow").selectOption("minimax_h3");
    await page.locator("#lora-preset-name").fill("Motion combination");
    await page.locator("#lora-preset-available-files").selectOption("first.safetensors");
    await page.locator("#add-lora-preset-entry-button").click();
    await setCardWeight(page, "lora-preset-selected-files", 0, "strength", 0.7);
    await setCardWeight(page, "lora-preset-selected-files", 0, "video_strength", 0.8);
    await setCardWeight(page, "lora-preset-selected-files", 0, "audio_strength", 0);
    await page.locator("#create-lora-preset-button").click();
    await waitForPreset(page, "preset-3");
    assert.deepEqual(savedPresets[2].loras[0], { name: "first.safetensors", strength: 0.7, video_strength: 0.8, audio_strength: 0 });
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDirectory, "lora-presets-desktop.png"), fullPage: true });
    await page.locator('[data-use-lora-preset="preset-3"]').click();
    assert.equal(await page.locator("#generate-workflow").inputValue(), "minimax_h3");
    assert.equal(await page.locator('#generate-lora-preset option').count(), 2);
    assert.equal(await page.locator('#selected-loras [data-lora-field="audio_strength"]').inputValue(), "0");
    availableLoras = ["second.safetensors"];
    await page.locator("#refresh-loras-button").click();
    await page.locator("#selected-loras .missing-lora").waitFor();
    await page.locator("#submit-button").click();
    assert.equal(batchSubmissions.length, 0);
    availableLoras = ["first.safetensors", "second.safetensors"];
    await page.locator("#refresh-loras-button").click();
    await page.locator('.sidebar [data-view="lora-presets"]').click();
    await page.locator('[data-use-lora-preset="preset-2"]').click();
    await page.locator("#generate-prefix").fill("portrait");
    await page.locator("#generate-count").fill("2");
    await page.locator("#submit-button").click();
    await page.waitForFunction(() => document.getElementById("view-jobs").classList.contains("hidden") === false);
    assert.equal(batchSubmissions[0].count, 2);
    assert.equal(batchSubmissions[0].loras[0].strength, 0.85);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.mobile-nav [data-view="lora-presets"]').click();
    await page.locator('[data-edit-lora-preset="preset-3"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(screenshotDirectory, "lora-presets-mobile.png"), fullPage: true });
    await page.locator('.mobile-nav [data-view="generate"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(await page.locator("#generate-count-field + #submit-button").count(), 1);
    await page.screenshot({ path: path.join(screenshotDirectory, "generate-mobile.png"), fullPage: true });
    assert.deepEqual(pageErrors, []);
    console.log("Passed: save, load, isolated edits, copy, update, delete, workflow weights, missing files, submission, mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
