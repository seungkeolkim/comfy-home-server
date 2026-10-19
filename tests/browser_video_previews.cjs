/** 실제 FFmpeg와 독립 HTTP 서버로 Desktop/Mobile의 점진 재생과 닫기·Toast를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const network = require("node:net");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** OS가 제공하는 빈 테스트 포트를 예약한 뒤 반환합니다. */
async function availableTestPort() {
  const server = network.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

/** 독립 서버의 기동만 제한 시간 동안 기다립니다. */
async function waitForServer(baseUrl, serverProcess, readLogs) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (serverProcess.exitCode !== null) throw new Error(readLogs());
    try {
      if ((await fetch(`${baseUrl}/api/session`)).ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Server start timeout: ${readLogs()}`);
}

/** 원본 전송 없이 변환 중 재생·완료 Cache·실패 Toast와 Focus 복귀를 확인합니다. */
async function verifyVideoPreviews(browser, width) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, `video-preview-${width}-`));
  const port = await availableTestPort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const serverProcess = spawn("python", [path.join(__dirname, "video_preview_browser_server.py"), runtimeDirectory, String(port)], {
    cwd: projectDirectory, env: { ...process.env, PYTHONPATH: `${projectDirectory}${path.delimiter}${__dirname}`, PYTHONUTF8: "1" },
    windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let serverLogs = "";
  serverProcess.stdout.on("data", data => { serverLogs = (serverLogs + data.toString()).slice(-24000); });
  serverProcess.stderr.on("data", data => { serverLogs = (serverLogs + data.toString()).slice(-24000); });
  const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: width < 600, hasTouch: width < 600 });
  const page = await context.newPage();
  const pageErrors = [];
  const originalRequests = [];
  const thumbnailFailures = [];
  page.on("response", async response => {
    if (response.url().includes("/api/outputs/preview/") && response.status() >= 400) {
      thumbnailFailures.push({ url: response.url(), status: response.status(), body: await response.text() });
    }
  });
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/media/")) originalRequests.push(request.url()); });
  try {
    await waitForServer(baseUrl, serverProcess, () => serverLogs);
    await page.goto(baseUrl);
    await page.locator("#login-password").fill("test");
    await page.locator('#login-form button[type="submit"]').click();
    await page.locator("#application").waitFor({ state: "visible" });
    await page.locator('[data-view="outputs"]:visible').first().click();
    await page.locator("[data-video-preview]").first().waitFor();
    const sources = await (await page.request.get(`${baseUrl}/api/test-video-sources`)).json();
    assert.equal(await page.locator("[data-video-preview]").count(), 3);
    assert.equal(await page.locator("[data-video-preview] img").count(), 3);
    await page.waitForFunction(() => [...document.querySelectorAll("[data-video-preview] img")].every(image => image.complete));
    assert.deepEqual(thumbnailFailures, []);
    assert.equal(await page.locator("[data-video-preview] img").evaluateAll(images => images.every(image => image.naturalWidth > 0)), true);

    const progressiveButton = page.locator(`[data-video-preview="${sources.progressive}"]`);
    await progressiveButton.click();
    await page.waitForFunction(() => document.getElementById("video-preview-player").currentTime > 0.15, { timeout: 12000 });
    const converting = await (await page.request.get(`${baseUrl}/api/outputs/${sources.progressive}/video-preview`)).json();
    assert.equal(converting.state, "converting", "Playback must begin before full conversion completes");
    assert.match(await page.locator("#video-preview-notice").textContent(), /변환 중|대기 중/);
    const playbackState = await page.locator("#video-preview-player").evaluate(video => ({
      currentTime: video.currentTime, width: video.videoWidth, height: video.videoHeight, muted: video.muted,
    }));
    assert.ok(playbackState.currentTime > 0 && playbackState.width === 640 && playbackState.height === 360);
    await page.screenshot({ path: path.join(artifactDirectory, `video-preview-${width}.png`) });
    await page.locator("#video-preview-title").click();
    const dialogBounds = await page.locator("#video-preview-dialog").boundingBox();
    await page.mouse.click(dialogBounds.x + 4, dialogBounds.y + 4);
    assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), true);
    if (width >= 600) {
      const titleBounds = await page.locator("#video-preview-title").boundingBox();
      await page.mouse.move(titleBounds.x + 10, titleBounds.y + 10);
      await page.mouse.down();
      await page.mouse.move(5, 5);
      await page.mouse.up();
      assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), true);
      await page.mouse.click(5, 5);
    } else {
      await page.touchscreen.tap(5, 5);
    }
    assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator("#video-preview-player").getAttribute("src"), null);
    assert.equal(await progressiveButton.evaluate(button => button === document.activeElement), true);
    await page.waitForTimeout(800);
    assert.equal((await (await page.request.get(`${baseUrl}/api/outputs/${sources.progressive}/video-preview`)).json()).state, "converting");

    await page.locator(`[data-video-preview="${sources.failed}"]`).click();
    await page.locator("#video-preview-notice").filter({ hasText: "미리보기 변환에 실패했습니다." }).waitFor();
    await page.locator("#video-preview-notice button").click();
    await page.waitForFunction(() => document.getElementById("video-preview-player").currentTime > 0.15, { timeout: 12000 });
    assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), false);

    await page.locator(`[data-video-preview="${sources.ready}"]`).click();
    await page.waitForFunction(() => document.getElementById("video-preview-player").currentTime > 0.1);
    assert.equal(await page.locator("#video-preview-notice").isVisible(), false);
    await page.locator("#video-preview-close").click();
    const selectionButton = page.locator("#toggle-output-selection");
    await selectionButton.click();
    await page.locator("[data-select-output]").first().check();
    assert.equal(await page.locator("#video-preview-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator(".output-selected").count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(originalRequests, []);
    assert.deepEqual(pageErrors, []);

    await page.waitForFunction(async ({ baseUrl, identifiers }) => {
      const states = await Promise.all(identifiers.map(async identifier => (await fetch(`${baseUrl}/api/outputs/${identifier}/video-preview`)).json()));
      return states.every(status => status.state === "ready");
    }, { baseUrl, identifiers: [sources.progressive, sources.failed] }, { timeout: 15000 });
    await page.locator(`[data-video-preview="${sources.ready}"]`).click();
    await page.locator("#video-preview-delete:not([disabled])").waitFor();
    page.once("dialog", dialog => dialog.accept());
    const deletionResponse = page.waitForResponse(response => response.url() === `${baseUrl}/api/outputs/${sources.ready}` && response.request().method() === "DELETE");
    await page.locator("#video-preview-delete").click();
    assert.equal((await deletionResponse).status(), 200);
    await page.waitForFunction(outputIdentifier => !document.querySelector(`[data-video-preview="${outputIdentifier}"]`), sources.ready);
    assert.equal(filesystem.existsSync(path.join(runtimeDirectory, "outputs", "ready.mp4")), false);
    assert.equal((await page.request.get(`${baseUrl}/api/outputs/${sources.ready}/video-preview`)).status(), 404);
    filesystem.writeFileSync(path.join(runtimeDirectory, "server-check.log"), serverLogs);
  } catch (error) {
    filesystem.writeFileSync(path.join(runtimeDirectory, "server-check.log"), serverLogs);
    error.message += `\nServer logs:\n${serverLogs.slice(-7000)}`;
    throw error;
  } finally {
    await context.close();
    serverProcess.kill();
    await new Promise(resolve => serverProcess.once("exit", resolve));
  }
}

/** 390px와 1280px에서 같은 실제 재생 계약을 확인합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const width of [1280, 390]) await verifyVideoPreviews(browser, width);
    process.stdout.write("Passed: progressive playback, backdrop click/mobile tap dismissal, inside/drag isolation, close keeps encoding, persisted cache, retry Toast, keyboard/focus and mobile layout.\n");
  } finally {
    await browser.close();
  }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
