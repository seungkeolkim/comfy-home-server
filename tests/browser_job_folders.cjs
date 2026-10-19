/** 실제 DB·API와 Edge에서 3단계 폴더 분류·조회·삭제 및 Mobile UI를 검증합니다. */
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

/** Mobile 패널을 필요할 때만 펼치고 안정적인 폴더 ID로 탐색합니다. */
async function navigateHistoryFolder(page, identifier) {
  if (!await page.locator("#jobs-folder-panel").evaluate(panel => panel.open)) {
    await page.locator("#jobs-folder-panel-title").click();
  }
  await page.locator(`[data-history-folder="${identifier}"]`).click();
  await page.waitForFunction(folderIdentifier => applicationState.jobFolderId === folderIdentifier && !applicationState.jobsLoading, identifier);
}

/** 같은 실제 시나리오를 Desktop·Mobile에서 반복하고 결과 화면을 남깁니다. */
async function verifyJobHistoryFolders(browser, width) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, `job-folders-${width}-`));
  const baseUrl = `http://127.0.0.1:${await availableJobFolderPort()}`;
  const serverProcess = spawn("python", [path.join(__dirname, "job_folder_browser_server.py"), runtimeDirectory, new URL(baseUrl).port], {
    cwd: projectDirectory, env: { ...process.env, PYTHONPATH: `${projectDirectory}${path.delimiter}${__dirname}`, PYTHONUTF8: "1" },
    windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  serverProcess.stdout.on("data", data => { logs = (logs + data.toString()).slice(-20000); });
  serverProcess.stderr.on("data", data => { logs = (logs + data.toString()).slice(-20000); });
  const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: width < 600, hasTouch: width < 600 });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  try {
    await waitForJobFolderServer(baseUrl, serverProcess, () => logs);
    await page.goto(`${baseUrl}/?view=jobs`);
    await page.locator("#login-password").fill("test");
    await page.locator('#login-form button[type="submit"]').click();
    await page.locator('[data-job-prompt-card="running-job"]').waitFor();
    const initialFolders = await (await page.request.get(`${baseUrl}/api/job-folders`)).json();
    const root = initialFolders.items.find(folder => folder.name === "인물 A");
    const child = initialFolders.items.find(folder => folder.name === "표정 비교");
    const leaf = initialFolders.items.find(folder => folder.name === "최종 후보");
    const background = initialFolders.items.find(folder => folder.name === "배경 실험");
    assert.equal(initialFolders.total_count, 25);
    assert.equal(await page.locator("#jobs-folder-panel").evaluate(panel => panel.open), width >= 800);
    await navigateHistoryFolder(page, root.folder_id);
    assert.match(await page.locator("#jobs-folder-count").textContent(), /23개/);
    await page.screenshot({ path: path.join(artifactDirectory, `job-folders-overview-${width}.png`) });
    await page.locator("#jobs-search").fill("조명 비교");
    await page.locator("#jobs-search").press("Enter");
    await page.waitForFunction(() => applicationState.jobSearch === "조명 비교" && !applicationState.jobsLoading);
    await page.locator('#jobs-pagination [data-jobs-page="2"]').first().click();
    await page.waitForFunction(() => applicationState.jobsPage === 2 && !applicationState.jobsLoading);
    assert.match(page.url(), /folder_id=/);
    assert.match(page.url(), /search=/);
    await page.locator('[data-view="generate"]:visible').first().click();
    await page.locator("#job-description").fill("편집 중 생성 입력");
    await page.locator("#job-history-folder").selectOption(leaf.folder_id);
    await page.locator('[data-view="jobs"]:visible').first().click();
    await page.waitForFunction(() => applicationState.jobsPage === 2 && !applicationState.jobsLoading);
    assert.equal(await page.locator("#jobs-search").inputValue(), "조명 비교");
    await page.goBack();
    await page.waitForFunction(() => applicationState.currentView === "generate");
    assert.equal(await page.locator("#job-description").inputValue(), "편집 중 생성 입력");
    await page.goForward();
    await page.waitForFunction(() => applicationState.currentView === "jobs" && !applicationState.jobsLoading);
    const thumbnail = page.locator("[data-job-result-preview]").first();
    await thumbnail.waitFor();
    assert.equal(await thumbnail.locator("img").evaluate(image => image.complete && image.naturalWidth > 0), true);
    await thumbnail.click();
    await page.waitForFunction(() => document.getElementById("image-preview-dialog").open && !outputPreviewNavigationState.loading);
    assert.equal(await page.evaluate(() => outputPreviewNavigationState.filter.type), "job");
    const previewJob = await page.evaluate(() => outputPreviewNavigationState.filter.id);
    await page.locator("#image-preview-next").click();
    await page.waitForFunction(() => !outputPreviewNavigationState.loading);
    assert.equal(await page.evaluate(() => outputPreviewNavigationState.filter.id), previewJob);
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#image-preview-delete").click();
    await page.waitForFunction(jobIdentifier =>
      applicationState.visibleJobs.find(job => job.job_id === jobIdentifier)?.preview_files.length === 2 &&
      !outputPreviewNavigationState.loading, previewJob);
    assert.equal(await page.evaluate(() => outputPreviewNavigationState.filter.id), previewJob);
    await page.locator("#image-preview-close").click();
    await page.locator("#toggle-job-selection").click();
    await page.locator("#select-every-job").click();
    await page.waitForFunction(() => applicationState.selectedJobIds.size === 12);
    await page.locator("#move-selected-job-folder").click();
    await page.locator("#job-folder-move-dialog").waitFor({ state: "visible" });
    await page.locator(`#job-folder-move-tree input[value="${background.folder_id}"]`).check();
    await page.locator("#job-folder-move-save").click();
    await page.waitForFunction(() => !document.getElementById("job-folder-move-dialog").open && !applicationState.jobsLoading);
    assert.equal(await page.locator("[data-job-prompt-card]").count(), 0);
    assert.equal(await page.evaluate(() => applicationState.selectedJobIds.size), 0);
    await navigateHistoryFolder(page, root.folder_id);
    await page.locator('[data-select-job="running-job"]').check();
    assert.equal(await page.locator("#delete-selected-job-history").isDisabled(), true);
    assert.equal(await page.locator("#move-selected-job-folder").isEnabled(), true);
    await page.locator("#move-selected-job-folder").click();
    await page.locator("#job-folder-move-dialog").waitFor({ state: "visible" });
    await page.locator(`#job-folder-move-tree input[value="${background.folder_id}"]`).check();
    await page.locator("#job-folder-move-save").click();
    await page.waitForFunction(() => !document.getElementById("job-folder-move-dialog").open && !applicationState.jobsLoading);
    const runningJob = await (await page.request.get(`${baseUrl}/api/jobs/running-job`)).json();
    assert.equal(runningJob.folder_id, background.folder_id);
    assert.equal(runningJob.deletion_protected, true);
    assert.equal(runningJob.status, "running");
    await page.locator("#toggle-job-selection").click();
    await navigateHistoryFolder(page, leaf.folder_id);
    if (width < 800) await page.locator("#jobs-folder-panel-title").click();
    assert.equal(await page.locator("#create-job-folder").isDisabled(), true);
    await navigateHistoryFolder(page, child.folder_id);
    if (width < 800) await page.locator("#jobs-folder-panel-title").click();
    await page.locator("#create-job-folder").click();
    await page.locator("#job-folder-name").fill("새 후보");
    await page.evaluate(() => loadJobs());
    assert.equal(await page.locator("#job-folder-name").inputValue(), "새 후보");
    await page.locator("#job-folder-editor-save").click();
    await page.waitForFunction(() => !document.getElementById("job-folder-editor").open && !applicationState.jobsLoading);
    let folders = await (await page.request.get(`${baseUrl}/api/job-folders`)).json();
    const created = folders.items.find(folder => folder.name === "새 후보");
    assert.equal(created.depth, 3);
    await navigateHistoryFolder(page, created.folder_id);
    await page.locator("#jobs-folder-menu summary").click();
    await page.locator("#edit-job-folder").click();
    await page.locator("#job-folder-name").fill("이름 변경");
    await page.locator("#job-folder-parent").selectOption(background.folder_id);
    await page.locator("#job-folder-editor-save").click();
    await page.waitForFunction(() => !document.getElementById("job-folder-editor").open && !applicationState.jobsLoading);
    assert.equal(await page.locator("#jobs-folder-location").textContent(), "배경 실험 / 이름 변경");
    await navigateHistoryFolder(page, background.folder_id);
    await page.screenshot({ path: path.join(artifactDirectory, `job-folders-${width}.png`), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await navigateHistoryFolder(page, root.folder_id);
    const beforeOutputs = await (await page.request.get(`${baseUrl}/api/outputs`)).json();
    await page.locator("#jobs-folder-menu summary").click();
    page.once("dialog", dialog => {
      assert.match(dialog.message(), /작업 이력과 결과물 파일은 유지/);
      dialog.accept();
    });
    await page.locator("#delete-job-folder").click();
    await page.waitForFunction(() => applicationState.jobFolderId === "unassigned" && !applicationState.jobsLoading);
    const afterOutputs = await (await page.request.get(`${baseUrl}/api/outputs`)).json();
    assert.equal(afterOutputs.total, beforeOutputs.total);
    folders = await (await page.request.get(`${baseUrl}/api/job-folders`)).json();
    assert.equal(folders.items.some(folder => folder.folder_id === leaf.folder_id), false);
    assert.equal(folders.total_count, 25);
    assert.equal(await page.locator("#job-history-folder").inputValue(), "");
    assert.equal(await page.locator("#job-description").inputValue(), "편집 중 생성 입력");
    await navigateHistoryFolder(page, created.folder_id);
    await page.request.delete(`${baseUrl}/api/job-folders/${created.folder_id}`);
    await page.evaluate(() => loadJobs());
    await page.waitForFunction(() => applicationState.jobFolderId === "unassigned" && !applicationState.jobsLoading);
    assert.deepEqual(pageErrors, []);
  } catch (error) {
    await page.screenshot({ path: path.join(artifactDirectory, `job-folders-error-${width}.png`), fullPage: true });
    error.message += `\n${logs.slice(-4000)}`;
    throw error;
  } finally {
    await context.close();
    serverProcess.kill();
    if (serverProcess.exitCode === null) await new Promise(resolve => serverProcess.once("exit", resolve));
  }
}

/** 운영과 무관한 두 격리 서버에서 실제 DB와 UI를 검증합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const width of [1280, 390]) await verifyJobHistoryFolders(browser, width);
    process.stdout.write("Passed: 3-level folders, search/pagination/history, thumbnail previews, bulk/running/protected moves, create/rename/reparent, recursive deletion and external deletion recovery on desktop/mobile.\n");
  } finally { await browser.close(); }
}

main().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
