/** Mock API에서 태그 Import의 오류·대기·확인·목록 갱신을 Desktop/Mobile로 검증합니다. */
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
const { createTagManagerFixtures, createTagManagerHandler } = require("./browser_tag_manager.cjs");

/** 선택한 입력 방식으로 동일한 태그 문서를 준비합니다. */
async function fillTagImportDocument(page, inputSource, document) {
  if (inputSource === "file") {
    await page.locator("#tag-import-file").setInputFiles({ name: "tags.json", mimeType: "application/json",
      buffer: Buffer.from("\uFEFF" + JSON.stringify(document), "utf8") });
  } else {
    await page.locator("#tag-import-content").fill(JSON.stringify(document));
  }
}

/** 실패·확인 취소 후 선택한 입력이 보존되었는지 확인합니다. */
async function verifyTagImportInputPreserved(page, inputSource, document) {
  if (inputSource === "file") {
    assert.equal(await page.locator("#tag-import-file").evaluate(input => input.files[0]?.name), "tags.json");
  } else {
    assert.equal(await page.locator("#tag-import-content").inputValue(), JSON.stringify(document));
  }
}

/** 운영 데이터를 사용하지 않고 각 입력 방식의 Append와 전체 Replace를 확인합니다. */
async function verifyTagImport(browser, viewport, inputSource) {
  const fixtures = createTagManagerFixtures();
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await context.route("**/*", createTagManagerHandler(fixtures));
  const appendDocument = { format: "comfy-home-server.tags", schema_version: 1, groups: [
    { name: "그룹 00", tag_key: "CHR", tags: [{ name: "추가 태그", content: "new character", weight: 1.0 }] },
    { name: "새 그룹", tag_key: "EXTRA", tags: [{ name: "추가 항목", content: "soft light", weight: 1.0 }] },
  ] };
  try {
    await page.goto("http://tag-import.test/?view=tags");
    await page.locator('[data-select-managed-group="group-00"]').waitFor();
    await page.evaluate(() => {
      document.getElementById("generate-anima-prompt").value = "keep [CHR]";
      applicationState.selectedTagIds.add("group-00-entry-00");
    });
    await page.locator("#import-tags-button").click();
    assert.equal(await page.locator("#tag-import-submit").isDisabled(), true);
    if (inputSource === "file") {
      await page.locator("#tag-import-content").fill(JSON.stringify({ format: "comfy-home-server.tags", schema_version: 1, groups: [] }));
      await page.locator("#tag-import-source").selectOption("file");
    } else {
      await page.locator("#tag-import-source").selectOption("file");
      await page.locator("#tag-import-file").setInputFiles({ name: "ignored.json", mimeType: "application/json", buffer: Buffer.from("{invalid ignored file") });
      await page.locator("#tag-import-source").selectOption("text");
    }
    assert.equal(await page.locator("#tag-import-submit").isDisabled(), true);
    assert.equal(await page.locator("#tag-import-text-panel").isVisible(), inputSource === "text");
    assert.equal(await page.locator("#tag-import-file-panel").isVisible(), inputSource === "file");
    assert.equal(await page.locator("#tag-import-content").isDisabled(), inputSource === "file");
    assert.equal(await page.locator("#tag-import-file").isDisabled(), inputSource === "text");
    await fillTagImportDocument(page, inputSource, appendDocument);
    fixtures.rejectSave = true;
    await page.locator("#tag-import-submit").click();
    await page.locator("#tag-import-status").filter({ hasText: "Import하지 못했습니다" }).waitFor();
    await verifyTagImportInputPreserved(page, inputSource, appendDocument);
    assert.equal(await page.locator("#tag-import-mode").inputValue(), "append");
    assert.equal(await page.locator("#tag-import-submit").isEnabled(), true);
    assert.equal(fixtures.groups.length, 28);
    assert.equal(fixtures.entries.length, 159);
    fixtures.rejectSave = false;

    let releaseImport;
    fixtures.saveGate = new Promise(resolve => { releaseImport = resolve; });
    await page.locator("#tag-import-submit").click();
    await page.waitForFunction(() => document.getElementById("tag-import-source").disabled);
    for (const identifier of ["tag-import-content", "tag-import-file", "tag-import-mode", "tag-import-close", "tag-import-submit"]) {
      assert.equal(await page.locator(`#${identifier}`).isDisabled(), true);
    }
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#tag-import-dialog").isVisible(), true);
    await page.evaluate(() => switchView("jobs"));
    assert.equal(await page.locator("#view-tags").isVisible(), true);
    await page.evaluate(() => submitTagImport());
    releaseImport();
    fixtures.saveGate = null;
    await page.waitForFunction(() => !document.getElementById("tag-import-dialog").open);
    assert.equal(fixtures.mutations.length, 2);
    assert.deepEqual(fixtures.mutations.at(-1).payload.data, appendDocument);
    assert.equal(fixtures.groups.length, 29);
    assert.equal(fixtures.entries.length, 161);
    assert.equal(await page.locator(inputSource === "file" ? "#tag-import-file" : "#tag-import-content").inputValue(), "");
    if (inputSource === "file") {
      assert.match(await page.locator("#tag-import-content").inputValue(), /"groups":\[\]/);
    } else {
      assert.equal(await page.locator("#tag-import-file").evaluate(input => input.files[0]?.name), "ignored.json");
    }
    assert.equal(await page.locator('[data-select-managed-group]').count(), 29);
    assert.equal(await page.locator("#tag-manager-entry-count").textContent(), "46 / 46개 항목");
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "keep [CHR]");
    assert.equal(await page.evaluate(() => applicationState.selectedTagIds.has("group-00-entry-00")), true);

    const replaceDocument = { format: "comfy-home-server.tags", schema_version: 1, groups: [
      { name: "교체된 그룹", tag_key: "IMPORTED", tags: [{ name: "교체된 태그", content: "new light", weight: 1.0 }] },
    ] };
    await page.locator("#import-tags-button").click();
    await fillTagImportDocument(page, inputSource, replaceDocument);
    await page.locator("#tag-import-mode").selectOption("replace");
    assert.equal(await page.locator("#tag-import-submit").textContent(), "전체 Replace");
    const replaceDismissed = page.waitForEvent("dialog").then(dialog => dialog.dismiss());
    await page.locator("#tag-import-submit").click();
    await replaceDismissed;
    await page.waitForFunction(() => !tagImportState.busy);
    assert.equal(fixtures.mutations.length, 2);
    assert.equal(await page.locator("#tag-import-dialog").isVisible(), true);
    await verifyTagImportInputPreserved(page, inputSource, replaceDocument);
    const replaceConfirmed = page.waitForEvent("dialog").then(dialog => dialog.accept());
    await page.locator("#tag-import-submit").click();
    await replaceConfirmed;
    await page.waitForFunction(() => !document.getElementById("tag-import-dialog").open);
    assert.equal(fixtures.mutations.length, 3);
    assert.equal(fixtures.mutations.at(-1).payload.mode, "replace");
    assert.deepEqual(fixtures.mutations.at(-1).payload.data, replaceDocument);
    assert.equal(fixtures.groups.length, 1);
    assert.equal(fixtures.entries.length, 1);
    assert.equal(await page.locator("#tag-manager-selected-name").textContent(), "교체된 그룹");
    assert.equal(await page.locator("#tag-manager-entry-count").textContent(), "1 / 1개 항목");
    assert.equal(await page.locator("#generate-anima-prompt").inputValue(), "keep [CHR]");
    assert.equal(await page.evaluate(() => applicationState.selectedTagIds.size), 0);
    assert.deepEqual(pageErrors, []);
  } finally {
    await context.close();
  }
}

/** 파일 읽기와 JSON 문법 오류가 서버 요청 없이 입력을 보존하는지 확인합니다. */
async function verifyTagImportFileErrors(browser, viewport) {
  const fixtures = createTagManagerFixtures();
  const context = await browser.newContext({ viewport });
  await context.route("**/*", createTagManagerHandler(fixtures));
  const page = await context.newPage();
  try {
    await page.goto("http://tag-import-file.test/?view=tags");
    await page.locator('[data-select-managed-group="group-00"]').waitFor();
    await page.locator("#import-tags-button").click();
    await page.locator("#tag-import-source").selectOption("file");
    assert.equal(await page.locator("#tag-import-submit").isDisabled(), true);
    await page.locator("#tag-import-file").setInputFiles({ name: "invalid.json", mimeType: "application/json", buffer: Buffer.from("{invalid JSON") });
    await page.locator("#tag-import-submit").click();
    await page.locator("#tag-import-status").filter({ hasText: "JSON 문법" }).waitFor();
    assert.equal(await page.locator("#tag-import-file").evaluate(input => input.files[0]?.name), "invalid.json");
    assert.equal(await page.locator("#tag-import-source").isEnabled(), true);
    assert.deepEqual(fixtures.mutations, []);

    await page.locator("#tag-import-file").setInputFiles({ name: "unreadable.json", mimeType: "application/json", buffer: Buffer.from("{}") });
    await page.evaluate(() => {
      const selectedFile = document.getElementById("tag-import-file").files[0];
      selectedFile.text = () => Promise.reject(new Error("File read failed"));
    });
    await page.locator("#tag-import-submit").click();
    await page.locator("#tag-import-status").filter({ hasText: "파일을 읽지 못했습니다" }).waitFor();
    assert.equal(await page.locator("#tag-import-file").evaluate(input => input.files[0]?.name), "unreadable.json");
    assert.deepEqual(fixtures.mutations, []);

    await page.evaluate(() => {
      const selectedFile = document.getElementById("tag-import-file").files[0];
      selectedFile.text = () => new Promise(resolve => { window.finishTagImportFileRead = resolve; });
    });
    await page.locator("#tag-import-submit").click();
    await page.waitForFunction(() => typeof window.finishTagImportFileRead === "function");
    for (const identifier of ["tag-import-source", "tag-import-file", "tag-import-mode", "tag-import-close", "tag-import-submit"]) {
      assert.equal(await page.locator(`#${identifier}`).isDisabled(), true);
    }
    assert.deepEqual(fixtures.mutations, []);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#tag-import-dialog").isVisible(), true);
    await page.evaluate(() => window.finishTagImportFileRead("{invalid JSON"));
    await page.locator("#tag-import-status").filter({ hasText: "JSON 문법" }).waitFor();
    assert.equal(await page.locator("#tag-import-source").isEnabled(), true);
    assert.equal(await page.locator("#tag-import-file").isEnabled(), true);
    assert.deepEqual(fixtures.mutations, []);
  } finally {
    await context.close();
  }
}

/** 320px Mobile을 포함해 실제 저장 전후의 조작 상태를 확인합니다. */
async function main() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || "msedge", headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 320, height: 844 }]) {
      for (const inputSource of ["text", "file"]) await verifyTagImport(browser, viewport, inputSource);
      await verifyTagImportFileErrors(browser, viewport);
    }
    console.log("Passed: exclusive text/file input, Append/Replace, BOM, file read/JSON failures, pending safety, confirmation and generation input preservation on desktop/mobile.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
