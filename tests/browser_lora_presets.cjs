/** Mock API를 사용하는 Edge에서 LoRA 조합과 작업 계층의 UI 흐름을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
const savedPromptPresets = [];
const savedPresets = [];
const batchSubmissions = [];
const savedJobs = [];
const outputQueries = [];
const mockOutputFiles = [];
const previewRequests = [];
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
  else if (requestPath === "/api/jobs") {
    const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
    const pageSize = Number(requestUrl.searchParams.get("page_size") || 10);
    response = {
      items: savedJobs.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
      page: pageNumber, page_size: pageSize, total: savedJobs.length,
      total_pages: Math.max(1, Math.ceil(savedJobs.length / pageSize)),
      active_count: savedJobs.filter(job => job.requests.some(child =>
        ["submitting", "pending", "running", "cancelling"].includes(child.status))).length,
    };
  }
  else if (requestPath === "/api/presets" && method === "GET") response = savedPromptPresets;
  else if (requestPath === "/api/presets" && method === "POST") {
    const payload = request.postDataJSON();
    const savedIndex = savedPromptPresets.findIndex(preset => preset.preset_id === payload.preset_id);
    response = {
      ...payload,
      preset_id: payload.preset_id || `prompt-${savedPromptPresets.length + 1}`,
      version: savedIndex < 0 ? 1 : savedPromptPresets[savedIndex].version + 1,
      updated_at: "2026-10-07",
    };
    if (savedIndex < 0) savedPromptPresets.push(structuredClone(response));
    else savedPromptPresets[savedIndex] = structuredClone(response);
  }
  else if (requestPath === "/api/outputs") {
    outputQueries.push(requestUrl.search);
    const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
    const pageSize = Number(requestUrl.searchParams.get("page_size") || 24);
    const selectedFiles = requestUrl.searchParams.has("job_id") || requestUrl.searchParams.has("request_id")
      ? [] : mockOutputFiles;
    response = {
      files: selectedFiles.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
      page: pageNumber, page_size: pageSize, total: selectedFiles.length,
      total_pages: Math.max(1, Math.ceil(selectedFiles.length / pageSize)),
    };
  }
  else if (requestPath.startsWith("/api/outputs/preview/")) {
    previewRequests.push(requestPath);
    await route.fulfill({
      contentType: "image/gif",
      body: Buffer.from("R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=", "base64"),
    });
    return;
  }
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
    response = { job_id: "test-job", request_ids: ["request-1", "request-2"] };
    savedJobs.push({
      job_id: "test-job", workflow: "anima", description: request.postDataJSON().description, request_count: 2,
      created_at: "2026-10-07", status: "pending", status_counts: { pending: 1, completed: 1 },
      requests: [
        { request_id: "request-1", request_index: 1, prompt_id: "prompt-1", status: "pending", detail: {} },
        { request_id: "request-2", request_index: 2, prompt_id: "prompt-2", status: "completed", detail: { resolved: { prompt: "portrait" } } },
      ],
    });
  } else if (requestPath === "/api/requests/request-1/cancel") {
    savedJobs[0].requests[0].status = "cancelled";
    savedJobs[0].status = "partial";
    savedJobs[0].status_counts = { cancelled: 1, completed: 1 };
    response = { status: "cancelling" };
  } else if (requestPath.startsWith("/api/jobs/") && method === "DELETE") {
    const jobIdentifier = requestPath.split("/").at(-1);
    savedJobs.splice(savedJobs.findIndex(job => job.job_id === jobIdentifier), 1);
    response = { deleted: true, deleted_files: requestUrl.searchParams.has("delete_outputs") ? 1 : 0, missing_files: 0 };
  } else if (requestPath.startsWith("/api/jobs/") && requestPath.endsWith("/cancel")) {
    const jobIdentifier = requestPath.split("/").at(-2);
    const selectedJob = savedJobs.find(job => job.job_id === jobIdentifier);
    const activeRequests = selectedJob.requests.filter(child => ["pending", "running"].includes(child.status));
    for (const child of activeRequests) child.status = "cancelled";
    selectedJob.status = "cancelled";
    response = { cancelled_count: activeRequests.length, failed_count: 0 };
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

/** LoRA 조합, 작업 계층, 결과 필터와 mobile 화면을 검증합니다. */
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
    await page.locator("#job-description").fill("아침 조명 비교");
    await page.locator("#submit-button").click();
    await page.waitForFunction(() => document.getElementById("view-jobs").classList.contains("hidden") === false);
    assert.equal(batchSubmissions[0].count, 2);
    assert.equal(batchSubmissions[0].loras[0].strength, 0.85);
    assert.equal(batchSubmissions[0].description, "아침 조명 비교");
    assert.equal(await page.locator(".job-card").count(), 1);
    assert.equal(await page.locator(".job-description").textContent(), "아침 조명 비교");
    assert.equal(await page.locator(".job-card .status-badge").first().textContent(), "대기");
    await page.locator(".job-requests summary").click();
    assert.equal(await page.locator(".job-request").count(), 2);
    await page.locator('[data-cancel-request="request-1"]').click();
    await page.locator(".job-card .status-badge").first().getByText("일부 완료").waitFor();
    assert.equal(await page.locator(".job-requests").getAttribute("open"), "");
    await page.locator('[data-show-job-results="test-job"]').click();
    await page.waitForFunction(() => document.getElementById("view-outputs").classList.contains("hidden") === false);
    assert.ok(outputQueries.some(query => new URLSearchParams(query).get("job_id") === "test-job"));
    await page.locator('.sidebar [data-view="jobs"]').click();
    await page.locator('[data-show-request-results="request-2"]').click();
    assert.ok(outputQueries.some(query => new URLSearchParams(query).get("request_id") === "request-2"));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.mobile-nav [data-view="lora-presets"]').click();
    await page.locator('[data-edit-lora-preset="preset-3"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(screenshotDirectory, "lora-presets-mobile.png"), fullPage: true });
    await page.locator('.mobile-nav [data-view="generate"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(await page.locator("#generate-count-field + #submit-button").count(), 1);
    await page.screenshot({ path: path.join(screenshotDirectory, "generate-mobile.png"), fullPage: true });
    await page.locator('.mobile-nav [data-view="jobs"]').click();
    await page.locator(".job-requests[open]").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(screenshotDirectory, "jobs-mobile.png"), fullPage: true });
    for (let jobNumber = 0; jobNumber < 10; jobNumber += 1) {
      savedJobs.push({
        job_id: `old-job-${jobNumber}`, workflow: "anima", description: `이전 작업 ${jobNumber}`,
        request_count: 1, created_at: "2026-10-06", status: "completed",
        status_counts: { completed: 1 }, requests: [{
          request_id: `old-request-${jobNumber}`, request_index: 1,
          prompt_id: `old-prompt-${jobNumber}`, status: "completed", detail: {},
        }],
      });
    }
    await page.locator('.mobile-nav [data-view="generate"]').click();
    await page.locator('.mobile-nav [data-view="jobs"]').click();
    await page.locator('[data-jobs-page="2"]').first().click();
    await page.locator('.job-card').first().getByText('이전 작업 9').waitFor();
    page.once("dialog", dialog => dialog.accept());
    await page.locator('[data-delete-job="old-job-9"]').click();
    await page.locator('[data-delete-job-outputs="test-job"]').waitFor();
    assert.equal(savedJobs.some(job => job.job_id === "old-job-9"), false);
    page.once("dialog", dialog => dialog.accept());
    await page.locator('[data-delete-job-outputs="test-job"]').click();
    await page.locator('[data-delete-job-outputs="test-job"]').waitFor({ state: "detached" });
    assert.equal(savedJobs.some(job => job.job_id === "test-job"), false);
    for (let outputNumber = 0; outputNumber < 26; outputNumber += 1) {
      const isVideo = outputNumber === 0;
      const filename = `result-${String(outputNumber).padStart(2, "0")}.${isVideo ? "webm" : "png"}`;
      mockOutputFiles.push({
        path: `anima/${filename}`, name: filename, size: 2048,
        modified_at: 100 - outputNumber, kind: isVideo ? "video" : "image",
      });
    }
    await page.setViewportSize({ width: 1280, height: 950 });
    await page.locator('.sidebar [data-view="outputs"]').click();
    await page.locator("#refresh-outputs-button").click();
    await page.locator(".output-card").first().waitFor();
    assert.equal(await page.locator(".output-card").count(), 24);
    assert.equal(await page.locator(".output-video-placeholder").count(), 1);
    assert.equal(await page.locator(".output-card img").count(), 23);
    assert.equal(await page.locator('.output-card img[src^="/api/outputs/preview/"]').count(), 23);
    await page.locator('#outputs-pagination [data-outputs-page="2"]').first().click();
    await page.waitForFunction(() => document.querySelectorAll(".output-card").length === 2);
    assert.ok(outputQueries.some(query => new URLSearchParams(query).get("page") === "2"));
    await page.locator("#refresh-outputs-button").click();
    await page.waitForFunction(() => document.querySelectorAll(".output-card").length === 24);
    assert.ok(previewRequests.length > 0);
    const scenarioPage = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    await scenarioPage.route("**/*", handleBrowserRequest);
    await scenarioPage.goto("http://home-server.test/");
    await scenarioPage.locator('#available-loras option[value="first.safetensors"]').waitFor({ state: "attached" });
    await scenarioPage.locator('.sidebar [data-view="prompts"]').click();
    await scenarioPage.locator("#preset-name").fill("다중 상황 Prompt");
    await scenarioPage.locator("#preset-prefix").fill("portrait");
    await scenarioPage.locator("#add-scenario-button").click();
    await scenarioPage.locator(".scenario-editor-card").waitFor();
    await scenarioPage.locator('.scenario-editor-card [data-scenario-field="name"]').fill("주간");
    await scenarioPage.locator('.scenario-editor-card [data-scenario-field="situation"]').fill("daylight");
    await scenarioPage.locator("#save-preset-button").click();
    await scenarioPage.waitForFunction(() => document.getElementById("preset-version").textContent === "현재 v1");
    await scenarioPage.locator("#add-scenario-button").click();
    assert.equal(await scenarioPage.locator(".scenario-editor-card").count(), 2);
    await scenarioPage.locator('.scenario-editor-card [data-scenario-field="name"]').nth(1).fill("야간");
    await scenarioPage.locator('.scenario-editor-card [data-scenario-field="situation"]').nth(1).fill("nightlight");
    await scenarioPage.locator("#save-preset-button").click();
    await scenarioPage.waitForFunction(() => document.getElementById("preset-version").textContent === "현재 v2");
    assert.equal(savedPromptPresets.length, 1);
    assert.deepEqual(savedPromptPresets[0].body.scenarios.map(scenario => scenario.name), ["주간", "야간"]);
    assert.equal(new Set(savedPromptPresets[0].body.scenarios.map(scenario => scenario.id)).size, 2);
    await scenarioPage.reload();
    await scenarioPage.locator('#generate-preset option[value="prompt-1"]').waitFor({ state: "attached" });
    await scenarioPage.locator("#generate-preset").selectOption("prompt-1");
    assert.equal(await scenarioPage.locator("#generate-scenarios input:checked").count(), 2);
    assert.equal(await scenarioPage.locator(".scenario-editor-card").count(), 2);
    await scenarioPage.locator("#edit-preset-button").click();
    const scenarioFields = await scenarioPage.locator('.scenario-editor-card[data-scenario-index="0"] [data-scenario-field]').all();
    const fieldPositions = [];
    for (const scenarioField of scenarioFields) {
      const fieldName = await scenarioField.getAttribute("data-scenario-field");
      if (fieldName === "name") continue;
      fieldPositions.push(await scenarioField.boundingBox());
    }
    assert.equal(fieldPositions.length, 6);
    for (let fieldIndex = 1; fieldIndex < fieldPositions.length; fieldIndex += 1) {
      assert.ok(fieldPositions[fieldIndex].y > fieldPositions[fieldIndex - 1].y);
      assert.equal(fieldPositions[fieldIndex].x, fieldPositions[0].x);
    }
    await scenarioPage.close();
    assert.deepEqual(pageErrors, []);
    console.log("Passed: LoRA presets, grouped jobs, pagination, cancellation, deletion, multiple scenarios, mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
