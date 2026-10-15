/** Mock API와 Edge에서 일반 탭 이동의 페이지·필터·스크롤 보존을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 여러 페이지와 펼친 요청을 확인할 작업 및 결과물을 준비합니다. */
function createNavigationFixtures() {
  const jobs = [];
  const outputs = [];
  for (let jobNumber = 1; jobNumber <= 30; jobNumber += 1) {
    const jobIdentifier = `navigation-job-${jobNumber}`;
    jobs.push({
      job_id: jobIdentifier, workflow: "anima", description: `탭 이동 검증 ${jobNumber}`,
      created_at: "2026-10-15", status: "completed", status_counts: { completed: 1 },
      request_count: 1, inputs: { body: { prompt: `original prompt ${jobNumber}` }, settings: {}, loras: [] },
      requests: [{ request_id: `${jobIdentifier}-request`, request_index: 1, status: "completed", result: {} }],
    });
    for (let outputNumber = 1; outputNumber <= 2; outputNumber += 1) {
      const filename = `${jobIdentifier}-${outputNumber}.mp4`;
      outputs.push({ path: `anima/${filename}`, name: filename, kind: "video", job_id: jobIdentifier });
    }
  }
  return { jobs, outputs, queries: [], mutations: [], inputRequests: 0, responseGate: null };
}

/** 페이지와 작업 필터에 맞는 Mock API 응답을 실제 화면에 제공합니다. */
function createNavigationRequestHandler(fixtures) {
  return async function handleNavigationRequest(route) {
    const requestUrl = new URL(route.request().url());
    const requestPath = requestUrl.pathname;
    if (route.request().method() !== "GET") fixtures.mutations.push(requestPath);
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({
        contentType: contentTypes[filename],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8"),
      });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/presets" || requestPath === "/api/loras/presets") response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath.startsWith("/api/jobs/") && requestPath.endsWith("/inputs")) {
      fixtures.inputRequests += 1;
      response = fixtures.jobs.find(job => job.job_id === requestPath.split("/").at(-2));
    }
    else if (requestPath === "/api/jobs/deletion-candidates") {
      response = { job_ids: fixtures.jobs.map(job => job.job_id) };
    } else if (requestPath === "/api/jobs" || requestPath === "/api/outputs") {
      const pageNumber = Number(requestUrl.searchParams.get("page"));
      const pageSize = Number(requestUrl.searchParams.get("page_size"));
      const jobIdentifier = requestUrl.searchParams.get("job_id");
      fixtures.queries.push({ path: requestPath, pageNumber, jobIdentifier });
      let matchingItems = requestPath === "/api/jobs" ? fixtures.jobs : fixtures.outputs;
      if (jobIdentifier) matchingItems = matchingItems.filter(item => item.job_id === jobIdentifier);
      const requestIdentifier = requestUrl.searchParams.get("request_id");
      if (requestIdentifier) matchingItems = matchingItems.filter(item => `${item.job_id}-request` === requestIdentifier);
      const pageItems = matchingItems.slice((pageNumber - 1) * pageSize, pageNumber * pageSize);
      response = {
        page: pageNumber, total: matchingItems.length,
        total_pages: Math.max(1, Math.ceil(matchingItems.length / pageSize)), active_count: 0,
        ...(requestPath === "/api/jobs"
          ? { items: pageItems.map(job => ({ ...job, requests: undefined })) } : { files: pageItems }),
      };
      const responseGate = fixtures.responseGate;
      if (responseGate?.path === requestPath && responseGate.pageNumber === pageNumber) {
        fixtures.responseGate = null;
        responseGate.markStarted();
        await responseGate.promise;
        if (responseGate.fail) {
          await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Delayed stale error" }) });
          return;
        }
      }
    } else if (requestPath.startsWith("/api/jobs/")) {
      response = fixtures.jobs.find(job => job.job_id === requestPath.split("/").at(-1));
    } else if (requestPath === "/api/batches") {
      response = { job_id: "submitted-job", request_ids: ["submitted-request"] };
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${route.request().method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** Desktop과 mobile에서 현재 보이는 탭 버튼으로 이동합니다. */
async function clickNavigationTab(browserPage, viewName) {
  await browserPage.locator(`[data-view="${viewName}"]:visible`).click();
  await browserPage.locator(`#view-${viewName}`).waitFor({ state: "visible" });
}

/** 목록 갱신이 끝난 후 스크롤이 저장한 위치와 같은지 확인합니다. */
async function assertScrollPosition(browserPage, expectedPosition) {
  await browserPage.waitForFunction(expected => Math.abs(window.scrollY - expected) <= 2, expectedPosition);
  const actualPosition = await browserPage.evaluate(() => window.scrollY);
  assert.ok(Math.abs(actualPosition - expectedPosition) <= 2, `Expected scroll ${expectedPosition}, got ${actualPosition}`);
}

/** 작업 결과 왕복, 선택·펼침·입력 보존과 명시적 필터 전환을 검증합니다. */
async function verifyNavigation(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createNavigationRequestHandler(createNavigationFixtures()));
  try {
    await browserPage.goto("http://navigation.test/");
    await browserPage.locator("#application").waitFor({ state: "visible" });
    await browserPage.locator("#generate-anima-prompt").fill("keep this input");
    await browserPage.evaluate(() => window.scrollTo(0, 400));
    const generationScrollPosition = await browserPage.evaluate(() => window.scrollY);
    await clickNavigationTab(browserPage, "jobs");
    await browserPage.locator('[data-show-job-results="navigation-job-1"]').waitFor();
    await assertScrollPosition(browserPage, 0);
    await browserPage.locator('[data-jobs-page="2"]').first().click();
    await browserPage.locator('[data-show-job-results="navigation-job-11"]').waitFor();
    await browserPage.locator("#toggle-job-selection").click();
    await browserPage.locator('[data-select-job="navigation-job-14"]').check();
    await browserPage.locator('[data-job-details="navigation-job-14"] > summary').click();
    await browserPage.locator('[data-job-details="navigation-job-14"] .job-request').waitFor();
    const resultsButton = browserPage.locator('[data-show-job-results="navigation-job-14"]');
    await resultsButton.scrollIntoViewIfNeeded();
    const jobsScrollPosition = await browserPage.evaluate(() => window.scrollY);
    assert.ok(jobsScrollPosition > 300);
    await resultsButton.click();
    await browserPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 작업의 결과 2개");
    await assertScrollPosition(browserPage, 0);

    await clickNavigationTab(browserPage, "jobs");
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    assert.equal(await browserPage.locator('[data-jobs-page="2"][aria-current="page"]').count(), 1);
    assert.equal(await browserPage.locator('[data-select-job="navigation-job-14"]').isChecked(), true);
    assert.equal(await browserPage.locator('[data-job-details="navigation-job-14"]').getAttribute("open"), "");
    await assertScrollPosition(browserPage, jobsScrollPosition);
    await clickNavigationTab(browserPage, "jobs");
    await assertScrollPosition(browserPage, jobsScrollPosition);

    await clickNavigationTab(browserPage, "outputs");
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 작업의 결과 2개");
    await browserPage.locator("#clear-output-filter").click();
    await browserPage.waitForFunction(() => document.getElementById("output-count").textContent === "60개 파일");
    await browserPage.locator('[data-outputs-page="2"]').first().click();
    await browserPage.locator('.output-info strong').filter({ hasText: "navigation-job-13-1.mp4" }).waitFor();
    await browserPage.evaluate(() => {
      window.retainedOutputCard = document.querySelector(".output-card");
      window.scrollTo(0, 700);
    });
    const outputsScrollPosition = await browserPage.evaluate(() => window.scrollY);
    assert.ok(outputsScrollPosition > 300);
    await clickNavigationTab(browserPage, "tags");
    await assertScrollPosition(browserPage, 0);
    const outputResponse = browserPage.waitForResponse(response => response.url().includes("/api/outputs?"));
    await clickNavigationTab(browserPage, "outputs");
    await outputResponse;
    await browserPage.waitForFunction(() => applicationState.outputsRenderSignature !== null);
    assert.equal(await browserPage.locator('[data-outputs-page="2"][aria-current="page"]').count(), 1);
    await assertScrollPosition(browserPage, outputsScrollPosition);
    assert.equal(await browserPage.evaluate(() => window.retainedOutputCard === document.querySelector(".output-card")), true);

    await browserPage.locator('[data-output-job="navigation-job-14"]').first().click();
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    assert.equal(await browserPage.locator(".job-card").count(), 1);
    assert.match(await browserPage.locator("#jobs-filter-label").textContent(), /navigation-job-14/);
    await assertScrollPosition(browserPage, 0);
    await clickNavigationTab(browserPage, "generate");
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), "keep this input");
    await assertScrollPosition(browserPage, generationScrollPosition);
    await clickNavigationTab(browserPage, "jobs");
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    assert.equal(await browserPage.locator(".job-card").count(), 1);
    assert.equal(await browserPage.locator("#jobs-filter").isVisible(), true);
    await browserPage.locator("#clear-jobs-filter").click();
    await browserPage.locator('[data-show-job-results="navigation-job-1"]').waitFor();
    assert.equal(await browserPage.locator('[data-jobs-page="1"][aria-current="page"]').count(), 1);
    await browserPage.locator('[data-restore-job="navigation-job-1"]').click();
    await browserPage.locator("#view-generate").waitFor({ state: "visible" });
    await assertScrollPosition(browserPage, 0);
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), "original prompt 1");
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserPage.close();
  }
}

/** 특정 목록 응답을 보류하여 History 이동과 응답 순서가 엇갈리게 만듭니다. */
function holdNextListResponse(fixtures, requestPath, pageNumber, fail = false) {
  let releaseResponse;
  let markStarted;
  const promise = new Promise(resolve => { releaseResponse = resolve; });
  const started = new Promise(resolve => { markStarted = resolve; });
  fixtures.responseGate = { path: requestPath, pageNumber, promise, markStarted, fail };
  return { started, releaseResponse };
}

/** 저장된 History 항목까지 이동하고 목록 및 스크롤 복원을 기다립니다. */
async function traverseNavigationHistory(browserPage, direction, entryIdentifier) {
  await browserPage.evaluate(historyDirection => window.history[historyDirection](), direction);
  await browserPage.waitForFunction(expectedIdentifier =>
    applicationState.navigationEntryId === expectedIdentifier &&
    !applicationState.pendingNavigationScroll && !applicationState.jobsLoading, entryIdentifier);
}

/** 현재 Browser History 항목의 ID를 읽습니다. */
async function currentNavigationEntry(browserPage) {
  return browserPage.evaluate(() => window.history.state.homeServerNavigation.entryId);
}

/** History의 페이지·필터·스크롤 복원과 오래된 응답·변경 동작 재실행 방지를 검증합니다. */
async function verifyBrowserHistory(browser, viewport) {
  const fixtures = createNavigationFixtures();
  const browserPage = await browser.newPage({ viewport });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createNavigationRequestHandler(fixtures));
  try {
    await browserPage.goto("http://history.test/");
    await browserPage.locator("#application").waitFor({ state: "visible" });
    const initialEntry = await currentNavigationEntry(browserPage);
    await clickNavigationTab(browserPage, "jobs");
    await browserPage.locator('[data-show-job-results="navigation-job-1"]').waitFor();
    const firstJobsEntry = await currentNavigationEntry(browserPage);
    await traverseNavigationHistory(browserPage, "back", initialEntry);
    assert.equal(await browserPage.locator("#view-generate").isVisible(), true);
    await traverseNavigationHistory(browserPage, "forward", firstJobsEntry);
    const historyLength = await browserPage.evaluate(() => window.history.length);
    await clickNavigationTab(browserPage, "jobs");
    await browserPage.waitForTimeout(1200);
    assert.equal(await browserPage.evaluate(() => window.history.length), historyLength);

    await browserPage.locator('[data-jobs-page="2"]').first().click();
    await browserPage.locator('[data-show-job-results="navigation-job-14"]').waitFor();
    await browserPage.locator('[data-job-details="navigation-job-14"] > summary').click();
    await browserPage.locator('[data-job-details="navigation-job-14"] .job-request').waitFor();
    const resultsButton = browserPage.locator('[data-show-job-results="navigation-job-14"]');
    await resultsButton.scrollIntoViewIfNeeded();
    const jobsScrollPosition = await browserPage.evaluate(() => window.scrollY);
    const secondJobsEntry = await currentNavigationEntry(browserPage);
    await resultsButton.click();
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    const jobResultsEntry = await currentNavigationEntry(browserPage);
    await browserPage.locator('[data-output-job="navigation-job-14"]').first().click();
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    const filteredJobsEntry = await currentNavigationEntry(browserPage);
    await traverseNavigationHistory(browserPage, "back", jobResultsEntry);
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 작업의 결과 2개");
    await traverseNavigationHistory(browserPage, "back", secondJobsEntry);
    assert.equal(await browserPage.locator('[data-jobs-page="2"][aria-current="page"]').count(), 1);
    assert.equal(await browserPage.locator('[data-job-details="navigation-job-14"]').getAttribute("open"), "");
    await assertScrollPosition(browserPage, jobsScrollPosition);
    await traverseNavigationHistory(browserPage, "forward", jobResultsEntry);
    await traverseNavigationHistory(browserPage, "forward", filteredJobsEntry);
    assert.equal(await browserPage.locator(".job-card").count(), 1);
    await traverseNavigationHistory(browserPage, "back", jobResultsEntry);
    await clickNavigationTab(browserPage, "tags");
    const tagsEntry = await currentNavigationEntry(browserPage);
    await browserPage.evaluate(() => window.history.forward());
    await browserPage.waitForTimeout(100);
    assert.equal(await currentNavigationEntry(browserPage), tagsEntry);

    await clickNavigationTab(browserPage, "outputs");
    await browserPage.locator("#clear-output-filter").click();
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    const allOutputsEntry = await currentNavigationEntry(browserPage);
    await browserPage.locator('[data-outputs-page="2"]').first().click();
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    const secondOutputsEntry = await currentNavigationEntry(browserPage);
    await browserPage.evaluate(() => window.scrollTo(0, 700));
    await assertScrollPosition(browserPage, 700);
    await browserPage.locator('[data-outputs-page="3"]').first().evaluate(button => button.click());
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    const outputQueriesBeforeBack = fixtures.queries.filter(query => query.path === "/api/outputs").length;
    await traverseNavigationHistory(browserPage, "back", secondOutputsEntry);
    await assertScrollPosition(browserPage, 700);
    assert.ok(fixtures.queries.filter(query => query.path === "/api/outputs").length > outputQueriesBeforeBack);

    const delayedOutputs = holdNextListResponse(fixtures, "/api/outputs", 3, true);
    await browserPage.locator('[data-outputs-page="3"]').first().evaluate(button => button.click());
    await delayedOutputs.started;
    await traverseNavigationHistory(browserPage, "back", secondOutputsEntry);
    const delayedOutputResponse = browserPage.waitForResponse(response => response.status() === 503);
    delayedOutputs.releaseResponse();
    await delayedOutputResponse;
    assert.equal(await browserPage.locator('[data-outputs-page="2"][aria-current="page"]').count(), 1);
    assert.doesNotMatch(await browserPage.locator("#notice").textContent(), /Delayed stale error/);

    await traverseNavigationHistory(browserPage, "back", allOutputsEntry);
    const delayedScroll = holdNextListResponse(fixtures, "/api/outputs", 2);
    await browserPage.evaluate(() => window.history.forward());
    await delayedScroll.started;
    await browserPage.mouse.wheel(0, 150);
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    await browserPage.evaluate(() => window.scrollTo(0, 150));
    const delayedScrollResponse = browserPage.waitForResponse(response => response.url().includes("/api/outputs?") && response.status() === 200);
    delayedScroll.releaseResponse();
    await delayedScrollResponse;
    await assertScrollPosition(browserPage, 150);

    await clickNavigationTab(browserPage, "jobs");
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    await browserPage.locator("#clear-jobs-filter").click();
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    const unfilteredJobsEntry = await currentNavigationEntry(browserPage);
    const delayedJobs = holdNextListResponse(fixtures, "/api/jobs", 2, true);
    await browserPage.locator('[data-jobs-page="2"]').first().click();
    await delayedJobs.started;
    await browserPage.evaluate(() => window.history.back());
    await browserPage.waitForFunction(expected => applicationState.navigationEntryId === expected, unfilteredJobsEntry);
    delayedJobs.releaseResponse();
    await browserPage.waitForFunction(() => !applicationState.jobsLoading && !applicationState.pendingNavigationScroll);
    assert.equal(await browserPage.locator('[data-jobs-page="1"][aria-current="page"]').count(), 1);
    assert.doesNotMatch(await browserPage.locator("#notice").textContent(), /Delayed stale error/);

    await browserPage.locator('[data-job-details="navigation-job-1"] > summary').click();
    await browserPage.locator('[data-show-request-results="navigation-job-1-request"]').click();
    await browserPage.waitForFunction(() => !applicationState.pendingNavigationScroll);
    const requestResultsEntry = await currentNavigationEntry(browserPage);
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 요청의 결과 2개");
    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);
    await traverseNavigationHistory(browserPage, "forward", requestResultsEntry);
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 요청의 결과 2개");
    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);

    await browserPage.locator('[data-restore-job="navigation-job-1"]').click();
    await browserPage.locator("#view-generate").waitFor({ state: "visible" });
    await browserPage.waitForFunction(() => !document.getElementById("submit-button").disabled);
    const restoredGenerationEntry = await currentNavigationEntry(browserPage);
    const inputRequests = fixtures.inputRequests;
    await browserPage.locator("#generate-anima-prompt").fill("edited after restoration");
    await browserPage.locator("#submit-button").click();
    await browserPage.waitForFunction(() => !document.getElementById("submit-button").disabled);
    assert.deepEqual(fixtures.mutations, ["/api/batches"]);
    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);
    await traverseNavigationHistory(browserPage, "forward", restoredGenerationEntry);
    assert.equal(await browserPage.locator("#generate-anima-prompt").inputValue(), "edited after restoration");
    assert.equal(fixtures.inputRequests, inputRequests);
    assert.deepEqual(fixtures.mutations, ["/api/batches"]);

    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);
    await browserPage.locator('[data-jobs-page="3"]').first().click();
    await browserPage.waitForFunction(() => !applicationState.jobsLoading);
    const removedPageEntry = await currentNavigationEntry(browserPage);
    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);
    fixtures.jobs = fixtures.jobs.slice(0, 5);
    await traverseNavigationHistory(browserPage, "forward", removedPageEntry);
    assert.equal(await browserPage.locator(".job-card").count(), 5);
    assert.equal(await browserPage.evaluate(() => window.history.state.homeServerNavigation.pageNumber), 1);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserPage.close();
  }
}

/** Desktop과 mobile에서 탭 상태 보존 및 Browser History 계약을 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyNavigation(browser, { width: 1280, height: 950 });
    await verifyNavigation(browser, { width: 390, height: 844 });
    await verifyBrowserHistory(browser, { width: 1280, height: 950 });
    await verifyBrowserHistory(browser, { width: 390, height: 844 });
    console.log("Passed: desktop/mobile tab state, browser back/forward, pagination, filters, scroll, stale responses, input/action safety.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
