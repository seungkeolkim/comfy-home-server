/** Mock API와 Edge에서 작업 다중 선택과 두 삭제 방식의 사용자 흐름을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");
const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** 활성 상태와 종료 상태, 두 페이지 분량의 작업 및 결과물 fixture를 만듭니다. */
function createJobFixtures() {
  const statuses = [
    "completed", "failed", "partial", "cancelled", "stopped", "completed",
    "submitting", "pending", "running", "cancelling", "completed", "completed",
  ];
  const jobs = [];
  for (let statusIndex = 0; statusIndex < statuses.length; statusIndex += 1) {
    const jobIdentifier = `deletion-job-${statusIndex + 1}`;
    const requestStatus = statuses[statusIndex] === "partial" ? "failed" : statuses[statusIndex];
    jobs.push({
      job_id: jobIdentifier, workflow: "anima", description: `삭제 검증 ${statusIndex + 1}`,
      deletion_protected: false,
      request_count: 1, created_at: "2026-10-09", status: statuses[statusIndex],
      status_counts: { [requestStatus]: 1 },
      inputs: { settings: { width: 1024, height: 1024 }, loras: [] },
      requests: [{
        request_id: `${jobIdentifier}-request`, request_index: 1, prompt_id: "test-prompt",
        status: requestStatus, result: {},
      }],
    });
  }
  return jobs;
}

/** 실제 앱 파일과 종료 작업의 삭제 규칙을 따르는 독립된 Mock API를 제공합니다. */
function createBrowserRequestHandler(mockState) {
  return async function handleBrowserRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    if (await handleJobFolderReadRequest(route, mockState.jobs || [])) return;
    if (requestPath.startsWith("/api/outputs/preview/")) {
      await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="24"></svg>' });
      return;
    }
    if (["/", "/app.css", "/app.js"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({
        contentType: contentTypes[filename],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8"),
      });
      return;
    }
    let response = {};
    let responseStatus = 200;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 4 };
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/jobs") {
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      const pageSize = Number(requestUrl.searchParams.get("page_size") || 10);
      const filterJobId = requestUrl.searchParams.get("job_id");
      const matchingJobs = filterJobId
        ? mockState.jobs.filter(job => job.job_id === filterJobId) : mockState.jobs;
      response = {
        items: matchingJobs.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
        page: pageNumber, total: matchingJobs.length,
        total_pages: Math.max(1, Math.ceil(matchingJobs.length / pageSize)), active_count: 4,
      };
    } else if (requestPath === "/api/jobs/deletion-candidates") {
      const filterJobId = requestUrl.searchParams.get("job_id");
      response = { job_ids: mockState.jobs.filter(job =>
        (!filterJobId || job.job_id === filterJobId) && !job.deletion_protected &&
        job.requests.every(child => !["submitting", "pending", "running", "cancelling"].includes(child.status)),
      ).map(job => job.job_id) };
    } else if (requestPath.endsWith("/protection") && request.method() === "PATCH") {
      const jobIdentifier = requestPath.split("/").at(-2);
      const selectedJob = mockState.jobs.find(job => job.job_id === jobIdentifier);
      selectedJob.deletion_protected = request.postDataJSON().deletion_protected;
      response = { job_id: jobIdentifier, deletion_protected: selectedJob.deletion_protected };
    } else if (requestPath.startsWith("/api/jobs/") && request.method() === "DELETE") {
      const jobIdentifier = decodeURIComponent(requestPath.split("/").at(-1));
      const deleteOutputs = requestUrl.searchParams.get("delete_outputs") === "true";
      mockState.deletionRequests.push({ jobIdentifier, deleteOutputs });
      if (mockState.deletionGate) await mockState.deletionGate;
      const jobIndex = mockState.jobs.findIndex(job => job.job_id === jobIdentifier);
      const selectedJob = mockState.jobs[jobIndex];
      if (mockState.failedJobIds.has(jobIdentifier)) {
        responseStatus = 409;
        response = { detail: "결과물 파일을 삭제할 수 없습니다." };
      } else if (!selectedJob) {
        responseStatus = 404;
        response = { detail: "작업을 찾을 수 없습니다." };
      } else if (selectedJob.deletion_protected) {
        responseStatus = 409;
        response = { detail: "삭제 보호된 작업입니다. 보호를 해제한 뒤 삭제해 주세요." };
      } else if (selectedJob.requests.some(child =>
        ["submitting", "pending", "running", "cancelling"].includes(child.status))) {
        responseStatus = 409;
        response = { detail: "진행 중인 작업은 삭제할 수 없습니다." };
      } else {
        mockState.jobs.splice(jobIndex, 1);
        if (deleteOutputs) mockState.outputJobIds.delete(jobIdentifier);
        response = { deleted: true, deleted_files: deleteOutputs ? 1 : 0, missing_files: 0 };
      }
    } else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/outputs") response = {
      files: [{ path: "anima/test.mp4", name: "test.mp4", kind: "video", size: 1024, job_id: "deletion-job-12" }],
      total: 1, total_pages: 1, page: 1,
    };
    else if (["/api/presets", "/api/tags/groups", "/api/tags/entries", "/api/loras/presets"].includes(requestPath)) {
      response = [];
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`예상하지 않은 요청: ${request.method()} ${requestPath}`);
    await route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 선택 건수가 UI에 반영될 때까지 기다립니다. */
async function waitForSelectedCount(page, selectedCount) {
  await page.waitForFunction(expectedCount =>
    document.getElementById("selected-job-count").textContent === `${expectedCount}개 선택`, selectedCount);
}

/** 삭제 확인창을 한 번 처리하고 표시된 경고 문구를 반환합니다. */
async function confirmDeletion(page, buttonIdentifier, acceptConfirmation) {
  let confirmationMessage = null;
  page.once("dialog", async dialog => {
    confirmationMessage = dialog.message();
    if (acceptConfirmation) await dialog.accept();
    else await dialog.dismiss();
  });
  await page.locator(`#${buttonIdentifier}`).click();
  assert.ok(confirmationMessage, "삭제 확인창이 표시되어야 합니다.");
  return confirmationMessage;
}

/** 보호·진행 상태는 이동용 선택을 유지하고 실제 삭제 대상에서만 제외합니다. */
async function verifyProtectionAndGlobalSelection(browser) {
  const mockState = {
    jobs: createJobFixtures(), outputJobIds: new Set(), deletionRequests: [],
    failedJobIds: new Set(), deletionGate: null,
  };
  mockState.jobs[0].deletion_protected = true;
  mockState.jobs[10].deletion_protected = true;
  mockState.outputJobIds = new Set(mockState.jobs.map(job => job.job_id));
  const browserPage = await browser.newPage({ viewport: { width: 1280, height: 950 } });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createBrowserRequestHandler(mockState));
  try {
    await browserPage.goto("http://home-server.test/?view=jobs");
    await browserPage.locator('[data-toggle-job-protection="deletion-job-1"]').waitFor();
    assert.equal(await browserPage.locator('[data-delete-job="deletion-job-1"]').count(), 0);
    await browserPage.locator("#toggle-job-selection").click();
    await browserPage.locator("#select-every-job").click();
    await waitForSelectedCount(browserPage, 12);
    assert.equal(await browserPage.locator('[data-select-job="deletion-job-1"]').isEnabled(), true);
    assert.equal(await browserPage.locator('[data-select-job="deletion-job-1"]').isChecked(), true);
    assert.equal(await browserPage.locator("#delete-selected-job-history").textContent(), "이력만 삭제 (6)");
    await browserPage.locator('#jobs-pagination [data-jobs-page="2"]').first().click();
    await browserPage.locator('[data-select-job="deletion-job-11"]').waitFor();
    await browserPage.locator('[data-toggle-job-protection="deletion-job-12"]').click();
    await browserPage.waitForFunction(() => document.getElementById("delete-selected-job-history").textContent === "이력만 삭제 (5)");
    await waitForSelectedCount(browserPage, 12);
    assert.equal(await browserPage.locator('[data-select-job="deletion-job-12"]').isChecked(), true);
    await browserPage.locator('[data-toggle-job-protection="deletion-job-12"]').click();
    await browserPage.waitForFunction(() => document.getElementById("delete-selected-job-history").textContent === "이력만 삭제 (6)");
    await confirmDeletion(browserPage, "delete-selected-job-history", true);
    await waitForSelectedCount(browserPage, 6);
    const expectedDeletedJobs = [2, 3, 4, 5, 6, 12].map(number => `deletion-job-${number}`);
    assert.deepEqual(mockState.deletionRequests.map(request => request.jobIdentifier), expectedDeletedJobs);
    assert.equal(await browserPage.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await browserPage.locator("#move-selected-job-folder").isEnabled(), true);
    assert.equal(mockState.outputJobIds.size, 12);
    mockState.jobs = createJobFixtures();
    mockState.jobs[0].deletion_protected = true;
    mockState.jobs[10].deletion_protected = true;
    mockState.deletionRequests = [];
    await browserPage.waitForFunction(() => applicationState.selectableJobIds.size === 12);
    await browserPage.locator("#select-every-job").click();
    await waitForSelectedCount(browserPage, 12);
    await confirmDeletion(browserPage, "delete-selected-job-outputs", true);
    await waitForSelectedCount(browserPage, 6);
    assert.deepEqual(mockState.deletionRequests.map(request => request.jobIdentifier), expectedDeletedJobs);
    for (const identifier of ["deletion-job-1", "deletion-job-11"]) {
      assert.equal(mockState.outputJobIds.has(identifier), true);
      assert.equal(mockState.jobs.some(job => job.job_id === identifier), true);
    }
    for (const identifier of expectedDeletedJobs) assert.equal(mockState.outputJobIds.has(identifier), false);
    await browserPage.setViewportSize({ width: 390, height: 844 });
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
  } finally { await browserPage.close(); }
}

/** 선택 상태, polling, 취소, 파일 삭제, 부분 실패, 페이지 경계와 모바일을 검증합니다. */
async function main() {
  const mockState = {
    jobs: createJobFixtures(), outputJobIds: new Set(), deletionRequests: [],
    failedJobIds: new Set(), deletionGate: null,
  };
  mockState.outputJobIds = new Set(mockState.jobs.map(job => job.job_id));
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
    const pageErrors = [];
    const dialogs = [];
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("dialog", dialog => dialogs.push(dialog.message()));
    await page.route("**/*", createBrowserRequestHandler(mockState));
    await page.goto("http://home-server.test/");
    await page.locator('.sidebar [data-view="jobs"]').click();
    await page.locator('[data-delete-job="deletion-job-1"]').waitFor();
    assert.equal(await page.locator("[data-select-job]").count(), 0);
    assert.equal(await page.locator("#job-selection-actions").isVisible(), false);
    assert.equal(await page.locator('#jobs-pagination [data-jobs-page="0"]').isDisabled(), true);

    await page.locator("#toggle-job-selection").click();
    assert.equal(await page.locator("[data-select-job]").count(), 10);
    assert.equal(await page.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await page.locator("#delete-selected-job-outputs").isDisabled(), true);
    assert.equal(await page.locator("[data-delete-job]").count(), 0);
    for (const activeJobNumber of [7, 8, 9, 10]) {
      assert.equal(await page.locator(`[data-select-job="deletion-job-${activeJobNumber}"]`).isDisabled(), false);
    }
    await page.locator('[data-select-job="deletion-job-1"]').check();
    await waitForSelectedCount(page, 1);
    assert.equal(await page.locator("#delete-selected-job-history").isEnabled(), true);
    assert.equal(await page.locator("#delete-selected-job-outputs").isEnabled(), true);
    await page.locator('[data-select-job="deletion-job-1"]').uncheck();
    await waitForSelectedCount(page, 0);
    assert.equal(await page.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await page.locator("#delete-selected-job-outputs").isDisabled(), true);

    await page.locator("#select-all-jobs").click();
    await waitForSelectedCount(page, 10);
    assert.equal(await page.locator("[data-select-job]:checked").count(), 10);
    assert.equal(await page.locator('[data-select-job="deletion-job-11"]').count(), 0);
    await page.locator("#select-all-jobs").click();
    await waitForSelectedCount(page, 0);

    await page.locator("#select-every-job").click();
    await waitForSelectedCount(page, 12);
    assert.equal(await page.locator("[data-select-job]:checked").count(), 10);
    assert.equal(await page.locator("#select-every-job").textContent(), "범위 전체 선택 해제");
    await page.locator("#select-every-job").click();
    await waitForSelectedCount(page, 0);

    await page.locator('[data-select-job="deletion-job-1"]').check();
    await page.locator('[data-select-job="deletion-job-2"]').check();
    await page.locator('[data-select-job="deletion-job-2"]').focus();
    await page.waitForResponse(response => new URL(response.url()).pathname === "/api/jobs");
    await waitForSelectedCount(page, 2);
    assert.equal(await page.locator('[data-select-job="deletion-job-2"]').evaluate(checkbox =>
      document.activeElement === checkbox), true);
    const cancelledMessage = await confirmDeletion(page, "delete-selected-job-history", false);
    assert.match(cancelledMessage, /2개의 이력/);
    assert.match(cancelledMessage, /결과물 파일은 유지/);
    assert.equal(mockState.deletionRequests.length, 0);
    await waitForSelectedCount(page, 2);

    await confirmDeletion(page, "delete-selected-job-history", true);
    await waitForSelectedCount(page, 0);
    assert.deepEqual(mockState.deletionRequests, [
      { jobIdentifier: "deletion-job-1", deleteOutputs: false },
      { jobIdentifier: "deletion-job-2", deleteOutputs: false },
    ]);
    assert.equal(dialogs.length, 2);
    assert.equal(mockState.outputJobIds.has("deletion-job-1"), true);
    assert.equal(mockState.outputJobIds.has("deletion-job-2"), true);
    assert.equal(mockState.jobs.some(job => job.job_id === "deletion-job-3"), true);

    mockState.failedJobIds.add("deletion-job-4");
    await page.locator('[data-select-job="deletion-job-3"]').check();
    await page.locator('[data-select-job="deletion-job-4"]').check();
    let releaseDeletion;
    mockState.deletionGate = new Promise(resolve => { releaseDeletion = resolve; });
    const outputMessage = await confirmDeletion(page, "delete-selected-job-outputs", true);
    assert.match(outputMessage, /2개의 이력과/);
    assert.match(outputMessage, /영구 삭제/);
    await page.waitForFunction(() => document.getElementById("selected-job-count").textContent === "삭제 중…");
    assert.equal(await page.locator("#toggle-job-selection").isDisabled(), true);
    assert.equal(await page.locator("#select-all-jobs").isDisabled(), true);
    assert.equal(await page.locator("#select-every-job").isDisabled(), true);
    assert.equal(await page.locator("[data-toggle-job-protection]:enabled").count(), 0);
    assert.equal(await page.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await page.locator("#delete-selected-job-outputs").isDisabled(), true);
    assert.equal(await page.locator("[data-select-job]:enabled").count(), 0);
    assert.equal(await page.locator("#jobs-pagination").getAttribute("inert"), "");
    await page.locator("#delete-selected-job-outputs").evaluate(button => button.click());
    assert.equal(dialogs.length, 3);
    releaseDeletion();
    mockState.deletionGate = null;
    await waitForSelectedCount(page, 1);
    assert.equal(await page.locator('[data-select-job="deletion-job-4"]').isChecked(), true);
    assert.equal(mockState.outputJobIds.has("deletion-job-3"), false);
    assert.equal(mockState.outputJobIds.has("deletion-job-4"), true);
    assert.deepEqual(mockState.deletionRequests.slice(2), [
      { jobIdentifier: "deletion-job-3", deleteOutputs: true },
      { jobIdentifier: "deletion-job-4", deleteOutputs: true },
    ]);
    await page.waitForFunction(() => /삭제 실패 1개/.test(document.getElementById("notice").textContent));
    mockState.failedJobIds.clear();
    await confirmDeletion(page, "delete-selected-job-outputs", true);
    await waitForSelectedCount(page, 0);
    assert.equal(mockState.outputJobIds.has("deletion-job-4"), false);

    mockState.jobs = createJobFixtures();
    await page.waitForFunction(() => document.querySelectorAll("[data-select-job]").length === 10);
    await page.locator('[data-select-job="deletion-job-1"]').check();
    await page.locator('.sidebar [data-view="outputs"]').click();
    await page.locator('[data-output-job="deletion-job-12"]').click();
    await page.waitForFunction(() => document.querySelectorAll("[data-select-job]").length === 1);
    await waitForSelectedCount(page, 0);
    await page.locator('[data-select-job="deletion-job-12"]').check();
    await page.locator("#clear-jobs-filter").click();
    await page.locator('[data-select-job="deletion-job-1"]').waitFor();
    await waitForSelectedCount(page, 0);
    await page.locator('[data-select-job="deletion-job-1"]').check();
    await page.locator('#jobs-pagination [data-jobs-page="2"]').first().click();
    await page.locator('[data-select-job="deletion-job-11"]').waitFor();
    await waitForSelectedCount(page, 1);
    assert.equal(await page.locator('#jobs-pagination [data-jobs-page="3"]').isDisabled(), true);
    await page.locator("#select-all-jobs").click();
    await waitForSelectedCount(page, 3);
    await confirmDeletion(page, "delete-selected-job-history", true);
    await page.locator('[data-select-job="deletion-job-2"]').waitFor();
    await waitForSelectedCount(page, 0);
    assert.equal(await page.locator("#jobs-pagination").isVisible(), false);
    await page.locator("#toggle-job-selection").click();
    assert.equal(await page.locator("[data-select-job]").count(), 0);
    assert.equal(await page.locator("#job-selection-actions").isVisible(), false);
    await page.locator("#toggle-job-selection").click();
    await waitForSelectedCount(page, 0);

    await page.locator('[data-select-job="deletion-job-2"]').check();
    mockState.jobs[0].requests[0].status = "running";
    await page.waitForFunction(() => document.getElementById("delete-selected-job-history").disabled);
    await waitForSelectedCount(page, 1);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#select-all-jobs").click();
    await waitForSelectedCount(page, 9);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await page.screenshot({ path: path.join(screenshotDirectory, "job-multiple-deletion-mobile.png"), fullPage: true });

    mockState.jobs = [];
    await page.waitForFunction(() => document.querySelectorAll("[data-select-job]").length === 0);
    await waitForSelectedCount(page, 0);
    assert.equal(await page.locator("#select-all-jobs").isDisabled(), true);
    assert.equal(await page.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await page.locator("#delete-selected-job-outputs").isDisabled(), true);
    assert.deepEqual(pageErrors, []);
    await verifyProtectionAndGlobalSelection(browser);
    console.log("Passed: multiple job deletion, all pages, protection, confirmations, polling, partial failures, mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
