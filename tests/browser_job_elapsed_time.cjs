/** 서버 시간과 timezone을 기준으로 작업·하위 요청의 단순 경과시간 표시를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");
const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** 실행·종료 상태와 기존 이력을 섞고 동일 UTC 시각을 서로 다른 offset으로 표현합니다. */
function createElapsedTimeFixtures() {
  const jobs = [];
  for (const status of ["pending", "running", "completed", "cancelled", "failed", "partial", "legacy"]) {
    const requestStatus = status === "legacy" || status === "partial" ? "completed" : status;
    const startedAt = ["pending", "legacy"].includes(status) ? null : "2026-10-23T12:00:00+09:00";
    const requests = [{
      request_id: `${status}-request`, request_index: 1, status: requestStatus, started_at: startedAt,
      updated_at: "2026-10-23T03:06:06+00:00", prompt_id: `${status}-prompt`, result: { prompt: "확정 Prompt" },
    }];
    if (status === "partial") {
      requests.push({ request_id: "unstarted-cancelled", request_index: 2, status: "cancelled", started_at: null,
        updated_at: "2026-10-23T03:06:06+00:00", result: {} });
    }
    jobs.push({
      job_id: `${status}-job`, workflow: "anima", description: `${status} 시간 확인`, status: status === "legacy" ? "completed" : status,
      created_at: "2026-10-23T02:00:00+00:00", started_at: startedAt, updated_at: "2026-10-23T03:06:06+00:00",
      request_count: requests.length, status_counts: status === "partial" ? { completed: 1, cancelled: 1 } : { [requestStatus]: 1 },
      inputs: { body: { prompt: "원본 Prompt" }, settings: { width: 768, height: 512 }, loras: [] }, requests,
    });
  }
  return { jobs, serverTime: "2026-10-23T03:06:06Z", detailRequests: [] };
}

/** Browser는 요약·상세의 서버 시각만 받고 실제 ComfyUI에는 접근하지 않습니다. */
function createElapsedTimeHandler(fixtures) {
  return async function handleElapsedTimeRequest(route) {
    const requestUrl = new URL(route.request().url());
    const requestPath = requestUrl.pathname;
    if (await handleJobFolderReadRequest(route, fixtures.jobs)) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({ contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[filename],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 2 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/jobs") {
      const items = fixtures.jobs.map(job => {
        const { requests, inputs, ...summary } = job;
        return { ...summary, summary: inputs };
      });
      response = { items, page: 1, total: items.length, total_pages: 1, active_count: 2, server_time: fixtures.serverTime };
    } else if (requestPath.startsWith("/api/jobs/")) {
      const jobIdentifier = requestPath.slice("/api/jobs/".length);
      fixtures.detailRequests.push(jobIdentifier);
      response = { ...fixtures.jobs.find(job => job.job_id === jobIdentifier), server_time: fixtures.serverTime };
    } else {
      await route.fulfill({ status: 404, body: "Not found" });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 다른 timezone과 잘못된 Browser 시계에서도 서버 기준으로 표시하고 Polling의 DOM을 보존합니다. */
async function verifyJobElapsedTime(browser, viewportWidth) {
  const fixtures = createElapsedTimeFixtures();
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: 900 }, timezoneId: "America/Los_Angeles" });
  await context.addInitScript(() => { Date.now = () => 0; });
  await context.route("**/*", createElapsedTimeHandler(fixtures));
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await page.goto("http://job-elapsed.test/?view=jobs");
    await page.locator('[data-job-elapsed-time="running-job"]').filter({ hasText: "6분 6초 작업됨" }).waitFor();
    await page.evaluate(() => window.clearTimeout(applicationState.pollingTimer));
    assert.equal(await page.locator('[data-job-elapsed-time="pending-job"]').textContent(), "대기중");
    assert.equal(await page.locator('[data-job-elapsed-time="legacy-job"]').textContent(), "N/A");
    for (const status of ["running", "completed", "cancelled", "failed", "partial"]) {
      assert.equal(await page.locator(`[data-job-elapsed-time="${status}-job"]`).textContent(), "6분 6초 작업됨");
      await page.locator(`[data-job-details="${status}-job"] > summary`).click();
      await page.locator(`[data-request-elapsed-time="${status}-request"]`).filter({ hasText: "6분 6초 작업됨" }).waitFor();
    }
    assert.equal(await page.locator('[data-request-elapsed-time="unstarted-cancelled"]').textContent(), "N/A");
    const detailRequestCount = fixtures.detailRequests.length;
    await page.evaluate(() => { window.savedRunningCard = document.querySelector('[data-job-prompt-card="running-job"]'); });
    fixtures.serverTime = "2026-10-23T03:06:16Z";
    await page.evaluate(() => loadJobs());
    assert.equal(await page.locator('[data-job-elapsed-time="running-job"]').textContent(), "6분 16초 작업됨");
    assert.equal(await page.locator('[data-request-elapsed-time="running-request"]').textContent(), "6분 16초 작업됨");
    assert.equal(await page.evaluate(() => window.savedRunningCard === document.querySelector('[data-job-prompt-card="running-job"]')), true);
    assert.equal(fixtures.detailRequests.length, detailRequestCount);
    for (const status of ["completed", "cancelled", "failed", "partial"]) {
      assert.equal(await page.locator(`[data-job-elapsed-time="${status}-job"]`).textContent(), "6분 6초 작업됨");
    }
    const runningJob = fixtures.jobs.find(job => job.job_id === "running-job");
    runningJob.status = "completed";
    runningJob.status_counts = { completed: 1 };
    runningJob.requests[0].status = "completed";
    runningJob.updated_at = runningJob.requests[0].updated_at = "2026-10-23T03:06:20Z";
    fixtures.serverTime = "2026-10-23T03:08:00Z";
    await page.evaluate(() => loadJobs());
    await page.locator('[data-request-elapsed-time="running-request"]').filter({ hasText: "6분 20초 작업됨" }).waitFor();
    assert.equal(await page.locator('[data-job-elapsed-time="running-job"]').textContent(), "6분 20초 작업됨");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.screenshot({ path: path.join(artifactDirectory, `job-elapsed-time-${viewportWidth}.png`), fullPage: true });
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** Desktop·Mobile의 실제 Browser에서 시간 표시를 검증합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const viewportWidth of [1280, 390]) await verifyJobElapsedTime(browser, viewportWidth);
    process.stdout.write("Passed: server clock, timezone offsets, waiting/N/A, parent/request elapsed time, frozen terminal durations and stable polling on desktop/mobile.\n");
  } finally { await browser.close(); }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
