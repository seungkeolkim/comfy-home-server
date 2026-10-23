/** 실제 앱 UI와 Mock API에서 MiniMax 서버 입력·모드·공통 해상도를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");

/** 파일명 정렬과 혼합 크기, 100장 상한을 확인할 후보를 준비합니다. */
function createMinimaxFixtures() {
  const images = [
    { output_id: 1, name: "a.png", path: "folder/a.png", width: 65, height: 97 },
    { output_id: 2, name: "b.png", path: "folder/b.png", width: 128, height: 64 },
    { output_id: 3, name: "c.png", path: "folder/c.png", width: 65, height: 97 },
  ];
  for (let imageNumber = 0; imageNumber < 101; imageNumber += 1) {
    images.push({ output_id: imageNumber + 100, name: `${imageNumber}.png`, path: `big/${imageNumber}.png`, width: 64, height: 96 });
  }
  return { images, submissions: [], previews: [], inspections: [], inspectionGate: null, rejectInspection: false };
}

/** 현재 앱 파일을 제공하고 GPU·실제 파일을 건드리는 요청은 받지 않습니다. */
function createMinimaxRequestHandler(fixtures) {
  return async function handleMinimaxRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    if (await handleJobFolderReadRequest(route, fixtures.jobs || [])) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({ contentType: contentTypes[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    if (requestPath.startsWith("/api/outputs/preview/")) {
      await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="128"><rect width="96" height="128" fill="#586e85"/></svg>' });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/jobs") response = { items: [{
      job_id: "source-job", workflow: "anima", description: "원본 작업", created_at: "2026-10-19", status: "completed",
      status_counts: { completed: 2 }, request_count: 2, deletion_protected: true,
      summary: { body: { prompt: "자동 복사하면 안 되는 원본 Prompt" }, settings: {} },
    }], page: 1, total: 1, total_pages: 1, active_count: 0 };
    else if (requestPath === "/api/outputs/input-jobs") {
      const pageNumber = Number(requestUrl.searchParams.get("page"));
      response = { items: [{ job_id: pageNumber === 1 ? "source-job" : "big-job", workflow: "anima", description: pageNumber === 1 ? "원본 작업" : "많은 이미지", created_at: "2026-10-19", image_count: pageNumber === 1 ? 2 : 101 }], total_pages: 2 };
    } else if (/^\/api\/jobs\/[^/]+\/input-images$/.test(requestPath)) {
      const jobIdentifier = requestPath.split("/")[3];
      if (fixtures.jobImageGate) {
        const imageGate = fixtures.jobImageGate;
        fixtures.jobImageGate = null;
        imageGate.markStarted();
        await imageGate.promise;
      }
      if (fixtures.rejectJobImages) {
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "입력 작업을 찾을 수 없습니다." }) });
        return;
      }
      response = { job: { job_id: jobIdentifier, workflow: "anima", description: "원본 작업" }, files: fixtures.emptyJobImages ? [] : fixtures.images.filter(image => jobIdentifier === "big-job" ? image.output_id >= 100 : [1, 3].includes(image.output_id)) };
    }
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = {
      groups: [
        { group_id: "actions", name: "동작", tag_key: "ACTION", default_expanded: true },
        { group_id: "actors", name: "인물", tag_key: "ACTOR", default_expanded: true },
      ],
      entries: [
        { tag_id: "action", group_id: "actions", name: "걷기", content: "[ACTOR] walks", weight: 1 },
        { tag_id: "actor-a", group_id: "actors", name: "인물 A", content: "person A", weight: 1 },
        { tag_id: "actor-b", group_id: "actors", name: "인물 B", content: "person B", weight: 2 },
      ],
    };
    else if (requestPath === "/api/prompts/preview") {
      const payload = route.request().postDataJSON();
      fixtures.previews.push(payload);
      response = { combined_prompt: null, examples: Array.from({ length: payload.count }, (unused, exampleIndex) => ({
        index: exampleIndex + 1, seed: exampleIndex, prompt: `person ${exampleIndex % 2 ? "A" : "B"} walks`,
        selected_path: [{ name: "걷기" }, { name: exampleIndex % 2 ? "인물 A" : "인물 B" }],
      })) };
    }
    else if (requestPath === "/api/outputs/directories") {
      const directoryPath = requestUrl.searchParams.get("path") || "";
      response = {
        path: directoryPath, parent_path: directoryPath ? "" : null,
        directories: directoryPath ? [] : ["folder", "empty", "big"].map(directoryName => ({ name: directoryName, path: directoryName })),
      };
    } else if (requestPath === "/api/outputs/input-images") {
      const directoryPath = requestUrl.searchParams.get("path") || "";
      response = { files: fixtures.images.filter(image => image.path.split("/").slice(0, -1).join("/") === directoryPath) };
    } else if (requestPath === "/api/outputs/input-images/inspect") {
      const payload = request.postDataJSON();
      fixtures.inspections.push(payload);
      if (fixtures.inspectionGate) {
        const inspectionGate = fixtures.inspectionGate;
        fixtures.inspectionGate = null;
        inspectionGate.markStarted();
        await inspectionGate.promise;
      }
      if (fixtures.rejectInspection) {
        await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "입력 이미지가 삭제되었습니다. 다시 선택해 주세요." }) });
        return;
      }
      response = { files: fixtures.images.filter(image => payload.output_ids.includes(image.output_id)) };
    } else if (requestPath === "/api/batches") {
      const payload = request.postDataJSON();
      fixtures.submissions.push(payload);
      response = { job_id: "new-job", request_ids: payload.output_ids.map(outputId => `request-${outputId}`) };
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 공용 서버 탐색기에서 현재 폴더의 이미지를 선택합니다. */
async function chooseInputImages(browserPage, directoryName, singleIdentifier = null) {
  await browserPage.locator("#select-minimax-input").click();
  await browserPage.locator(`#folder-picker-directories [data-folder-path="${directoryName}"]`).click();
  if (singleIdentifier !== null) await browserPage.locator(`[data-pick-input="${singleIdentifier}"]`).check();
  await browserPage.locator("#folder-picker-confirm").click();
  await browserPage.waitForFunction(() => !document.getElementById("selected-images").textContent.includes("확인하는 중") &&
    document.getElementById("minimax-selected-images").children.length > 0);
}

/** Mobile과 Desktop에서 입력·해상도·제출 계약을 실제 UI 조작으로 확인합니다. */
async function verifyMinimaxGeneration(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createMinimaxFixtures();
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createMinimaxRequestHandler(fixtures));
  try {
    await browserPage.goto("http://minimax.test/");
    await browserPage.locator("#generate-workflow").selectOption("minimax_h3");
    assert.equal(await browserPage.locator('#minimax-input-fields input[type="file"]').count(), 0);
    await browserPage.locator("#generate-minimax-prompt").fill("[ACTION]\n[Scene]\n{camera|lighting}\n__literal__");
    assert.equal(await browserPage.locator("#generate-tag-fields").isVisible(), true);
    await browserPage.locator('[data-select-tag="action"]').check();
    await browserPage.locator('[data-select-tag="actor-a"]').check();
    await browserPage.locator('[data-select-tag="actor-b"]').check();
    await browserPage.locator("#preview-button").click();
    await browserPage.waitForFunction(() => document.querySelectorAll("#preview-results .preview-item").length === 5);
    assert.deepEqual(fixtures.previews.at(-1).selected_tag_ids, ["action", "actor-a", "actor-b"]);
    assert.match(await browserPage.locator("#preview-results").textContent(), /걷기 → 인물/);
    await chooseInputImages(browserPage, "folder", 1);
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "65");
    assert.equal(await browserPage.locator("#minimax-height").inputValue(), "97");
    assert.match(await browserPage.locator("#minimax-resolution-reference").textContent(), /제출 96 × 128/);
    await browserPage.locator("#select-minimax-input").click();
    assert.equal(await browserPage.locator("#folder-picker-create-form").isVisible(), false);
    await browserPage.locator("#folder-picker-cancel").click();
    assert.equal(await browserPage.locator("#minimax-selected-images .input-image-card").count(), 1);
    for (const generationMode of ["F2VA", "L2VA", "FL2VA"]) {
      await browserPage.locator("#minimax-generation-mode").selectOption(generationMode);
      await browserPage.locator("#submit-button").click();
      await browserPage.waitForFunction(() => !document.getElementById("submit-button").disabled);
      const submission = fixtures.submissions.at(-1);
      assert.deepEqual(submission.output_ids, [1]);
      assert.equal(submission.settings.generation_mode, generationMode);
      assert.equal(submission.input_scope, "single");
      assert.equal(submission.body.prompt, "[ACTION]\n[Scene]\n{camera|lighting}\n__literal__");
      assert.deepEqual(submission.selected_tag_ids, ["action", "actor-a", "actor-b"]);
      assert.equal(submission.upload_ids, undefined);
    }
    await browserPage.locator("#generate-minimax-prompt").fill("[Scene]\n{camera|lighting}\n__literal__");
    assert.match(await browserPage.locator("#tag-selection-status").textContent(), /태그 선택이 필요하지 않습니다/);
    await browserPage.locator("#minimax-input-scope").selectOption("folder");
    assert.equal(await browserPage.locator("#minimax-selected-images .input-image-card").count(), 0);
    await chooseInputImages(browserPage, "folder");
    assert.match(await browserPage.locator("#minimax-resolution-reference").textContent(), /해상도가 다른/);
    await browserPage.locator('[data-minimax-selected="1"]').uncheck();
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "128");
    assert.equal(await browserPage.locator("#minimax-height").inputValue(), "64");
    await browserPage.locator("#minimax-width").fill("320");
    await browserPage.locator("#minimax-height").fill("240");
    await chooseInputImages(browserPage, "folder");
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "320");
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => !document.getElementById("submit-button").disabled);
    assert.equal(fixtures.submissions.at(-1).settings.resolution_mode, "manual");
    assert.deepEqual(fixtures.submissions.at(-1).selected_tag_ids, []);
    assert.deepEqual(fixtures.submissions.at(-1).output_ids, [1, 2, 3]);
    assert.equal(fixtures.submissions.at(-1).input_directory, "folder");
    await browserPage.locator("#minimax-automatic-resolution").click();
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "65");
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('#folder-picker-directories [data-folder-path="empty"]').click();
    await browserPage.waitForFunction(() => document.getElementById("folder-picker-status").textContent.includes("이미지 0장"));
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), true);
    await browserPage.locator("#folder-picker-parent").click();
    await browserPage.locator('#folder-picker-directories [data-folder-path="big"]').click();
    await browserPage.waitForFunction(() => document.querySelectorAll("[data-pick-input]").length === 101);
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), true);
    await browserPage.locator('[data-pick-input="100"]').uncheck();
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), false);
    await browserPage.keyboard.press("Escape");
    assert.equal(fixtures.submissions.length, 4);

    let markStarted;
    let releaseInspection;
    const inspectionStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.inspectionGate = { markStarted, promise: new Promise(resolve => { releaseInspection = resolve; }) };
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('#folder-picker-directories [data-folder-path="folder"]').click();
    await browserPage.locator("#folder-picker-confirm").click();
    await inspectionStarted;
    await browserPage.locator("#minimax-input-scope").selectOption("single");
    const staleResponse = browserPage.waitForResponse(response => response.url().endsWith("/inspect"));
    releaseInspection();
    await staleResponse;
    assert.equal(await browserPage.locator("#minimax-selected-images .input-image-card").count(), 0);
    fixtures.rejectInspection = true;
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('#folder-picker-directories [data-folder-path="folder"]').click();
    await browserPage.locator('[data-pick-input="1"]').check();
    await browserPage.locator("#folder-picker-confirm").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("삭제되었습니다"));
    assert.equal(await browserPage.locator("#minimax-selected-images .input-image-card").count(), 0);
    fixtures.rejectInspection = false;
    await chooseInputImages(browserPage, "folder", 1);
    await browserPage.locator("#minimax-input-scope").selectOption("job");
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator("#job-input-next").click();
    await browserPage.locator('[data-pick-input-job="big-job"]').click();
    await browserPage.waitForFunction(() => document.querySelectorAll("[data-pick-job-input]").length === 101);
    assert.equal(await browserPage.locator("#job-input-confirm").isDisabled(), true);
    await browserPage.locator('[data-pick-job-input="100"]').uncheck();
    assert.equal(await browserPage.locator("#job-input-confirm").isDisabled(), false);
    await browserPage.locator("#job-input-select-all").click();
    assert.equal(await browserPage.locator("#job-input-confirm").isDisabled(), true);
    await browserPage.locator("#job-input-select-all").click();
    assert.match(await browserPage.locator("#job-input-status").textContent(), /선택 0장/);
    await browserPage.locator("#job-input-back").click();
    await browserPage.locator("#job-input-previous").click();
    await browserPage.locator('[data-pick-input-job="source-job"]').click();
    await browserPage.locator('[data-pick-job-input="1"]').uncheck();
    await browserPage.locator("#job-input-confirm").click();
    await browserPage.waitForFunction(() => document.querySelectorAll("[data-minimax-selected]").length === 1);
    assert.equal(fixtures.inspections.at(-1).input_job_id, "source-job");
    assert.deepEqual(fixtures.inspections.at(-1).output_ids, [3]);
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "65");
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => !document.getElementById("submit-button").disabled);
    assert.equal(fixtures.submissions.at(-1).input_job_id, "source-job");
    assert.equal(fixtures.submissions.at(-1).input_scope, "job");
    assert.equal(fixtures.submissions.at(-1).input_directory, null);
    assert.deepEqual(fixtures.submissions.at(-1).output_ids, [3]);
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.keyboard.press("Escape");
    assert.equal(await browserPage.locator('[data-minimax-selected="3"]').isChecked(), true);

    // 이력 바로가기는 확정 후에만 생성 화면으로 이동하며 작성 중인 MiniMax 입력을 보존합니다.
    await browserPage.locator("#generate-minimax-prompt").fill("내가 작성한 Prompt");
    await browserPage.locator("#minimax-width").fill("320");
    await browserPage.locator('[data-view="jobs"]:visible').first().click();
    await browserPage.locator('[data-use-job-input="source-job"]').click();
    await browserPage.locator("#job-input-cancel").click();
    assert.equal(await browserPage.locator("#view-jobs").isVisible(), true);
    await browserPage.locator('[data-use-job-input="source-job"]').click();
    await browserPage.locator("#job-input-confirm").click();
    await browserPage.waitForFunction(() => document.querySelectorAll("[data-minimax-selected]").length === 2);
    assert.equal(await browserPage.locator("#generate-minimax-prompt").inputValue(), "내가 작성한 Prompt");
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "320");
    assert.equal(fixtures.submissions.length, 5);
    await browserPage.locator("#minimax-automatic-resolution").click();
    await browserPage.locator('[data-minimax-selected="1"]').uncheck();
    assert.equal(await browserPage.locator("#minimax-width").inputValue(), "65");

    fixtures.rejectJobImages = true;
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('[data-pick-input-job="source-job"]').click();
    await browserPage.waitForFunction(() => document.getElementById("job-input-status").textContent.includes("찾을 수 없습니다"));
    assert.equal(await browserPage.locator("#job-input-confirm").isDisabled(), true);
    fixtures.rejectJobImages = false;
    fixtures.emptyJobImages = true;
    await browserPage.locator("#job-input-retry").click();
    await browserPage.waitForFunction(() => document.getElementById("job-input-status").textContent.includes("이미지 0장"));
    assert.equal(await browserPage.locator("#job-input-confirm").isDisabled(), true);
    await browserPage.locator("#job-input-cancel").click();
    fixtures.emptyJobImages = false;

    let markJobStarted;
    let releaseJobImages;
    const jobImagesStarted = new Promise(resolve => { markJobStarted = resolve; });
    fixtures.jobImageGate = { markStarted: markJobStarted, promise: new Promise(resolve => { releaseJobImages = resolve; }) };
    await browserPage.locator("#select-minimax-input").click();
    await browserPage.locator('[data-pick-input-job="source-job"]').click();
    await jobImagesStarted;
    await browserPage.locator("#job-input-cancel").click();
    await browserPage.locator("#select-minimax-input").click();
    const staleJobResponse = browserPage.waitForResponse(response => response.url().endsWith("/source-job/input-images"));
    releaseJobImages();
    await staleJobResponse;
    assert.equal(await browserPage.locator("#job-input-images").isVisible(), false);
    await browserPage.keyboard.press("Escape");
    await browserPage.locator("#generate-workflow").selectOption("anima");
    await browserPage.locator('[data-view="jobs"]:visible').first().click();
    await browserPage.locator('[data-use-job-input="source-job"]').click();
    await browserPage.locator("#job-input-confirm").click();
    await browserPage.waitForFunction(() => document.getElementById("generate-workflow").value === "minimax_h3" && document.querySelectorAll("[data-minimax-selected]").length === 2);
    assert.equal(await browserPage.locator("#generate-minimax-prompt").inputValue(), "");
    assert.equal(fixtures.submissions.length, 5);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `minimax-generation-${viewport.width}.png`), fullPage: true });
  } finally {
    await browserPage.close();
  }
}

/** GPU 없이 두 화면 너비에서 검증합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyMinimaxGeneration(browser, { width: 1280, height: 950 });
    await verifyMinimaxGeneration(browser, { width: 390, height: 844 });
    console.log("Passed: MiniMax modes, folder/job image selection, source metadata, history shortcut, limits, cancellation, stale responses and desktop/mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
