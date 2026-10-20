/** 실제 Browser에서 VRAM 해제 경고·취소·중복 방지·실패와 모바일 배치를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 운영 서버 연결 없이 경고 확인과 해제 요청의 생명주기를 검증합니다. */
async function verifyMemoryRelease(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  const unexpectedRequests = [];
  let memoryRequestCount = 0;
  let rejectMemoryRequest = false;
  let releaseMemoryRequest;
  const memoryRequestGate = new Promise(resolve => { releaseMemoryRequest = resolve; });
  page.on("pageerror", error => pageErrors.push(error.message));

  await context.route("**/*", async function handleApplicationRequest(route) {
    const requestPath = new URL(route.request().url()).pathname;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const fileName = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({
        contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[fileName],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", fileName), "utf8"),
      });
      return;
    }
    let responseBody;
    let responseStatus = 200;
    if (requestPath === "/api/comfy/free-memory") {
      assert.equal(route.request().method(), "POST");
      memoryRequestCount += 1;
      await memoryRequestGate;
      responseStatus = rejectMemoryRequest ? 502 : 200;
      responseBody = rejectMemoryRequest ? { detail: "ComfyUI에 VRAM 비우기를 요청하지 못했습니다." } : { accepted: true };
    } else if (requestPath === "/api/session") responseBody = { authenticated: true };
    else if (requestPath === "/api/status") responseBody = { comfy_connected: true };
    else if (requestPath === "/api/system-resources") responseBody = { status: "unavailable" };
    else if (requestPath === "/api/jobs/activity") responseBody = { active_count: 0 };
    else if (requestPath === "/api/jobs") responseBody = { items: [], page: 1, page_size: 10, total: 0, total_pages: 1, active_count: 0 };
    else if (requestPath === "/api/job-folders") responseBody = { items: [], total_count: 0, unassigned_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) responseBody = [];
    else if (requestPath === "/api/loras") responseBody = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") responseBody = { groups: [], entries: [] };
    else {
      unexpectedRequests.push(requestPath);
      await route.abort();
      return;
    }
    await route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(responseBody) });
  });

  try {
    await page.goto("http://comfy-memory.test/");
    await page.locator("#system-resources summary").click();
    const freeMemoryButton = page.locator("#free-vram-button");
    await freeMemoryButton.waitFor();
    assert.equal(await freeMemoryButton.evaluate(button => button.closest(".resource-details") !== null && button.classList.contains("danger")), true);
    const originalUrl = page.url();
    await page.locator("#job-description").fill("다음 작업 설명 유지");

    page.once("dialog", async function dismissMemoryWarning(dialog) {
      assert.equal(dialog.type(), "confirm");
      assert.match(dialog.message(), /model과 cache/);
      assert.match(dialog.message(), /시간이 더 걸릴/);
      assert.match(dialog.message(), /현재 작업 이후/);
      await dialog.dismiss();
    });
    await freeMemoryButton.click();
    assert.equal(memoryRequestCount, 0);
    assert.equal(await freeMemoryButton.isEnabled(), true);

    page.once("dialog", dialog => dialog.accept());
    await freeMemoryButton.click();
    await page.waitForFunction(() => document.getElementById("free-vram-button").disabled);
    assert.equal(await freeMemoryButton.textContent(), "요청 중…");
    await page.evaluate(() => freeComfyMemory());
    releaseMemoryRequest();
    await page.locator("#notice").filter({ hasText: "VRAM 비우기를 요청했습니다" }).waitFor();
    assert.equal(memoryRequestCount, 1);
    assert.equal(await freeMemoryButton.isEnabled(), true);
    assert.equal(await freeMemoryButton.textContent(), "VRAM 비우기");

    rejectMemoryRequest = true;
    page.once("dialog", dialog => dialog.accept());
    await freeMemoryButton.click();
    await page.locator("#notice.error").filter({ hasText: "요청하지 못했습니다" }).waitFor();
    assert.equal(memoryRequestCount, 2);
    assert.equal(await freeMemoryButton.isEnabled(), true);
    assert.equal(await page.locator("#job-description").inputValue(), "다음 작업 설명 유지");
    assert.equal(page.url(), originalUrl);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const buttonBounds = await freeMemoryButton.boundingBox();
    assert.ok(buttonBounds.x >= 0 && buttonBounds.x + buttonBounds.width <= viewport.width);
    assert.deepEqual(unexpectedRequests, []);
    assert.deepEqual(pageErrors, []);

    const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(artifactDirectory, { recursive: true });
    await page.screenshot({ path: path.join(artifactDirectory, `comfy-memory-${viewport.width}.png`) });
  } finally {
    releaseMemoryRequest();
    await context.close();
  }
}

/** Desktop과 좁은 모바일 화면에서 동일한 해제 동작을 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyMemoryRelease(browser, { width: 1280, height: 950 });
    await verifyMemoryRelease(browser, { width: 320, height: 844 });
    console.log("Passed: VRAM warning/cancel, accepted request, duplicate prevention, failure recovery, input preservation and desktop/mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
