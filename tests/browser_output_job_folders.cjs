/** 실제 DB·API와 Edge에서 결과물 분류 선택과 범위 유지를 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const network = require("node:net");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** 충돌 없는 임시 포트를 운영체제에서 얻습니다. */
async function availableJobFolderPort() {
  const server = network.createServer();
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

/** 테스트 서버가 응답하거나 기동 오류가 확인될 때까지 제한 시간만 기다립니다. */
async function waitForJobFolderServer(baseUrl, process, readLogs) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (process.exitCode !== null) throw new Error(readLogs());
    try { if ((await fetch(`${baseUrl}/api/session`)).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Server startup timeout: ${readLogs()}`);
}

/** 결과물 조회가 완료되어 화면과 현재 분류 범위가 일치할 때까지 기다립니다. */
async function waitForOutputFolder(page, folderIdentifier, expectedTotal) {
  await page.waitForFunction(({ folderIdentifier, expectedTotal }) => {
    const currentIdentifier = applicationState.outputFilter?.type === "folder" ? applicationState.outputFilter.id : "";
    return currentIdentifier === folderIdentifier && element("output-job-folder").value === folderIdentifier &&
      element("output-count").textContent.includes(`${expectedTotal}개`) &&
      applicationState.outputSelectionScope === JSON.stringify(applicationState.outputFilter);
  }, { folderIdentifier, expectedTotal });
}

/** Desktop·Mobile에서 분류 탐색·페이지·선택·미리보기와 삭제 복구를 검증합니다. */
async function verifyOutputJobFolders(browser, viewportWidth) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, `output-job-folders-${viewportWidth}-`));
  const baseUrl = `http://127.0.0.1:${await availableJobFolderPort()}`;
  const serverProcess = spawn("python", [path.join(__dirname, "job_folder_browser_server.py"), runtimeDirectory, new URL(baseUrl).port], {
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
    await waitForJobFolderServer(baseUrl, serverProcess, () => serverLogs);
    await page.goto(`${baseUrl}/?view=outputs`);
    await page.locator("#login-password").fill("test");
    await page.locator('#login-form button[type="submit"]').click();
    await waitForOutputFolder(page, "", 72);
    const folders = await (await page.request.get(`${baseUrl}/api/job-folders`)).json();
    const parentFolder = folders.items.find(folder => folder.name === "인물 A");
    const leafFolder = folders.items.find(folder => folder.name === "최종 후보");
    const emptyFolder = folders.items.find(folder => folder.name === "배경 실험");
    await page.locator("#output-job-folder").selectOption(parentFolder.folder_id);
    await waitForOutputFolder(page, parentFolder.folder_id, 66);
    assert.match(page.url(), /folder_id=/);
    assert.equal(await page.locator(".output-card").count(), 64);
    await page.locator("#toggle-output-selection").click();
    await page.waitForFunction(() => applicationState.selectableOutputIds.size === 66);
    await page.locator("#select-every-output").click();
    await page.waitForFunction(() => applicationState.selectedOutputIds.size === 66 && !outputSelectionIsBusy());
    assert.equal(await page.evaluate(() => applicationState.deletableOutputIds.size), 63);
    await page.locator('#outputs-pagination [data-outputs-page="2"]').first().click();
    await page.waitForFunction(() => applicationState.outputsPage === 2 && applicationState.visibleOutputs.length === 2);
    assert.equal(await page.evaluate(() => applicationState.selectedOutputIds.size), 66);
    const nextPageFirstIdentifier = await page.evaluate(() => applicationState.visibleOutputs[0].output_id);
    await page.locator('#outputs-pagination [data-outputs-page="1"]').first().click();
    await page.waitForFunction(() => applicationState.outputsPage === 1 && applicationState.visibleOutputs.length === 64);
    await page.locator("#toggle-output-selection").click();
    await page.locator("[data-image-preview]").last().click();
    await page.waitForFunction(() => !outputPreviewNavigationState.loading);
    assert.equal(await page.evaluate(() => outputPreviewNavigationState.next.output_id), nextPageFirstIdentifier);
    await page.locator("#image-preview-next").click();
    await page.waitForFunction(outputIdentifier => outputPreviewNavigationState.outputId === outputIdentifier &&
      !outputPreviewNavigationState.loading, nextPageFirstIdentifier);
    await page.keyboard.press("Escape");
    await page.locator("#output-job-folder").selectOption(leafFolder.folder_id);
    await waitForOutputFolder(page, leafFolder.folder_id, 33);
    assert.equal(await page.evaluate(() => applicationState.selectedOutputIds.size), 0);
    await page.locator('[data-view="jobs"]:visible').first().click();
    await page.locator('[data-view="outputs"]:visible').first().click();
    await waitForOutputFolder(page, leafFolder.folder_id, 33);
    await page.locator("#output-job-folder").selectOption("unassigned");
    await waitForOutputFolder(page, "unassigned", 6);
    await page.goBack();
    await waitForOutputFolder(page, leafFolder.folder_id, 33);
    await page.reload();
    await waitForOutputFolder(page, leafFolder.folder_id, 33);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    await page.screenshot({ path: path.join(artifactDirectory, `output-job-folders-${viewportWidth}.png`) });
    await page.locator("#output-job-folder").selectOption(emptyFolder.folder_id);
    await waitForOutputFolder(page, emptyFolder.folder_id, 0);
    assert.equal(await page.locator(".output-card").count(), 0);
    await page.locator("#output-job-folder").selectOption(parentFolder.folder_id);
    await waitForOutputFolder(page, parentFolder.folder_id, 66);
    await page.locator("#toggle-output-selection").click();
    await page.waitForFunction(() => applicationState.selectableOutputIds.size === 66);
    assert.equal((await page.request.delete(`${baseUrl}/api/job-folders/${parentFolder.folder_id}`)).status(), 200);
    await page.evaluate(() => loadOutputs());
    await waitForOutputFolder(page, "unassigned", 72);
    assert.deepEqual(pageErrors, []);
  } catch (error) {
    await page.screenshot({ path: path.join(artifactDirectory, `output-job-folders-error-${viewportWidth}.png`), fullPage: true });
    error.message += `\n${serverLogs.slice(-4000)}`;
    throw error;
  } finally {
    await context.close();
    serverProcess.kill();
    if (serverProcess.exitCode === null) await new Promise(resolve => serverProcess.once("exit", resolve));
  }
}

/** 운영 데이터와 분리된 서버로 Desktop·Mobile 검증을 실행합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const viewportWidth of [1280, 390]) await verifyOutputJobFolders(browser, viewportWidth);
    process.stdout.write("Passed: output folder scope, descendants, pagination, bulk selection, preview boundary, history/reload, empty folders and external deletion recovery on desktop/mobile.\n");
  } finally { await browser.close(); }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });

