/** Mock API와 Edge에서 이미지 단건 삭제의 확인·실패·페이지 보정을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 마지막 페이지에 이미지 하나만 남는 결과물을 준비합니다. */
function createOutputFixtures() {
  const outputs = [];
  for (let outputNumber = 1; outputNumber <= 65; outputNumber += 1) {
    const filename = outputNumber === 1 ? "movie.mp4" : `이미지 ${outputNumber}.png`;
    outputs.push({
      output_id: outputNumber, name: filename, path: `sorted/${filename}`,
      kind: outputNumber === 1 ? "video" : "image", job_id: "image-job",
      width: 768, height: 512, dimensions_source: "settings",
    });
  }
  return { outputs, deletionRequests: [], outputQueries: [], candidateQueries: [], rejectDeletion: false, failedOutputIds: new Set(), deletionGate: null };
}

/** 작업·요청 필터를 적용하여 전체 선택이 현재 목록의 범위를 넘지 않게 합니다. */
function matchingOutputs(fixtures, requestUrl) {
  const jobIdentifier = requestUrl.searchParams.get("job_id");
  const requestIdentifier = requestUrl.searchParams.get("request_id");
  return fixtures.outputs.filter(output =>
    (!jobIdentifier || output.job_id === jobIdentifier) &&
    (!requestIdentifier || `${output.job_id}-request` === requestIdentifier),
  );
}

/** 실제 앱 파일과 이미지 삭제 상태를 반영하는 Mock API를 제공합니다. */
function createOutputRequestHandler(fixtures) {
  return async function handleOutputRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = decodeURIComponent(requestUrl.pathname);
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({
        contentType: contentTypes[filename],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8"),
      });
      return;
    }
    if (requestPath.startsWith("/api/outputs/preview/")) {
      await route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="256"><rect width="384" height="256" fill="#687d94"/></svg>',
      });
      return;
    }
    let response;
    let responseStatus = 200;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/outputs/sync") response = {};
    else if (requestPath === "/api/outputs/deletion-candidates") {
      fixtures.candidateQueries.push(Object.fromEntries(requestUrl.searchParams));
      response = { output_ids: matchingOutputs(fixtures, requestUrl)
        .filter(output => output.kind === "image" && !output.deletion_protected)
        .map(output => output.output_id) };
    }
    else if (requestPath === "/api/outputs" && request.method() === "GET") {
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      fixtures.outputQueries.push(Object.fromEntries(requestUrl.searchParams));
      const matchingFiles = matchingOutputs(fixtures, requestUrl);
      response = {
        files: matchingFiles.slice((pageNumber - 1) * 64, pageNumber * 64),
        page: pageNumber, page_size: 64, total: matchingFiles.length,
        total_pages: Math.max(1, Math.ceil(matchingFiles.length / 64)),
      };
    } else if (/^\/api\/outputs\/\d+$/.test(requestPath) && request.method() === "DELETE") {
      const outputIdentifier = Number(requestPath.split("/").at(-1));
      fixtures.deletionRequests.push(outputIdentifier);
      if (fixtures.deletionGate) {
        const deletionGate = fixtures.deletionGate;
        fixtures.deletionGate = null;
        deletionGate.markStarted();
        await deletionGate.promise;
      }
      const selectedOutput = fixtures.outputs.find(output => output.output_id === outputIdentifier);
      if (fixtures.rejectDeletion || fixtures.failedOutputIds.has(outputIdentifier) || selectedOutput?.deletion_protected) {
        responseStatus = 409;
        response = { detail: "이미지 파일을 삭제할 수 없습니다." };
      } else {
        fixtures.outputs = fixtures.outputs.filter(output => output.output_id !== outputIdentifier);
        response = { deleted: true, deleted_files: 1 };
      }
    } else if (requestPath === "/api/jobs") {
      response = { items: [], page: 1, total: 0, total_pages: 1, active_count: 0 };
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 선택 개수와 선택된 삭제 조작이 최신 화면에 반영될 때까지 확인합니다. */
async function waitForSelectedOutputs(browserPage, selectedCount) {
  await browserPage.waitForFunction(expectedCount =>
    document.getElementById("selected-output-count").textContent === `${expectedCount}개 선택`, selectedCount);
}

/** 한 번의 확인창으로 다중 삭제를 승인하거나 취소합니다. */
async function confirmMultipleOutputDeletion(browserPage, selectedCount, acceptDeletion) {
  const dialogPromise = browserPage.waitForEvent("dialog");
  const clickPromise = browserPage.locator("#delete-selected-outputs").click();
  const dialog = await dialogPromise;
  assert.match(dialog.message(), new RegExp(`이미지 ${selectedCount}개`));
  assert.match(dialog.message(), /작업 이력은 유지/);
  if (acceptDeletion) await dialog.accept();
  else await dialog.dismiss();
  await clickPromise;
}

/** Desktop과 mobile에서 다중 선택·보호·일부 실패·전체 삭제를 실제 UI로 확인합니다. */
async function verifyMultipleOutputDeletion(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createOutputFixtures();
  fixtures.outputs[1].deletion_protected = true;
  fixtures.outputs.push({
    output_id: 66, name: "other-job.png", path: "anima/other-job.png", kind: "image",
    job_id: "other-job", width: 768, height: 512,
  });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createOutputRequestHandler(fixtures));
  try {
    await browserPage.goto("http://output-deletion.test/?view=outputs&page=1&job_id=image-job");
    await browserPage.locator('[data-delete-output="2"]').waitFor();
    assert.equal(await browserPage.locator('[data-delete-output="2"]').isDisabled(), true);
    assert.equal(await browserPage.locator('[data-delete-output="2"]').getAttribute("title"), "삭제 보호된 작업의 결과물입니다.");
    await browserPage.locator("#toggle-output-selection").click();
    await browserPage.waitForFunction(() => !document.getElementById("select-every-output").disabled);
    assert.equal(await browserPage.locator('[data-select-output="1"]').isDisabled(), true);
    assert.equal(await browserPage.locator('[data-select-output="2"]').isDisabled(), true);
    await browserPage.locator("#select-all-outputs").click();
    await waitForSelectedOutputs(browserPage, 62);
    await browserPage.locator('[data-outputs-page="2"]').first().click();
    await browserPage.locator('[data-select-output="65"]').check();
    await waitForSelectedOutputs(browserPage, 63);
    await browserPage.locator('[data-outputs-page="1"]').first().click();
    assert.equal(await browserPage.locator('[data-select-output="3"]').isChecked(), true);
    assert.ok(fixtures.candidateQueries.every(query => query.job_id === "image-job"));

    await browserPage.locator("#clear-output-filter").click();
    await waitForSelectedOutputs(browserPage, 0);
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 64);
    assert.equal(await browserPage.locator("#select-every-output").textContent(), "전체 선택 해제");
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 0);

    await browserPage.locator('[data-select-output="3"]').check();
    fixtures.outputs.find(output => output.output_id === 3).deletion_protected = true;
    await browserPage.locator("#refresh-outputs-button").click();
    await browserPage.waitForFunction(() => document.querySelector('[data-delete-output="3"]').disabled);
    await waitForSelectedOutputs(browserPage, 0);
    assert.equal(await browserPage.locator('[data-select-output="3"]').isDisabled(), true);
    fixtures.outputs.find(output => output.output_id === 3).deletion_protected = false;
    await browserPage.locator("#refresh-outputs-button").click();
    await browserPage.waitForFunction(() => !document.querySelector('[data-delete-output="3"]').disabled);
    await browserPage.locator('[data-select-output="3"]').check();
    await browserPage.locator('[data-select-output="4"]').check();
    await confirmMultipleOutputDeletion(browserPage, 2, false);
    assert.deepEqual(fixtures.deletionRequests, []);

    let markStarted;
    let releaseDeletion;
    const deletionStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.deletionGate = { markStarted, promise: new Promise(resolve => { releaseDeletion = resolve; }) };
    fixtures.failedOutputIds.add(4);
    await confirmMultipleOutputDeletion(browserPage, 2, true);
    await deletionStarted;
    assert.equal(await browserPage.locator("#refresh-outputs-button").isDisabled(), true);
    assert.equal(await browserPage.locator("#select-all-outputs").isDisabled(), true);
    assert.equal(await browserPage.locator("#toggle-output-selection").isDisabled(), true);
    assert.equal(await browserPage.locator("[data-select-output]:enabled").count(), 0);
    assert.equal(await browserPage.locator("[data-delete-output]:enabled").count(), 0);
    assert.equal(await browserPage.locator("#outputs-pagination").getAttribute("inert"), "");
    await browserPage.locator('[data-outputs-page="2"]').first().evaluate(button => button.click());
    assert.equal(new URL(browserPage.url()).searchParams.get("page"), "1");
    releaseDeletion();
    await waitForSelectedOutputs(browserPage, 1);
    assert.deepEqual(fixtures.deletionRequests, [3, 4]);
    assert.equal(await browserPage.locator('[data-select-output="4"]').isChecked(), true);
    assert.match(await browserPage.locator("#notice").textContent(), /삭제 실패 1개/);
    assert.equal(await browserPage.locator('[data-delete-output="2"]').isDisabled(), true);

    fixtures.failedOutputIds.clear();
    await confirmMultipleOutputDeletion(browserPage, 1, true);
    await waitForSelectedOutputs(browserPage, 0);
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 62);
    await confirmMultipleOutputDeletion(browserPage, 62, true);
    await waitForSelectedOutputs(browserPage, 0);
    assert.deepEqual(fixtures.outputs.map(output => output.output_id), [1, 2]);
    assert.equal(await browserPage.locator(".output-card").count(), 2);
    assert.equal(await browserPage.locator("#select-every-output").isDisabled(), true);
    assert.equal(await browserPage.locator("#outputs-pagination").isVisible(), false);
    assert.equal(fixtures.deletionRequests.includes(1), false);
    assert.equal(fixtures.deletionRequests.includes(2), false);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `output-multiple-deletion-${viewport.width}.png`) });
    await browserPage.locator("#toggle-output-selection").click();
    assert.equal(await browserPage.locator("[data-select-output]").count(), 0);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browserPage.close();
  }
}

/** 표시된 확인창을 승인하거나 취소하고 삭제 버튼을 누릅니다. */
async function confirmImageDeletion(browserPage, outputIdentifier, acceptDeletion) {
  const dialogPromise = browserPage.waitForEvent("dialog");
  const clickPromise = browserPage.locator(`[data-delete-output="${outputIdentifier}"]`).click();
  const dialog = await dialogPromise;
  assert.match(dialog.message(), /영구 삭제/);
  assert.match(dialog.message(), /sorted\//);
  if (acceptDeletion) await dialog.accept();
  else await dialog.dismiss();
  await clickPromise;
}

/** Desktop과 mobile에서 취소·실패·성공 및 마지막 페이지 보정을 확인합니다. */
async function verifyOutputDeletion(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createOutputFixtures();
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createOutputRequestHandler(fixtures));
  try {
    await browserPage.goto("http://output-deletion.test/?view=outputs&page=2&job_id=image-job");
    await browserPage.locator('[data-delete-output="65"]').waitFor();
    await confirmImageDeletion(browserPage, 65, false);
    assert.deepEqual(fixtures.deletionRequests, []);
    assert.equal(await browserPage.locator('[data-delete-output="65"]').count(), 1);

    fixtures.rejectDeletion = true;
    await confirmImageDeletion(browserPage, 65, true);
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent === "이미지 파일을 삭제할 수 없습니다.");
    await browserPage.waitForFunction(() => !document.querySelector('[data-delete-output="65"]').disabled);
    assert.equal(await browserPage.locator(".output-card").count(), 1);

    fixtures.rejectDeletion = false;
    await confirmImageDeletion(browserPage, 65, true);
    await browserPage.waitForFunction(() => document.getElementById("output-count").textContent === "이 작업의 결과 64개");
    assert.equal(await browserPage.locator(".output-card").count(), 64);
    assert.equal(await browserPage.locator('[data-delete-output="65"]').count(), 0);
    assert.equal(await browserPage.locator('[data-delete-output="1"]').count(), 0);
    assert.equal(await browserPage.locator("[data-delete-output]").count(), 63);
    assert.deepEqual(fixtures.deletionRequests, [65, 65]);
    assert.equal(fixtures.outputQueries.at(-1).page, "1");
    assert.ok(fixtures.outputQueries.every(query => query.job_id === "image-job"));
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `output-deletion-${viewport.width}.png`) });
  } finally {
    await browserPage.close();
  }
}

/** GPU나 운영 파일을 사용하지 않고 두 화면 크기의 검증을 실행합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyOutputDeletion(browser, { width: 1280, height: 950 });
    await verifyOutputDeletion(browser, { width: 390, height: 844 });
    await verifyMultipleOutputDeletion(browser, { width: 1280, height: 950 });
    await verifyMultipleOutputDeletion(browser, { width: 390, height: 844 });
    console.log("Passed: desktop/mobile single and multiple image deletion, protection, all pages, confirmation, partial failures, retry, pagination and filters.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
