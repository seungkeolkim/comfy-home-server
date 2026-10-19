/** Mock API와 Edge에서 일반 탭 이동의 페이지·필터·스크롤 보존을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

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
    for (let outputNumber = 1; outputNumber <= 6; outputNumber += 1) {
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
    if (await handleJobFolderReadRequest(route, fixtures.jobs || [])) return;
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
    if (requestPath === "/api/session") response = { authenticated: fixtures.authenticated !== false };
    else if (requestPath === "/api/login") {
      fixtures.authenticated = true;
      response = { authenticated: true };
    }
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
    } else if (requestPath.startsWith("/api/outputs/preview/")) {
      await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="black"/></svg>' });
      return;
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
    await browserPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 작업의 결과 6개");
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
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 작업의 결과 6개");
    await browserPage.locator("#clear-output-filter").click();
    await browserPage.waitForFunction(() => document.getElementById("output-count").textContent === "180개 파일");
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
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 작업의 결과 6개");
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
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 요청의 결과 6개");
    await traverseNavigationHistory(browserPage, "back", unfilteredJobsEntry);
    await traverseNavigationHistory(browserPage, "forward", requestResultsEntry);
    assert.equal(await browserPage.locator("#output-count").textContent(), "이 요청의 결과 6개");
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

/** 실제 가운데 버튼 또는 Ctrl+클릭으로 새 탭을 열고 원래 화면의 History를 확인합니다. */
async function openNavigationInNewTab(browserPage, navigationLocator, clickOptions = { button: "middle" }) {
  const originalEntry = await currentNavigationEntry(browserPage);
  const [destinationPage] = await Promise.all([
    browserPage.context().waitForEvent("page"),
    navigationLocator.click(clickOptions),
  ]);
  await destinationPage.waitForLoadState("domcontentloaded");
  await destinationPage.locator("#application").waitFor({ state: "visible" });
  assert.equal(await currentNavigationEntry(browserPage), originalEntry);
  return destinationPage;
}

/** 브라우저가 직접 여는 새 탭의 최초 요청도 처리하도록 로컬 Mock HTTP 서버를 엽니다. */
async function startNavigationFixtureServer(fixtures) {
  const handleRequest = createNavigationRequestHandler(fixtures);
  const server = http.createServer((request, response) => {
    handleRequest({
      request: () => ({
        url: () => `http://${request.headers.host}${request.url}`,
        method: () => request.method,
      }),
      fulfill: async ({ status = 200, contentType = "text/plain", body = "" }) => {
        response.writeHead(status, { "Content-Type": contentType });
        response.end(body);
      },
    }).catch(error => {
      response.writeHead(500);
      response.end(error.message);
    });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  return server;
}

/** 새 탭의 페이지·작업/요청 필터, URL 재진입, 로그인과 변경 동작 격리를 검증합니다. */
async function verifyNewTabNavigation(browser, viewport) {
  const fixtures = createNavigationFixtures();
  const fixtureServer = await startNavigationFixtureServer(fixtures);
  const baseUrl = `http://127.0.0.1:${fixtureServer.address().port}`;
  const browserContext = await browser.newContext({ viewport });
  const pageErrors = [];
  browserContext.on("page", openedPage => openedPage.on("pageerror", error => pageErrors.push(error.message)));
  try {
    const originalPage = await browserContext.newPage();
    await originalPage.goto(`${baseUrl}/`);
    await originalPage.locator("#application").waitFor({ state: "visible" });
    await originalPage.locator("#generate-anima-prompt").fill("original tab input");
    const jobsPage = await openNavigationInNewTab(originalPage, originalPage.locator('[data-view="jobs"]:visible'));
    await jobsPage.locator('[data-show-job-results="navigation-job-1"]').waitFor();
    assert.equal(await originalPage.locator("#view-generate").isVisible(), true);
    assert.equal(await originalPage.locator("#generate-anima-prompt").inputValue(), "original tab input");
    const secondJobsPage = await openNavigationInNewTab(jobsPage, jobsPage.locator('[data-jobs-page="2"]').first());
    await secondJobsPage.locator('[data-show-job-results="navigation-job-14"]').waitFor();
    assert.equal(new URL(secondJobsPage.url()).searchParams.get("page"), "2");
    assert.equal(await jobsPage.locator('[data-jobs-page="1"][aria-current="page"]').count(), 1);

    const jobOutputsPage = await openNavigationInNewTab(secondJobsPage,
      secondJobsPage.locator('[data-show-job-results="navigation-job-14"]'));
    await jobOutputsPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 작업의 결과 6개");
    assert.equal(new URL(jobOutputsPage.url()).searchParams.get("job_id"), "navigation-job-14");
    const linkedJobPage = await openNavigationInNewTab(jobOutputsPage,
      jobOutputsPage.locator('[data-output-job="navigation-job-14"]').first());
    await linkedJobPage.waitForFunction(() => !applicationState.jobsLoading);
    assert.equal(await linkedJobPage.locator(".job-card").count(), 1);
    assert.match(await linkedJobPage.locator("#jobs-filter-label").textContent(), /navigation-job-14/);
    const allJobsPage = await openNavigationInNewTab(linkedJobPage, linkedJobPage.locator("#clear-jobs-filter"));
    await allJobsPage.locator('[data-show-job-results="navigation-job-1"]').waitFor();
    assert.equal(new URL(allJobsPage.url()).searchParams.has("job_id"), false);

    await secondJobsPage.locator('[data-job-details="navigation-job-14"] > summary').click();
    const requestOutputsPage = await openNavigationInNewTab(secondJobsPage,
      secondJobsPage.locator('[data-show-request-results="navigation-job-14-request"]'));
    await requestOutputsPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 요청의 결과 6개");
    assert.equal(new URL(requestOutputsPage.url()).searchParams.get("request_id"), "navigation-job-14-request");
    await requestOutputsPage.reload();
    await requestOutputsPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 요청의 결과 6개");

    const allOutputsPage = await openNavigationInNewTab(jobOutputsPage, jobOutputsPage.locator("#clear-output-filter"));
    await allOutputsPage.waitForFunction(() => document.getElementById("output-count").textContent === "180개 파일");
    const secondOutputsPage = await openNavigationInNewTab(allOutputsPage,
      allOutputsPage.locator('[data-outputs-page="2"]').first());
    await secondOutputsPage.locator('[data-outputs-page="2"][aria-current="page"]').waitFor();
    assert.equal(new URL(secondOutputsPage.url()).searchParams.get("page"), "2");
    await clickNavigationTab(secondOutputsPage, "generate");
    const rememberedOutputsPage = await openNavigationInNewTab(secondOutputsPage,
      secondOutputsPage.locator('[data-view="outputs"]:visible'));
    await rememberedOutputsPage.locator('[data-outputs-page="2"][aria-current="page"]').waitFor();
    const tagsPage = await openNavigationInNewTab(originalPage, originalPage.locator('[data-view="tags"]:visible'),
      { modifiers: ["Control"] });
    assert.equal(await tagsPage.locator("#view-tags").isVisible(), true);

    const copiedUrlPage = await browserContext.newPage();
    await copiedUrlPage.goto(secondJobsPage.url());
    await copiedUrlPage.locator('[data-jobs-page="2"][aria-current="page"]').waitFor();
    await copiedUrlPage.goto(`${baseUrl}/?view=unknown&page=-5&job_id=ignored`);
    await copiedUrlPage.locator("#application").waitFor({ state: "visible" });
    assert.equal(await copiedUrlPage.locator("#view-generate").isVisible(), true);
    assert.equal(await copiedUrlPage.locator('[data-restore-job]').first().evaluate(button => button.tagName), "BUTTON");
    assert.deepEqual(fixtures.mutations, []);
    assert.equal(fixtures.inputRequests, 0);

    const loginPage = await browserContext.newPage();
    fixtures.authenticated = false;
    const outputQueriesBeforeLogin = fixtures.queries.filter(query => query.path === "/api/outputs").length;
    await loginPage.goto(jobOutputsPage.url());
    await loginPage.locator("#login-screen").waitFor({ state: "visible" });
    assert.equal(fixtures.queries.filter(query => query.path === "/api/outputs").length, outputQueriesBeforeLogin);
    await loginPage.locator("#login-password").fill("test-password");
    await loginPage.locator('#login-form button[type="submit"]').click();
    await loginPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 작업의 결과 6개");
    assert.deepEqual(fixtures.mutations, ["/api/login"]);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserContext.close();
    await new Promise(resolve => fixtureServer.close(resolve));
  }
}

/** Desktop과 mobile에서 탭 상태·History·가운데 버튼 새 탭 열기를 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyNavigation(browser, { width: 1280, height: 950 });
    await verifyNavigation(browser, { width: 390, height: 844 });
    await verifyBrowserHistory(browser, { width: 1280, height: 950 });
    await verifyBrowserHistory(browser, { width: 390, height: 844 });
    await verifyNewTabNavigation(browser, { width: 1280, height: 950 });
    await verifyNewTabNavigation(browser, { width: 390, height: 844 });
    console.log("Passed: desktop/mobile tab state, history, middle/Ctrl new tabs, deep links, pagination/filters, login, action safety.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
