/** Mock API를 사용하는 Edge에서 LoRA 조합과 작업 계층의 UI 흐름을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
const savedPromptPresets = [];
const savedTagGroups = [];
const savedTagEntries = [];
const savedPresets = [];
const batchSubmissions = [];
const savedJobs = [];
const jobQueries = [];
const outputQueries = [];
const mockOutputFiles = [];
const previewRequests = [];
const tagPreviewRequests = [];
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
    jobQueries.push(requestUrl.search);
    const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
    const pageSize = Number(requestUrl.searchParams.get("page_size") || 10);
    const selectedJobId = requestUrl.searchParams.get("job_id");
    const matchingJobs = selectedJobId ? savedJobs.filter(job => job.job_id === selectedJobId) : savedJobs;
    response = {
      items: matchingJobs.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
      page: pageNumber, page_size: pageSize, total: matchingJobs.length,
      total_pages: Math.max(1, Math.ceil(matchingJobs.length / pageSize)),
      active_count: savedJobs.filter(job => job.requests.some(child =>
        ["submitting", "pending", "running", "cancelling"].includes(child.status))).length,
    };
  }
  else if (requestPath === "/api/presets" && method === "GET") response = savedPromptPresets;
  else if (requestPath === "/api/presets" && method === "POST") {
    const payload = request.postDataJSON();
    const savedBody = structuredClone(payload.body);
    const savedIndex = savedPromptPresets.findIndex(preset => preset.preset_id === payload.preset_id);
    response = {
      ...payload,
      body: savedBody,
      preset_id: payload.preset_id || `prompt-${savedPromptPresets.length + 1}`,
      version: savedIndex < 0 ? 1 : savedPromptPresets[savedIndex].version + 1,
      updated_at: "2026-10-07",
    };
    if (savedIndex < 0) savedPromptPresets.push(structuredClone(response));
    else savedPromptPresets[savedIndex] = structuredClone(response);
  }
  else if (requestPath === "/api/tags" && method === "GET") {
    response = { groups: savedTagGroups, entries: savedTagEntries };
  }
  else if (requestPath === "/api/tags/groups" && method === "POST") {
    response = { ...request.postDataJSON(), group_id: `tag-group-${savedTagGroups.length + 1}` };
    savedTagGroups.push(structuredClone(response));
  }
  else if (requestPath.startsWith("/api/tags/groups/") && method === "PUT") {
    const groupId = requestPath.split("/").at(-1);
    const groupIndex = savedTagGroups.findIndex(group => group.group_id === groupId);
    response = { ...request.postDataJSON(), group_id: groupId };
    savedTagGroups[groupIndex] = structuredClone(response);
  }
  else if (requestPath.startsWith("/api/tags/groups/") && method === "DELETE") {
    const groupId = requestPath.split("/").at(-1);
    savedTagGroups.splice(savedTagGroups.findIndex(group => group.group_id === groupId), 1);
    response = { deleted: true };
  }
  else if (requestPath === "/api/tags/entries" && method === "POST") {
    response = { ...request.postDataJSON(), tag_id: `tag-entry-${savedTagEntries.length + 1}` };
    savedTagEntries.push(structuredClone(response));
  }
  else if (requestPath.startsWith("/api/tags/entries/") && method === "PUT") {
    const tagId = requestPath.split("/").at(-1);
    const tagIndex = savedTagEntries.findIndex(entry => entry.tag_id === tagId);
    response = { ...request.postDataJSON(), tag_id: tagId };
    savedTagEntries[tagIndex] = structuredClone(response);
  }
  else if (requestPath.startsWith("/api/tags/entries/") && method === "DELETE") {
    const tagId = requestPath.split("/").at(-1);
    savedTagEntries.splice(savedTagEntries.findIndex(entry => entry.tag_id === tagId), 1);
    response = { deleted: true };
  }
  else if (requestPath === "/api/prompts/preview" && method === "POST") {
    const payload = request.postDataJSON();
    tagPreviewRequests.push(payload);
    response = {
      combined_prompt: null,
      examples: [{
        index: 1, seed: 77,
        prompt: "character A, attacking monster",
        selected_path: [
          { tag_id: "tag-entry-1", name: "몬스터 공격" },
          { tag_id: "tag-entry-2", name: "1인 a" },
        ],
      }],
    };
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
    const submission = request.postDataJSON();
    batchSubmissions.push(submission);
    response = { job_id: "test-job", request_ids: ["request-1", "request-2"] };
    savedJobs.push({
      job_id: "test-job", workflow: "anima", description: submission.description, request_count: 2,
      created_at: "2026-10-07", status: "pending", status_counts: { pending: 1, completed: 1 },
      requests: [
        { request_id: "request-1", request_index: 1, prompt_id: "prompt-1", status: "pending",
          detail: { settings: submission.settings, loras: submission.loras } },
        { request_id: "request-2", request_index: 2, prompt_id: "prompt-2", status: "completed",
          detail: { settings: submission.settings, loras: submission.loras, resolved: { prompt: "portrait" } } },
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
      await page.locator("#view-generate .form-grid > .panel:visible .panel-heading h3").allTextContents(),
      ["기본 설정", "태그 선택", "LoRA", "Workflow 옵션"],
    );
    assert.equal(await page.locator("#generate-count-field").isVisible(), true);
    assert.equal(await page.locator("#generate-count-field + #submit-button").count(), 1);
    assert.equal(await page.locator("#anima-aspect-ratio").inputValue(), "2:3");
    assert.deepEqual(await page.locator("#anima-aspect-ratio option").evaluateAll(options =>
      options.map(option => option.value)), ["16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16", "custom"]);
    assert.equal(await page.locator("#anima-resolution").inputValue(), "1024x1536");
    await page.locator("#anima-aspect-ratio").selectOption("16:9");
    assert.equal(await page.locator("#anima-resolution option").count(), 3);
    await page.locator("#anima-resolution").selectOption("1280x720");
    assert.equal(await page.locator("#anima-width").inputValue(), "1280");
    assert.equal(await page.locator("#anima-height").inputValue(), "720");
    await page.locator("#anima-aspect-ratio").selectOption("custom");
    assert.equal(await page.locator("#anima-resolution").isDisabled(), true);
    await page.locator("#anima-width").fill("1408");
    await page.locator("#anima-height").fill("960");
    assert.equal(await page.locator("#anima-width").inputValue(), "1408");
    assert.deepEqual(await page.evaluate(() => {
      const settings = generationSettings();
      return [settings.width, settings.height];
    }), [1408, 960]);
    await page.locator("#anima-aspect-ratio").selectOption("2:3");
    assert.equal(await page.locator("#anima-resolution").isDisabled(), false);
    assert.equal(await page.locator("#anima-width").inputValue(), "1024");
    assert.equal(await page.locator("#anima-height").inputValue(), "1536");
    await page.locator("#generate-workflow").selectOption("minimax_h3");
    assert.equal(await page.locator("#generate-tag-fields").isVisible(), false);
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
    await page.locator("#generate-anima-prompt").fill("portrait");
    await page.locator("#anima-aspect-ratio").selectOption("16:9");
    await page.locator("#anima-resolution").selectOption("1280x720");
    await page.locator("#generate-count").fill("2");
    await page.locator("#job-description").fill("아침 조명 비교");
    await page.locator("#submit-button").click();
    await page.waitForFunction(() => document.getElementById("submit-button").disabled === false);
    assert.equal(await page.locator("#view-generate").isVisible(), true);
    assert.equal(await page.locator("#view-jobs").isVisible(), false);
    assert.equal(await page.locator("#submit-button").textContent(), "작업 제출");
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "portrait");
    assert.equal(await page.locator("#notice").isVisible(), true);
    assert.match(await page.locator("#notice").textContent(), /작업 접수 완료 · 요청 2건/);
    assert.equal(await page.locator("#notice").evaluate(notice => notice === notice.parentElement.lastElementChild), true);
    assert.equal(await page.locator("#notice").evaluate(notice => {
      const position = notice.getBoundingClientRect();
      return position.top >= 0 && position.bottom <= window.innerHeight;
    }), true);
    assert.equal(batchSubmissions[0].count, 2);
    assert.equal(batchSubmissions[0].loras[0].strength, 0.85);
    assert.equal(batchSubmissions[0].description, "아침 조명 비교");
    assert.equal(batchSubmissions[0].settings.width, 1280);
    assert.equal(batchSubmissions[0].settings.height, 720);
    await page.locator('.sidebar [data-view="jobs"]').click();
    assert.equal(await page.locator(".job-card").count(), 1);
    assert.equal(await page.locator(".job-description").textContent(), "아침 조명 비교");
    assert.match(await page.locator(".job-card > div:first-child p").first().textContent(),
      /2026-10-07 · 16:9 · 1280 × 720 · 완료 1\/2장/);
    assert.equal(await page.locator(".job-card .status-badge").first().textContent(), "대기");
    await page.locator(".job-requests summary").click();
    assert.equal(await page.locator(".job-request").count(), 2);
    assert.match(await page.locator(".job-request").last().textContent(), /Prompt portrait/);
    assert.match(await page.locator(".job-request").last().textContent(), /LoRA first\.safetensors, second\.safetensors/);
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
    await page.evaluate(() => showNotice("모바일 알림 확인"));
    assert.equal(await page.locator("#notice").evaluate(notice => {
      const noticePosition = notice.getBoundingClientRect();
      const navigationPosition = document.querySelector(".mobile-nav").getBoundingClientRect();
      return noticePosition.top >= 0 && noticePosition.bottom < navigationPosition.top;
    }), true);
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
        job_id: isVideo ? "old-job-8" : null,
        width: isVideo ? 720 : 1024, height: isVideo ? 1280 : 1536,
        dimensions_source: isVideo ? "settings" : "file",
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
    assert.match(await page.locator(".output-card").first().locator("small").textContent(),
      /0\.0 MB · 9:16 · 720 × 1280 \(설정\)/);
    assert.match(await page.locator(".output-card").nth(1).locator("small").textContent(),
      /0\.0 MB · 2:3 · 1024 × 1536/);
    assert.equal(await page.locator(".output-card [data-output-job]").count(), 1);
    assert.notEqual(await page.locator(".output-card [data-output-job]").evaluate(button =>
      getComputedStyle(button).backgroundColor), await page.locator(".output-card [data-move-output]").first().evaluate(button =>
      getComputedStyle(button).backgroundColor));
    await page.locator('.output-card [data-output-job="old-job-8"]').click();
    await page.locator("#jobs-filter").waitFor({ state: "visible" });
    await page.locator(".job-card").first().getByText("이전 작업 8").waitFor();
    assert.equal(await page.locator(".job-card").count(), 1);
    assert.ok(jobQueries.some(query => new URLSearchParams(query).get("job_id") === "old-job-8"));
    assert.equal(await page.locator("#jobs-pagination").isVisible(), false);
    await page.locator("#clear-jobs-filter").click();
    await page.waitForFunction(() => document.querySelectorAll(".job-card").length === 9);
    await page.locator('.sidebar [data-view="outputs"]').click();
    await page.locator('#outputs-pagination [data-outputs-page="2"]').first().click();
    await page.waitForFunction(() => document.querySelectorAll(".output-card").length === 2);
    assert.ok(outputQueries.some(query => new URLSearchParams(query).get("page") === "2"));
    await page.locator("#refresh-outputs-button").click();
    await page.waitForFunction(() => document.querySelectorAll(".output-card").length === 24);
    assert.ok(previewRequests.length > 0);
    const tagPage = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const tagPageErrors = [];
    tagPage.on("pageerror", error => tagPageErrors.push(error.message));
    await tagPage.route("**/*", handleBrowserRequest);
    await tagPage.goto("http://home-server.test/");
    await tagPage.locator('.sidebar [data-view="tags"]').click();
    await tagPage.locator("#tag-group-name").fill("장면");
    await tagPage.locator('#tag-group-form button[type="submit"]').click();
    await tagPage.locator('[data-edit-tag-group="tag-group-1"]').waitFor();
    await tagPage.locator("#new-tag-group-button").click();
    await tagPage.locator("#tag-group-name").fill("캐릭터");
    await tagPage.locator("#tag-group-default-expanded").uncheck();
    await tagPage.locator('#tag-group-form button[type="submit"]').click();
    await tagPage.locator('[data-edit-tag-group="tag-group-2"]').waitFor();
    await tagPage.locator("#tag-entry-group").selectOption("tag-group-1");
    await tagPage.locator("#tag-entry-key").fill("ACTION");
    await tagPage.locator("#tag-entry-name").fill("몬스터 공격");
    await tagPage.locator("#tag-entry-content").fill("[CHR], attacking monster");
    await tagPage.locator('#tag-entry-form button[type="submit"]').click();
    await tagPage.locator('[data-edit-tag-entry="tag-entry-1"]').waitFor();
    await tagPage.locator("#tag-entry-group").selectOption("tag-group-2");
    await tagPage.locator("#tag-entry-key").fill("CHR");
    await tagPage.locator("#tag-entry-name").fill("1인 a");
    await tagPage.locator("#tag-entry-content").fill("character A");
    await tagPage.locator('#tag-entry-form button[type="submit"]').click();
    await tagPage.locator('[data-manage-tag-group-open="tag-group-2"]').waitFor();
    assert.equal(await tagPage.locator('[data-manage-tag-group-open]').count(), 2);
    assert.equal(await tagPage.locator('[data-manage-tag-group-open="tag-group-1"]').evaluate(group => group.open), true);
    assert.equal(await tagPage.locator('[data-manage-tag-group-open="tag-group-2"]').evaluate(group => group.open), false);
    assert.match(await tagPage.locator('[data-manage-tag-group-open="tag-group-2"] summary').textContent(), /1개 항목/);
    assert.equal(await tagPage.locator('[data-edit-tag-entry="tag-entry-2"]').isVisible(), false);
    await tagPage.locator('[data-manage-tag-group-open="tag-group-2"] summary').click();
    assert.equal(await tagPage.locator('[data-edit-tag-entry="tag-entry-2"]').isVisible(), true);
    await tagPage.locator('[data-manage-tag-group-open="tag-group-2"] summary').click();
    await tagPage.locator('.sidebar [data-view="generate"]').click();
    await tagPage.locator("#generate-anima-prompt").fill("[ACTION]");
    assert.match(await tagPage.locator("#tag-selection-status").textContent(), /\[ACTION\] 선택 필요/);
    assert.equal(await tagPage.locator('[data-tag-group-open="tag-group-2"]').count(), 0);
    assert.equal(await tagPage.locator('[data-tag-group-open="tag-group-1"]').evaluate(group => group.open), true);
    await tagPage.locator('[data-select-tag="tag-entry-1"]').check();
    assert.match(await tagPage.locator("#tag-selection-status").textContent(), /\[CHR\] 선택 필요/);
    assert.equal(await tagPage.locator('[data-tag-group-open="tag-group-2"]').evaluate(group => group.open), false);
    await tagPage.locator('[data-tag-group-open="tag-group-2"] summary').click();
    await tagPage.locator('[data-select-tag="tag-entry-2"]').check();
    await tagPage.locator('[data-tag-group-open="tag-group-2"] summary').click();
    assert.equal(await tagPage.locator('[data-select-tag="tag-entry-2"]').isChecked(), true);
    await tagPage.setViewportSize({ width: 390, height: 844 });
    assert.equal(await tagPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await tagPage.screenshot({ path: path.join(screenshotDirectory, "tag-selection-mobile.png"), fullPage: true });
    await tagPage.locator('.mobile-nav [data-view="tags"]').click();
    assert.equal(await tagPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await tagPage.screenshot({ path: path.join(screenshotDirectory, "tag-management-mobile.png"), fullPage: true });
    await tagPage.locator('.mobile-nav [data-view="generate"]').click();
    await tagPage.setViewportSize({ width: 1280, height: 950 });
    await tagPage.locator("#preview-button").click();
    await tagPage.locator("#preview-results").getByText("character A, attacking monster").waitFor();
    assert.deepEqual(tagPreviewRequests.at(-1).selected_tag_ids, ["tag-entry-1", "tag-entry-2"]);
    await tagPage.locator("#submit-button").click();
    await tagPage.waitForFunction(() => document.querySelector("#submit-button").disabled === false);
    assert.equal(batchSubmissions.at(-1).prompt_mode, undefined);
    assert.deepEqual(batchSubmissions.at(-1).selected_tag_ids, ["tag-entry-1", "tag-entry-2"]);
    await tagPage.locator("#save-current-preset-button").click();
    assert.equal(await tagPage.locator("#preset-anima-prompt").inputValue(), "[ACTION]");
    await tagPage.locator("#preset-name").fill("태그 조합 preset");
    await tagPage.locator("#save-preset-button").click();
    await tagPage.waitForFunction(() => document.getElementById("preset-version").textContent === "현재 v1");
    assert.deepEqual(savedPromptPresets.at(-1).body, { prompt: "[ACTION]", negative: "" });
    await tagPage.setViewportSize({ width: 390, height: 844 });
    assert.equal(await tagPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await tagPage.screenshot({ path: path.join(screenshotDirectory, "tag-preset-mobile.png"), fullPage: true });
    await tagPage.setViewportSize({ width: 1280, height: 950 });
    await tagPage.locator('.sidebar [data-view="tags"]').click();
    await tagPage.locator('[data-manage-tag-group-open="tag-group-2"] summary').click();
    await tagPage.locator('[data-edit-tag-entry="tag-entry-2"]').click();
    await tagPage.locator("#tag-entry-content").fill("character B");
    await Promise.all([
      tagPage.waitForResponse(response => response.url().endsWith("/api/tags/entries/tag-entry-2") && response.request().method() === "PUT"),
      tagPage.locator('#tag-entry-form button[type="submit"]').click(),
    ]);
    await tagPage.locator('.sidebar [data-view="generate"]').click();
    assert.match(await tagPage.locator("#tag-selection-status").textContent(), /\[ACTION\] 선택 필요/);
    await tagPage.locator('[data-select-tag="tag-entry-1"]').check();
    await tagPage.locator('[data-tag-group-open="tag-group-2"] summary').click();
    await tagPage.locator('[data-select-tag="tag-entry-2"]').check();
    await Promise.all([
      tagPage.waitForResponse(response => response.url().endsWith("/api/prompts/preview")),
      tagPage.locator("#preview-button").click(),
    ]);
    assert.deepEqual(tagPreviewRequests.at(-1).body, { prompt: "[ACTION]", negative: "" });
    assert.deepEqual(tagPreviewRequests.at(-1).selected_tag_ids, ["tag-entry-1", "tag-entry-2"]);
    await tagPage.locator('.sidebar [data-view="tags"]').click();
    await tagPage.locator("#new-tag-group-button").click();
    await tagPage.locator("#tag-group-name").fill("가장 앞");
    await tagPage.locator('#tag-group-form button[type="submit"]').click();
    await tagPage.locator('[data-manage-tag-group-open="tag-group-3"]').waitFor();
    await tagPage.locator("#tag-entry-group").selectOption("tag-group-1");
    await tagPage.locator("#tag-entry-key").fill("ACTION");
    await tagPage.locator("#tag-entry-name").fill("걷기");
    await tagPage.locator("#tag-entry-content").fill("walking");
    await tagPage.locator('#tag-entry-form button[type="submit"]').click();
    await tagPage.locator('[data-edit-tag-entry="tag-entry-3"]').waitFor();
    await tagPage.locator("#tag-entry-group").selectOption("tag-group-3");
    await tagPage.locator("#tag-entry-key").fill("ACTION");
    await tagPage.locator("#tag-entry-name").fill("새 장면");
    await tagPage.locator("#tag-entry-content").fill("new action");
    await tagPage.locator('#tag-entry-form button[type="submit"]').click();
    await tagPage.locator('[data-edit-tag-entry="tag-entry-4"]').waitFor();
    assert.deepEqual(await tagPage.locator("[data-manage-tag-group-open]").evaluateAll(
      groups => groups.map(group => group.dataset.manageTagGroupOpen),
    ), ["tag-group-3", "tag-group-1", "tag-group-2"]);
    assert.deepEqual(await tagPage.locator("#tag-group-list [data-edit-tag-group]").evaluateAll(
      buttons => buttons.map(button => button.dataset.editTagGroup),
    ), ["tag-group-3", "tag-group-1", "tag-group-2"]);
    assert.deepEqual(await tagPage.locator("#tag-entry-group option").evaluateAll(
      options => options.map(option => option.value),
    ), ["tag-group-3", "tag-group-1", "tag-group-2"]);
    assert.deepEqual(await tagPage.locator('[data-manage-tag-group-open="tag-group-1"] .tag-entry-row strong').allTextContents(),
      ["걷기", "몬스터 공격"]);
    await tagPage.locator('.sidebar [data-view="generate"]').click();
    assert.deepEqual(await tagPage.locator("[data-tag-group-open]").evaluateAll(
      groups => groups.map(group => group.dataset.tagGroupOpen),
    ), ["tag-group-3", "tag-group-1", "tag-group-2"]);
    assert.deepEqual(await tagPage.locator('[data-tag-group-open="tag-group-1"] .tag-choice strong').allTextContents(),
      ["걷기", "몬스터 공격"]);
    assert.deepEqual(tagPageErrors, []);
    await tagPage.close();
    assert.deepEqual(pageErrors, []);
    console.log("Passed: LoRA presets, grouped jobs, tag groups and selection, mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
