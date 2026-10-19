/** Mock API와 실제 Browser에서 제출된 작업 설명의 수정·Polling·취소와 카드 표시를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");

/** 두 페이지의 작업과 보호된 진행 작업을 준비합니다. */
function createDescriptionFixtures() {
  const jobs = [];
  for (let jobIndex = 0; jobIndex < 12; jobIndex += 1) {
    const status = jobIndex === 0 ? "running" : "completed";
    jobs.push({
      job_id: `job-${jobIndex}`, workflow: "anima", status, description: `원래 설명 ${jobIndex}`,
      created_at: "2026-10-19T06:00:00+00:00", deletion_protected: jobIndex === 0,
      request_count: 1, status_counts: { [status]: 1 }, inputs: { body: { prompt: "원본 Prompt", negative: "원본 Negative" }, settings: { width: 768, height: 512 }, loras: [] },
      requests: [{ request_id: `request-${jobIndex}`, request_index: 1, status, result: { prompt: "확정 Prompt" } }],
    });
  }
  return { jobs, patches: [], rejectDescription: false, descriptionGate: null };
}

/** 설명 이외의 변경 요청은 허용하지 않으며 저장 지연과 실패를 제어합니다. */
function createDescriptionHandler(fixtures) {
  return async function handleDescriptionRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    if (await handleJobFolderReadRequest(route, fixtures.jobs || [])) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({ contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 1 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/jobs") {
      const matchingJobs = fixtures.jobs.filter(job => !requestUrl.searchParams.get("job_id") || job.job_id === requestUrl.searchParams.get("job_id"));
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      response = { items: matchingJobs.slice((pageNumber - 1) * 10, pageNumber * 10), page: pageNumber, total: matchingJobs.length, total_pages: Math.ceil(matchingJobs.length / 10), active_count: 1 };
    } else if (requestPath === "/api/jobs/deletion-candidates") response = { job_ids: fixtures.jobs.filter(job => !job.deletion_protected && job.status === "completed").map(job => job.job_id) };
    else if (/^\/api\/jobs\/[^/]+\/description$/.test(requestPath) && request.method() === "PATCH") {
      const jobIdentifier = requestPath.split("/")[3];
      const payload = request.postDataJSON();
      fixtures.patches.push({ job_id: jobIdentifier, ...payload });
      if (fixtures.descriptionGate) {
        const descriptionGate = fixtures.descriptionGate;
        fixtures.descriptionGate = null;
        descriptionGate.markStarted();
        await descriptionGate.promise;
      }
      if (fixtures.rejectDescription) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "설명을 저장하지 못했습니다." }) });
        return;
      }
      const job = fixtures.jobs.find(candidate => candidate.job_id === jobIdentifier);
      job.description = payload.description.trim();
      response = { job_id: jobIdentifier, description: job.description };
    } else if (/^\/api\/jobs\/[^/]+$/.test(requestPath)) response = fixtures.jobs.find(job => job.job_id === requestPath.split("/")[3]);
    else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** Desktop/Mobile에서 현재 위치·선택·입력과 독립된 설명 수정을 확인합니다. */
async function verifyJobDescription(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const fixtures = createDescriptionFixtures();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createDescriptionHandler(fixtures));
  try {
    await page.goto("http://job-description.test/?view=jobs&page=2");
    const editButton = page.locator('[data-edit-job-description="job-10"]');
    const jobCard = page.locator('[data-job-prompt-card="job-10"]');
    await editButton.waitFor();
    assert.equal(await jobCard.locator(".job-description-text").textContent(), "원래 설명 10");
    assert.equal(await jobCard.locator(".job-actions [data-edit-job-description]").count(), 0);
    assert.equal(await editButton.locator("svg").count(), 1);
    const originalUrl = page.url();
    await page.evaluate(() => { document.getElementById("job-description").value = "다음 제출용 작성 중인 설명"; });
    await page.locator("#toggle-job-selection").click();
    await page.locator('[data-select-job="job-10"]').check();
    await jobCard.locator("summary").click();
    await editButton.click();
    assert.equal(await page.locator("#job-description-input").inputValue(), "원래 설명 10");
    assert.equal(await page.locator("#job-description-input").getAttribute("maxlength"), "200");
    const updatedDescription = "바꾼 설명 <escaped> & 확인";
    await page.locator("#job-description-input").fill(`  ${updatedDescription}  `);
    await page.evaluate(() => loadJobs());
    assert.equal(await page.locator("#job-description-input").inputValue(), `  ${updatedDescription}  `);
    await page.locator("#job-description-input").press("Enter");
    await page.waitForFunction(() => !document.getElementById("job-description-dialog").open);
    assert.equal(await jobCard.locator(".job-description-text").textContent(), updatedDescription);
    assert.equal(await jobCard.locator("escaped").count(), 0);
    assert.deepEqual(await jobCard.locator(".job-description").evaluate(description => ({ fontSize: getComputedStyle(description).fontSize, fontWeight: getComputedStyle(description).fontWeight })), { fontSize: "13px", fontWeight: "700" });
    assert.equal(page.url(), originalUrl);
    assert.equal(await page.locator('[data-select-job="job-10"]').isChecked(), true);
    assert.equal(await jobCard.locator("details").getAttribute("open"), "");
    assert.equal(await jobCard.locator("[data-toggle-job-prompt]").getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator("#job-description").inputValue(), "다음 제출용 작성 중인 설명");
    assert.equal(await editButton.evaluate(button => button === document.activeElement), true);
    const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(artifactDirectory, { recursive: true });
    await page.screenshot({ path: path.join(artifactDirectory, `job-description-${viewport.width}.png`) });

    await editButton.click();
    await page.locator("#job-description-input").fill("취소할 설명");
    await page.locator("#job-description-cancel").click();
    assert.equal(fixtures.patches.length, 1);
    await editButton.click();
    await page.keyboard.press("Escape");
    assert.equal(fixtures.patches.length, 1);
    await editButton.click();
    await page.locator("#job-description-input").fill("");
    await page.locator("#job-description-save").click();
    await page.waitForFunction(() => !document.getElementById("job-description-dialog").open);
    assert.equal(await jobCard.locator(".job-description-text").textContent(), "(작업 설명 없음)");
    assert.equal(await editButton.isVisible(), true);

    fixtures.rejectDescription = true;
    await editButton.click();
    await page.locator("#job-description-input").fill("실패 후 유지할 설명");
    await page.locator("#job-description-save").click();
    await page.locator("#job-description-status").filter({ hasText: "저장하지 못했습니다" }).waitFor();
    assert.equal(await page.locator("#job-description-input").inputValue(), "실패 후 유지할 설명");
    assert.equal(await page.locator("#job-description-save").isDisabled(), false);
    fixtures.rejectDescription = false;
    let markStarted;
    let releaseDescription;
    const descriptionStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.descriptionGate = { markStarted, promise: new Promise(resolve => { releaseDescription = resolve; }) };
    await page.locator("#job-description-save").click();
    await descriptionStarted;
    assert.equal(await page.locator("#job-description-save").isDisabled(), true);
    await page.locator("#job-description-cancel").click();
    releaseDescription();
    await jobCard.locator(".job-description").filter({ hasText: "실패 후 유지할 설명" }).waitFor();
    assert.equal(await page.locator("#job-description-dialog").evaluate(dialog => dialog.open), false);

    await page.goto("http://job-description.test/?view=jobs&job_id=job-0");
    await page.locator('[data-edit-job-description="job-0"]').click();
    await page.locator("#job-description-input").fill("진행 중 보호된 작업의 새 설명");
    await page.locator("#job-description-save").click();
    await page.waitForFunction(() => !document.getElementById("job-description-dialog").open);
    assert.equal(fixtures.jobs[0].deletion_protected, true);
    assert.equal(fixtures.jobs[0].status, "running");
    assert.equal(fixtures.jobs[0].description, "진행 중 보호된 작업의 새 설명");
    assert.equal(new URL(page.url()).searchParams.get("job_id"), "job-0");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** 운영 DB·생성 요청 없이 두 화면 너비의 동작을 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyJobDescription(browser, { width: 1280, height: 950 });
    await verifyJobDescription(browser, { width: 390, height: 844 });
    console.log("Passed: description edit/save/clear/cancel/failure, polling and pending-close safety, protected/running jobs, page/filter/selection/focus preservation and 13px bold desktop/mobile display.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
