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
  return { outputs, deletionRequests: [], outputQueries: [], rejectDeletion: false };
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
    else if (requestPath === "/api/outputs" && request.method() === "GET") {
      const pageNumber = Number(requestUrl.searchParams.get("page") || 1);
      fixtures.outputQueries.push(Object.fromEntries(requestUrl.searchParams));
      response = {
        files: fixtures.outputs.slice((pageNumber - 1) * 64, pageNumber * 64),
        page: pageNumber, page_size: 64, total: fixtures.outputs.length,
        total_pages: Math.max(1, Math.ceil(fixtures.outputs.length / 64)),
      };
    } else if (/^\/api\/outputs\/\d+$/.test(requestPath) && request.method() === "DELETE") {
      const outputIdentifier = Number(requestPath.split("/").at(-1));
      fixtures.deletionRequests.push(outputIdentifier);
      if (fixtures.rejectDeletion) {
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
    console.log("Passed: desktop/mobile image deletion, confirmation cancellation, failure recovery, pagination and filter retention.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
