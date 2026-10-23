/** Prompt·태그 관리 내부 화면의 Back·Forward와 입력 보호를 격리된 API로 검증합니다. */
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { createPromptFixtures, createPromptHandler } = require("./browser_prompt_manager.cjs");
const { createTagManagerFixtures, createTagManagerHandler } = require("./browser_tag_manager.cjs");

/** 스크롤 복원까지 끝난 현재 History 항목을 읽습니다. */
async function currentEntry(page) {
  await page.waitForFunction(() => !applicationState.pendingNavigationScroll && !managerHistoryState.traversalPending);
  return page.evaluate(() => history.state.homeServerNavigation.entryId);
}

/** Back·Forward가 예상한 항목과 화면 복원을 끝낼 때까지 기다립니다. */
async function traverseHistory(page, direction, expectedEntry) {
  await page.evaluate(historyDirection => history[historyDirection](), direction);
  await page.waitForFunction(entryIdentifier => applicationState.navigationEntryId === entryIdentifier &&
    history.state.homeServerNavigation.entryId === entryIdentifier &&
    !applicationState.pendingNavigationScroll && !managerHistoryState.traversalPending, expectedEntry);
}

/** 취소되거나 저장 중인 이동이 입력을 건드리지 않고 원래 항목으로 복귀하는지 확인합니다. */
async function assertRejectedBack(page, expectedEntry, acceptConfirmation = null) {
  const traversal = page.waitForEvent("framenavigated");
  if (acceptConfirmation !== null) page.once("dialog", dialog => acceptConfirmation ? dialog.accept() : dialog.dismiss());
  await page.evaluate(() => history.back());
  await traversal;
  await page.waitForFunction(entryIdentifier => history.state.homeServerNavigation.entryId === entryIdentifier &&
    !managerHistoryState.traversalPending && !managerHistoryState.rejectedEntry, expectedEntry);
}

/** Prompt의 목록·편집·버전·신규 작성 이동과 미저장 입력·저장 요청을 보호합니다. */
async function verifyPromptHistory(browser, viewport) {
  const fixtures = createPromptFixtures();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createPromptHandler(fixtures));
  try {
    await page.goto("http://prompt-history.test/");
    await page.locator('#generate-preset option[value="portrait"]').waitFor({ state: "attached" });
    await page.locator("#generate-anima-prompt").fill("생성 화면의 입력은 History가 덮어쓰면 안 됩니다.");
    const generationEntry = await currentEntry(page);
    await page.locator('[data-view="prompts"]:visible').click();
    const listEntry = await currentEntry(page);
    const initialHistoryLength = await page.evaluate(() => history.length);
    await page.locator("#preset-search").fill("Template");
    await page.locator("#preset-workflow-filter").selectOption("anima");
    assert.equal(await page.evaluate(() => history.length), initialHistoryLength);
    await page.locator('[data-load-preset="portrait"]').scrollIntoViewIfNeeded();
    const listPosition = await page.evaluate(() => scrollY);
    await page.locator('[data-load-preset="portrait"]').click();
    const editEntry = await currentEntry(page);
    assert.notEqual(editEntry, listEntry);
    await page.locator("#preset-history-tab").click();
    await page.locator('[data-preview-version="1"]').waitFor();
    const historyEntry = await currentEntry(page);
    await page.locator('[data-preview-version="1"]').click();
    const previewEntry = await currentEntry(page);
    await page.locator("#load-preset-version-button").click();
    const earlierEditEntry = await currentEntry(page);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, earlier");
    await traverseHistory(page, "back", previewEntry);
    assert.equal(await page.locator("#view-prompts").isVisible(), true);
    assert.equal(await page.locator("#preset-history-panel").isVisible(), true);
    assert.match(await page.locator("#preset-preview-title").textContent(), /v1/);
    await traverseHistory(page, "back", historyEntry);
    assert.match(await page.locator("#preset-preview-title").textContent(), /v2/);
    await traverseHistory(page, "back", editEntry);
    assert.equal(await page.locator("#preset-edit-panel").isVisible(), true);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, daylight, latest");
    await traverseHistory(page, "back", listEntry);
    assert.equal(await page.locator("#preset-search").inputValue(), "Template");
    assert.equal(await page.locator("#preset-workflow-filter").inputValue(), "anima");
    assert.ok(Math.abs(await page.evaluate(() => scrollY) - listPosition) <= 2);
    await traverseHistory(page, "forward", editEntry);
    await traverseHistory(page, "forward", historyEntry);
    await traverseHistory(page, "forward", previewEntry);
    await traverseHistory(page, "forward", earlierEditEntry);
    assert.match(await page.locator("#preset-version").textContent(), /v1에서 시작/);
    await traverseHistory(page, "back", previewEntry);
    await traverseHistory(page, "back", historyEntry);
    await traverseHistory(page, "back", editEntry);

    let releaseVersions;
    fixtures.versionGates.set("portrait", new Promise(resolve => { releaseVersions = resolve; }));
    await page.evaluate(() => history.go(3));
    await page.waitForFunction(() => promptEditorState.navigationLoading);
    await page.evaluate(() => history.go(-3));
    await page.waitForFunction(entryIdentifier => applicationState.navigationEntryId === entryIdentifier &&
      !applicationState.pendingNavigationScroll, editEntry);
    fixtures.rejectVersions = true;
    const staleResponse = page.waitForResponse(response => response.status() === 503);
    releaseVersions();
    await staleResponse;
    fixtures.versionGates.delete("portrait");
    fixtures.rejectVersions = false;
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "portrait, daylight, latest");
    assert.equal(await currentEntry(page), editEntry);
    assert.doesNotMatch(await page.locator("#notice").textContent(), /버전 조회 실패/);

    await page.locator("#preset-anima-prompt").fill("보존할 기존 Prompt 초안");
    await page.locator("#preset-history-tab").click();
    const dirtyHistoryEntry = await currentEntry(page);
    await traverseHistory(page, "back", editEntry);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "보존할 기존 Prompt 초안");
    await traverseHistory(page, "back", listEntry);
    await traverseHistory(page, "forward", editEntry);
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "보존할 기존 Prompt 초안");
    await traverseHistory(page, "forward", dirtyHistoryEntry);
    await traverseHistory(page, "back", editEntry);
    page.once("dialog", dialog => dialog.accept());
    await page.locator("#new-preset-detail-button").click();
    const newEntry = await currentEntry(page);
    await page.locator("#preset-name").fill("버리면 안 되는 신규 Prompt");
    await page.locator("#preset-anima-prompt").fill("새 작성 입력");
    assert.doesNotMatch(await page.evaluate(() => JSON.stringify(history.state)), /새 작성 입력|버리면 안 되는 신규 Prompt/);
    await assertRejectedBack(page, newEntry, false);
    assert.equal(await page.locator("#preset-name").inputValue(), "버리면 안 되는 신규 Prompt");
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "새 작성 입력");
    page.once("dialog", dialog => dialog.accept());
    await traverseHistory(page, "back", editEntry);
    await traverseHistory(page, "forward", newEntry);
    assert.equal(await page.locator("#preset-name").inputValue(), "");
    assert.equal(await page.locator("#preset-anima-prompt").inputValue(), "");
    await page.locator("#preset-name").fill("신규 저장 대상");
    await page.locator("#preset-anima-prompt").fill("저장 중 보호할 본문");
    let releaseSave;
    fixtures.saveGate = new Promise(resolve => { releaseSave = resolve; });
    await page.locator("#save-preset-button").click();
    await page.waitForFunction(() => promptEditorState.saving);
    await assertRejectedBack(page, newEntry);
    assert.equal(await page.locator("#preset-name").isDisabled(), true);
    releaseSave();
    fixtures.saveGate = null;
    await page.waitForFunction(() => !promptEditorState.saving);
    const mutationCount = fixtures.mutations.length;
    await traverseHistory(page, "back", editEntry);
    await traverseHistory(page, "forward", newEntry);
    assert.equal(fixtures.mutations.length, mutationCount);
    assert.equal(await page.locator("#preset-name").inputValue(), "신규 저장 대상");
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "생성 화면의 입력은 History가 덮어쓰면 안 됩니다.");
    assert.equal(fixtures.mutations[0].preset_id, null);
    await traverseHistory(page, "back", editEntry);
    await traverseHistory(page, "back", listEntry);
    await traverseHistory(page, "back", generationEntry);
    assert.equal(await page.locator("#view-generate").isVisible(), true);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** 태그 그룹·편집 Dialog의 Back·Forward와 위치·취소·저장 보호를 검증합니다. */
async function verifyTagHistory(browser, viewport) {
  const fixtures = createTagManagerFixtures();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createTagManagerHandler(fixtures));
  try {
    await page.goto("http://tag-history.test/");
    await page.locator('[data-select-managed-group="group-10"]').waitFor({ state: "attached" });
    const generationEntry = await currentEntry(page);
    await page.locator('[data-view="tags"]:visible').click();
    const groupsEntry = await currentEntry(page);
    await page.locator("#tag-manager-group-search").fill("그룹");
    await page.locator("#tag-manager-reference-filter").selectOption("CHR");
    await page.locator('[data-select-managed-group="group-10"]').scrollIntoViewIfNeeded();
    const groupPosition = await page.evaluate(() => ({ window: scrollY, list: document.getElementById("tag-group-list").scrollTop }));
    await page.locator('[data-select-managed-group="group-10"]').click();
    const entriesEntry = await currentEntry(page);
    await page.locator("#tag-manager-entry-search").fill("sample 02");
    await page.locator('[data-edit-tag-entry="group-10-entry-02"]').scrollIntoViewIfNeeded();
    const entriesPosition = await page.evaluate(() => ({ window: scrollY, list: document.getElementById("tag-entry-list").scrollTop }));
    await page.locator('[data-edit-tag-entry="group-10-entry-02"]').click();
    const editorEntry = await currentEntry(page);
    await traverseHistory(page, "back", entriesEntry);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator("#view-tags").isVisible(), true);
    assert.equal(await page.locator("#tag-manager-entry-search").inputValue(), "sample 02");
    assert.deepEqual(await page.evaluate(() => ({ window: scrollY, list: document.getElementById("tag-entry-list").scrollTop })), entriesPosition);
    assert.equal(await page.locator('[data-edit-tag-entry="group-10-entry-02"]').evaluate(button => button === document.activeElement), true);
    await traverseHistory(page, "forward", editorEntry);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), true);
    await page.locator("#tag-entry-name").fill("취소하면 유지할 입력");
    assert.doesNotMatch(await page.evaluate(() => JSON.stringify(history.state)), /취소하면 유지할 입력/);
    await assertRejectedBack(page, editorEntry, false);
    assert.equal(await page.locator("#tag-entry-name").inputValue(), "취소하면 유지할 입력");
    page.once("dialog", dialog => dialog.accept());
    await traverseHistory(page, "back", entriesEntry);
    await traverseHistory(page, "forward", editorEntry);
    assert.equal(await page.locator("#tag-entry-name").inputValue(), "항목 02");
    await page.locator("#tag-entry-cancel").click();
    assert.equal(await currentEntry(page), entriesEntry);
    await traverseHistory(page, "back", groupsEntry);
    assert.equal(await page.locator("#tag-manager-group-search").inputValue(), "그룹");
    assert.equal(await page.locator("#tag-manager-reference-filter").inputValue(), "CHR");
    assert.deepEqual(await page.evaluate(() => ({ window: scrollY, list: document.getElementById("tag-group-list").scrollTop })), groupPosition);
    await traverseHistory(page, "forward", entriesEntry);
    await traverseHistory(page, "forward", editorEntry);

    await page.locator("#tag-entry-name").fill("저장된 항목 이름");
    let releaseSave;
    fixtures.saveGate = new Promise(resolve => { releaseSave = resolve; });
    await page.locator('#tag-entry-form button[type="submit"]').click();
    await page.waitForFunction(() => tagManagerState.editorBusy);
    await assertRejectedBack(page, editorEntry);
    assert.equal(await page.locator("#tag-entry-name").isDisabled(), true);
    releaseSave();
    fixtures.saveGate = null;
    await page.waitForFunction(() => !document.getElementById("tag-entry-dialog").open);
    const mutationCount = fixtures.mutations.length;
    await traverseHistory(page, "back", entriesEntry);
    await traverseHistory(page, "forward", editorEntry);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(fixtures.mutations.length, mutationCount);
    await traverseHistory(page, "back", entriesEntry);
    await page.locator('[data-edit-tag-entry="group-10-entry-02"]').click();
    const removedEditorEntry = await currentEntry(page);
    await traverseHistory(page, "back", entriesEntry);
    fixtures.entries = fixtures.entries.filter(entry => entry.tag_id !== "group-10-entry-02");
    await page.evaluate(() => loadTags());
    await traverseHistory(page, "forward", removedEditorEntry);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    assert.equal(fixtures.mutations.length, mutationCount);
    await traverseHistory(page, "back", entriesEntry);
    await traverseHistory(page, "back", groupsEntry);
    await page.locator("#new-tag-group-button").click();
    const newGroupEditorEntry = await currentEntry(page);
    await traverseHistory(page, "back", groupsEntry);
    await traverseHistory(page, "forward", newGroupEditorEntry);
    assert.equal(await page.locator("#tag-group-dialog").evaluate(dialog => dialog.open), true);
    assert.equal(await page.locator("#tag-group-name").inputValue(), "");
    await page.locator("#tag-group-cancel").click();
    assert.equal(await currentEntry(page), groupsEntry);
    await traverseHistory(page, "back", generationEntry);
    assert.equal(await page.locator("#view-generate").isVisible(), true);
    assert.equal(await page.locator("#tag-entry-dialog").evaluate(dialog => dialog.open), false);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** Desktop과 모바일에서 관리 화면과 브라우저 History의 이동 단계를 맞춥니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      await verifyPromptHistory(browser, viewport);
      await verifyTagHistory(browser, viewport);
    }
    console.log("Passed: manager Back/Forward steps, version restoration, dialog close/reopen, dirty cancellation, pending-save protection, filters/scroll/focus and no mutation replay on desktop/mobile.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
