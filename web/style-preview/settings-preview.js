"use strict";

/** Pipeline과 성분 기본값을 가진 글로벌 설정 예시를 만듭니다. */
function createGlobalSettingsPreview() {
  return {
    revision: 1,
    pipelineIdentifier: "anima-preview",
    artistMinimumStrength: 0.5,
    artistMaximumStrength: 1.2,
    loraMinimumStrength: 0.3,
    loraMaximumStrength: 0.9,
    additionalArtists: [],
    availableComponents: {
      "artist:soft_ink": true, "artist:daylight": true,
      "lora:watercolor": true, "lora:flat_color": true,
    },
  };
}

/** 고정 예시 성분과 이번 탭에서 등록한 작가를 같은 Catalog로 조회합니다. */
function settingsCatalogComponents(globalSettings = previewState.globalSettings) {
  return [...sampleComponents, ...(globalSettings.additionalArtists || [])];
}

/** 성분 종류에 맞는 기본 STR 범위를 독립된 값으로 반환합니다. */
function settingsComponentRange(component, globalSettings) {
  const rangePrefix = component.kind === "작가" ? "artist" : "lora";
  return {
    minimumStrength: globalSettings[`${rangePrefix}MinimumStrength`],
    maximumStrength: globalSettings[`${rangePrefix}MaximumStrength`],
  };
}

/** 새 프로젝트가 글로벌 기본값의 독립 사본으로 시작하게 합니다. */
function createProjectSettingsPreview(name, promptCases, globalSettings) {
  const componentPolicies = {};
  // 첫 예시 프로젝트를 만드는 시점에도 성분 식별자는 이미 선언되어 있습니다.
  for (const component of settingsCatalogComponents(globalSettings)) {
    const strengthRange = settingsComponentRange(component, globalSettings);
    componentPolicies[component.identifier] = {
      ...strengthRange,
      enabled: globalSettings.availableComponents[component.identifier],
    };
  }
  return {
    name, purpose: "", pipelineIdentifier: globalSettings.pipelineIdentifier,
    promptCases: structuredClone(promptCases), negativePrompt: "",
    seed: 42, aspectRatio: "2:3", steps: 12, cfg: 1,
    width: ANIMA_RESOLUTIONS["2:3"][0][0], height: ANIMA_RESOLUTIONS["2:3"][0][1],
    componentPolicies, defaultsRevision: globalSettings.revision,
  };
}

/** 이전 Phase 0 Session의 프로젝트와 작성 내용을 유지하며 설정 필드만 보충합니다. */
function ensureSettingsPreviewState() {
  previewState.globalSettings ??= createGlobalSettingsPreview();
  previewState.settingsDrafts ??= { global: null, projects: {} };
  previewState.artistBulkInput ??= "";
  previewState.artistBulkRegistrationResult ??= "";
  previewState.globalSettings.additionalArtists ??= [];
  if (previewState.settingsDrafts.global) {
    previewState.settingsDrafts.global.additionalArtists ??= structuredClone(previewState.globalSettings.additionalArtists);
  }
  removeStandaloneConnectionSettings(previewState.globalSettings);
  if (previewState.settingsDrafts.global) removeStandaloneConnectionSettings(previewState.settingsDrafts.global);
  for (const project of previewState.projects) {
    if (!project.settings) {
      project.settings = createProjectSettingsPreview(project.name, project.promptCases, previewState.globalSettings);
      for (const componentIdentifier of project.excludedComponents) {
        if (project.settings.componentPolicies[componentIdentifier]) {
          project.settings.componentPolicies[componentIdentifier].enabled = false;
        }
      }
    }
    migrateProjectStrengthRanges(project.settings);
    migrateProjectWorkflowOptions(project.settings);
    ensureProjectCatalogPolicies(project.settings);
    const projectDraft = previewState.settingsDrafts.projects[project.identifier];
    if (projectDraft) {
      migrateProjectStrengthRanges(projectDraft);
      migrateProjectWorkflowOptions(projectDraft);
      ensureProjectCatalogPolicies(projectDraft);
    }
  }
}

/** 신규 Catalog 성분만 기본 범위로 보충하며 기존 프로젝트에서는 선택하지 않습니다. */
function ensureProjectCatalogPolicies(settings) {
  for (const component of settingsCatalogComponents()) {
    if (settings.componentPolicies[component.identifier]) continue;
    settings.componentPolicies[component.identifier] = {
      ...settingsComponentRange(component, previewState.globalSettings), enabled: false,
    };
  }
}

/** 기존 생성 조건을 보존하면서 CHS의 비율·CFG 필드 형식으로 보충합니다. */
function migrateProjectWorkflowOptions(settings) {
  settings.cfg ??= settings.guidanceScale ?? 1;
  delete settings.guidanceScale;
  if (settings.aspectRatio === "custom" || ANIMA_RESOLUTIONS[settings.aspectRatio]) return;
  settings.aspectRatio = "custom";
  for (const [aspectRatio, resolutions] of Object.entries(ANIMA_RESOLUTIONS)) {
    if (resolutions.some(([width, height]) => width === settings.width && height === settings.height)) {
      settings.aspectRatio = aspectRatio;
      break;
    }
  }
}

/** 과거 목업의 별도 연결값을 제거하고 Home 공통 설정만 사용하게 합니다. */
function removeStandaloneConnectionSettings(settings) {
  delete settings.executorIdentifier;
  delete settings.endpoint;
}

/** 이전 STR 고정 의도를 같은 최소·최대 범위로 옮기고 전용 필드를 제거합니다. */
function migrateProjectStrengthRanges(settings) {
  for (const policy of Object.values(settings.componentPolicies)) {
    if (policy.locked && Number.isFinite(policy.fixedStrength)) {
      policy.minimumStrength = policy.fixedStrength;
      policy.maximumStrength = policy.fixedStrength;
    }
    delete policy.locked;
    delete policy.fixedStrength;
  }
}

/** 명시적으로 반영하기 전까지 원본과 분리한 설정 초안을 유지합니다. */
function settingsPreviewDraft(scope, projectIdentifier = previewState.currentProjectIdentifier) {
  if (scope === "global") {
    previewState.settingsDrafts.global ??= structuredClone(previewState.globalSettings);
    return previewState.settingsDrafts.global;
  }
  const project = previewState.projects.find(project => project.identifier === projectIdentifier);
  previewState.settingsDrafts.projects[project.identifier] ??= structuredClone(project.settings);
  return previewState.settingsDrafts.projects[project.identifier];
}

/** Mobile과 Desktop에서 동일한 두 설정 범위로 이동하게 합니다. */
function settingsNavigationMarkup(scope) {
  return `<nav class="settings-tabs" aria-label="설정 범위">
    <button data-action="navigate" data-screen="project-settings" ${scope === "project" ? 'aria-current="page"' : ""}>프로젝트 설정</button>
    <button data-action="navigate" data-screen="global-settings" ${scope === "global" ? 'aria-current="page"' : ""}>글로벌 설정</button>
    </nav>`;
}

/** 현재 화면에서 다루는 범위와 임시 반영 상태를 명확히 표시합니다. */
function settingsHeadingMarkup(scope) {
  const isGlobal = scope === "global";
  return `${settingsNavigationMarkup(scope)}<div class="page-heading"><div>
    <p class="eyebrow">${isGlobal ? "GLOBAL DEFAULTS" : escapeMarkup(currentProject().name)}</p>
    <h1>${isGlobal ? "글로벌 설정" : "프로젝트 설정"}</h1>
    <p class="muted">${isGlobal ? "새 프로젝트가 사용할 Pipeline과 성분 기본값입니다." : "이 프로젝트에서 시험할 Prompt와 사용할 성분을 정합니다."}</p>
    </div></div><div class="settings-boundary-note">
    <strong>설정 화면 미리보기</strong><p>변경 내용은 이 탭에만 임시 보관됩니다. 실제 서버 설정·생성·이미지에는 아직 적용되지 않습니다.</p></div>`;
}

/** 범위가 분명한 단일 숫자 입력을 일관된 이름으로 만듭니다. */
function settingsNumberField(identifier, label, value, attributes = "") {
  return `<div><label for="${identifier}">${label}</label><input id="${identifier}" type="number" value="${value}" required ${attributes} /></div>`;
}

/** 글로벌 Pipeline·성분 Catalog·STR 기본값을 편집합니다. */
function renderGlobalSettingsPreview() {
  const draft = settingsPreviewDraft("global");
  return `${settingsHeadingMarkup("global")}<form id="global-settings-form" class="form-layout settings-form">
    <section class="panel"><h2>모델·Pipeline별 성분</h2><label for="settings-pipeline">Pipeline</label>
      <select id="settings-pipeline" data-settings-scope="global" data-settings-field="pipelineIdentifier"><option value="anima-preview">Anima Turbo · 화면 예시</option><option disabled>Moss · 등록·호환성 연결 예정</option></select>
      <p class="form-note">아래는 호환성이 확인됐다고 가정한 예시 Catalog입니다. 실제 설치 파일이나 등록 Workflow 목록이 아닙니다.</p>
      ${globalComponentGroupMarkup("작가", "작가 태그", "artist")}
      ${globalComponentGroupMarkup("LoRA", "LoRA", "lora")}</section>
    <section class="panel"><h2>새 프로젝트의 기본 STR 범위</h2><p class="muted form-note">프로젝트 안에서 별도로 조정할 수 있습니다.</p>
      <div class="settings-range-group"><h3>작가 태그</h3><div class="form-row">
      ${globalStrengthField("artistMinimumStrength", "최소 STR", draft.artistMinimumStrength)}
      ${globalStrengthField("artistMaximumStrength", "최대 STR", draft.artistMaximumStrength)}</div></div>
      <div class="settings-range-group"><h3>LoRA</h3><div class="form-row">
      ${globalStrengthField("loraMinimumStrength", "최소 STR", draft.loraMinimumStrength)}
      ${globalStrengthField("loraMaximumStrength", "최대 STR", draft.loraMaximumStrength)}</div></div>
      <p class="form-note">반영해도 기존 프로젝트는 바뀌지 않습니다. 프로젝트 설정에서 변경 내용을 확인한 뒤 STR 기본값만 가져올 수 있습니다.</p></section>
    ${settingsFormActionsMarkup("global")}</form>`;
}

/** 글로벌 Catalog를 작가 태그와 LoRA 구역으로 나누어 표시합니다. */
function globalComponentGroupMarkup(kind, title, groupIdentifier) {
  const draft = settingsPreviewDraft("global");
  const componentMarkup = [];
  for (const component of settingsCatalogComponents(draft)) {
    if (component.kind !== kind) continue;
    componentMarkup.push(`<label class="settings-checkbox"><input type="checkbox" data-settings-scope="global" data-settings-available="${escapeMarkup(component.identifier)}" ${draft.availableComponents[component.identifier] ? "checked" : ""} /><span><strong>${escapeMarkup(component.name)}</strong><small>이 Pipeline에서 사용 가능</small></span></label>`);
  }
  return `<section class="settings-component-group" data-settings-kind="${groupIdentifier}" aria-labelledby="settings-catalog-${groupIdentifier}"><h3 id="settings-catalog-${groupIdentifier}">${title}</h3>${kind === "작가" ? artistBulkInputMarkup() : ""}<div class="settings-catalog">${componentMarkup.join("")}</div></section>`;
}

/** Style Lab의 접두어·공백·괄호 Escape 정리를 줄 단위 작가 이름에 적용합니다. */
function normalizeArtistRegistrationLine(line) {
  let name = line.trim();
  if (name.startsWith("artist:")) name = name.slice("artist:".length);
  else if (name.startsWith("@")) name = name.slice(1);
  name = name.replace(/\\/g, "").trim().replace(/\s+/g, "_");
  if (!name) return { error: "작가 이름이 비어 있습니다." };
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(name)) return { error: "숫자만 있는 줄은 작가 이름으로 등록하지 않습니다." };
  if (/[,\x00-\x1f:@<>{}\[\]|]/.test(name)) return { error: "한 줄에 작가 이름만 입력해 주세요. Prompt·쉼표 목록·가중치 문법은 지원하지 않습니다." };
  return { identifier: `artist:${name}`, name, kind: "작가" };
}

/** 빈 줄과 등록·입력 중복을 구분하고 입력 순서를 보존한 신규 작가 목록을 만듭니다. */
function analyzeArtistBulkInput(text) {
  const existingIdentifiers = new Set(settingsCatalogComponents().filter(component => component.kind === "작가").map(component => component.identifier));
  const inputIdentifiers = new Set();
  const additions = [];
  const rows = [];
  let existingCount = 0;
  let duplicateCount = 0;
  let invalidCount = 0;
  let blankCount = 0;
  for (const [lineIndex, line] of text.split(/\r\n|\n|\r/).entries()) {
    if (!line.trim()) {
      blankCount += 1;
      continue;
    }
    const component = normalizeArtistRegistrationLine(line);
    let status = "신규";
    if (component.error) {
      status = component.error;
      invalidCount += 1;
    } else if (inputIdentifiers.has(component.identifier)) {
      status = "입력 중복";
      duplicateCount += 1;
    } else {
      inputIdentifiers.add(component.identifier);
      if (existingIdentifiers.has(component.identifier)) {
        status = "이미 등록됨";
        existingCount += 1;
      } else {
        additions.push(component);
      }
    }
    rows.push({ lineNumber: lineIndex + 1, rawLine: line, tag: component.identifier || line.trim(), status, invalid: Boolean(component.error) });
  }
  return { additions, rows, existingCount, duplicateCount, invalidCount, blankCount };
}

/** 등록 전 신규·중복·제외 수와 정규화 결과를 제한된 길이로 보여줍니다. */
function artistBulkPreviewMarkup(analysis) {
  if (!analysis.rows.length) return '<p class="form-note">한 줄마다 작가 태그 한 개를 등록합니다.</p>';
  return `<p class="form-note">신규 ${analysis.additions.length}명 · 이미 등록 ${analysis.existingCount}명 · 입력 중복 ${analysis.duplicateCount}명 · 확인 필요 ${analysis.invalidCount}줄 · 빈 줄 ${analysis.blankCount}줄 제외</p>
    <ol class="artist-bulk-preview-list">${analysis.rows.slice(0, 20).map(row => `<li><span>${row.lineNumber}행</span><code>${escapeMarkup(row.tag)}</code><small>${escapeMarkup(row.status)}</small></li>`).join("")}</ol>
    ${analysis.rows.length > 20 ? `<p class="form-note">미리보기는 앞 20줄만 표시합니다. 전체 ${analysis.additions.length}명의 신규 작가가 등록됩니다.</p>` : ""}`;
}

/** 글로벌 작가 구역에 줄 단위 입력·미리보기·명시적 등록 버튼을 배치합니다. */
function artistBulkInputMarkup() {
  const analysis = analyzeArtistBulkInput(previewState.artistBulkInput);
  return `<section class="artist-bulk-registration" aria-label="작가 태그 일괄 등록"><label for="artist-bulk-input">작가 태그 일괄 등록</label>
    <textarea id="artist-bulk-input" rows="5" spellcheck="false" placeholder="necomi&#10;artist:shigure_ui&#10;@mignon" aria-describedby="artist-bulk-help">${escapeMarkup(previewState.artistBulkInput)}</textarea>
    <p id="artist-bulk-help" class="form-note">한 줄에 한 명씩 입력하세요. 이름·artist:이름·@이름을 지원하며, 공백은 _로 정리하고 중복·빈 줄은 건너뜁니다.</p>
    <div id="artist-bulk-preview" aria-live="polite">${artistBulkPreviewMarkup(analysis)}</div>
    <div class="form-actions"><button id="artist-bulk-register-button" type="button" data-settings-action="register-artists" ${analysis.additions.length ? "" : "disabled"}>신규 작가 ${analysis.additions.length}명 등록</button></div>
    <p id="artist-bulk-registration-result" class="form-note" role="status">${escapeMarkup(previewState.artistBulkRegistrationResult)}</p>
    <p class="form-note">등록은 이 탭의 글로벌 작가 목록에 바로 반영됩니다. 기존 프로젝트에서는 사용을 직접 선택하세요.</p></section>`;
}

/** 입력 중에는 Textarea를 교체하지 않고 분석 결과와 등록 버튼만 갱신합니다. */
function updateArtistBulkPreview() {
  const analysis = analyzeArtistBulkInput(previewState.artistBulkInput);
  document.querySelector("#artist-bulk-preview").innerHTML = artistBulkPreviewMarkup(analysis);
  const button = document.querySelector("#artist-bulk-register-button");
  button.disabled = analysis.additions.length === 0;
  button.textContent = `신규 작가 ${analysis.additions.length}명 등록`;
}

/** 신규 작가만 탭의 글로벌 목록에 등록하고 기존 프로젝트의 선택·범위는 유지합니다. */
function registerBulkArtistsPreview() {
  const analysis = analyzeArtistBulkInput(previewState.artistBulkInput);
  if (!analysis.additions.length) return;
  const globalSettings = previewState.globalSettings;
  globalSettings.additionalArtists.push(...analysis.additions);
  globalSettings.revision += 1;
  const globalDraft = previewState.settingsDrafts.global;
  for (const component of analysis.additions) {
    globalSettings.availableComponents[component.identifier] = true;
    if (globalDraft) globalDraft.availableComponents[component.identifier] = true;
  }
  if (globalDraft) globalDraft.additionalArtists = structuredClone(globalSettings.additionalArtists);
  for (const project of previewState.projects) {
    ensureProjectCatalogPolicies(project.settings);
    const draft = previewState.settingsDrafts.projects[project.identifier];
    if (draft) ensureProjectCatalogPolicies(draft);
  }
  previewState.artistBulkInput = analysis.rows.filter(row => row.invalid).map(row => row.rawLine).join("\n");
  previewState.artistBulkRegistrationResult = `작가 ${analysis.additions.length}명 등록 · 이미 등록 ${analysis.existingCount}명 · 입력 중복 ${analysis.duplicateCount}명 · 확인 필요 ${analysis.invalidCount}줄 제외`;
  renderPreview(false);
  showToast(`신규 작가 ${analysis.additions.length}명을 등록했습니다 · 이 탭의 예시`);
}

/** 글로벌 STR 입력을 공통 검증 범위와 연결합니다. */
function globalStrengthField(field, label, value) {
  return settingsNumberField(`settings-${field}`, label, value, `min="-10" max="10" step="0.05" data-settings-scope="global" data-settings-field="${field}"`);
}

/** 프로젝트용 Prompt Case 편집기를 그리되 기존 예시 결과와 분리합니다. */
function projectSettingsPromptMarkup(promptCase, caseIndex) {
  return `<section class="prompt-editor"><div class="prompt-editor-heading"><span>${caseIndex + 1}</span>
    <label class="visually-hidden" for="settings-case-name-${caseIndex}">Prompt ${caseIndex + 1} 이름</label>
    <input id="settings-case-name-${caseIndex}" required maxlength="60" value="${escapeMarkup(promptCase.name)}" data-settings-case="${caseIndex}" data-settings-case-field="name" />
    <button type="button" class="quiet small" data-settings-action="remove-prompt" data-case="${caseIndex}" ${settingsPreviewDraft("project").promptCases.length === 1 ? "disabled" : ""}>제거</button></div>
    <label for="settings-case-prompt-${caseIndex}">Positive Prompt</label><textarea id="settings-case-prompt-${caseIndex}" required maxlength="3000" data-settings-case="${caseIndex}" data-settings-case-field="prompt">${escapeMarkup(promptCase.prompt)}</textarea></section>`;
}

/** 특정 성분의 허용 여부와 STR 범위를 여러 줄의 프로젝트 설정으로 표시합니다. */
function projectComponentPolicyMarkup(component, componentIndex) {
  const policy = settingsPreviewDraft("project").componentPolicies[component.identifier];
  const available = previewState.globalSettings.availableComponents[component.identifier];
  const inputAttributes = `min="-10" max="10" step="0.05" data-settings-component="${escapeMarkup(component.identifier)}"`;
  return `<section class="settings-component" data-policy-component="${escapeMarkup(component.identifier)}"><div class="settings-component-heading">
    <label class="settings-checkbox"><input type="checkbox" data-settings-component="${escapeMarkup(component.identifier)}" data-settings-policy="enabled" ${policy.enabled ? "checked" : ""} /><span><strong>${escapeMarkup(component.name)}</strong><small>${component.kind}${available ? "" : " · 글로벌에서 사용 불가"}</small></span></label>
    </div>
    <fieldset ${policy.enabled ? "" : "disabled"}><legend class="visually-hidden">${escapeMarkup(component.name)} STR</legend><div class="settings-strength-grid">
      ${settingsNumberField(`settings-component-${componentIndex}-minimum`, "최소 STR", policy.minimumStrength, `${inputAttributes} data-settings-policy="minimumStrength"`)}
      ${settingsNumberField(`settings-component-${componentIndex}-maximum`, "최대 STR", policy.maximumStrength, `${inputAttributes} data-settings-policy="maximumStrength"`)}</div></fieldset></section>`;
}

/** 프로젝트 성분을 종류별로 묶되 각 성분의 여유 공간과 독립된 입력 행을 유지합니다. */
function projectComponentGroupMarkup(kind, title, groupIdentifier) {
  const componentMarkup = [];
  for (const [componentIndex, component] of settingsCatalogComponents().entries()) {
    if (component.kind !== kind) continue;
    componentMarkup.push(projectComponentPolicyMarkup(component, componentIndex));
  }
  return `<section class="settings-component-group" data-settings-kind="${groupIdentifier}" aria-labelledby="settings-project-${groupIdentifier}"><h3 id="settings-project-${groupIdentifier}">${title}</h3>${componentMarkup.join("")}</section>`;
}

/** Prompt·생성 조건·성분 탐색 범위를 현재 프로젝트에 한정해 편집합니다. */
function renderProjectSettingsPreview() {
  const draft = settingsPreviewDraft("project");
  return `${settingsHeadingMarkup("project")}<form id="project-settings-form" data-settings-project="${currentProject().identifier}" class="form-layout settings-form">
    <section class="panel"><h2>프로젝트 목적</h2><label for="settings-project-name">프로젝트 이름</label><input id="settings-project-name" required maxlength="80" value="${escapeMarkup(draft.name)}" data-settings-scope="project" data-settings-field="name" />
      <label for="settings-project-purpose">찾고 싶은 그림체 · 메모</label><textarea id="settings-project-purpose" maxlength="2000" placeholder="예: 전신에서도 선이 선명한 수채 느낌" data-settings-scope="project" data-settings-field="purpose">${escapeMarkup(draft.purpose)}</textarea></section>
    <section class="panel"><h2>함께 비교할 Prompt</h2><p class="form-note settings-section-note">모든 Prompt를 함께 보고 조합 하나를 선택합니다. 한 개부터 시작할 수 있습니다.</p>
      ${draft.promptCases.map(projectSettingsPromptMarkup).join("")}<button type="button" data-settings-action="add-prompt">＋ Prompt 추가</button>
      <label for="settings-negative-prompt">공통 Negative Prompt</label><textarea id="settings-negative-prompt" maxlength="3000" data-settings-scope="project" data-settings-field="negativePrompt">${escapeMarkup(draft.negativePrompt)}</textarea>
      <p class="form-note">현재 예시 이미지는 그대로입니다. 실제 연결 후에는 조건 변경을 별도 평가 구간·Prompt 재시험으로 다룹니다.</p></section>
    ${projectWorkflowOptionsMarkup(draft)}
    <section class="panel"><div class="settings-section-heading"><div><h2>이 프로젝트의 성분 범위</h2><p class="form-note">글로벌 기본값 ${draft.defaultsRevision}번에서 시작 · 현재 ${previewState.globalSettings.revision}번</p></div>
      <button type="button" data-settings-action="preview-defaults">최신 STR 기본값 가져오기</button></div>
      <p class="form-note settings-section-note">체크를 끄면 향후 새 조합에서 제외합니다. 같은 강도로 사용하려면 최소·최대 STR을 같게 입력합니다. 예: 0.4 ~ 0.4.</p>
      ${projectComponentGroupMarkup("작가", "작가 태그", "artist")}
      ${projectComponentGroupMarkup("LoRA", "LoRA", "lora")}
      <p class="form-note">기존 조합의 성분·독립 CLIP 값·점수는 변경하지 않습니다. 다른 프로젝트에도 적용되지 않습니다.</p></section>
    ${settingsFormActionsMarkup("project")}</form>`;
}

/** CHS의 이미지 Workflow 옵션과 같은 항목·순서·해상도 후보를 표시합니다. */
function projectWorkflowOptionsMarkup(draft) {
  const isCustom = draft.aspectRatio === "custom";
  return `<section class="panel settings-workflow-options"><h2>Workflow 옵션</h2>
    <label for="settings-project-pipeline">Workflow</label><select id="settings-project-pipeline" data-settings-scope="project" data-settings-field="pipelineIdentifier"><option value="anima-preview">Anima Turbo V9 · 이미지</option><option disabled>Moss · 등록 후 선택 가능</option></select>
    <div class="form-row"><div><label for="settings-project-aspectRatio">비율</label><select id="settings-project-aspectRatio" data-settings-scope="project" data-settings-field="aspectRatio">${ANIMA_ASPECT_RATIO_OPTIONS.map(option => `<option value="${option.value}" ${option.value === draft.aspectRatio ? "selected" : ""}>${option.label}</option>`).join("")}</select></div>
      <div><label for="settings-project-resolution">해상도</label><select id="settings-project-resolution" data-settings-resolution ${isCustom ? "disabled" : ""}>${projectResolutionOptionsMarkup(draft)}</select></div></div>
    <div class="form-row">
      ${projectSamplingField("width", "너비", draft.width, `min="1" ${isCustom ? "" : "readonly"}`)}
      ${projectSamplingField("height", "높이", draft.height, `min="1" ${isCustom ? "" : "readonly"}`)}</div>
    <p class="form-note">직접 입력하려면 비율에서 사용자 지정을 선택하세요.</p>
    <div class="form-row">
      ${projectSamplingField("steps", "Steps", draft.steps, 'min="1"')}
      ${projectSamplingField("cfg", "CFG", draft.cfg, 'step="0.1"')}</div></section>`;
}

/** 선택한 비율의 해상도 목록과 현재 선택값을 CHS 공통 후보로 만듭니다. */
function projectResolutionOptionsMarkup(draft) {
  if (draft.aspectRatio === "custom") return '<option value="custom">직접 입력</option>';
  return ANIMA_RESOLUTIONS[draft.aspectRatio].map(([width, height]) => `<option value="${width}x${height}" ${width === draft.width && height === draft.height ? "selected" : ""}>${width} × ${height}</option>`).join("");
}

/** 비율·해상도 선택에 따른 크기와 직접 입력 상태만 갱신합니다. */
function updateProjectResolutionControls(form, draft) {
  const isCustom = draft.aspectRatio === "custom";
  const resolutionSelect = form.querySelector("#settings-project-resolution");
  resolutionSelect.innerHTML = projectResolutionOptionsMarkup(draft);
  resolutionSelect.disabled = isCustom;
  for (const dimension of ["width", "height"]) {
    const field = form.querySelector(`#settings-project-${dimension}`);
    field.readOnly = !isCustom;
    field.value = draft[dimension];
  }
}

/** 프로젝트 숫자 입력을 화면 상태의 설명적인 필드에 연결합니다. */
function projectSamplingField(field, label, value, attributes) {
  return settingsNumberField(`settings-project-${field}`, label, value, `${attributes} data-settings-scope="project" data-settings-field="${field}"`);
}

/** 초안과 임시 반영을 구분하고 공통 오류 표시 영역을 만듭니다. */
function settingsFormActionsMarkup(scope) {
  return `<p id="settings-form-error" class="error" role="alert"></p><div class="form-actions settings-actions"><span>입력 초안은 화면을 이동해도 유지됩니다.</span>
    <button type="button" class="quiet" data-settings-action="reset-draft" data-settings-scope="${scope}">초안 되돌리기</button><button type="submit" class="primary">이 탭의 예시에 반영</button></div>`;
}

/** 범위 역전과 사용할 수 없는 성분을 저장 전에 검사하고 같은 최소·최대값은 허용합니다. */
function validateSettingsPreview(scope, draft) {
  if (scope === "global") {
    if (draft.artistMinimumStrength > draft.artistMaximumStrength || draft.loraMinimumStrength > draft.loraMaximumStrength) {
      return "최소 STR은 최대 STR보다 클 수 없습니다.";
    }
    return "";
  }
  if (!draft.name.trim() || draft.promptCases.some(promptCase => !promptCase.name.trim() || !promptCase.prompt.trim())) {
    return "프로젝트 이름과 각 Prompt의 이름·내용을 입력해 주세요.";
  }
  for (const component of settingsCatalogComponents()) {
    const policy = draft.componentPolicies[component.identifier];
    if (!policy.enabled) continue;
    if (!previewState.globalSettings.availableComponents[component.identifier]) return `${component.name}: 글로벌 설정에서 사용 불가입니다. 이 프로젝트의 사용을 해제하거나 글로벌 설정을 확인해 주세요.`;
    if (policy.minimumStrength > policy.maximumStrength) return `${component.name}: 최소 STR은 최대 STR보다 클 수 없습니다.`;
  }
  return "";
}

/** 성분 제외 창과 프로젝트 설정의 사용 여부가 어긋나지 않게 합니다. */
function synchronizeSettingsComponentExclusion(project, componentIdentifier) {
  const enabled = !project.excludedComponents.includes(componentIdentifier);
  project.settings.componentPolicies[componentIdentifier].enabled = enabled;
  const draft = previewState.settingsDrafts.projects[project.identifier];
  if (draft) draft.componentPolicies[componentIdentifier].enabled = enabled;
}

/** 글로벌 STR 기본값만 가져올 때의 변경 내용을 먼저 보여줍니다. */
function renderSettingsDefaultsPreview() {
  const project = currentProject();
  const draft = settingsPreviewDraft("project");
  const globalSettings = previewState.globalSettings;
  const defaultChanges = [];
  for (const component of settingsCatalogComponents()) {
    const previousRange = draft.componentPolicies[component.identifier];
    const nextRange = settingsComponentRange(component, globalSettings);
    defaultChanges.push(`<li><strong>${escapeMarkup(component.name)}</strong><span>STR ${previousRange.minimumStrength} ~ ${previousRange.maximumStrength} → ${nextRange.minimumStrength} ~ ${nextRange.maximumStrength}</span></li>`);
  }
  const dialog = document.querySelector("#settings-defaults-dialog");
  dialog.dataset.projectIdentifier = project.identifier;
  dialog.innerHTML = `<div class="dialog-heading"><h2 id="settings-defaults-title">STR 기본값 적용 미리보기</h2><button data-settings-action="close-defaults" aria-label="기본값 적용 닫기">✕</button></div>
    <p>대상: <strong>${escapeMarkup(project.name)}</strong></p><p class="muted">현재 글로벌 기본값 ${globalSettings.revision}번을 이 프로젝트의 설정 초안에 가져옵니다.</p>
    <ul class="settings-default-changes">${defaultChanges.join("")}</ul><p class="form-note">STR 범위만 바꿉니다. 최소·최대가 같은 범위도 새 기본값으로 바뀝니다. Prompt·Workflow·사용 여부·기존 이미지·점수·다른 프로젝트는 유지됩니다.</p>
    <p id="settings-defaults-error" class="error" role="alert"></p><div class="form-actions"><button data-settings-action="close-defaults">취소</button><button class="primary" data-settings-action="apply-defaults">이 프로젝트 초안에 적용</button></div>`;
  dialog.showModal();
}

/** 기본값의 적용 범위를 검증하고 명시적으로 선택한 프로젝트 초안만 바꿉니다. */
function applySettingsDefaultsPreview() {
  const dialog = document.querySelector("#settings-defaults-dialog");
  if (dialog.dataset.projectIdentifier !== currentProject().identifier) {
    dialog.close();
    return;
  }
  const draft = settingsPreviewDraft("project");
  const updatedDraft = structuredClone(draft);
  for (const component of settingsCatalogComponents()) {
    Object.assign(updatedDraft.componentPolicies[component.identifier], settingsComponentRange(component, previewState.globalSettings));
  }
  const errorMessage = validateSettingsPreview("project", updatedDraft);
  if (errorMessage) {
    document.querySelector("#settings-defaults-error").textContent = `${errorMessage} 초안을 유지했습니다.`;
    return;
  }
  updatedDraft.defaultsRevision = previewState.globalSettings.revision;
  previewState.settingsDrafts.projects[currentProject().identifier] = updatedDraft;
  dialog.close();
  renderPreview(false);
  showToast("STR 기본값을 프로젝트 초안에 가져왔습니다.");
}

/** 입력을 초안에만 반영하고 프로젝트를 오갈 때 서로 섞이지 않게 합니다. */
function handleSettingsPreviewInput(event) {
  const field = event.target;
  if (!field.isConnected || !field.closest(".settings-form")) return;
  const form = field.closest("form");
  const scope = form.id === "global-settings-form" ? "global" : "project";
  // 프로젝트 전환 직후 늦게 전달된 change도 입력을 작성한 프로젝트에 귀속합니다.
  const draft = settingsPreviewDraft(scope, form.dataset.settingsProject);
  if (field.id === "artist-bulk-input") {
    previewState.artistBulkInput = field.value;
    previewState.artistBulkRegistrationResult = "";
    document.querySelector("#artist-bulk-registration-result").textContent = "";
    updateArtistBulkPreview();
  }
  if (field.dataset.settingsField) {
    let fieldValue = field.value;
    if (field.type === "number" && field.value !== "") fieldValue = Number(field.value);
    draft[field.dataset.settingsField] = fieldValue;
    if (field.dataset.settingsField === "aspectRatio") {
      if (draft.aspectRatio !== "custom") {
        [draft.width, draft.height] = ANIMA_RESOLUTIONS[draft.aspectRatio][0];
      }
      updateProjectResolutionControls(form, draft);
    }
  }
  if (field.hasAttribute("data-settings-resolution") && draft.aspectRatio !== "custom") {
    [draft.width, draft.height] = field.value.split("x").map(Number);
    updateProjectResolutionControls(form, draft);
  }
  if (field.dataset.settingsAvailable) draft.availableComponents[field.dataset.settingsAvailable] = field.checked;
  if (field.dataset.settingsCase !== undefined) {
    draft.promptCases[Number(field.dataset.settingsCase)][field.dataset.settingsCaseField] = field.value;
  }
  if (field.dataset.settingsComponent) {
    const policy = draft.componentPolicies[field.dataset.settingsComponent];
    let policyValue = field.value;
    if (field.type === "checkbox") policyValue = field.checked;
    else if (field.value !== "") policyValue = Number(field.value);
    policy[field.dataset.settingsPolicy] = policyValue;
    if (field.type === "checkbox") {
      const section = field.closest(".settings-component");
      section.querySelector("fieldset").disabled = !policy.enabled;
    }
  }
  persistPreviewSession();
}

/** 설정의 추가·취소·기본값 적용을 기존 선별 조작과 분리해 처리합니다. */
function handleSettingsPreviewAction(event) {
  const button = event.target.closest("button[data-settings-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.settingsAction;
  if (action === "register-artists") registerBulkArtistsPreview();
  if (action === "add-prompt") {
    const draft = settingsPreviewDraft("project");
    draft.promptCases.push({ name: `Prompt ${draft.promptCases.length + 1}`, prompt: "", scene: "garden" });
    renderPreview(false);
  }
  if (action === "remove-prompt") {
    const draft = settingsPreviewDraft("project");
    if (draft.promptCases.length > 1) draft.promptCases.splice(Number(button.dataset.case), 1);
    renderPreview(false);
  }
  if (action === "reset-draft") {
    if (button.dataset.settingsScope === "global") previewState.settingsDrafts.global = null;
    else delete previewState.settingsDrafts.projects[currentProject().identifier];
    renderPreview(false);
    showToast("마지막으로 반영한 설정 예시로 되돌렸습니다.");
  }
  if (action === "preview-defaults") renderSettingsDefaultsPreview();
  if (action === "close-defaults") document.querySelector("#settings-defaults-dialog").close();
  if (action === "apply-defaults") applySettingsDefaultsPreview();
  persistPreviewSession();
}

/** 유효한 설정 초안만 임시 반영하며 실제 서비스·생성 API는 호출하지 않습니다. */
function submitSettingsPreview(event) {
  if (!["global-settings-form", "project-settings-form"].includes(event.target.id)) return;
  event.preventDefault();
  const scope = event.target.id === "global-settings-form" ? "global" : "project";
  const draft = settingsPreviewDraft(scope);
  let errorMessage;
  try {
    errorMessage = validateSettingsPreview(scope, draft);
  } catch (error) {
    errorMessage = "설정 형식을 확인해 주세요.";
  }
  if (errorMessage) {
    document.querySelector("#settings-form-error").textContent = errorMessage;
    return;
  }
  if (scope === "global") {
    const nextRevision = previewState.globalSettings.revision + 1;
    previewState.globalSettings = structuredClone(draft);
    previewState.globalSettings.revision = nextRevision;
    previewState.settingsDrafts.global = null;
  } else {
    const project = currentProject();
    project.settings = structuredClone(draft);
    project.name = draft.name.trim();
    project.excludedComponents = settingsCatalogComponents().filter(component => !draft.componentPolicies[component.identifier].enabled).map(component => component.identifier);
    delete previewState.settingsDrafts.projects[project.identifier];
  }
  renderPreview(false);
  showToast(scope === "global" ? "글로벌 설정 예시에 반영했습니다. 기존 프로젝트는 유지됩니다." : "현재 프로젝트 설정 예시에 반영했습니다. 기존 이미지는 그대로입니다.");
}

document.addEventListener("input", handleSettingsPreviewInput);
document.addEventListener("change", handleSettingsPreviewInput);
document.addEventListener("click", handleSettingsPreviewAction);
document.addEventListener("submit", submitSettingsPreview);
