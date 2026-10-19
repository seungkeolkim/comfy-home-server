/** Mock API와 실제 Browser에서 이미지 미리보기의 Network·닫기·원본 보기 동작을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 경로 특수문자·세로 이미지·실패 이미지와 영상을 함께 준비합니다. */
function createImagePreviewFixtures() {
  const filenames = ["장면 #1 '가나다'.png", `${"긴 이미지 이름 ".repeat(12)}.webp`, "missing.png", "movie.mp4"];
  const files = filenames.map((filename, index) => ({
    output_id: index + 1, name: filename, path: `폴더/${filename}`, kind: index === 3 ? "video" : "image",
    width: index === 1 ? 512 : 768, height: index === 1 ? 768 : 512,
    deletion_protected: index === 1,
  }));
  return { files, originalRequests: [], mutations: [], neighborQueries: [], neighborGate: null, rejectNeighbors: false };
}

/** 원본 요청을 따로 기록하여 Thumbnail 미리보기만으로 원본을 받지 않는지 확인합니다. */
function createImagePreviewHandler(fixtures) {
  return async function handleImagePreviewRequest(route) {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const requestPath = requestUrl.pathname;
    const matchingFiles = fixtures.files.filter(output =>
      (!requestUrl.searchParams.get("job_id") || output.job_id === requestUrl.searchParams.get("job_id")) &&
      (!requestUrl.searchParams.get("request_id") || output.request_id === requestUrl.searchParams.get("request_id")));
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({ contentType: contentTypes[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    if (requestPath.startsWith("/api/outputs/preview/") || requestPath.startsWith("/media/")) {
      if (requestPath.startsWith("/media/")) fixtures.originalRequests.push(decodeURIComponent(requestPath));
      if (requestPath.endsWith("/missing.png")) {
        await route.fulfill({ status: 404, body: "missing image" });
        return;
      }
      const portraitImage = decodeURIComponent(requestPath).includes("긴 이미지");
      await route.fulfill({ contentType: "image/svg+xml", body: `<svg xmlns="http://www.w3.org/2000/svg" width="${portraitImage ? 256 : 384}" height="${portraitImage ? 384 : 256}"><rect width="100%" height="100%" fill="#586e85"/><circle cx="50%" cy="50%" r="60" fill="#7ed6c0"/></svg>` });
      return;
    }
    let response;
    if (request.method() !== "GET") fixtures.mutations.push(requestPath);
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true, output_directory: "test-output" };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/jobs") response = { items: [], page: 1, total: 0, total_pages: 1, active_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/outputs") {
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      response = { files: matchingFiles.slice((pageNumber - 1) * 64, pageNumber * 64), page: pageNumber, total: matchingFiles.length, total_pages: Math.ceil(matchingFiles.length / 64) };
    }
    else if (/^\/api\/outputs\/\d+\/neighbors$/.test(requestPath)) {
      fixtures.neighborQueries.push({ output_id: Number(requestPath.split("/")[3]), ...Object.fromEntries(requestUrl.searchParams) });
      if (fixtures.neighborGate) {
        const neighborGate = fixtures.neighborGate;
        fixtures.neighborGate = null;
        neighborGate.markStarted();
        await neighborGate.promise;
      }
      const currentIndex = matchingFiles.findIndex(output => output.output_id === Number(requestPath.split("/")[3]));
      if (fixtures.rejectNeighbors || currentIndex < 0) {
        await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "현재 조회 범위에서 결과물을 찾을 수 없습니다." }) });
        return;
      }
      response = { previous: matchingFiles[currentIndex - 1] || null, next: matchingFiles[currentIndex + 1] || null };
    }
    else if (requestPath === "/api/outputs/selection-candidates") response = {
      output_ids: fixtures.files.map(output => output.output_id),
      deletable_output_ids: fixtures.files.filter(output => output.kind === "image" && !output.deletion_protected).map(output => output.output_id),
    };
    else if (/^\/api\/outputs\/\d+\/video-preview$/.test(requestPath)) response = { state: "failed" };
    else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 64장 경계를 넘는 작업 범위와 이미지·영상 혼합 이동 및 늦은 응답을 확인합니다. */
async function verifyPreviewNavigation(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 600 });
  const fixtures = createImagePreviewFixtures();
  fixtures.files = [];
  for (let outputIdentifier = 1; outputIdentifier <= 136; outputIdentifier += 1) {
    const videoOutput = outputIdentifier === 129;
    fixtures.files.push({
      output_id: outputIdentifier, name: `result-${outputIdentifier}.${videoOutput ? "mp4" : "png"}`,
      path: `results/result-${outputIdentifier}.${videoOutput ? "mp4" : "png"}`, kind: videoOutput ? "video" : "image",
      job_id: outputIdentifier % 2 ? "first-job" : "second-job",
      request_id: outputIdentifier % 4 === 1 ? "first-request" : "second-request", width: 768, height: 512,
    });
  }
  await context.route("**/*", createImagePreviewHandler(fixtures));
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await page.goto("http://image-preview.test/?view=outputs&job_id=first-job");
    const originalButton = page.locator('[data-image-preview="127"]');
    await originalButton.click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    assert.match(await page.locator("#image-preview-navigation-status").textContent(), /이 작업의 결과물/);
    const originalUrl = page.url();
    const originalScroll = await page.evaluate(() => window.scrollY);
    await page.locator("#image-preview-next").click();
    await page.locator("#video-preview-next:not([disabled])").waitFor();
    assert.equal(await page.locator("#video-preview-title").textContent(), "result-129.mp4");
    assert.equal(await page.locator("#image-preview-dialog").evaluate(dialog => dialog.open), false);
    await page.locator("#video-preview-next").click();
    await page.locator("#image-preview-previous:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-131.png");
    await page.keyboard.press("ArrowLeft");
    await page.locator("#video-preview-previous:not([disabled])").waitFor();
    await page.locator("#video-preview-previous").click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-127.png");
    await page.locator("#image-preview-close").click();
    assert.equal(page.url(), originalUrl);
    assert.equal(await page.evaluate(() => window.scrollY), originalScroll);
    assert.equal(await originalButton.evaluate(button => button === document.activeElement), true);
    assert.equal(await page.locator('[data-image-preview="127"]').count(), 1);
    assert.equal(await page.locator('[data-image-preview="131"]').count(), 0);
    assert.ok(fixtures.neighborQueries.every(query => query.job_id === "first-job"));

    await page.goto("http://image-preview.test/?view=outputs&job_id=first-job&page=2");
    await page.locator('[data-image-preview="135"]').click();
    await page.locator("#image-preview-previous:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-next").isDisabled(), true);
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-135.png");
    await page.keyboard.press("Escape");
    await page.locator('[data-video-preview="129"]').click();
    await page.locator("#video-preview-previous:not([disabled])").waitFor();
    await page.locator("#video-preview-previous").click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-127.png");
    assert.match(page.url(), /page=2/);
    await page.keyboard.press("Escape");

    await page.goto("http://image-preview.test/?view=outputs&request_id=first-request");
    await page.locator('[data-image-preview="1"]').click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-previous").isDisabled(), true);
    await page.locator("#image-preview-next").click();
    await page.locator("#image-preview-previous:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-5.png");
    assert.equal(fixtures.neighborQueries.at(-1).request_id, "first-request");
    await page.keyboard.press("Escape");

    await page.goto("http://image-preview.test/?view=outputs");
    await page.locator('[data-image-preview="1"]').click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    await page.locator("#image-preview-next").click();
    await page.locator("#image-preview-previous:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-2.png");
    assert.equal(fixtures.neighborQueries.at(-1).job_id, undefined);
    await page.keyboard.press("Escape");
    let markStarted;
    let releaseNeighbors;
    const neighborsStarted = new Promise(resolve => { markStarted = resolve; });
    fixtures.neighborGate = { markStarted, promise: new Promise(resolve => { releaseNeighbors = resolve; }) };
    await page.locator('[data-image-preview="1"]').click();
    await neighborsStarted;
    assert.equal(await page.locator("#image-preview-next").isDisabled(), true);
    await page.keyboard.press("Escape");
    await page.locator('[data-image-preview="3"]').click();
    await page.locator("#image-preview-next:not([disabled])").waitFor();
    releaseNeighbors();
    await page.locator("#image-preview-next").click();
    await page.locator("#image-preview-previous:not([disabled])").waitFor();
    assert.equal(await page.locator("#image-preview-title").textContent(), "result-4.png");
    await page.keyboard.press("Escape");
    fixtures.rejectNeighbors = true;
    await page.locator('[data-image-preview="1"]').click();
    await page.locator("#image-preview-navigation-status").filter({ hasText: "불러올 수 없습니다" }).waitFor();
    assert.equal(await page.locator("#image-preview-next").isDisabled(), true);
    assert.equal(await page.locator("#image-preview-original").isVisible(), true);
    await page.keyboard.press("Escape");
    assert.deepEqual(fixtures.originalRequests, []);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** 미리보기의 실제 이미지가 준비될 때까지 기다립니다. */
async function waitForPreviewImage(browserPage) {
  await browserPage.waitForFunction(() => {
    const image = document.getElementById("image-preview-content");
    return image.complete && image.naturalWidth > 0 && document.getElementById("image-preview-dialog").open;
  });
}

/** Desktop과 Touch 환경에서 원본 요청 분리·닫기·Focus·실패·화면 경계를 확인합니다. */
async function verifyImagePreviews(browser, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, hasTouch: width < 600 });
  const fixtures = createImagePreviewFixtures();
  const pageErrors = [];
  await context.route("**/*", createImagePreviewHandler(fixtures));
  const page = await context.newPage();
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await page.goto("http://image-preview.test/?view=outputs");
    const firstImageButton = page.locator('[data-image-preview="1"]');
    const imageDialog = page.locator("#image-preview-dialog");
    await firstImageButton.focus();
    await page.keyboard.press("Enter");
    await waitForPreviewImage(page);
    assert.deepEqual(fixtures.originalRequests, []);
    assert.equal(await page.locator("#image-preview-title").textContent(), fixtures.files[0].name);
    assert.equal(await page.locator("#image-preview-close").evaluate(button => button === document.activeElement), true);
    assert.equal(await page.locator("#image-preview-original").getAttribute("href"), `/media/${fixtures.files[0].path.split("/").map(encodeURIComponent).join("/")}`);
    await page.locator("#image-preview-content").click();
    const dialogBounds = await imageDialog.boundingBox();
    await page.mouse.click(dialogBounds.x + 4, dialogBounds.y + 4);
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), true);
    const titleBounds = await page.locator("#image-preview-title").boundingBox();
    await page.mouse.move(titleBounds.x + 5, titleBounds.y + 5);
    await page.mouse.down();
    await page.mouse.move(5, 5);
    await page.mouse.up();
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), true);
    if (width < 600) await page.touchscreen.tap(5, 5);
    else await page.mouse.click(5, 5);
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator("#image-preview-content").getAttribute("src"), null);
    assert.equal(await firstImageButton.evaluate(button => button === document.activeElement), true);

    await firstImageButton.click();
    await waitForPreviewImage(page);
    const popupPromise = page.waitForEvent("popup");
    await page.locator("#image-preview-original").click();
    const popup = await popupPromise;
    await popup.waitForLoadState("domcontentloaded");
    assert.deepEqual(fixtures.originalRequests, [`/media/${fixtures.files[0].path}`]);
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), true);
    await popup.close();
    await page.locator("#image-preview-close").click();
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), false);
    await firstImageButton.click();
    await page.keyboard.press("Escape");
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), false);

    await page.locator("#toggle-output-selection").click();
    await page.locator('[data-select-output="2"]').check();
    assert.equal(await imageDialog.evaluate(dialog => dialog.open), false);
    await page.locator('[data-image-preview="2"]').click();
    await waitForPreviewImage(page);
    assert.equal(await page.locator('[data-select-output="2"]').isChecked(), true);
    assert.equal(await imageDialog.evaluate(dialog => dialog.scrollWidth <= dialog.clientWidth), true);
    const portraitBounds = await page.locator("#image-preview-content").boundingBox();
    assert.ok(portraitBounds.y >= 0 && portraitBounds.y + portraitBounds.height <= 900);
    const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(artifactDirectory, { recursive: true });
    await page.screenshot({ path: path.join(artifactDirectory, `image-preview-${width}.png`) });
    await page.keyboard.press("Escape");
    await page.locator('[data-image-preview="3"]').click();
    await page.locator("#image-preview-status").filter({ hasText: "불러올 수 없습니다" }).waitFor();
    assert.equal(await page.locator("#image-preview-original").isVisible(), true);
    await page.locator("#image-preview-close").click();
    await firstImageButton.click();
    await waitForPreviewImage(page);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#image-preview-status").textContent(), "");

    await page.locator('[data-video-preview="4"]').click();
    await page.locator("#video-preview-notice").filter({ hasText: "변환에 실패했습니다" }).waitFor();
    await page.locator("#video-preview-close").click();
    await page.locator('[data-view="jobs"]:visible').first().click();
    await page.locator('[data-view="outputs"]:visible').first().click();
    await firstImageButton.click();
    await page.evaluate(() => window.history.back());
    await page.waitForFunction(() => !document.getElementById("image-preview-dialog").open);
    assert.equal(await page.locator("#image-preview-content").getAttribute("src"), null);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(fixtures.mutations, ["/api/outputs/4/video-preview"]);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** 실제 GPU·운영 이미지 변경 없이 두 화면 크기를 검증합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyImagePreviews(browser, 1280);
    await verifyImagePreviews(browser, 390);
    await verifyPreviewNavigation(browser, 1280);
    await verifyPreviewNavigation(browser, 390);
    console.log("Passed: image preview, scoped cross-page image/video navigation, keyboard/boundaries, stale/error responses, original-only requests, close/touch/focus and desktop/mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
