/** 많은 그룹의 탐색·Dialog CRUD·모바일 목록 복귀를 운영 데이터 없이 검증합니다. */
const assert = require("node:assert/strict");
const filesystem = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const { handleJobFolderReadRequest } = require("./browser_job_folder_mock.cjs");

const projectDirectory = path.resolve(__dirname, "..");

/** 현재 운영 규모와 같은 28개 그룹·159개 항목의 독립된 Fixture를 만듭니다. */
function createTagManagerFixtures() {
  const groups = [];
  const entries = [];
  for (let groupIndex = 0; groupIndex < 28; groupIndex += 1) {
    const suffix = String(groupIndex).padStart(2, "0");
    const groupIdentifier = `group-${suffix}`;
    groups.push({ group_id: groupIdentifier, name: `그룹 ${suffix}`, tag_key: groupIndex < 12 ? "CHR" : groupIndex < 20 ? "FACE" : "STYLE", default_expanded: groupIndex % 2 === 0 });
    const entryCount = groupIndex === 0 ? 45 : groupIndex === 1 ? 10 : 4;
    for (let entryIndex = 0; entryIndex < entryCount; entryIndex += 1) {
      const entrySuffix = String(entryIndex).padStart(2, "0");
      entries.push({ tag_id: `${groupIdentifier}-entry-${entrySuffix}`, group_id: groupIdentifier,
        name: `항목 ${entrySuffix}`, content: `portrait, sample ${entrySuffix}\n[STYLE]\n${"long_content ".repeat(35)}`, weight: 1 });
    }
  }
  return { groups, entries, mutations: [], rejectSave: false, saveGate: null };
}

/** 실제 HTML/CSS/JS와 독립된 태그 API만 제공하고 예상하지 못한 요청은 실패시킵니다. */
function createTagManagerHandler(fixtures) {
  return async function handleTagManagerRequest(route) {
    const requestPath = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (await handleJobFolderReadRequest(route)) return;
    if (["/", "/app.js", "/app.css"].includes(requestPath)) {
      const fileName = requestPath === "/" ? "index.html" : requestPath.slice(1);
      await route.fulfill({ contentType: { "index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css" }[fileName],
        body: filesystem.readFileSync(path.join(projectDirectory, "web", fileName), "utf8") });
      return;
    }
    let response;
    if (requestPath === "/api/session") response = { authenticated: true };
    else if (requestPath === "/api/status") response = { comfy_connected: true };
    else if (requestPath === "/api/jobs/activity") response = { active_count: 0 };
    else if (requestPath === "/api/jobs") response = { items: [], total: 0, total_pages: 1, active_count: 0 };
    else if (["/api/presets", "/api/loras/presets"].includes(requestPath)) response = [];
    else if (requestPath === "/api/loras") response = { files: [], profiles: [] };
    else if (requestPath === "/api/tags" && method === "GET") response = { groups: fixtures.groups, entries: fixtures.entries };
    else if (requestPath === "/api/tags/export" && method === "GET") {
      response = { format: "comfy-home-server.tags", schema_version: 1, exported_at: "2026-10-26T03:00:00+00:00", groups: [] };
      for (const group of fixtures.groups) {
        const exportedTags = [];
        for (const entry of fixtures.entries) {
          if (entry.group_id === group.group_id) exportedTags.push({ name: entry.name, content: entry.content, weight: entry.weight });
        }
        response.groups.push({ name: group.name, tag_key: group.tag_key, tags: exportedTags });
      }
      await route.fulfill({ contentType: "application/json", headers: { "Content-Disposition": 'attachment; filename="tags_20261026T030000Z.json"' },
        body: JSON.stringify(response, null, 2) });
      return;
    }
    else if (requestPath.startsWith("/api/tags/")) {
      fixtures.mutations.push({ path: requestPath, method });
      if (fixtures.saveGate) await fixtures.saveGate;
      if (fixtures.rejectSave) {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "저장하지 못했습니다." }) });
        return;
      }
      const isGroup = requestPath.startsWith("/api/tags/groups");
      const records = isGroup ? fixtures.groups : fixtures.entries;
      const identifierName = isGroup ? "group_id" : "tag_id";
      const identifier = method === "POST" ? `new-${fixtures.mutations.length}` : requestPath.split("/").at(-1);
      const recordIndex = records.findIndex(record => record[identifierName] === identifier);
      if (method === "DELETE") {
        records.splice(recordIndex, 1);
        response = { deleted: true };
      } else {
        response = { ...route.request().postDataJSON(), [identifierName]: identifier };
        if (recordIndex < 0) records.push(response);
        else records[recordIndex] = response;
      }
    } else throw new Error(`Unexpected request: ${method} ${requestPath}`);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(response) });
  };
}

/** 필터와 무관한 전체 다운로드 및 DB 요청 없는 Import 더미 화면을 확인합니다. */
async function verifyTagTransferControls(page, fixtures) {
  await page.locator("#tag-manager-reference-filter").selectOption("CHR");
  await page.locator("#tag-manager-group-search").fill("그룹 00");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-tags-button").click();
  const downloadedFile = await downloadPromise;
  assert.equal(downloadedFile.suggestedFilename(), "tags_20261026T030000Z.json");
  const exportedDefinitions = JSON.parse(filesystem.readFileSync(await downloadedFile.path(), "utf8"));
  assert.equal(exportedDefinitions.groups.length, 28);
  assert.equal(exportedDefinitions.groups.reduce((total, group) => total + group.tags.length, 0), 159);
  assert.deepEqual(Object.keys(exportedDefinitions.groups[0]).sort(), ["name", "tag_key", "tags"]);
  assert.deepEqual(Object.keys(exportedDefinitions.groups[0].tags[0]).sort(), ["content", "name", "weight"]);

  await page.locator("#import-tags-button").click();
  assert.equal(await page.locator("#tag-import-dialog").isVisible(), true);
  assert.equal(await page.locator("#tag-import-mode").inputValue(), "append");
  assert.match(await page.locator("#tag-import-description").textContent(), /실제 태그는 변경되지 않습니다/);
  await page.locator("#tag-import-content").fill(JSON.stringify(exportedDefinitions));
  for (const importMode of ["replace", "append"]) {
    await page.locator("#tag-import-mode").selectOption(importMode);
    assert.equal(await page.locator("#tag-import-submit").isDisabled(), true);
  }
  const dialogFitsViewport = await page.locator("#tag-import-dialog").evaluate(dialog => {
    const bounds = dialog.getBoundingClientRect();
    return bounds.left >= 0 && bounds.right <= innerWidth && dialog.scrollWidth <= dialog.clientWidth;
  });
  assert.equal(dialogFitsViewport, true);
  await page.locator("#tag-import-close").click();
  assert.equal(await page.locator("#tag-import-dialog").isVisible(), false);
  assert.equal(await page.locator("#import-tags-button").evaluate(button => button === document.activeElement), true);
  await page.locator("#import-tags-button").click();
  await page.locator("#tag-import-content").press("Escape");
  assert.equal(await page.locator("#tag-import-dialog").isVisible(), false);
  assert.deepEqual(fixtures.mutations, []);
  assert.equal(fixtures.groups.length, 28);
  assert.equal(fixtures.entries.length, 159);
  await page.locator("#tag-manager-group-search").fill("");
  await page.locator("#tag-manager-reference-filter").selectOption("");
}

/** 검색·수정·오류·취소·저장 후 위치와 모바일 탐색을 하나의 화면 흐름으로 확인합니다. */
async function verifyTagManager(browser, viewport) {
  const fixtures = createTagManagerFixtures();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createTagManagerHandler(fixtures));
  try {
    await page.goto("http://tag-manager.test/?view=tags");
    await page.locator('[data-select-managed-group="group-00"]').waitFor();
    assert.equal(await page.locator('[data-select-managed-group]').count(), 28);
    assert.equal(await page.locator("#tag-group-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    await verifyTagTransferControls(page, fixtures);
    await page.locator("#tag-manager-reference-filter").selectOption("CHR");
    assert.equal(await page.locator('[data-select-managed-group]').count(), 12);
    await page.locator("#tag-manager-group-search").fill("그룹 00");
    assert.equal(await page.locator('[data-select-managed-group]').count(), 1);
    await page.locator('[data-select-managed-group="group-00"]').click();
    assert.equal(await page.locator("[data-edit-tag-entry]").count(), 45);
    assert.equal(await page.locator("#tag-manager-entry-count").textContent(), "45 / 45개 항목");
    await page.locator("#tag-manager-entry-search").fill("sample 07");
    assert.equal(await page.locator("[data-edit-tag-entry]").count(), 1);
    await page.locator("#tag-manager-entry-search").fill("");
    await page.locator('[data-edit-tag-entry="group-00-entry-20"]').click();
    const originalPosition = await page.evaluate(() => ({ page: scrollY, list: document.getElementById("tag-entry-list").scrollTop }));
    assert.equal(await page.locator("#tag-entry-name").inputValue(), "항목 20");
    await page.locator("#tag-entry-content").fill("<img src=x onerror=alert(1)>\n변경된 본문 [STYLE]");
    await page.evaluate(() => loadTags());
    assert.match(await page.locator("#tag-entry-content").inputValue(), /변경된 본문/);
    fixtures.rejectSave = true;
    await page.locator('#tag-entry-form button[type="submit"]').click();
    await page.locator("#tag-entry-editor-status").filter({ hasText: "저장하지 못했습니다" }).waitFor();
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), true);
    assert.match(await page.locator("#tag-entry-content").inputValue(), /변경된 본문/);
    fixtures.rejectSave = false;
    let releaseSave;
    fixtures.saveGate = new Promise(resolve => { releaseSave = resolve; });
    await page.locator('#tag-entry-form button[type="submit"]').click();
    assert.equal(await page.locator("#tag-entry-name").isDisabled(), true);
    await page.locator("#tag-entry-dialog").press("Escape");
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), true);
    releaseSave();
    fixtures.saveGate = null;
    await page.waitForFunction(() => !document.getElementById("tag-entry-dialog").open);
    assert.equal(await page.locator('#tag-entry-list img').count(), 0);
    assert.equal(await page.locator("#tag-manager-selected-name").textContent(), "그룹 00");
    assert.deepEqual(await page.evaluate(() => ({ page: scrollY, list: document.getElementById("tag-entry-list").scrollTop })), originalPosition);
    assert.equal(await page.locator('[data-edit-tag-entry="group-00-entry-20"]').evaluate(button => button === document.activeElement), true);

    await page.locator('[data-edit-tag-entry="group-00-entry-20"]').click();
    await page.locator("#tag-entry-name").fill("버리면 안 되는 편집");
    page.once("dialog", dialog => dialog.dismiss());
    await page.locator("#tag-entry-cancel").click();
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), true);
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#tag-entry-cancel").click();
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    await page.locator("#edit-selected-tag-group").click();
    assert.equal(await page.locator("#delete-selected-tag-group").isDisabled(), true);
    await page.locator("#tag-group-cancel").click();
    await page.locator("#new-tag-entry-button").click();
    assert.equal(await page.locator("#tag-entry-group").inputValue(), "group-00");
    await page.locator("#tag-entry-name").fill("새 항목");
    await page.locator("#tag-entry-content").fill("new content");
    await page.locator('#tag-entry-form button[type="submit"]').click();
    await page.waitForFunction(() => !document.getElementById("tag-entry-dialog").open);
    assert.equal(await page.locator("[data-edit-tag-entry]").count(), 46);

    const newEntry = fixtures.entries.at(-1);
    await page.locator(`[data-edit-tag-entry="${newEntry.tag_id}"]`).click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#delete-selected-tag-entry").click();
    await page.waitForFunction(() => !document.getElementById("tag-entry-dialog").open);
    await page.locator(`[data-edit-tag-entry="${newEntry.tag_id}"]`).waitFor({ state: "detached" });
    assert.equal(await page.locator("[data-edit-tag-entry]").count(), 45);
    if (viewport.width <= 800) {
      assert.equal(await page.locator(".tag-manager-groups").isVisible(), false);
      await page.locator("#tag-manager-back").click();
      assert.equal(await page.locator(".tag-manager-entries").isVisible(), false);
      assert.equal(await page.locator("#tag-manager-group-search").inputValue(), "그룹 00");
      assert.equal(await page.locator("#tag-manager-reference-filter").inputValue(), "CHR");
      await page.locator('[data-select-managed-group="group-00"]').click();
    }
    await page.locator("#tag-manager-entry-search").fill("sample 07");
    const navigationSelector = viewport.width <= 800 ? ".mobile-nav" : ".sidebar";
    await page.locator(`${navigationSelector} [data-view="generate"]`).click();
    await page.locator("#generate-anima-prompt").fill("[CHR]");
    assert.equal(await page.locator("[data-tag-group-open]").count(), 12);
    assert.equal(await page.locator('[data-tag-group-open="group-00"]').evaluate(group => group.open), true);
    assert.equal(await page.locator('[data-tag-group-open="group-01"]').evaluate(group => group.open), false);
    await page.locator(`${navigationSelector} [data-view="tags"]`).click();
    assert.equal(await page.locator("#tag-manager-entry-search").inputValue(), "sample 07");
    assert.equal(await page.locator("[data-edit-tag-entry]").count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const artifactDirectory = path.join(projectDirectory, "runtime", "browser-check");
    filesystem.mkdirSync(artifactDirectory, { recursive: true });
    await page.screenshot({ path: path.join(artifactDirectory, `tag-manager-${viewport.width}.png`) });
    if (viewport.width <= 800) await page.locator("#tag-manager-back").click();
    await page.locator("#new-tag-group-button").click();
    await page.locator("#tag-group-name").fill("새 빈 그룹");
    await page.locator("#tag-group-key").fill("NEW");
    await page.locator("#tag-group-default-expanded").uncheck();
    await page.locator('#tag-group-form button[type="submit"]').click();
    await page.waitForFunction(() => !document.getElementById("tag-group-dialog").open);
    assert.equal(await page.locator("#tag-manager-selected-name").textContent(), "새 빈 그룹");
    assert.equal(await page.locator("#tag-manager-entry-count").textContent(), "0 / 0개 항목");
    await page.locator("#edit-selected-tag-group").click();
    assert.equal(await page.locator("#delete-selected-tag-group").isEnabled(), true);
    await page.locator("#tag-group-name").fill("새 빈 그룹 수정");
    await page.locator('#tag-group-form button[type="submit"]').click();
    await page.waitForFunction(() => !document.getElementById("tag-group-dialog").open);
    assert.equal(await page.locator("#tag-manager-selected-name").textContent(), "새 빈 그룹 수정");
    await page.locator("#edit-selected-tag-group").click();
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#delete-selected-tag-group").click();
    await page.waitForFunction(() => !document.getElementById("tag-group-dialog").open);
    assert.equal(fixtures.groups.length, 28);
    assert.equal(fixtures.entries.length, 159);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** Desktop과 320px 모바일에서 같은 태그 관리 동작을 검증합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    await verifyTagManager(browser, { width: 1440, height: 1000 });
    await verifyTagManager(browser, { width: 320, height: 844 });
    console.log("Passed: full JSON export, import placeholder without mutations, 28 groups/159 entries, local filters, dialog CRUD and generation defaults on desktop/mobile.");
  } finally {
    await browser.close();
  }
}

module.exports = { createTagManagerFixtures, createTagManagerHandler };
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
