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
  return { files, originalRequests: [], mutations: [] };
}

/** 원본 요청을 따로 기록하여 Thumbnail 미리보기만으로 원본을 받지 않는지 확인합니다. */
function createImagePreviewHandler(fixtures) {
  return async function handleImagePreviewRequest(route) {
    const request = route.request();
    const requestPath = new URL(request.url()).pathname;
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
    else if (requestPath === "/api/outputs") response = { files: fixtures.files, page: 1, total: fixtures.files.length, total_pages: 1 };
    else if (requestPath === "/api/outputs/selection-candidates") response = {
      output_ids: fixtures.files.map(output => output.output_id),
      deletable_output_ids: fixtures.files.filter(output => output.kind === "image" && !output.deletion_protected).map(output => output.output_id),
    };
    else if (requestPath === "/api/outputs/4/video-preview") response = { state: "failed" };
    else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${request.method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
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
    console.log("Passed: image preview, explicit original-only request, close/backdrop/Escape, touch/drag/focus, protected/multiselect images, failure recovery, navigation and mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
