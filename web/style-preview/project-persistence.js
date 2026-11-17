"use strict";

const PERSISTENT_STYLE_WORKSPACE = window.location.pathname === "/style";
document.body.classList.toggle("persistent-workspace", PERSISTENT_STYLE_WORKSPACE);
const STYLE_WORKSPACE_SESSION_KEY = "comfy-home-style-workspace-session-v1";
let persistentWorkspaceMetadata = { workflows: [], components: [], catalogNotice: "" };
let persistentSettingsBusy = false;
let persistentWorkspaceLoaded = false;

/** 외부 HTTP 접속에서도 사용할 수 있는 브라우저 난수로 요청 ID를 만듭니다. */
function newStyleClientIdentifier() {
  const randomBytes = new Uint8Array(16);
  window.crypto.getRandomValues(randomBytes);
  return Array.from(randomBytes, randomByte => randomByte.toString(16).padStart(2, "0")).join("");
}

/** 실제 API의 검증 오류를 초안을 지우지 않는 사용자 메시지로 전달합니다. */
async function styleProjectApi(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...options.headers } });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      if (persistentWorkspaceLoaded) persistPreviewSession();
      window.ComfyWorkspaceShell.redirectToLogin();
    }
    const message = Array.isArray(result.detail) ? result.detail.map(detail => detail.msg).join(" · ") : result.detail;
    const error = new Error(message || "서버에 저장하지 못했습니다. 작성한 초안은 유지됩니다.");
    error.status = response.status;
    throw error;
  }
  return result;
}

/** 서버 데이터 대신 탭별 선택과 미저장 초안만 Session Storage에 보관합니다. */
function persistStyleWorkspaceSession() {
  const sessionState = {};
  for (const field of ["currentProjectIdentifier", "screen", "libraryFilter", "libraryFavoriteFilters", "libraryLoraPresetFilters", "settingsDrafts", "projectDraftRevisions", "creationSettings", "pendingProjectSaves", "pendingProjectForks", "candidateGenerationRequests", "randomGenerationRequests", "artistBulkInput", "candidateSortOrder"]) {
    sessionState[field] = previewState[field];
  }
  try {
    sessionStorage.setItem(STYLE_WORKSPACE_SESSION_KEY, JSON.stringify(sessionState));
  } catch (error) {
    // 브라우저 임시 저장이 제한되어도 서버에 저장한 프로젝트는 유지합니다.
  }
}

/** 처음 시작하는 프로젝트는 실제 생성물이 없는 빈 Prompt 하나로 준비합니다. */
function newPersistentProjectSettings() {
  return createProjectSettingsPreview("", [{ identifier: newStyleClientIdentifier(), name: "Prompt 1", prompt: "", negativePrompt: "" }], previewState.globalSettings);
}

/** 실제 프로젝트만 불러오며 과거 목업 Session은 가져오지 않습니다. */
async function loadPersistentStyleWorkspace(restoreSession = false) {
  const workspace = await styleProjectApi("/api/style-workspace");
  persistentWorkspaceMetadata = workspace;
  previewState.projects = workspace.projects;
  previewState.globalSettings = workspace.globalSettings;
  if (restoreSession) {
    previewState.settingsDrafts = { global: null, projects: {} };
    previewState.projectDraftRevisions = {};
    previewState.creationSettings = null;
    previewState.currentProjectIdentifier = null;
    previewState.screen = "projects";
    try {
      const storedSession = JSON.parse(sessionStorage.getItem(STYLE_WORKSPACE_SESSION_KEY) || "null");
      if (storedSession && typeof storedSession === "object") {
        for (const field of ["currentProjectIdentifier", "screen", "libraryFilter", "libraryFavoriteFilters", "libraryLoraPresetFilters", "settingsDrafts", "projectDraftRevisions", "creationSettings", "pendingProjectSaves", "pendingProjectForks", "candidateGenerationRequests", "randomGenerationRequests", "artistBulkInput", "candidateSortOrder"]) {
          if (storedSession[field] !== undefined) previewState[field] = storedSession[field];
        }
      }
    } catch (error) {
      // 파손된 임시 초안은 서버 프로젝트의 조회를 막지 않습니다.
    }
  }
  previewState.settingsDrafts ??= { global: null, projects: {} };
  previewState.settingsDrafts.projects ??= {};
  previewState.projectDraftRevisions ??= {};
  previewState.pendingProjectSaves ??= {};
  previewState.pendingProjectForks ??= {};
  previewState.candidateGenerationRequests ??= {};
  previewState.randomGenerationRequests ??= {};
  if (!previewState.projects.some(project => project.identifier === previewState.currentProjectIdentifier)) {
    previewState.currentProjectIdentifier = previewState.projects[0]?.identifier || null;
  }
  ensureSettingsPreviewState();
  ensureRankingPreviewState();
  document.title = "스타일 구성 · Comfy Home";
  document.body.classList.add("persistent-workspace");
  document.querySelector(".phase-badge").dataset.screen = "project-settings";
  document.querySelector("#workspace-active-count").textContent = `프로젝트 ${workspace.projects.length}`;
  document.querySelector(".preview-notice").hidden = true;
  persistentWorkspaceLoaded = true;
  if (workspace.catalogNotice) showToast(workspace.catalogNotice);
}

/** 공통 설정 UI에 실제 등록 Workflow만 제공합니다. */
function persistentWorkflowOptions(selectedIdentifier) {
  return persistentWorkspaceMetadata.workflows.map(workflow => `<option value="${escapeMarkup(workflow.identifier)}" ${selectedIdentifier === workflow.identifier ? "selected" : ""}>${escapeMarkup(workflow.name)} · ${escapeMarkup(workflow.modelIdentifier)}</option>`).join("");
}

/** 프로젝트가 없을 때도 목록과 글로벌 설정으로 이동할 수 있게 합니다. */
function renderEmptyPersistentNavigation() {
  document.querySelector('.phase-badge').dataset.screen = 'global-settings';
  document.querySelector("#project-context").innerHTML = '<span>현재 프로젝트 없음</span><span>새 프로젝트를 만들어 시작하세요.</span>';
  document.querySelector("#preview-sidebar").innerHTML = '<button data-action="navigate" data-screen="projects">▦　모든 프로젝트</button><button data-action="navigate" data-screen="global-settings">◎　글로벌 설정</button>';
  document.querySelector("#preview-mobile-navigation").innerHTML = '<button class="active" data-action="navigate" data-screen="projects"><b>▦</b>프로젝트</button><button disabled><b>◇</b>그림체</button><button disabled><b>↔</b>선별</button><button disabled><b>⟳</b>진화</button>';
}

/** 전체 프로젝트의 조건·현재 선택을 표시하고 카드에서 작업 대상을 명시적으로 고릅니다. */
function renderPersistentProjects() {
  const projectCards = [];
  for (const project of previewState.projects) {
    const isCurrentProject = project.identifier === previewState.currentProjectIdentifier;
    const workflow = persistentWorkspaceMetadata.workflows.find(item => item.identifier === project.settings.pipelineIdentifier);
    const modelName = workflow?.modelIdentifier || project.settings.pipelineIdentifier;
    const selectedIndicator = isCurrentProject ? '<span class="project-current-indicator">현재 프로젝트</span>' : '';
    projectCards.push(`<article class="panel project-card ${isCurrentProject ? 'current-project' : ''}" data-project-card="${project.identifier}" ${isCurrentProject ? 'aria-current="true"' : ''}><div class="project-card-body">${selectedIndicator}<h2>${escapeMarkup(project.name)}</h2>${project.settings.purpose ? `<p class="muted">${escapeMarkup(project.settings.purpose)}</p>` : ''}<p>${project.promptCases.map(promptCase => escapeMarkup(promptCase.name)).join(" · ")}</p><div class="card-meta"><span>${escapeMarkup(modelName)}</span><span>${project.generation ?? 0}세대 · 조합 ${project.candidateCount}개</span><span>${project.promptCases.length}개 Prompt</span></div>${styleProjectForkSourceMarkup(project)}<div class="project-card-actions"><button class="${isCurrentProject ? 'primary' : ''}" data-action="open-project" data-project="${project.identifier}">${isCurrentProject ? '이어서 작업하기' : '이 프로젝트 선택'} →</button><button class="project-fork-button" data-project-fork="${project.identifier}">Fork</button></div></div></article>`);
  }
  return `<div class="page-heading"><div><h1>프로젝트</h1><span class="project-list-count">${previewState.projects.length}개 프로젝트</span></div><button class="primary" data-action="navigate" data-screen="create">＋ 새 프로젝트</button></div><div class="toolbar"><button data-persistent-action="reload">서버에서 다시 불러오기</button></div>${projectCards.length ? `<div class="project-grid">${projectCards.join('')}</div>` : '<section class="panel empty-state"><h2>아직 프로젝트가 없습니다</h2><p>프로젝트를 만들면 Prompt와 설정을 다른 기기에서도 다시 열 수 있습니다.</p><button class="primary" data-action="navigate" data-screen="create">새 프로젝트 만들기</button></section>'}`;
}

/** 생성하지 않고 여러 Prompt와 실제 Workflow 옵션으로 Fresh 프로젝트를 저장합니다. */
function renderPersistentProjectCreation() {
  const draft = settingsPreviewDraft("project", "new-project");
  ensureProjectCatalogPolicies(draft);
  return `<div class="page-heading"><div><p class="eyebrow">NEW PROJECT</p><h1>어떤 그림체를 찾을까요?</h1><p class="muted">새로 시작 · 조합 0개 · 투표 0회 · 0세대</p></div></div><form id="persistent-project-form" data-settings-project="new-project" class="form-layout settings-form"><section class="panel"><label for="settings-project-name">프로젝트 이름</label><input id="settings-project-name" data-settings-field="name" required maxlength="80" value="${escapeMarkup(draft.name)}" /><label for="settings-project-purpose">찾고 싶은 그림체 · 메모</label><textarea id="settings-project-purpose" data-settings-field="purpose" maxlength="2000">${escapeMarkup(draft.purpose)}</textarea></section><section class="panel"><h2>함께 비교할 Prompt</h2>${draft.promptCases.map(projectSettingsPromptMarkup).join("")}<button type="button" data-settings-action="add-prompt">＋ Prompt 추가</button><label for="settings-negative-prompt">공통 Negative Prompt</label><textarea id="settings-negative-prompt" data-settings-field="negativePrompt" maxlength="3000">${escapeMarkup(draft.negativePrompt)}</textarea></section>${projectWorkflowOptionsMarkup(draft)}${componentCountSettingsMarkup(draft, "project")}<section class="panel"><h2>사용할 성분</h2><p class="form-note">등록된 작가와 설치 LoRA 중 사용할 성분을 고릅니다. 생성 계획 확인 시 ComfyUI의 파일·필수 Node를 검사합니다.</p>${projectComponentGroupMarkup("작가", "작가 태그", "artist")}${projectComponentGroupMarkup("LoRA", "LoRA", "lora")}</section><p id="settings-form-error" class="error" role="alert"></p><div class="form-actions"><span>프로젝트 저장은 이미지 생성을 실행하지 않습니다.</span><button type="button" data-action="navigate" data-screen="projects">목록으로</button><button class="primary" type="submit">프로젝트 저장</button></div></form>`;
}

/** 프로젝트가 소유한 실제 조합을 카드 목록으로 조회합니다. */
function renderPersistentStyleLibrary() {
  const project = currentProject();
  if (previewState.blind) return rankingBlindNoticeMarkup();
  return `<div class="page-heading"><h1>그림체</h1><button class="primary" data-generation-action="open-generator">＋ 조합 생성</button></div><div id="style-prompt-regeneration-controls">${stylePromptRegenerationMarkup(project, currentStyleGenerationState())}</div><p id="style-generation-error" class="error" role="alert">${escapeMarkup(currentStyleGenerationState().error)}</p><div class="toolbar"><label for="style-library-lifecycle">표시</label><select id="style-library-lifecycle" ${styleLibrarySavedOnly() ? "disabled" : ""}>${[["active", "활성·진화 중"], ["retired", "퇴역"], ["cancelled", "취소"], ["all", "전체"]].map(([value, label]) => `<option value="${value}" ${(styleLibrarySavedOnly() ? "all" : currentStyleGenerationState().libraryLifecycle || "active") === value ? "selected" : ""}>${label}</option>`).join("")}</select><label for="candidate-sort-order">정렬</label><select id="candidate-sort-order">${[["elo", "Elo 높은 순"], ["matches", "평가 횟수 많은 순"], ["creation", "등록 순"]].map(([value, label]) => `<option value="${value}" ${previewState.candidateSortOrder === value ? "selected" : ""}>${label}</option>`).join("")}</select>${styleLibraryFavoritesFilterMarkup(currentStyleGenerationState().results)}${styleLibraryLoraPresetsFilterMarkup(currentStyleGenerationState().results)}</div><div id="style-render-results">${initialStyleResultsMarkup(currentStyleGenerationState().results)}</div>`;
}

/** 실제 설정은 Prompt부터 바로 편집하고 기존 공통 Workflow·성분 입력을 재사용합니다. */
function renderPersistentProjectSettings() {
  const project = currentProject();
  const draft = settingsPreviewDraft("project");
  return `${settingsNavigationMarkup("project")}<div class="page-heading"><h1>프로젝트 설정</h1></div><form id="project-settings-form" data-settings-project="${project.identifier}" class="form-layout settings-form">
    <section class="panel"><h2>Prompt</h2>${draft.promptCases.map(projectSettingsPromptMarkup).join("")}<button type="button" data-settings-action="add-prompt">＋ Prompt 추가</button><label for="settings-negative-prompt">공통 Negative Prompt</label><textarea id="settings-negative-prompt" maxlength="3000" data-settings-field="negativePrompt">${escapeMarkup(draft.negativePrompt)}</textarea></section>
    ${projectWorkflowOptionsMarkup(draft)}${componentCountSettingsMarkup(draft, "project")}
    <section class="panel"><div class="settings-section-heading"><h2>작가 · LoRA</h2><div class="form-actions"><button type="button" data-component-statistics-refresh>통계 새로고침</button><button type="button" data-settings-action="preview-defaults">기본값 가져오기</button></div></div><p id="style-component-statistics-status" role="status"></p>${projectComponentGroupMarkup("작가", "작가 태그", "artist")}${projectComponentGroupMarkup("LoRA", "LoRA", "lora")}</section>
    <section class="panel"><h2>프로젝트</h2><label for="settings-project-name">이름</label><input id="settings-project-name" required maxlength="80" value="${escapeMarkup(draft.name)}" data-settings-field="name" /><label for="settings-project-purpose">메모</label><textarea id="settings-project-purpose" maxlength="2000" data-settings-field="purpose">${escapeMarkup(draft.purpose)}</textarea></section>
    ${settingsFormActionsMarkup("project")}</form>`;
}

/** 현재 실제 연결 범위와 후속 생성·평가 단계를 구분합니다. */
function renderPersistentScope() {
  return '<div class="page-heading"><h1>현재 연결 범위</h1></div><section class="panel"><h2>저장·이미지 생성</h2><p>프로젝트 설정과 여러 Prompt를 저장하고, 허용한 성분·개수·STR로 Random 초기 조합을 뽑고 장수 확인 후 실제 이미지를 생성합니다. 같은 조합은 모든 Prompt에서 유지합니다.</p><h2>작업·출력 관리</h2><p>스타일 전용 분류·출력 루트·세대 메모를 사용합니다. 일반 목록에서는 선택해서 표시하고, 작업·이미지의 임의 이동은 막습니다. 프로젝트 이름을 바꾸면 분류와 실제 폴더도 함께 변경합니다.</p><h2>선별·순위</h2><p>여러 Prompt를 함께 보고 조합 단위로 투표합니다. Elo·Skip·최근 30개 선택의 Undo를 저장하며 그림체에서 순위와 전적을 확인합니다.</p><h2>다음 세대</h2><p>10개 이상 평가한 조합의 상위 30%를 부모로 고정하고 Mutate·Crossover·Random 자녀를 생성합니다. 부모 점수를 유지하며 자녀를 선별하고 세대를 확정하거나 취소합니다. 퇴역·취소 조합의 이미지도 보존합니다.</p><h2>프로젝트 Fork</h2><p>각 세대의 마지막 저장 설정으로 0세대 프로젝트를 만듭니다. 성분 선호도·승패도 선택해서 가져옵니다. 이미지·조합·Elo·생성 작업은 새 프로젝트에서 시작합니다.</p><h2>후속 단계</h2><p>공통 성분 잠금·북마크 보호·계보별 부모 기회·세대 복원·Prompt 재시험은 아직 연결하지 않았습니다.</p><a href="/style-preview">예시 목업 별도로 열기</a></section>';
}

/** Case ID를 유지하고 화면 전용 필드가 실제 평가 조건에 들어가지 않게 합니다. */
function persistentProjectPayload(settings) {
  const copiedSettings = structuredClone(settings);
  copiedSettings.promptCases = settings.promptCases.map(promptCase => {
    promptCase.identifier ??= newStyleClientIdentifier();
    return { identifier: promptCase.identifier, name: promptCase.name, prompt: promptCase.prompt, negativePrompt: promptCase.negativePrompt || "" };
  });
  return copiedSettings;
}

/** 저장 중 같은 화면에서 중복 제출하거나 다른 프로젝트로 바꾸지 않게 합니다. */
function setPersistentSettingsBusy(busy, form) {
  persistentSettingsBusy = busy;
  document.querySelector("#workspace-refresh-button").disabled = busy;
  form.inert = busy;
  for (const selector of ["#project-context", "#preview-sidebar", "#preview-mobile-navigation"]) {
    document.querySelector(selector).inert = busy;
  }
  const submitButton = form.querySelector('button[type="submit"]');
  if (submitButton) submitButton.disabled = busy;
}

/** 저장 결과와 미저장 상태를 항상 같은 위치에서 보여 줍니다. */
function updatePersistentSettingsStatus(message, status = "dirty") {
  const indicator = document.querySelector("#style-settings-save-status");
  if (!indicator) return;
  indicator.textContent = message;
  indicator.dataset.status = status;
}

/** 서버가 확인한 프로젝트만 화면에 반영하며 실패하면 초안과 요청 ID를 유지합니다. */
async function savePersistentStyleSettings(form) {
  if (persistentSettingsBusy) return;
  const isGlobal = form.id === "global-settings-form";
  const isCreation = form.id === "persistent-project-form";
  const projectIdentifier = isCreation ? "new-project" : form.dataset.settingsProject;
  const draft = settingsPreviewDraft(isGlobal ? "global" : "project", projectIdentifier);
  const validationMessage = validateSettingsPreview(isGlobal ? "global" : "project", draft);
  if (validationMessage) {
    document.querySelector("#settings-form-error").textContent = validationMessage;
    updatePersistentSettingsStatus("저장하지 못했습니다", "error");
    showToast(validationMessage);
    return;
  }
  setPersistentSettingsBusy(true, form);
  updatePersistentSettingsStatus("저장 중…", "saving");
  try {
    if (isGlobal) {
      previewState.globalSettings = await styleProjectApi("/api/style-settings", { method: "PUT", body: JSON.stringify(draft) });
      previewState.settingsDrafts.global = null;
    } else {
      const settings = persistentProjectPayload(draft);
      const settingsText = JSON.stringify(settings);
      let pending = previewState.pendingProjectSaves[projectIdentifier];
      if (!pending || pending.settingsText !== settingsText) {
        pending = { operationIdentifier: newStyleClientIdentifier(), settingsText };
        previewState.pendingProjectSaves[projectIdentifier] = pending;
      }
      persistStyleWorkspaceSession();
      const payload = { settings, operationIdentifier: pending.operationIdentifier, expectedRevision: isCreation ? null : previewState.projectDraftRevisions[projectIdentifier] };
      const savedProject = await styleProjectApi(isCreation ? "/api/style-projects" : `/api/style-projects/${projectIdentifier}`, { method: isCreation ? "POST" : "PUT", body: JSON.stringify(payload) });
      const projectIndex = previewState.projects.findIndex(project => project.identifier === savedProject.identifier);
      if (projectIndex === -1) previewState.projects.unshift(savedProject);
      else previewState.projects[projectIndex] = savedProject;
      const generationState = currentStyleGenerationState(savedProject.identifier);
      generationState.options = null;
      generationState.pendingPromptRegeneration = null;
      generationState.comparisonPlanIdentifier = null;
      delete previewState.settingsDrafts.projects[projectIdentifier];
      delete previewState.projectDraftRevisions[projectIdentifier];
      delete previewState.pendingProjectSaves[projectIdentifier];
      if (isCreation) {
        previewState.currentProjectIdentifier = savedProject.identifier;
        previewState.creationSettings = null;
        previewState.screen = "project-settings";
        window.history.replaceState(null, "", "#project-settings");
      }
    }
    renderPreview(false);
    updatePersistentSettingsStatus("저장됨", "saved");
    showToast("저장했습니다.");
  } catch (error) {
    if (form.isConnected) document.querySelector("#settings-form-error").textContent = error.message;
    updatePersistentSettingsStatus("저장 실패 · 입력 유지", "error");
    const reloadButton = form.querySelector("[data-persistent-action=reload]");
    if (reloadButton && error.status === 409) reloadButton.hidden = false;
    showToast(error.message);
  } finally {
    setPersistentSettingsBusy(false, form);
    persistStyleWorkspaceSession();
  }
}

/** 작가만 즉시 등록하고 다른 글로벌 설정 초안은 그대로 둡니다. */
async function registerPersistentArtists() {
  if (persistentSettingsBusy) return;
  const analysis = analyzeArtistBulkInput(previewState.artistBulkInput);
  if (!analysis.additions.length) return;
  const form = document.querySelector("#global-settings-form");
  setPersistentSettingsBusy(true, form);
  try {
    const updatedSettings = structuredClone(previewState.globalSettings);
    updatedSettings.additionalArtists.push(...analysis.additions);
    for (const artist of analysis.additions) updatedSettings.availableComponents[artist.identifier] = true;
    const savedSettings = await styleProjectApi("/api/style-settings", { method: "PUT", body: JSON.stringify(updatedSettings) });
    previewState.globalSettings = savedSettings;
    if (previewState.settingsDrafts.global) {
      Object.assign(previewState.settingsDrafts.global, { revision: savedSettings.revision, additionalArtists: structuredClone(savedSettings.additionalArtists) });
      for (const artist of analysis.additions) previewState.settingsDrafts.global.availableComponents[artist.identifier] = true;
    }
    previewState.artistBulkInput = analysis.rows.filter(row => row.invalid).map(row => row.rawLine).join("\n");
    previewState.artistBulkRegistrationResult = `작가 ${analysis.additions.length}명을 서버에 등록했습니다.`;
    ensureSettingsPreviewState();
    renderPreview(false);
    showToast(previewState.artistBulkRegistrationResult);
  } catch (error) {
    document.querySelector("#settings-form-error").textContent = error.message;
  } finally {
    setPersistentSettingsBusy(false, form);
    persistStyleWorkspaceSession();
  }
}

/** 명시적 다시 불러오기는 다른 탭의 변경을 읽되 현재 초안을 덮어쓰지 않습니다. */
async function handlePersistentWorkspaceAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest('[data-persistent-action="reload"]');
  if (!button || persistentSettingsBusy) return;
  button.disabled = true;
  try {
    await loadPersistentStyleWorkspace();
    renderPreview(false);
    showToast("서버의 프로젝트를 다시 불러왔습니다. 미저장 초안은 유지됩니다.");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

/** 새 프로젝트 Form만 실제 저장으로 전달합니다. */
function submitPersistentProject(event) {
  if (!PERSISTENT_STYLE_WORKSPACE || event.target.id !== "persistent-project-form") return;
  event.preventDefault();
  savePersistentStyleSettings(event.target);
}

document.addEventListener("click", handlePersistentWorkspaceAction);
document.addEventListener("submit", submitPersistentProject);
