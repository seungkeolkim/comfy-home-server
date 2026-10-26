/** 독립된 실제 API와 Edge에서 관리자 백업·설명·삭제·복원과 Mobile 표시를 확인합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const network = require("node:net");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");
const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");

/** 다른 개발 서버와 충돌하지 않는 임시 Port를 선택합니다. */
async function selectAvailablePort() {
  const temporaryServer = network.createServer();
  await new Promise(resolve => temporaryServer.listen(0, "127.0.0.1", resolve));
  const selectedPort = temporaryServer.address().port;
  await new Promise(resolve => temporaryServer.close(resolve));
  return selectedPort;
}

/** 독립 테스트 서버가 준비될 때까지 제한 시간 동안 기다립니다. */
async function waitForAdministrationServer(baseUrl, serverProcess) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (serverProcess.exitCode !== null) throw new Error(`Test server exited: ${serverProcess.exitCode}`);
    try {
      const response = await fetch(`${baseUrl}/api/session`);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Administration test server did not become ready");
}

/** 현재 표시된 백업 설명으로 해당 Card를 선택합니다. */
function backupCard(browserPage, description) {
  return browserPage.locator("#database-backup-list .administration-card").filter({ has: browserPage.locator(".administration-description", { hasText: description }) });
}

/** Desktop과 Mobile에서 확인 취소, 실제 복원, 읽기 전용 진단을 검증합니다. */
async function verifyAdministrationViewport(browser, viewport) {
  const runtimeDirectory = filesystem.mkdtempSync(path.join(artifactDirectory, "administration-"));
  const selectedPort = await selectAvailablePort();
  const baseUrl = `http://127.0.0.1:${selectedPort}`;
  const pythonExecutable = process.env.HOME_SERVER_TEST_PYTHON || path.join(projectDirectory, ".venv", "Scripts", "python.exe");
  const fixtureScript = path.join(__dirname, "administration_browser_server.py");
  const pythonArguments = [fixtureScript, runtimeDirectory, String(selectedPort)];
  const serverProcess = spawn(pythonExecutable, pythonArguments, {
    cwd: projectDirectory, windowsHide: true,
    env: { ...process.env, PYTHONPATH: [projectDirectory, __dirname].join(path.delimiter), PYTHONUTF8: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let serverOutput = "";
  serverProcess.stdout.on("data", data => { serverOutput += data; });
  serverProcess.stderr.on("data", data => { serverOutput += data; });
  const browserContext = await browser.newContext({ viewport });
  const browserPage = await browserContext.newPage();
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  try {
    await waitForAdministrationServer(baseUrl, serverProcess);
    await browserPage.goto(baseUrl);
    await browserPage.locator("#login-password").fill("test");
    await browserPage.locator('#login-form button[type="submit"]').click();
    await browserPage.locator("#application").waitFor({ state: "visible" });
    assert.equal(await browserPage.locator('#view-administration').isVisible(), false);
    await browserPage.locator("#system-resources summary").click();
    await browserPage.locator('.resource-actions a[data-view="administration"]').click();
    await browserPage.waitForFunction(() => document.getElementById("database-schema-status").textContent.includes("14"));
    await browserPage.waitForFunction(() => !document.getElementById("create-database-backup").disabled);
    assert.equal(await backupCard(browserPage, "이전 Schema 백업").getByRole("button", { name: "복원", exact: true }).isDisabled(), true);

    await browserPage.locator("#database-backup-description").fill("Browser 생성 백업");
    await browserPage.locator("#create-database-backup").click();
    await backupCard(browserPage, "Browser 생성 백업").waitFor();
    await backupCard(browserPage, "Browser 생성 백업").getByRole("button", { name: "설명 수정" }).click();
    const updatedDescription = '설명 수정 <img src=x onerror="alert(1)">';
    await browserPage.locator("#database-backup-description-editor").fill(updatedDescription);
    await browserPage.locator("#save-database-backup-description").click();
    await browserPage.locator("#database-backup-description-dialog").waitFor({ state: "hidden" });
    await backupCard(browserPage, updatedDescription).waitFor();
    assert.equal(await backupCard(browserPage, updatedDescription).locator("img").count(), 0);

    browserPage.once("dialog", dialog => dialog.dismiss());
    await backupCard(browserPage, updatedDescription).getByRole("button", { name: "삭제", exact: true }).click();
    assert.equal(await backupCard(browserPage, updatedDescription).count(), 1);
    browserPage.once("dialog", dialog => dialog.accept());
    await backupCard(browserPage, updatedDescription).getByRole("button", { name: "삭제", exact: true }).click();
    await backupCard(browserPage, updatedDescription).waitFor({ state: "detached" });

    browserPage.once("dialog", dialog => dialog.dismiss());
    await backupCard(browserPage, "복원 기준 백업").getByRole("button", { name: "복원", exact: true }).click();
    assert.equal((await browserContext.request.get(`${baseUrl}/api/presets`).then(response => response.json())).length, 2);
    browserPage.once("dialog", async dialog => {
      assert.match(dialog.message(), /백업해 두셨습니까/);
      await dialog.accept();
    });
    await Promise.all([
      browserPage.waitForEvent("load"),
      backupCard(browserPage, "복원 기준 백업").getByRole("button", { name: "복원", exact: true }).click(),
    ]);
    await browserPage.waitForFunction(() => document.getElementById("administration-history-list").querySelector("strong")?.textContent === "복원");
    const restoredPresets = await browserContext.request.get(`${baseUrl}/api/presets`).then(response => response.json());
    assert.deepEqual(restoredPresets.map(preset => preset.preset_id), ["before"]);
    assert.equal(filesystem.existsSync(path.join(runtimeDirectory, "outputs", "unregistered.png")), true);
    assert.equal(filesystem.readdirSync(path.join(runtimeDirectory, "backups")).length, 2);
    await browserPage.locator("#inspect-database-connections").click();
    await browserPage.getByText("현재 파일은 있으나 DB에 등록되지 않은 결과물 · 1개", { exact: true }).waitFor();
    await browserPage.locator("#inspect-administration-storage").click();
    await browserPage.locator(".administration-storage-grid").waitFor();
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
    assert.equal(await browserPage.evaluate(() => {
      const titleRange = document.createRange();
      titleRange.selectNodeContents(document.getElementById("page-title"));
      return titleRange.getClientRects().length;
    }), 1);
    await browserPage.screenshot({ path: path.join(artifactDirectory, `administration-${viewport.width}.png`), fullPage: true });
    await browserPage.evaluate(() => window.scrollTo(0, 0));
    await browserPage.screenshot({ path: path.join(artifactDirectory, `administration-top-${viewport.width}.png`) });
    await browserPage.goBack();
    await browserPage.locator("#view-generate").waitFor({ state: "visible" });
    await browserPage.goForward();
    await browserPage.locator("#view-administration").waitFor({ state: "visible" });
    assert.deepEqual(pageErrors, []);
  } catch (error) {
    console.error(serverOutput);
    throw error;
  } finally {
    await browserContext.close();
    const serverExited = new Promise(resolve => serverProcess.once("exit", resolve));
    serverProcess.kill();
    if (serverProcess.exitCode === null) await serverExited;
  }
}

/** 각 Viewport의 독립 DB에서 검증하고 화면 결과를 저장합니다. */
async function main() {
  filesystem.mkdirSync(artifactDirectory, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await verifyAdministrationViewport(browser, viewport);
    }
    console.log("Passed: administration backup, descriptions, delete/restore confirmation, schema mismatch, separate history, diagnostics and storage on Desktop/Mobile.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
