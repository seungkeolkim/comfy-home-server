/** Mock API와 Edge에서 상위 작업의 생성 입력 복원과 현재 목록 적용을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 과거 후보와 현재 태그 정의가 다른 두 Workflow의 작업을 준비합니다. */
function createRestorationFixtures() {
  const originalAnimaBody = { prompt: "[SCENE], {morning|evening}", negative: "blurry [CHR]" };
  const animaLoras = [{ name: "image.safetensors", strength: 0.7, clip_strength: 0.4 }];
  const minimaxLoras = [{ name: "video.safetensors", strength: 0.8, video_strength: 0.3, audio_strength: 1.5 }];
  const tagGroups = [
    { group_id: "scene-group", name: "장면", tag_key: "SCENE", default_expanded: true },
    { group_id: "character-group", name: "인물", tag_key: "CHR", default_expanded: true },
    { group_id: "side-group", name: "다른 참조", tag_key: "SIDE", default_expanded: true },
  ];
  const tagEntries = [
    { tag_id: "scene", group_id: "scene-group", name: "현재 장면", content: "[CHR], current scene", weight: 1 },
    { tag_id: "character-a", group_id: "character-group", name: "인물 A", content: "character A", weight: 1 },
    { tag_id: "character-b", group_id: "character-group", name: "변경된 인물 B", content: "current character B", weight: 3 },
    { tag_id: "moved-character", group_id: "side-group", name: "이동된 인물", content: "moved character", weight: 1 },
  ];
  const selectedTags = [
    { tag_id: "scene", name: "과거 장면", tag_key: "SCENE", content: "[CHR], old scene", weight: 1 },
    { tag_id: "character-a", name: "인물 A", tag_key: "CHR", content: "character A", weight: 1 },
    { tag_id: "character-b", name: "과거 인물 B", tag_key: "CHR", content: "old character B", weight: 1 },
    { tag_id: "deleted-character", name: "삭제된 인물", tag_key: "CHR", content: "deleted character", weight: 1 },
    { tag_id: "moved-character", name: "과거 인물 C", tag_key: "CHR", content: "old character C", weight: 1 },
  ];
  const animaDetail = {
    body: originalAnimaBody, selected_tags: selectedTags, loras: animaLoras,
    prompt_preset_id: "anima-prompt", lora_preset_id: "anima-lora", lora_preset_name: "이미지 조합",
    settings: { width: 1280, height: 720, steps: 20, cfg: 1.3, seed: 2147483647 },
    resolved: { prompt: "resolved character A", negative: "resolved negative", settings: { width: 999, height: 777 },
      selected_path: [{ tag_id: "character-a", name: "인물 A" }], wildcard_seed: 2147483647 },
  };
  const animaJob = {
    job_id: "anima-job", workflow: "anima", description: "상위 작업 설명", request_count: 4,
    created_at: "2026-10-10", status: "completed", status_counts: { completed: 4 },
    inputs: { ...animaDetail, resolved: undefined }, requests: [],
  };
  for (let requestIndex = 1; requestIndex <= 4; requestIndex += 1) {
    animaJob.requests.push({ request_id: `anima-request-${requestIndex}`, request_index: requestIndex,
      status: "completed", prompt_id: `anima-prompt-${requestIndex}`, result: structuredClone(animaDetail.resolved) });
  }
  const minimaxJob = {
    job_id: "minimax-job", workflow: "minimax_h3", description: "영상 설명", request_count: 2,
    created_at: "2026-10-10", status: "completed", status_counts: { completed: 2 },
    inputs: {
      body: { prompt: "video [CHR]" }, selected_tags: structuredClone(selectedTags),
      prompt_preset_id: "video-prompt", lora_preset_id: "video-lora", lora_preset_name: "영상 조합",
      loras: structuredClone(minimaxLoras),
      settings: { width: 704, height: 512, duration: 3.5, frame_rate: 30, upscale_mode: "model", upscale_model_name: "saved-upscale.pth" },
    }, requests: [],
  };
  for (let requestIndex = 1; requestIndex <= 2; requestIndex += 1) {
    minimaxJob.requests.push({ request_id: `video-request-${requestIndex}`, request_index: requestIndex,
      status: "completed", upload_id: "removed-upload", result: {} });
  }
  const legacyJob = structuredClone(animaJob);
  legacyJob.job_id = "legacy-job";
  delete legacyJob.inputs.prompt_preset_id;
  delete legacyJob.inputs.lora_preset_id;
  legacyJob.inputs.settings = { width: 1000, height: 800, steps: 15, cfg: 0.9 };
  const missingBodyJob = structuredClone(animaJob);
  missingBodyJob.job_id = "missing-body-job";
  delete missingBodyJob.inputs.body;
  return {
    jobs: [animaJob, minimaxJob, legacyJob, missingBodyJob], tagGroups, tagEntries,
    promptPresets: [
      { preset_id: "anima-prompt", name: "이미지 Prompt", workflow: "anima", version: 1, body: structuredClone(originalAnimaBody) },
      { preset_id: "video-prompt", name: "영상 Prompt", workflow: "minimax_h3", version: 1, body: { prompt: "video [CHR]" } },
    ],
    loraPresets: [
      { preset_id: "anima-lora", name: "이미지 조합", workflow: "anima", loras: structuredClone(animaLoras) },
      { preset_id: "video-lora", name: "영상 조합", workflow: "minimax_h3", loras: structuredClone(minimaxLoras) },
    ],
    submissions: [], mutations: [], failTags: false,
  };
}

/** 현재 목록을 매번 반환하며 복원 중 쓰기 요청이 발생하는지도 기록합니다. */
function createRestorationRequestHandler(fixtures) {
  return async function handleRestorationRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    if (["/", "/app.css", "/app.js"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({ contentType: contentTypes[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    if (request.method() !== "GET" && requestPath !== "/api/outputs/input-images/inspect") fixtures.mutations.push(requestPath);
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath.startsWith("/api/jobs/") && requestPath.endsWith("/inputs")) {
      response = fixtures.jobs.find(job => job.job_id === requestPath.split("/").at(-2));
    }
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/outputs") response = { files: [], total: 0, total_pages: 1 };
    else if (requestPath === "/api/outputs/directories") response = { path: "", parent_path: null, directories: [] };
    else if (requestPath === "/api/outputs/input-images" || requestPath === "/api/outputs/input-images/inspect") {
      response = { files: [{ output_id: 1, name: "previous.png", path: "previous.png", width: 640, height: 480 }] };
    }
    else if (requestPath.startsWith("/api/outputs/preview/")) {
      await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48"/>' });
      return;
    }
    else if (requestPath === "/api/jobs") {
      const selectedJobId = requestUrl.searchParams.get("job_id");
      const matchingJobs = selectedJobId ? fixtures.jobs.filter(job => job.job_id === selectedJobId) : fixtures.jobs;
      response = { items: matchingJobs, total: matchingJobs.length, total_pages: 1, active_count: 0 };
    } else if (requestPath === "/api/presets") response = fixtures.promptPresets;
    else if (requestPath === "/api/loras/presets") response = fixtures.loraPresets;
    else if (requestPath === "/api/loras") response = { files: ["image.safetensors", "video.safetensors"], profiles: [] };
    else if (requestPath === "/api/tags") {
      if (fixtures.failTags) {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "태그 목록 조회 실패" }) });
        return;
      }
      response = { groups: fixtures.tagGroups, entries: fixtures.tagEntries };
    } else if (requestPath === "/api/batches") {
      fixtures.submissions.push(request.postDataJSON());
      response = { job_id: "new-job", request_ids: ["new-request"] };
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 상위 작업 버튼으로 복원하고 생성 탭 전환과 제출 버튼 활성화를 기다립니다. */
async function restoreJobFromCard(browserPage, jobIdentifier) {
  await browserPage.locator('[data-view="jobs"]:visible').click();
  await browserPage.locator(`[data-restore-job="${jobIdentifier}"]`).click();
  await browserPage.locator("#view-generate").waitFor({ state: "visible" });
  await browserPage.waitForFunction(() => document.getElementById("submit-button").disabled === false);
}

/** 복원, 현재 후보 적용, 변경 preset의 직접 구성과 MiniMax 이미지 초기화를 검증합니다. */
async function main() {
  const fixtures = createRestorationFixtures();
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    const browserPage = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const pageErrors = [];
    browserPage.on("pageerror", error => pageErrors.push(error.message));
    await browserPage.route("**/*", createRestorationRequestHandler(fixtures));
    await browserPage.goto("http://home-server.test/");
    await browserPage.locator('#generate-preset option[value="anima-prompt"]').waitFor({ state: "attached" });
    await restoreJobFromCard(browserPage, "anima-job");
    assert.equal(await browserPage.locator("#generate-workflow").inputValue(), "anima");
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), "[SCENE], {morning|evening}");
    assert.equal(await browserPage.locator("#generate-negative").inputValue(), "blurry [CHR]");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "anima-prompt");
    assert.equal(await browserPage.locator("#generate-lora-preset").inputValue(), "anima-lora");
    assert.equal(await browserPage.locator("#generate-count").inputValue(), "4");
    assert.equal(await browserPage.locator("#job-description").inputValue(), "상위 작업 설명");
    assert.equal(await browserPage.locator("#anima-aspect-ratio").inputValue(), "16:9");
    assert.equal(await browserPage.locator("#anima-resolution").inputValue(), "1280x720");
    assert.equal(await browserPage.locator("#anima-steps").inputValue(), "20");
    assert.equal(await browserPage.locator("#anima-cfg").inputValue(), "1.3");
    assert.deepEqual(await browserPage.locator('[data-select-tag]:checked').evaluateAll(inputs => inputs.map(input => input.dataset.selectTag).sort()),
      ["character-a", "character-b", "scene"]);
    assert.match(await browserPage.locator('[data-select-tag="character-b"]').locator("..").textContent(), /변경된 인물 B/);
    assert.equal(await browserPage.locator('[data-select-tag="deleted-character"]').count(), 0);
    assert.equal(await browserPage.locator('[data-select-tag="moved-character"]').count(), 0);
    assert.equal(await browserPage.locator("#preview-results").isVisible(), false);
    assert.deepEqual(fixtures.mutations, []);
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("submit-button").disabled === false);
    const restoredSubmission = fixtures.submissions.at(-1);
    assert.equal(restoredSubmission.count, 4);
    assert.deepEqual(restoredSubmission.selected_tag_ids, ["scene", "character-a", "character-b"]);
    assert.equal(restoredSubmission.prompt_preset_id, "anima-prompt");
    assert.equal(restoredSubmission.lora_preset_id, "anima-lora");
    assert.equal(restoredSubmission.settings.width, 1280);
    assert.ok(restoredSubmission.settings.seed < 2147483647);
    assert.equal(Object.hasOwn(restoredSubmission, "wildcard_seed"), false);

    fixtures.promptPresets[0].body.prompt = "changed preset";
    fixtures.loraPresets[0].loras[0].strength = 1.1;
    fixtures.tagEntries = fixtures.tagEntries.filter(entry => entry.tag_id !== "character-b");
    await restoreJobFromCard(browserPage, "anima-job");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "");
    assert.equal(await browserPage.locator("#generate-lora-preset").inputValue(), "");
    assert.equal(await browserPage.locator('#selected-loras [data-lora-field="strength"]').inputValue(), "0.7");
    assert.equal(await browserPage.locator('#selected-loras [data-lora-field="clip_strength"]').inputValue(), "0.4");
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), "[SCENE], {morning|evening}");
    assert.equal(await browserPage.locator('[data-select-tag="character-b"]').count(), 0);

    fixtures.promptPresets[0].body = structuredClone(fixtures.jobs[0].inputs.body);
    fixtures.loraPresets[0].loras[0].strength = 0.7;
    await restoreJobFromCard(browserPage, "legacy-job");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "anima-prompt");
    assert.equal(await browserPage.locator("#generate-lora-preset").inputValue(), "anima-lora");
    assert.equal(await browserPage.locator("#anima-aspect-ratio").inputValue(), "custom");
    assert.equal(await browserPage.locator("#anima-width").inputValue(), "1000");
    assert.equal(await browserPage.locator("#anima-height").inputValue(), "800");

    fixtures.promptPresets.push({ ...structuredClone(fixtures.promptPresets[0]), preset_id: "duplicate-prompt" });
    await restoreJobFromCard(browserPage, "legacy-job");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "");
    fixtures.promptPresets.pop();
    const deletedLoraPreset = fixtures.loraPresets.shift();
    await restoreJobFromCard(browserPage, "anima-job");
    assert.equal(await browserPage.locator("#generate-lora-preset").inputValue(), "");
    assert.equal(await browserPage.locator('#selected-loras [data-lora-field="strength"]').inputValue(), "0.7");
    fixtures.loraPresets.unshift(deletedLoraPreset);

    fixtures.tagEntries = fixtures.tagEntries.filter(entry => entry.tag_id !== "scene");
    await restoreJobFromCard(browserPage, "anima-job");
    assert.equal(await browserPage.locator('[data-select-tag="scene"]').count(), 0);
    assert.equal(fixtures.tagEntries.some(entry => entry.tag_id === "scene"), false);

    await browserPage.locator("#generate-workflow").selectOption("minimax_h3");
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('[data-pick-input="1"]').check();
    await browserPage.locator("#folder-picker-confirm").click();
    await browserPage.waitForFunction(() => document.getElementById("selected-images").textContent.includes("1개"));
    assert.match(await browserPage.locator("#selected-images").textContent(), /1개/);
    await restoreJobFromCard(browserPage, "minimax-job");
    assert.equal(await browserPage.locator("#generate-minimax-prompt").inputValue(), "video [CHR]");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "video-prompt");
    assert.equal(await browserPage.locator("#generate-lora-preset").inputValue(), "video-lora");
    assert.equal(await browserPage.locator('#selected-loras [data-lora-field="video_strength"]').inputValue(), "0.3");
    assert.equal(await browserPage.locator('#selected-loras [data-lora-field="audio_strength"]').inputValue(), "1.5");
    for (const [inputIdentifier, expectedValue] of [
      ["minimax-width", "704"], ["minimax-height", "512"], ["minimax-duration", "3.5"],
      ["minimax-frame-rate", "30"], ["minimax-upscale", "model"], ["minimax-upscale-model", "saved-upscale.pth"],
    ]) {
      assert.equal(await browserPage.locator(`#${inputIdentifier}`).inputValue(), expectedValue);
    }
    assert.equal(await browserPage.locator("#minimax-selected-images .input-image-card").count(), 0);
    assert.equal(await browserPage.locator("#selected-images").textContent(), "선택한 이미지가 없습니다.");
    assert.equal(await browserPage.locator('[data-select-tag]:checked').count(), 1);
    assert.equal(await browserPage.locator('[data-select-tag="character-a"]').isChecked(), true);
    assert.equal(await browserPage.locator('[data-select-tag="character-b"]').count(), 0);
    assert.equal(await browserPage.locator('[data-select-tag="moved-character"]').count(), 0);
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent === "MiniMax 입력 이미지를 선택해 주세요.");
    assert.equal(fixtures.submissions.length, 1);

    fixtures.failTags = true;
    await browserPage.locator('.sidebar [data-view="jobs"]').click();
    assert.equal(await browserPage.locator('.job-request [data-restore-job]').count(), 0);
    await browserPage.locator('[data-restore-job="anima-job"]').click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent === "태그 목록 조회 실패");
    assert.equal(await browserPage.locator("#generate-workflow").inputValue(), "minimax_h3");
    assert.equal(await browserPage.locator("#generate-minimax-prompt").inputValue(), "video [CHR]");
    fixtures.failTags = false;
    await browserPage.locator('[data-restore-job="missing-body-job"]').click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("원본 Prompt 기록이 없습니다"));
    assert.equal(await browserPage.locator("#generate-workflow").inputValue(), "minimax_h3");
    assert.deepEqual(fixtures.mutations, ["/api/batches"]);

    await browserPage.setViewportSize({ width: 390, height: 844 });
    await restoreJobFromCard(browserPage, "minimax-job");
    assert.equal(await browserPage.locator("#view-generate").isVisible(), true);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    assert.deepEqual(pageErrors, []);
    console.log("Passed: job restoration, current tags, preset changes, original settings, MiniMax image reset, mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
