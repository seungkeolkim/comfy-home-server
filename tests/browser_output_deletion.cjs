/** Mock API와 Edge에서 이미지 단건 삭제의 확인·실패·페이지 보정을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

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
  return {
    outputs, jobs: [], deletionRequests: [], outputQueries: [], candidateQueries: [], rejectDeletion: false,
    failedOutputIds: new Set(), deletionGate: null, movementRequests: [], failedMoveIds: new Set(), movementGate: null,
    directories: new Set(["", "sorted", "archive"]), directoryRequests: [], creationRequests: [],
    rejectDirectoryListing: false, rejectDirectoryCreation: false, directoryGate: null,
  };
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

/** Mock catalog의 현재 경로를 이동하고 충돌·같은 목적지를 실제 API와 같은 형식으로 반환합니다. */
function moveFixtureOutputs(fixtures, outputIdentifiers, destinationFolder) {
  const movedOutputIds = [];
  const skippedOutputIds = [];
  const failures = [];
  for (const outputIdentifier of outputIdentifiers) {
    const output = fixtures.outputs.find(candidate => candidate.output_id === outputIdentifier);
    if (!output || fixtures.failedMoveIds.has(outputIdentifier)) {
      failures.push({ output_id: outputIdentifier, detail: "목적지에 같은 이름의 파일이 있습니다." });
      continue;
    }
    const destinationPath = destinationFolder ? `${destinationFolder}/${output.name}` : output.name;
    if (output.path === destinationPath) skippedOutputIds.push(outputIdentifier);
    else {
      output.path = destinationPath;
      movedOutputIds.push(outputIdentifier);
    }
  }
  return {
    moved_count: movedOutputIds.length, skipped_count: skippedOutputIds.length,
    moved_output_ids: movedOutputIds, skipped_output_ids: skippedOutputIds, failures,
  };
}

/** 실제 앱 파일과 이미지 삭제 상태를 반영하는 Mock API를 제공합니다. */
function createOutputRequestHandler(fixtures) {
  return async function handleOutputRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = decodeURIComponent(requestUrl.pathname);
    if (await handleJobFolderReadRequest(route, fixtures.jobs || [])) return;
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
    else if (requestPath === "/api/outputs/directories") {
      if (request.method() === "POST") {
        const payload = request.postDataJSON();
        fixtures.creationRequests.push(payload);
        const directoryPath = payload.parent_path ? `${payload.parent_path}/${payload.name}` : payload.name;
        if (fixtures.rejectDirectoryCreation || fixtures.directories.has(directoryPath)) {
          responseStatus = 409;
          response = { detail: "같은 이름의 폴더 또는 파일이 이미 있습니다." };
        } else {
          fixtures.directories.add(directoryPath);
          responseStatus = 201;
          response = { name: payload.name, path: directoryPath };
        }
      } else {
        const directoryPath = requestUrl.searchParams.get("path") || "";
        fixtures.directoryRequests.push(directoryPath);
        if (fixtures.directoryGate) {
          const directoryGate = fixtures.directoryGate;
          fixtures.directoryGate = null;
          directoryGate.markStarted();
          await directoryGate.promise;
        }
        if (fixtures.rejectDirectoryListing) {
          responseStatus = 403;
          response = { detail: "폴더 목록을 읽을 수 없습니다." };
        } else {
          response = {
            path: directoryPath, parent_path: directoryPath ? directoryPath.split("/").slice(0, -1).join("/") : null,
            directories: [...fixtures.directories].filter(candidate => candidate && candidate !== directoryPath &&
              candidate.split("/").slice(0, -1).join("/") === directoryPath)
              .map(candidate => ({ name: candidate.split("/").at(-1), path: candidate })),
          };
        }
      }
    }
    else if (requestPath === "/api/outputs/selection-candidates") {
      fixtures.candidateQueries.push(Object.fromEntries(requestUrl.searchParams));
      const matchingFiles = matchingOutputs(fixtures, requestUrl);
      response = {
        output_ids: matchingFiles.map(output => output.output_id),
        deletable_output_ids: matchingFiles.filter(output => !output.deletion_protected)
          .map(output => output.output_id),
      };
    }
    else if (requestPath === "/api/outputs/move-batch" || requestPath.endsWith("/outputs/move")) {
      const payload = request.postDataJSON();
      const jobIdentifier = requestPath.startsWith("/api/jobs/") ? requestPath.split("/").at(-3) : null;
      const outputIdentifiers = jobIdentifier
        ? fixtures.outputs.filter(output => output.job_id === jobIdentifier).map(output => output.output_id)
        : requestPath === "/api/outputs/move" ? [fixtures.outputs.find(output => output.path === payload.source).output_id] : payload.output_ids;
      fixtures.movementRequests.push({ path: requestPath, ...payload });
      if (fixtures.movementGate) {
        const movementGate = fixtures.movementGate;
        fixtures.movementGate = null;
        movementGate.markStarted();
        await movementGate.promise;
      }
      response = moveFixtureOutputs(fixtures, outputIdentifiers, payload.destination_folder);
      if (requestPath === "/api/outputs/move") {
        response = { path: fixtures.outputs.find(output => output.output_id === outputIdentifiers[0]).path, moved: response.moved_count > 0 };
      }
    }
    else if (requestPath === "/api/outputs/deletion-candidates") {
      fixtures.candidateQueries.push(Object.fromEntries(requestUrl.searchParams));
      response = { output_ids: matchingOutputs(fixtures, requestUrl)
        .filter(output => !output.deletion_protected)
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
      response = { items: fixtures.jobs, page: 1, total: fixtures.jobs.length, total_pages: 1, active_count: 0 };
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
  assert.match(dialog.message(), new RegExp(`결과물 ${selectedCount}개`));
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
    assert.equal(await browserPage.locator('[data-select-output="1"]').isDisabled(), false);
    assert.equal(await browserPage.locator('[data-select-output="2"]').isDisabled(), false);
    await browserPage.locator("#select-all-outputs").click();
    await waitForSelectedOutputs(browserPage, 64);
    await browserPage.locator('[data-outputs-page="2"]').first().click();
    await browserPage.locator('[data-select-output="65"]').check();
    await waitForSelectedOutputs(browserPage, 65);
    await browserPage.locator('[data-outputs-page="1"]').first().click();
    assert.equal(await browserPage.locator('[data-select-output="3"]').isChecked(), true);
    assert.ok(fixtures.candidateQueries.every(query => query.job_id === "image-job"));

    await browserPage.locator("#clear-output-filter").click();
    await waitForSelectedOutputs(browserPage, 0);
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 66);
    assert.equal(await browserPage.locator("#select-every-output").textContent(), "전체 선택 해제");
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 0);

    await browserPage.locator('[data-select-output="3"]').check();
    fixtures.outputs.find(output => output.output_id === 3).deletion_protected = true;
    await browserPage.locator("#refresh-outputs-button").click();
    await browserPage.waitForFunction(() => document.querySelector('[data-delete-output="3"]').disabled);
    await waitForSelectedOutputs(browserPage, 1);
    assert.equal(await browserPage.locator('[data-select-output="3"]').isDisabled(), false);
    assert.equal(await browserPage.locator("#delete-selected-outputs").isDisabled(), true);
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
    await browserPage.locator("#notice").filter({ hasText: "삭제 실패 1개" }).waitFor();
    assert.match(await browserPage.locator("#notice").textContent(), /삭제 실패 1개/);
    assert.equal(await browserPage.locator('[data-delete-output="2"]').isDisabled(), true);

    fixtures.failedOutputIds.clear();
    await confirmMultipleOutputDeletion(browserPage, 1, true);
    await waitForSelectedOutputs(browserPage, 0);
    await browserPage.locator("#select-every-output").click();
    await waitForSelectedOutputs(browserPage, 64);
    await confirmMultipleOutputDeletion(browserPage, 63, true);
    await waitForSelectedOutputs(browserPage, 1);
    assert.deepEqual(fixtures.outputs.map(output => output.output_id), [2]);
    assert.equal(await browserPage.locator(".output-card").count(), 1);
    assert.equal(await browserPage.locator("#select-every-output").isDisabled(), false);
    assert.equal(await browserPage.locator("#delete-selected-outputs").isDisabled(), true);
    assert.equal(await browserPage.locator("#outputs-pagination").isVisible(), false);
    assert.equal(fixtures.deletionRequests.includes(1), true);
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
    assert.equal(await browserPage.locator('[data-delete-output="1"]').count(), 1);
    assert.equal(await browserPage.locator("[data-delete-output]").count(), 64);
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

/** 서버 폴더 탐색기에서 목적지를 고르거나 취소합니다. */
async function chooseMovementDestination(browserPage, buttonSelector, destinationFolder) {
  await browserPage.locator(buttonSelector).click();
  await browserPage.locator("#output-folder-picker[open]").waitFor();
  if (destinationFolder === null) await browserPage.locator("#folder-picker-cancel").click();
  else {
    let directoryPath = "";
    for (const directoryName of destinationFolder.split("/").filter(Boolean)) {
      directoryPath = directoryPath ? `${directoryPath}/${directoryName}` : directoryName;
      await browserPage.locator(`#folder-picker-directories [data-folder-path="${directoryPath}"]`).click();
    }
    await browserPage.locator("#folder-picker-confirm").click();
  }
}

/** 작업 카드와 결과물 다중 선택에서 보호·영상·부분 실패를 포함한 이동을 확인합니다. */
async function verifyOutputMovement(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createOutputFixtures();
  fixtures.outputs[1].deletion_protected = true;
  for (const jobIdentifier of ["image-job", "running-job"]) {
    const activeJob = jobIdentifier === "running-job";
    fixtures.jobs.push({
      job_id: jobIdentifier, workflow: "anima", description: "이동 검증", created_at: "2026-10-19",
      status: activeJob ? "running" : "completed", status_counts: activeJob ? { running: 1 } : { completed: 1 },
      request_count: 1, deletion_protected: !activeJob,
      inputs: { body: { prompt: "movement fixture" }, settings: { width: 768, height: 512 }, loras: [] },
      requests: [],
    });
  }
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createOutputRequestHandler(fixtures));
  try {
    await browserPage.goto("http://output-deletion.test/?view=outputs&page=1&request_id=image-job-request");
    await browserPage.locator('[data-delete-output="2"]').waitFor();
    await browserPage.locator("#toggle-output-selection").click();
    await browserPage.waitForFunction(() => !document.getElementById("select-every-output").disabled);
    await browserPage.locator('[data-select-output="1"]').check();
    await browserPage.locator('[data-select-output="2"]').check();
    assert.equal(await browserPage.locator("#delete-selected-outputs").isDisabled(), false);
    assert.equal(await browserPage.locator("#move-selected-outputs").isDisabled(), false);
    await browserPage.locator('[data-select-output="3"]').check();
    await browserPage.locator('[data-outputs-page="2"]').first().click();
    await browserPage.locator('[data-select-output="65"]').check();
    await waitForSelectedOutputs(browserPage, 4);
    await chooseMovementDestination(browserPage, "#move-selected-outputs", null);
    assert.equal(fixtures.movementRequests.length, 0);
    await waitForSelectedOutputs(browserPage, 4);

    let markStarted;
    let releaseMovement;
    const movementStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.movementGate = { markStarted, promise: new Promise(resolve => { releaseMovement = resolve; }) };
    fixtures.failedMoveIds.add(65);
    await chooseMovementDestination(browserPage, "#move-selected-outputs", "archive");
    await movementStarted;
    assert.equal(await browserPage.locator("#refresh-outputs-button").isDisabled(), true);
    assert.equal(await browserPage.locator("#move-selected-outputs").isDisabled(), true);
    assert.equal(await browserPage.locator("#toggle-output-selection").isDisabled(), true);
    assert.equal(await browserPage.locator("[data-select-output]:enabled").count(), 0);
    releaseMovement();
    await waitForSelectedOutputs(browserPage, 1);
    assert.deepEqual(fixtures.movementRequests[0].output_ids, [1, 2, 3, 65]);
    assert.match(await browserPage.locator("#notice").textContent(), /이동 실패 1개/);
    assert.equal(fixtures.outputs.find(output => output.output_id === 2).path, "archive/이미지 2.png");
    assert.equal(await browserPage.locator('[data-select-output="65"]').isChecked(), true);
    assert.equal(new URL(browserPage.url()).searchParams.get("request_id"), "image-job-request");
    fixtures.failedMoveIds.clear();
    await chooseMovementDestination(browserPage, "#move-selected-outputs", "archive");
    await waitForSelectedOutputs(browserPage, 0);
    assert.equal(fixtures.outputs.find(output => output.output_id === 65).path, "archive/이미지 65.png");

    await browserPage.locator('[data-view="jobs"]:visible').click();
    const jobMoveSelector = '[data-move-job-outputs="image-job"]';
    await browserPage.locator(jobMoveSelector).waitFor();
    assert.equal(await browserPage.locator(jobMoveSelector).isDisabled(), false);
    assert.equal(await browserPage.locator('[data-move-job-outputs="running-job"]').isDisabled(), true);
    const movementCountBeforeCancel = fixtures.movementRequests.length;
    await chooseMovementDestination(browserPage, jobMoveSelector, null);
    assert.equal(fixtures.movementRequests.length, movementCountBeforeCancel);
    fixtures.failedMoveIds.add(4);
    await chooseMovementDestination(browserPage, jobMoveSelector, "archive");
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("같은 폴더 4개"));
    assert.match(await browserPage.locator("#notice").textContent(), /이동 실패 1개/);
    await browserPage.waitForFunction(() => !document.querySelector('[data-move-job-outputs="image-job"]').disabled);
    fixtures.failedMoveIds.clear();
    await chooseMovementDestination(browserPage, jobMoveSelector, "archive");
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("결과물 1개를 이동"));
    assert.ok(fixtures.outputs.every(output => output.path.startsWith("archive/")));
    await browserPage.waitForFunction(() => !document.querySelector('[data-move-job-outputs="image-job"]').disabled);
    await browserPage.locator('[data-show-job-results="image-job"]').click();
    await browserPage.locator('[data-delete-output="2"]').waitFor();
    assert.equal(await browserPage.locator('[data-delete-output="2"]').isDisabled(), true);
    assert.equal(await browserPage.locator(".output-card").count(), 64);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.equal(fixtures.deletionRequests.length, 0);
    assert.deepEqual(pageErrors, []);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `output-movement-${viewport.width}.png`) });
  } finally {
    await browserPage.close();
  }
}

/** 새 폴더가 열릴 때까지 기다리며 생성 자체가 파일 이동을 하지 않는지 확인합니다. */
async function createPickerFolder(browserPage, fixtures, directoryName, expectedPath) {
  const movementCount = fixtures.movementRequests.length;
  await browserPage.locator("#folder-picker-name").fill(directoryName);
  await browserPage.locator("#folder-picker-create").click();
  await browserPage.waitForFunction(directoryPath => {
    const currentFolder = document.querySelector('#folder-picker-breadcrumb [aria-current="location"]');
    return currentFolder?.dataset.folderPath === directoryPath && !document.getElementById("folder-picker-confirm").disabled;
  }, expectedPath);
  assert.equal(fixtures.movementRequests.length, movementCount);
}

/** 공용 Modal의 생성·취소·경로 이동·에러 복구·늦은 응답을 Desktop과 Mobile에서 검증합니다. */
async function verifyOutputFolderPicker(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createOutputFixtures();
  const longDirectoryName = `${"긴 폴더 이름 ".repeat(12)}끝`;
  fixtures.directories.add(longDirectoryName);
  fixtures.jobs.push({
    job_id: "image-job", workflow: "anima", description: "폴더 선택 검증", created_at: "2026-10-19",
    status: "completed", status_counts: { completed: 1 }, request_count: 1, deletion_protected: false,
    inputs: { body: { prompt: "picker fixture" }, settings: { width: 768, height: 512 }, loras: [] }, requests: [],
  });
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createOutputRequestHandler(fixtures));
  try {
    await browserPage.goto("http://output-deletion.test/?view=outputs&page=1");
    const sourceSelector = '[data-move-output="sorted/이미지 2.png"]';
    await browserPage.locator(sourceSelector).click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-confirm").disabled);
    assert.equal(await browserPage.locator("#folder-picker-parent").isDisabled(), true);
    assert.equal(await browserPage.locator('#folder-picker-breadcrumb [aria-current="location"]').textContent(), "결과물");
    assert.equal(await browserPage.locator("#output-folder-picker").evaluate(dialog => dialog.scrollWidth <= dialog.clientWidth), true);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `output-folder-picker-${viewport.width}.png`) });

    await browserPage.locator("#folder-picker-name").fill("archive");
    await browserPage.locator("#folder-picker-create").click();
    await browserPage.waitForFunction(() => document.getElementById("folder-picker-status").textContent.includes("이미 있습니다"));
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), false);
    await browserPage.locator('#folder-picker-directories [data-folder-path="sorted"]').click();
    await browserPage.waitForFunction(() => document.getElementById("folder-picker-status").textContent === "하위 폴더가 없습니다.");
    await createPickerFolder(browserPage, fixtures, "사진 & 자료", "sorted/사진 & 자료");
    await browserPage.locator("#folder-picker-parent").click();
    await browserPage.locator('#folder-picker-directories [data-folder-path="sorted/사진 & 자료"]').waitFor();
    await browserPage.locator('#folder-picker-breadcrumb [data-folder-path=""]').click();
    await browserPage.waitForFunction(() => document.getElementById("folder-picker-parent").disabled);
    await browserPage.locator("#folder-picker-cancel").click();
    assert.equal(fixtures.movementRequests.length, 0);
    assert.equal(fixtures.directories.has("sorted/사진 & 자료"), true);

    await chooseMovementDestination(browserPage, sourceSelector, "sorted/사진 & 자료");
    await browserPage.locator('[data-move-output="sorted/사진 & 자료/이미지 2.png"]').waitFor();
    await chooseMovementDestination(browserPage, '[data-move-output="sorted/사진 & 자료/이미지 2.png"]', "");
    await browserPage.locator('[data-move-output="이미지 2.png"]').waitFor();
    assert.equal(fixtures.movementRequests.at(-1).destination_folder, "");
    await chooseMovementDestination(browserPage, '[data-move-output="이미지 2.png"]', "");
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("이미 같은 폴더"));
    await browserPage.waitForFunction(() => !document.querySelector('[data-move-output="이미지 2.png"]').disabled);

    fixtures.rejectDirectoryListing = true;
    await browserPage.locator('[data-move-output="이미지 2.png"]').click();
    await browserPage.locator("#folder-picker-retry:visible").waitFor();
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), true);
    fixtures.rejectDirectoryListing = false;
    await browserPage.locator("#folder-picker-retry").click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-confirm").disabled);
    let markStarted;
    let releaseDirectoryListing;
    const directoryStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.directoryGate = { markStarted, promise: new Promise(resolve => { releaseDirectoryListing = resolve; }) };
    await browserPage.locator('#folder-picker-directories [data-folder-path="archive"]').click();
    await directoryStarted;
    assert.equal(await browserPage.locator("#folder-picker-confirm").isDisabled(), true);
    await browserPage.locator("#folder-picker-cancel").click();
    await browserPage.locator('[data-move-output="이미지 2.png"]').click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-confirm").disabled);
    const staleResponse = browserPage.waitForResponse(response => response.url().includes("directories?path=archive"));
    releaseDirectoryListing();
    await staleResponse;
    assert.equal(await browserPage.locator('#folder-picker-breadcrumb [aria-current="location"]').getAttribute("data-folder-path"), "");
    await browserPage.keyboard.press("Escape");
    await browserPage.locator("#output-folder-picker").waitFor({ state: "hidden" });

    await browserPage.locator("#toggle-output-selection").click();
    await browserPage.locator('[data-select-output="3"]').check();
    await browserPage.locator('[data-select-output="4"]').check();
    await browserPage.locator("#move-selected-outputs").click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-create").disabled);
    await createPickerFolder(browserPage, fixtures, "일괄 이동", "일괄 이동");
    await browserPage.locator("#folder-picker-confirm").click();
    await waitForSelectedOutputs(browserPage, 0);
    assert.equal(fixtures.movementRequests.at(-1).destination_folder, "일괄 이동");

    await browserPage.locator('[data-view="jobs"]:visible').click();
    await browserPage.locator('[data-move-job-outputs="image-job"]').click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-create").disabled);
    fixtures.jobs[0].description = "선택창 뒤에서 작업 목록 갱신";
    await browserPage.evaluate(() => loadJobs());
    assert.equal(await browserPage.locator('[data-move-job-outputs="image-job"]').isDisabled(), true);
    await browserPage.locator("#folder-picker-cancel").click();
    assert.equal(await browserPage.locator('[data-move-job-outputs="image-job"]').isDisabled(), false);
    assert.equal(await browserPage.evaluate(() => document.activeElement?.dataset.moveJobOutputs), "image-job");
    await browserPage.locator('[data-move-job-outputs="image-job"]').click();
    await browserPage.waitForFunction(() => !document.getElementById("folder-picker-create").disabled);
    await createPickerFolder(browserPage, fixtures, "작업 보관", "작업 보관");
    await browserPage.locator("#folder-picker-confirm").click();
    await browserPage.waitForFunction(() => document.getElementById("notice").textContent.includes("결과물 65개를 이동"));
    assert.ok(fixtures.outputs.every(output => output.path.startsWith("작업 보관/")));
    assert.equal(fixtures.deletionRequests.length, 0);
    assert.deepEqual(pageErrors, []);
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
    await verifyOutputMovement(browser, { width: 1280, height: 950 });
    await verifyOutputMovement(browser, { width: 390, height: 844 });
    await verifyOutputFolderPicker(browser, { width: 1280, height: 950 });
    await verifyOutputFolderPicker(browser, { width: 390, height: 844 });
    console.log("Passed: desktop/mobile deletion, movement, folder picker, folder creation, root destination, cancel, stale response, retry, protection and filters.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
