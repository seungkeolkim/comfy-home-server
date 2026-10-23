/** 실제 DB·API와 Edge에서 즐겨찾기 필터·원본 보관·단건 복원을 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const network = require("node:net");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** 운영 서버와 충돌하지 않는 임시 Port를 얻습니다. */
async function availableFavoritePort() {
  const server = network.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

/** 테스트 서버의 기동 실패와 응답 대기를 구분합니다. */
async function waitForFavoriteServer(baseUrl, serverProcess, readLogs) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (serverProcess.exitCode !== null) throw new Error(readLogs());
    try {
      if ((await fetch(`${baseUrl}/api/session`)).ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Server startup timeout: ${readLogs()}`);
}

/** 현재 범위의 조회가 끝나 화면과 필터가 일치할 때까지 기다립니다. */
async function waitForFavoriteListing(page, favoritesOnly, count) {
  await page.waitForFunction(({ favoritesOnly, count }) =>
    applicationState.outputsFavoritesOnly === favoritesOnly &&
    element("outputs-favorites-only").checked === favoritesOnly &&
    !requestFavoriteState.busy &&
    element("output-count").textContent.includes(favoritesOnly ? `즐겨찾기 ${count}건` : `결과 ${count}개`),
  { favoritesOnly, count });
}

/** Desktop·Mobile에서 같은 요청 저장·필터·복원 시나리오를 검증합니다. */
async function verifyRequestFavorites(browser, viewportWidth) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, `request-favorites-${viewportWidth}-`));
  const baseUrl = `http://127.0.0.1:${await availableFavoritePort()}`;
  const serverProcess = spawn("python", [path.join(__dirname, "request_favorite_browser_server.py"), runtimeDirectory, new URL(baseUrl).port], {
    cwd: projectDirectory, env: { ...process.env, PYTHONPATH: `${projectDirectory}${path.delimiter}${__dirname}`, PYTHONUTF8: "1" },
    windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let serverLogs = "";
  serverProcess.stdout.on("data", data => { serverLogs = (serverLogs + data.toString()).slice(-20000); });
  serverProcess.stderr.on("data", data => { serverLogs = (serverLogs + data.toString()).slice(-20000); });
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: 900 }, isMobile: viewportWidth < 600, hasTouch: viewportWidth < 600 });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await waitForFavoriteServer(baseUrl, serverProcess, () => serverLogs);
    await page.goto(`${baseUrl}/?view=outputs`);
    await page.locator("#login-password").fill("test");
    await page.locator('#login-form button[type="submit"]').click();
    await page.locator("[data-save-output-favorite]").first().waitFor();
    assert.equal(await page.locator("#outputs-favorites-only").isChecked(), false);
    assert.equal(await page.locator(".mobile-nav [data-view]").count(), 6);
    await page.locator("[data-save-output-favorite]").first().click();
    await page.waitForFunction(() => !requestFavoriteState.busy && applicationState.visibleOutputs.every(output => output.favorite_id));
    assert.equal(await page.locator('[data-save-output-favorite][aria-pressed="true"]').count(), 2);
    await page.locator("#outputs-favorites-only").check();
    await waitForFavoriteListing(page, true, 1);
    assert.equal(await page.locator(".output-card").count(), 1);
    assert.equal(await page.locator("#toggle-output-selection").isVisible(), false);
    assert.match(page.url(), /favorites=1/);
    const favoriteIdentifier = await page.locator("[data-favorite-details]").getAttribute("data-favorite-details");
    const folders = await (await page.request.get(`${baseUrl}/api/job-folders`)).json();
    const parentFolder = folders.items.find(folder => folder.name === "인물");
    const emptyFolder = folders.items.find(folder => folder.name === "배경");
    await page.locator("#output-job-folder").selectOption(parentFolder.folder_id);
    await waitForFavoriteListing(page, true, 1);
    await page.locator("#output-job-folder").selectOption(emptyFolder.folder_id);
    await waitForFavoriteListing(page, true, 0);
    await page.goBack();
    await waitForFavoriteListing(page, true, 1);
    await page.reload();
    await waitForFavoriteListing(page, true, 1);
    await page.locator('[data-view="jobs"]:visible').first().click();
    await page.locator('[data-view="outputs"]:visible').first().click();
    await waitForFavoriteListing(page, true, 1);
    await page.screenshot({ path: path.join(artifactDirectory, `request-favorites-list-${viewportWidth}.png`) });

    await page.locator("[data-image-preview]").click();
    await page.waitForFunction(() => !outputPreviewNavigationState.loading);
    assert.equal(await page.evaluate(() => outputPreviewNavigationState.filter.type), "favorite");
    const siblingIdentifier = await page.evaluate(() => outputPreviewNavigationState.next?.output_id || outputPreviewNavigationState.previous?.output_id);
    assert.ok(siblingIdentifier);
    await page.keyboard.press("Escape");
    await page.locator("[data-favorite-details]").click();
    await page.locator("#favorite-details-dialog[open]").waitFor();
    assert.match(await page.locator("#favorite-details-content").textContent(), /18446744073709551615/);
    await page.locator("#favorite-details-content summary").click();
    assert.match(await page.locator("#favorite-details-content").textContent(), /\[SCENE\]/);
    assert.match(await page.locator("#favorite-details-content").textContent(), /당시 정원/);
    await page.locator("#favorite-details-exact").click();
    await page.locator("#favorite-restoration-panel").waitFor();
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "saved garden, literal {unchanged}");
    assert.equal(await page.locator("#generate-negative").inputValue(), "saved negative");
    assert.equal(await page.locator("#generate-count").inputValue(), "1");
    assert.equal(await page.locator("#generate-count").isDisabled(), true);
    assert.equal(await page.locator("#preview-button").isDisabled(), true);
    assert.equal(await page.evaluate(() => applicationState.selectedLoras[0].strength), 0.75);
    assert.equal((await (await page.request.get(`${baseUrl}/api/jobs?summary=true`)).json()).total, 1);
    await page.locator("#favorite-restore-source").click();
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "[SCENE]");
    assert.equal(await page.locator('[data-favorite-tag="archived-tag"]').isChecked(), true);
    await page.locator('[data-favorite-tag="archived-tag"]').uncheck();
    await page.locator('[data-favorite-tag="archived-tag"]').check();
    await page.screenshot({ path: path.join(artifactDirectory, `request-favorites-restore-${viewportWidth}.png`) });
    await page.locator("#favorite-restore-exact").click();
    const submittedResponse = page.waitForResponse(response => response.url().endsWith(`/api/favorites/${favoriteIdentifier}/batches`) && response.request().method() === "POST");
    await page.locator("#submit-button").click();
    const submission = await submittedResponse;
    assert.equal(submission.status(), 200, await submission.text());
    const submittedJob = await submission.json();
    assert.equal(submittedJob.request_ids.length, 1);
    await page.waitForFunction(async jobIdentifier => {
      const response = await fetch(`/api/jobs/${jobIdentifier}`);
      const job = await response.json();
      return job.requests[0].result?.prompt === "saved garden, literal {unchanged}";
    }, submittedJob.job_id);
    await page.locator('[data-view="outputs"]:visible').first().click();
    await waitForFavoriteListing(page, true, 1);
    assert.equal((await page.request.delete(`${baseUrl}/api/jobs/favorite-job`)).status(), 200);
    await page.evaluate(() => loadOutputs());
    await waitForFavoriteListing(page, true, 0);
    await page.locator("#output-job-folder").selectOption("unassigned");
    await waitForFavoriteListing(page, true, 1);
    await page.locator("[data-remove-favorite]").click();
    await waitForFavoriteListing(page, true, 0);
    await page.locator("#outputs-favorites-only").uncheck();
    await waitForFavoriteListing(page, false, 2);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
    console.log(`Request favorites verified: ${viewportWidth}px`);
  } finally {
    await context.close();
    serverProcess.kill();
    await new Promise(resolve => serverProcess.exitCode !== null ? resolve() : serverProcess.once("exit", resolve));
  }
}

/** 과거 작업 입력 선택 상태와 분리하여 MiniMax 보관 이미지를 제출하는지 확인합니다. */
async function verifyMinimaxFavorite(browser) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, "request-favorites-minimax-"));
  const baseUrl = `http://127.0.0.1:${await availableFavoritePort()}`;
  const serverProcess = spawn("python", [path.join(__dirname, "request_favorite_browser_server.py"), runtimeDirectory, new URL(baseUrl).port, "minimax_h3"], {
    cwd: projectDirectory, env: { ...process.env, PYTHONPATH: `${projectDirectory}${path.delimiter}${__dirname}`, PYTHONUTF8: "1" },
    windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let serverLogs = "";
  serverProcess.stderr.on("data", data => { serverLogs = (serverLogs + data.toString()).slice(-20000); });
  const context = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await waitForFavoriteServer(baseUrl, serverProcess, () => serverLogs);
    await page.goto(`${baseUrl}/?view=outputs&favorites=1`);
    await page.locator("#login-password").fill("test");
    await page.locator('#login-form button[type="submit"]').click();
    await waitForFavoriteListing(page, true, 1);
    const files = await (await page.request.get(`${baseUrl}/api/outputs`)).json();
    const sourceFile = files.files.find(output => output.name === "source.png");
    assert.equal((await page.request.delete(`${baseUrl}/api/outputs/${sourceFile.output_id}`)).status(), 200);
    const favoriteIdentifier = await page.locator("[data-restore-favorite]").getAttribute("data-restore-favorite");
    await page.locator("[data-restore-favorite]").click();
    await page.locator("#favorite-restoration-panel").waitFor();
    assert.equal(await page.locator("#generate-workflow").inputValue(), "minimax_h3");
    assert.equal(await page.locator("#minimax-input-scope").inputValue(), "job");
    assert.equal(await page.locator("#minimax-input-fields").isVisible(), false);
    assert.equal(await page.locator("#generate-minimax-prompt").inputValue(), "saved garden, literal {unchanged}");
    assert.match(await page.locator("#favorite-restoration-summary").textContent(), /보관된 입력 이미지/);
    const submittedResponse = page.waitForResponse(response => response.url().endsWith(`/api/favorites/${favoriteIdentifier}/batches`) && response.request().method() === "POST");
    await page.locator("#submit-button").click();
    const submission = await submittedResponse;
    assert.equal(submission.status(), 200, await submission.text());
    assert.equal(submission.request().postDataJSON().input_scope, null);
    const submittedJob = await submission.json();
    assert.equal(submittedJob.request_ids.length, 1);
    await page.waitForFunction(async jobIdentifier => {
      const job = await (await fetch(`/api/jobs/${jobIdentifier}`)).json();
      return job.requests[0].prompt_id !== null;
    }, submittedJob.job_id);
    await page.locator("#clear-favorite-restoration").click();
    assert.equal(await page.locator("#minimax-input-fields").isVisible(), true);
    assert.equal(await page.locator("#preview-button").isDisabled(), false);
    assert.deepEqual(pageErrors, []);
    console.log("MiniMax favorite verified: archived job input, deleted source, fixed Seed and single submission");
  } finally {
    await context.close();
    serverProcess.kill();
    await new Promise(resolve => serverProcess.exitCode !== null ? resolve() : serverProcess.once("exit", resolve));
  }
}

/** 설치된 Edge로 Desktop과 좁은 Mobile 및 MiniMax 입력 복원을 차례로 확인합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const viewportWidth of [1280, 390, 320]) await verifyRequestFavorites(browser, viewportWidth);
    await verifyMinimaxFavorite(browser);
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
