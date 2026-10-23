/** 느린 API에서도 중복 조회 없이 요약·상세·취소·삭제 상태를 유지하는지 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");

/** 12개 작업의 공통 입력과 각각 100개 하위 요청 확정 결과를 준비합니다. */
function createLargeJobs() {
  const jobs = [];
  for (let jobIndex = 0; jobIndex < 12; jobIndex += 1) {
    const status = jobIndex === 0 ? "submitting" : "completed";
    const inputs = { body: { prompt: "portrait", negative: "blurry" },
      settings: { width: 768, height: 1024 }, loras: [] };
    const requests = [];
    for (let requestIndex = 1; requestIndex <= 100; requestIndex += 1) {
      requests.push({ request_id: `job-${jobIndex}-request-${requestIndex}`, request_index: requestIndex,
        status, result: { prompt: "final portrait", selected_path: [{ name: "chosen tag" }] }, created_at: "2026-10-10" });
    }
    jobs.push({ job_id: `job-${jobIndex}`, workflow: "anima", description: "100개 검증", request_count: 100,
      created_at: "2026-10-10", updated_at: "2026-10-10", status, status_counts: { [status]: 100 },
      deletion_protected: false, cancellation_requested: false, inputs, requests });
  }
  return jobs;
}

/** 순수 Mock API로 대량 요청의 서버 처리와 느린 목록 응답을 제공합니다. */
function createPerformanceHandler(mockState) {
  return async function handlePerformanceRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    if (await handleJobFolderReadRequest(route, mockState.jobs || [])) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({ contentType: filename.endsWith("html") ? "text/html" : filename.endsWith("js")
        ? "text/javascript" : "text/css", body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    let response = {};
    let responseStatus = 200;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/presets" || requestPath === "/api/loras/presets") response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/outputs") {
      mockState.outputRequests += 1;
      response = { files: [], total: 0, total_pages: 1, page: 1 };
    } else if (requestPath === "/api/jobs/deletion-candidates") {
      response = { job_ids: mockState.jobs.filter(job => !["submitting", "cancelling"].includes(job.status)).map(job => job.job_id) };
    } else if (requestPath === "/api/jobs") {
      assert.equal(requestUrl.searchParams.get("summary"), "true");
      mockState.activeQueries += 1;
      mockState.maximumActiveQueries = Math.max(mockState.maximumActiveQueries, mockState.activeQueries);
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      const pageJobs = mockState.jobs.slice((pageNumber - 1) * 10, pageNumber * 10);
      response = { items: pageJobs.map(job => ({ ...job, requests: undefined, summary: {
        body: job.inputs.body, settings: job.inputs.settings, loras: [],
      } })), page: pageNumber, total: mockState.jobs.length,
      total_pages: Math.max(1, Math.ceil(mockState.jobs.length / 10)), active_count: 0 };
      await new Promise(resolve => setTimeout(resolve, 1500));
      if (mockState.failJobs) {
        responseStatus = 503;
        response = { detail: "느린 목록 조회 실패" };
      }
      mockState.completedQueries += 1;
      mockState.activeQueries -= 1;
    } else if (requestPath.endsWith("/cancel")) {
      mockState.cancelRequests += 1;
      await new Promise(resolve => setTimeout(resolve, 400));
      const job = mockState.jobs.find(candidate => candidate.job_id === requestPath.split("/").at(-2));
      job.status = "cancelled";
      job.status_counts = { cancelled: 100 };
      job.cancellation_requested = true;
      for (const child of job.requests) child.status = "cancelled";
      response = { status: "cancelling", requested_count: 100 };
    } else if (requestPath.startsWith("/api/jobs/") && request.method() === "DELETE") {
      mockState.jobs = mockState.jobs.filter(job => job.job_id !== requestPath.split("/").at(-1));
      response = { deleted: true, deleted_files: 0 };
    } else if (requestPath.startsWith("/api/jobs/")) {
      mockState.detailRequests += 1;
      response = mockState.jobs.find(job => job.job_id === requestPath.split("/").at(-1));
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 느린 Polling·lazy 상세·즉시 취소 표시·삭제 후 목록 유지·조회 오류를 검증합니다. */
async function main() {
  const mockState = { jobs: createLargeJobs(), activeQueries: 0, maximumActiveQueries: 0,
    completedQueries: 0, detailRequests: 0, outputRequests: 0, cancelRequests: 0, failJobs: false };
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const pageErrors = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/*", createPerformanceHandler(mockState));
    await page.goto("http://performance.test/");
    await page.locator("#application").waitFor({ state: "visible" });
    await page.locator('.sidebar [data-view="jobs"]').click();
    await page.locator(".job-card").first().waitFor();
    assert.equal(await page.locator(".job-card").count(), 10);
    assert.equal(await page.locator(".job-request").count(), 0);
    assert.equal(mockState.detailRequests, 0);
    assert.equal(mockState.outputRequests, 0);
    await page.evaluate(() => { window.initialJobCard = document.querySelector(".job-card"); });
    await page.waitForTimeout(3500);
    assert.ok(mockState.completedQueries >= 2);
    assert.equal(mockState.maximumActiveQueries, 1);
    assert.equal(await page.evaluate(() => window.initialJobCard === document.querySelector(".job-card")), true);

    await page.locator('[data-job-details="job-0"] > summary').click();
    await page.waitForFunction(() => document.querySelectorAll('.job-request').length === 100);
    assert.equal(mockState.detailRequests, 1);
    await page.evaluate(() => document.querySelector('[data-cancel-job="job-0"]').click());
    assert.equal(await page.locator('[data-cancel-job="job-0"]').isDisabled(), true);
    assert.match(await page.locator("#notice").textContent(), / 요청하는 중/);
    await page.evaluate(() => document.querySelector('[data-cancel-job="job-0"]').click());
    await page.waitForFunction(() => document.querySelector('.job-card .status-badge').textContent === "취소");
    assert.equal(mockState.cancelRequests, 1);
    await page.locator('[data-job-details="job-0"] > summary').click();

    await page.locator("#toggle-job-selection").click();
    await page.locator("#select-all-jobs").click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#delete-selected-job-outputs").click();
    await page.waitForTimeout(250);
    assert.equal(await page.locator("#jobs-list .empty-state").count(), 0);
    await page.waitForFunction(() => document.querySelectorAll('.job-card').length === 2);
    assert.equal(mockState.jobs.length, 2);
    assert.equal(mockState.maximumActiveQueries, 1);

    mockState.failJobs = true;
    await page.evaluate(() => loadJobs());
    assert.equal(await page.locator(".job-card").count(), 2);
    assert.equal(await page.locator("#jobs-list .empty-state").count(), 0);
    assert.match(await page.locator("#jobs-loading-status").textContent(), /조회에 실패/);
    mockState.failJobs = false;
    await page.evaluate(() => loadJobs());
    assert.equal(await page.locator("#jobs-loading-status").textContent(), "");
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
    console.log("Passed: slow polling, one in-flight query, summary/lazy details, cancellation feedback, deletion refresh, errors, mobile.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
