/** Host 자원 표시·고정 Polling·실패 복구와 Desktop/Mobile 배치를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");

/** 실제 서버·GPU 작업 없이 자원 영역과 조회 주기를 확인합니다. */
async function verifySystemResources(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  const unexpectedRequests = [];
  const sampleTimes = [];
  let rejectResourceRequest = false;
  let resourceGate = null;
  const snapshot = {
    status: "ready", updated_at: "2026-10-20T12:00:00Z", cpu_percent: 12,
    ram_used_bytes: 24 * 1024 ** 3, ram_total_bytes: 96 * 1024 ** 3, ram_percent: 25,
    gpu_name: "NVIDIA GeForce RTX 5080", gpu_percent: 93,
    vram_used_bytes: 8 * 1024 ** 3, vram_total_bytes: 16 * 1024 ** 3, vram_percent: 50,
  };
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.addInitScript(() => {
    const originalSetInterval = window.setInterval;
    window.recordedIntervals = [];
    window.setInterval = function recordPollingInterval(callback, interval, ...argumentsList) {
      window.recordedIntervals.push(interval);
      return originalSetInterval(callback, interval, ...argumentsList);
    };
  });
  await context.route("**/*", async function handleResourceBrowserRequest(route) {
    const requestPath = new URL(route.request().url()).pathname;
    if (requestPath === "/api/system-resources") {
      sampleTimes.push(Date.now());
      if (resourceGate) await resourceGate;
      await route.fulfill({
        status: rejectResourceRequest ? 502 : 200, contentType: "application/json",
        body: JSON.stringify(rejectResourceRequest ? { detail: "offline" } : snapshot),
      });
      return;
    }
    if (await handleJobFolderReadRequest(route)) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const fileName = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({
        contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[fileName],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", fileName), "utf8"),
      });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/jobs") response = { items: [], total: 0, total_pages: 1, active_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else {
      unexpectedRequests.push(requestPath);
      await route.abort();
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  });

  try {
    await page.goto("http://system-resources.test/");
    await page.locator("#resource-cpu-value").filter({ hasText: "12%" }).waitFor();
    assert.equal(await page.locator("#resource-ram-value").textContent(), "24.0 / 96.0 GiB");
    assert.equal(await page.locator("#resource-gpu-value").textContent(), "93%");
    assert.equal(await page.locator("#resource-vram-value").textContent(), "8.0 / 16.0 GiB");
    assert.equal(await page.locator("#resource-gpu").evaluate(metric => metric.classList.contains("resource-high")), true);
    assert.equal(await page.locator("#free-vram-button").isVisible(), false);
    assert.deepEqual(await page.evaluate(() => window.recordedIntervals), [2000]);
    const gridColumns = await page.locator(".resource-metrics").evaluate(grid => getComputedStyle(grid).gridTemplateColumns.split(" ").length);
    assert.equal(gridColumns, viewport.width < 800 ? 2 : 4);
    assert.equal(await page.locator(".topbar .eyebrow").isVisible(), viewport.width >= 800);

    const nextPoll = page.waitForResponse(response => response.url().includes("/api/system-resources"));
    await nextPoll;
    assert.ok(sampleTimes[1] - sampleTimes[0] >= 1800 && sampleTimes[1] - sampleTimes[0] < 3500);
    await page.locator("#system-resources summary").press("Enter");
    assert.equal(await page.locator("#free-vram-button").isVisible(), true);
    const originalUrl = page.url();
    await page.locator("#job-description").fill("입력 유지");

    rejectResourceRequest = true;
    await page.evaluate(() => loadSystemResources());
    assert.equal(await page.locator("#resource-vram-value").textContent(), "—");
    assert.equal(await page.locator("#system-resources").evaluate(details => details.open), true);
    assert.equal(await page.locator("#notice.error:not(.hidden)").count(), 0);

    rejectResourceRequest = false;
    snapshot.cpu_percent = null;
    snapshot.status = "partial";
    await page.evaluate(() => loadSystemResources());
    assert.equal(await page.locator("#resource-cpu-value").textContent(), "—");
    assert.match(await page.locator("#resource-status").textContent(), /일부 지표/);
    snapshot.cpu_percent = 12;
    snapshot.status = "ready";
    let releaseResourceRequest;
    resourceGate = new Promise(resolve => { releaseResourceRequest = resolve; });
    const sampleCountBeforePending = sampleTimes.length;
    const pendingRequest = page.waitForRequest(request => request.url().includes("/api/system-resources"));
    await page.evaluate(() => { void loadSystemResources(); void loadSystemResources(); void loadSystemResources(); });
    await pendingRequest;
    await page.evaluate(() => { void loadSystemResources(); });
    releaseResourceRequest();
    resourceGate = null;
    await page.locator("#resource-cpu-value").filter({ hasText: "12%" }).waitFor();
    assert.equal(sampleTimes.length, sampleCountBeforePending + 1);

    const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(artifactDirectory, { recursive: true });
    await page.locator("#system-resources summary").click();
    await page.screenshot({ path: path.join(artifactDirectory, `system-resources-${viewport.width}.png`) });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.locator("#job-description").inputValue(), "입력 유지");
    assert.equal(page.url(), originalUrl);

    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForResponse(response => response.url().includes("/api/system-resources"));
    assert.deepEqual(await page.evaluate(() => window.recordedIntervals), [2000]);
    await page.evaluate(() => showLogin());
    assert.equal(await page.evaluate(() => applicationState.resourcePollingTimer), null);
    assert.deepEqual(pageErrors, []);
    assert.deepEqual(unexpectedRequests, []);
  } finally {
    await context.close();
  }
}

/** 같은 지표와 고정 2초 주기를 Desktop과 좁은 모바일 화면에서 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifySystemResources(browser, { width: 1280, height: 950 });
    await verifySystemResources(browser, { width: 320, height: 844 });
    console.log("Passed: host resource values, two-second polling, hidden-page policy, shared pending request, failure recovery, details/input preservation and desktop/mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
