/** 격리된 Mock API에서 Anima의 여러 Prompt 제출과 Desktop·Mobile 표시를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { createPromptFixtures, createPromptHandler } = require("./browser_prompt_manager.cjs");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const screenshotDirectory = path.resolve(__dirname, "..", "runtime", "verification", "anima-prompt-sections");
const promptTexts = [
  "[CHR_GIRL] is cooking, [PROMPT_NET]",
  "[CHR_GIRL] is eating spaghetti, [PROMPT_NET], [DINING]",
];
const originalPrompt = promptTexts.join("\n-----\n");

/** 뒤 Prompt에서만 필요한 참조를 포함한 후보와 원문 Preset을 준비합니다. */
function createPromptSectionFixtures() {
  const fixtures = createPromptFixtures();
  fixtures.presets.unshift({ preset_id: "multiple-situations", name: "요리와 식사", workflow: "anima", version: 1,
    body: { prompt: originalPrompt, negative: "blurry" } });
  fixtures.tagGroups = [
    { group_id: "characters", name: "캐릭터", tag_key: "CHR_GIRL", default_expanded: true },
    { group_id: "quality", name: "공통 Prompt", tag_key: "PROMPT_NET", default_expanded: true },
    { group_id: "dining", name: "식사 상황", tag_key: "DINING", default_expanded: true },
  ];
  fixtures.tagEntries = [
    { tag_id: "character-a", group_id: "characters", name: "캐릭터 A", content: "character A", weight: 1 },
    { tag_id: "character-b", group_id: "characters", name: "캐릭터 B", content: "character B", weight: 1 },
    { tag_id: "quality", group_id: "quality", name: "품질", content: "quality", weight: 1 },
    { tag_id: "dining", group_id: "dining", name: "식탁", content: "at a dining table", weight: 1 },
  ];
  fixtures.jobs = [];
  fixtures.submissions = [];
  fixtures.previews = [];
  return fixtures;
}

/** 기본 Prompt 관리 Mock에 여러 Job·미리보기·개별 입력 복원 응답을 연결합니다. */
function createPromptSectionHandler(fixtures) {
  const baseHandler = createPromptHandler(fixtures);
  return async function handlePromptSectionRequest(route) {
    const request = route.request();
    const requestPath = new URL(request.url()).pathname;
    if (await handleJobFolderReadRequest(route, fixtures.jobs)) return;
    let response;
    if (requestPath === "/api/tags") response = { groups: fixtures.tagGroups, entries: fixtures.tagEntries };
    else if (requestPath === "/api/prompts/preview") {
      fixtures.previews.push(request.postDataJSON());
      const promptSections = [];
      for (let sectionIndex = 0; sectionIndex < promptTexts.length; sectionIndex += 1) {
        promptSections.push({ section_index: sectionIndex + 1, prompt: promptTexts[sectionIndex], examples: [{
          index: 1, seed: sectionIndex + 100, prompt: sectionIndex === 0 ? "character A is cooking, quality" : "character B is eating spaghetti, quality, at a dining table",
          negative: "blurry", selected_path: [{ name: sectionIndex === 0 ? "캐릭터 A" : "캐릭터 B" }], negative_selected_path: [],
        }] });
      }
      response = { examples: promptSections.flatMap(section => section.examples), prompt_sections: promptSections };
    } else if (requestPath === "/api/batches") {
      const payload = request.postDataJSON();
      fixtures.submissions.push(payload);
      const registeredJobs = [];
      for (let sectionIndex = 0; sectionIndex < promptTexts.length; sectionIndex += 1) {
        const jobIdentifier = `section-job-${sectionIndex + 1}`;
        const requestIdentifiers = [];
        for (let requestIndex = 1; requestIndex <= payload.count; requestIndex += 1) {
          requestIdentifiers.push(`${jobIdentifier}-request-${requestIndex}`);
        }
        const inputs = { body: { prompt: promptTexts[sectionIndex], negative: payload.body.negative },
          settings: payload.settings, loras: [], selected_tags: structuredClone(fixtures.tagEntries),
          prompt_preset_id: payload.prompt_preset_id,
          prompt_section: { submission_identifier: "shared-submission", section_index: sectionIndex + 1, section_count: 2 } };
        fixtures.jobs.push({ job_id: jobIdentifier, workflow: "anima", description: payload.description,
          request_count: payload.count, status: "pending", status_counts: { pending: payload.count },
          created_at: "2026-11-28T01:00:00Z", inputs, summary: inputs, requests: [] });
        registeredJobs.push({ job_id: jobIdentifier, request_ids: requestIdentifiers, section_index: sectionIndex + 1 });
      }
      response = { jobs: registeredJobs, job_count: 2, request_count: payload.count * 2,
        request_ids: registeredJobs.flatMap(job => job.request_ids) };
    } else if (requestPath === "/api/jobs") {
      response = { items: fixtures.jobs, total: fixtures.jobs.length, total_pages: 1, active_count: 0 };
    } else if (requestPath.startsWith("/api/jobs/") && requestPath.endsWith("/inputs")) {
      response = fixtures.jobs.find(job => job.job_id === requestPath.split("/").at(-2));
    } else {
      await baseHandler(route);
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 전체 Prompt의 선택 검사·규모 표시·묶음 미리보기·작업별 복원을 화면 크기별로 확인합니다. */
async function verifyPromptSectionGeneration(browser, viewport, screenshotName) {
  const fixtures = createPromptSectionFixtures();
  const browserPage = await browser.newPage({ viewport });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  try {
    await browserPage.route("**/*", createPromptSectionHandler(fixtures));
    await browserPage.goto("http://home-server.test/");
    await browserPage.locator('#generate-preset option[value="multiple-situations"]').waitFor({ state: "attached" });
    await browserPage.locator("#generate-preset").selectOption("multiple-situations");
    await browserPage.locator("#generate-count").fill("3");
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), originalPrompt);
    assert.equal(await browserPage.locator("#anima-submit-summary").textContent(), "Prompt 2개 × 각 3장 = 작업 2개 · 총 6장");
    assert.equal(await browserPage.locator("#submit-button").textContent(), "2개 작업 · 총 6장 제출");
    await browserPage.locator('[data-select-tag="character-a"]').check();
    await browserPage.locator('[data-select-tag="quality"]').check();
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("[DINING]"));
    assert.equal(fixtures.submissions.length, 0);
    await browserPage.locator("#preview-button").click();
    assert.equal(fixtures.previews.length, 0);
    await browserPage.locator('[data-select-tag="dining"]').check();
    await browserPage.locator("#preview-button").click();
    await browserPage.locator(".prompt-preview-section").last().waitFor();
    assert.deepEqual(await browserPage.locator(".prompt-preview-section h3").allTextContents(), ["Prompt 1/2", "Prompt 2/2"]);
    assert.match(await browserPage.locator(".prompt-preview-section").first().textContent(), /is cooking/);
    assert.match(await browserPage.locator(".prompt-preview-section").last().textContent(), /eating spaghetti/);
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("작업 2개 접수 완료"));
    assert.equal(fixtures.submissions.length, 1);
    assert.equal(fixtures.submissions[0].count, 3);
    assert.equal(fixtures.submissions[0].body.prompt, originalPrompt);
    assert.deepEqual(fixtures.submissions[0].selected_tag_ids, ["character-a", "quality", "dining"]);
    await browserPage.locator('[data-view="jobs"]:visible').click();
    await browserPage.locator(".job-card").last().waitFor();
    assert.equal(await browserPage.locator(".job-card").count(), 2);
    assert.match(await browserPage.locator(".job-card h3").first().textContent(), /Prompt 1\/2/);
    assert.match(await browserPage.locator(".job-card h3").last().textContent(), /Prompt 2\/2/);
    await browserPage.locator('[data-restore-job="section-job-1"]').click();
    await browserPage.waitForFunction(() => document.getElementById("submit-button").disabled === false);
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), promptTexts[0]);
    assert.equal(await browserPage.locator("#generate-count").inputValue(), "3");
    assert.equal(await browserPage.locator("#generate-preset").inputValue(), "");
    assert.equal(await browserPage.locator("#anima-submit-summary").textContent(), "Prompt 1개 × 각 3장 = 작업 1개 · 총 3장");
    await browserPage.locator("#generate-preset").selectOption("multiple-situations");
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), originalPrompt);
    await browserPage.locator("#generate-anima-prompt").fill("-----\n  \n-----");
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("Anima Prompt를 입력"));
    assert.equal(fixtures.submissions.length, 1);
    await browserPage.locator("#generate-anima-prompt").fill("cooking\n-----\neating");
    await browserPage.locator("#generate-count").fill("");
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("생성 장수는"));
    assert.equal(fixtures.submissions.length, 1);
    await browserPage.locator("#generate-anima-prompt").fill(originalPrompt);
    await browserPage.locator("#generate-count").fill("3");
    for (const tagIdentifier of ["character-a", "quality", "dining"]) {
      await browserPage.locator(`[data-select-tag="${tagIdentifier}"]`).check();
    }
    await browserPage.locator("#notice").waitFor({ state: "hidden" });
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await browserPage.locator(".submit-panel").screenshot({ path: path.join(screenshotDirectory, screenshotName) });
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserPage.close();
  }
}

/** 실제 ComfyUI 연결 없이 Desktop과 좁은 Mobile viewport에서 같은 생성 흐름을 실행합니다. */
async function main() {
  filesystem.mkdirSync(screenshotDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyPromptSectionGeneration(browser, { width: 1440, height: 1000 }, "desktop.png");
    await verifyPromptSectionGeneration(browser, { width: 320, height: 844 }, "mobile.png");
    console.log("Passed: Anima prompt counts, tag validation across sections, grouped previews, one submission, separate job cards, restoration, desktop/mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
