/** 작업 원본 Prompt의 공통 5줄 접기와 카드·Keyboard·기존 조작을 실제 Browser로 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const projectDirectory = path.resolve(__dirname, "..");

/** 정확히 다섯 줄·여섯 줄·자동 줄바꿈·Negative 없음·HTML 문자를 가진 작업을 만듭니다. */
function createPromptFixtures() {
  const promptBodies = [
    { prompt: "POS1\nPOS2\nPOS3", negative: "NEG1\nNEG2" },
    { prompt: "POS1\nPOS2\nPOS3", negative: "NEG1\nNEG2\nNEG3" },
    { prompt: "매우 긴 Positive Prompt의 자동 줄바꿈을 확인합니다. ".repeat(80), negative: "마지막 Negative" },
    { prompt: "<script>alert('escaped')</script>\n단독 Prompt", negative: "" },
  ];
  return { jobs: promptBodies.map((body, jobIndex) => ({
    job_id: `prompt-job-${jobIndex}`, workflow: "anima", status: "completed", created_at: "2026-10-19",
    status_counts: { completed: 1 }, request_count: 1, deletion_protected: false,
    description: "접기 검증", inputs: { body, settings: { width: 768, height: 1024 }, loras: [] },
    requests: [{ request_id: `request-${jobIndex}`, request_index: 1, status: "completed", result: { prompt: "하위 요청의 확정 Prompt", negative: "확정 Negative" } }],
  })), queries: 0, protectionChanges: 0 };
}

/** 운영 데이터 없이 현재 앱 파일과 작업 목록의 갱신을 제공합니다. */
function createPromptRequestHandler(fixtures) {
  return async function handlePromptRequest(route) {
    const requestUrl = new URL(route.request().url());
    const requestPath = requestUrl.pathname;
    if (["/", "/app.css", "/app.js"].includes(requestPath)) {
      const filename = requestPath === "/" ? "index.html" : requestPath.slice(1);
      const contentTypes = { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" };
      await route.fulfill({ contentType: contentTypes[filename], body: filesystem.readFileSync(path.join(projectDirectory, "web", filename), "utf8") });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags") response = { groups: [], entries: [] };
    else if (requestPath === "/api/jobs") {
      fixtures.queries += 1;
      response = { items: fixtures.jobs, page: 1, total: fixtures.jobs.length, total_pages: 1, active_count: 0 };
    } else if (requestPath === "/api/jobs/deletion-candidates") {
      response = { job_ids: fixtures.jobs.filter(job => !job.deletion_protected).map(job => job.job_id) };
    } else if (requestPath.endsWith("/protection")) {
      fixtures.protectionChanges += 1;
      const jobIdentifier = requestPath.split("/").at(-2);
      const job = fixtures.jobs.find(candidate => candidate.job_id === jobIdentifier);
      job.deletion_protected = route.request().postDataJSON().deletion_protected;
      response = { deletion_protected: job.deletion_protected };
    } else if (requestPath === "/api/outputs/directories") {
      response = { path: "", parent_path: null, directories: [] };
    } else if (requestPath === "/api/outputs") {
      response = { files: [], page: 1, total: 0, total_pages: 1 };
    } else if (requestPath === "/favicon.ico") {
      await route.fulfill({ status: 204 });
      return;
    } else throw new Error(`Unexpected request: ${route.request().method()} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 접힌 영역 높이를 실제 line-height와 비교하여 두 Prompt가 한 예산을 사용하는지 확인합니다. */
async function promptDimensions(promptLocator) {
  return promptLocator.evaluate(container => ({
    height: container.getBoundingClientRect().height,
    lineHeight: Number.parseFloat(getComputedStyle(container).lineHeight),
    expanded: container.getAttribute("aria-expanded"),
  }));
}

/** Desktop과 Mobile에서 줄 수 경계와 카드 클릭·기존 버튼·갱신 상태를 확인합니다. */
async function verifyPromptFolding(browser, viewport) {
  const browserPage = await browser.newPage({ viewport });
  const fixtures = createPromptFixtures();
  const pageErrors = [];
  browserPage.on("pageerror", error => pageErrors.push(error.message));
  await browserPage.route("**/*", createPromptRequestHandler(fixtures));
  try {
    await browserPage.goto("http://job-prompts.test/?view=jobs");
    const fiveLinePrompt = browserPage.locator('[data-toggle-job-prompt="prompt-job-0"]');
    const sixLinePrompt = browserPage.locator('[data-toggle-job-prompt="prompt-job-1"]');
    const wrappedPrompt = browserPage.locator('[data-toggle-job-prompt="prompt-job-2"]');
    const sixLineCard = browserPage.locator('[data-job-prompt-card="prompt-job-1"]');
    await sixLinePrompt.waitFor();
    const fiveLineDimensions = await promptDimensions(fiveLinePrompt);
    assert.ok(Math.abs(fiveLineDimensions.height - fiveLineDimensions.lineHeight * 5) <= 1);
    await fiveLinePrompt.click();
    assert.equal((await promptDimensions(fiveLinePrompt)).height, fiveLineDimensions.height);
    for (const promptLocator of [sixLinePrompt, wrappedPrompt]) {
      const dimensions = await promptDimensions(promptLocator);
      assert.equal(dimensions.expanded, "false");
      assert.ok(dimensions.height <= dimensions.lineHeight * 5 + 1);
    }
    await sixLineCard.locator("h3").click();
    const expandedDimensions = await promptDimensions(sixLinePrompt);
    assert.equal(expandedDimensions.expanded, "true");
    assert.ok(Math.abs(expandedDimensions.height - expandedDimensions.lineHeight * 6) <= 1);
    assert.match(await sixLinePrompt.textContent(), /NEG3/);
    await sixLineCard.locator(".job-description").click();
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await sixLinePrompt.focus();
    await browserPage.keyboard.press("Enter");
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "true");
    fixtures.jobs[1].description = "갱신된 작업 설명";
    await browserPage.locator("#refresh-button").click();
    await sixLineCard.locator(".job-description").getByText("갱신된 작업 설명").waitFor();
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "true");
    await sixLinePrompt.focus();
    await browserPage.keyboard.press("Space");
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await sixLineCard.locator("summary").click();
    await sixLineCard.locator(".job-request").getByText("하위 요청의 확정 Prompt", { exact: false }).click();
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await sixLineCard.locator('[data-toggle-job-protection="prompt-job-1"]').click();
    await browserPage.waitForFunction(() => document.querySelector('[data-toggle-job-protection="prompt-job-1"]').textContent === "보호 해제");
    assert.equal(fixtures.protectionChanges, 1);
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await browserPage.locator("#toggle-job-selection").click();
    await browserPage.locator('[data-select-job="prompt-job-2"]').check();
    assert.equal(await wrappedPrompt.getAttribute("aria-expanded"), "false");
    await browserPage.locator("#toggle-job-selection").click();
    await sixLineCard.locator('[data-move-job-outputs="prompt-job-1"]').click();
    await browserPage.locator("#folder-picker-cancel").click();
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await sixLineCard.locator('[data-show-job-results="prompt-job-1"]').click();
    await browserPage.locator("#view-outputs").waitFor({ state: "visible" });
    assert.equal(new URL(browserPage.url()).searchParams.get("job_id"), "prompt-job-1");
    await browserPage.goBack();
    await sixLinePrompt.waitFor();
    assert.equal(await sixLinePrompt.getAttribute("aria-expanded"), "false");
    await wrappedPrompt.click();
    const wrappedDimensions = await promptDimensions(wrappedPrompt);
    assert.ok(wrappedDimensions.height > wrappedDimensions.lineHeight * 5);
    await wrappedPrompt.click();
    const htmlPrompt = browserPage.locator('[data-toggle-job-prompt="prompt-job-3"]');
    assert.match(await htmlPrompt.textContent(), /<script>/);
    assert.equal(await htmlPrompt.locator("script").count(), 0);
    assert.equal(await htmlPrompt.locator(".job-original-negative-prompt").count(), 0);
    assert.equal(await browserPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(pageErrors, []);
    const screenshotDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(screenshotDirectory, { recursive: true });
    await sixLineCard.scrollIntoViewIfNeeded();
    await browserPage.screenshot({ path: path.join(screenshotDirectory, `job-prompt-folding-${viewport.width}.png`) });
  } finally {
    await browserPage.close();
  }
}

/** GPU와 운영 이력을 사용하지 않고 두 화면 너비에서 검증합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyPromptFolding(browser, { width: 1280, height: 950 });
    await verifyPromptFolding(browser, { width: 390, height: 844 });
    console.log("Passed: combined five-line prompts, card/keyboard expansion, refresh persistence, action isolation, escaping and mobile layout.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
