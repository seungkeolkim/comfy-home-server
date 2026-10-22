"use strict";

const ANIMA_RESOLUTIONS = {
  "16:9": [[1024, 576], [1280, 720], [1536, 864]],
  "3:2": [[864, 576], [1152, 768], [1536, 1024]],
  "4:3": [[1024, 768], [1280, 960], [1536, 1152]],
  "1:1": [[768, 768], [1024, 1024], [1280, 1280]],
  "3:4": [[768, 1024], [960, 1280], [1152, 1536]],
  "2:3": [[576, 864], [768, 1152], [1024, 1536]],
  "9:16": [[576, 1024], [720, 1280], [864, 1536]],
};
const TAG_NAME_COLLATOR = new Intl.Collator("ko-KR", { numeric: true, sensitivity: "base" });
const KOREAN_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
const NAVIGATION_VIEW_NAMES = ["generate", "jobs", "outputs", "prompts", "tags", "lora-presets"];
const RESOURCE_POLL_INTERVAL_MILLISECONDS = 2000;
const videoPreviewState = {
  revision: 0, outputId: null, timer: null, controller: null,
  opener: null, lastStatus: null, attachedIdentifier: null,
  pointerStartedOutside: false,
};
const imagePreviewState = {
  outputId: null, opener: null, pointerStartedOutside: false,
};
const outputPreviewNavigationState = {
  revision: 0, controller: null, outputId: null, currentFile: null, filter: null, opener: null,
  previous: null, next: null, loading: false, error: "", showOriginalFiles: false,
};
const jobDescriptionEditorState = {
  jobIdentifier: null, revision: 0, openingElement: null,
};
const jobHistoryFolderState = {
  folders: [], totalCount: 0, unassignedCount: 0, loaded: false,
  collapsedFolderIds: new Set(), renderSignature: null,
  editingFolderId: null, movingJobIds: [], busy: false,
  dialogRevision: 0,
};
const tagManagerState = {
  selectedGroupId: null, groupSearch: "", referenceFilter: "", entrySearch: "",
  mobilePane: "groups", groupScrollPosition: 0, entryScrollPositions: new Map(),
  editorKind: null, editorFingerprint: null, editorOpener: null, editorRevision: 0,
  editorBusy: false,
  listHistoryIndex: null, editorParentHistoryIndex: null,
};
const promptEditorState = {
  selectedPresetId: null, sourceVersion: null, sourceBody: { prompt: "", negative: "" },
  baselineFingerprint: null, workflow: "anima", search: "", workflowFilter: "",
  activeTab: "edit", mobilePane: "list", listScrollPosition: 0,
  versions: [], versionsPresetId: null, previewVersion: null,
  versionsLoading: false, versionsError: "", versionsRevision: 0,
  saving: false, editorRevision: 0, navigationLoading: false,
  contextId: null, listHistoryIndex: null,
};
const managerHistoryState = {
  restoring: false, traversalPending: false, rejectedEntry: null,
};

const applicationState = {
  presets: [],
  currentPresetId: null,
  currentPresetVersion: null,
  currentBody: { prompt: "", negative: "" },
  availableLoras: [],
  loraProfiles: [],
  loraPresets: [],
  currentLoraPresetId: null,
  loraEditorPresetId: null,
  loraEditorEntries: [],
  loraCatalogAvailable: false,
  selectedLoras: [],
  minimaxInputImages: [],
  minimaxInputCandidates: [],
  minimaxInputDirectory: null,
  minimaxInputJob: null,
  minimaxInputLoading: false,
  minimaxSelectionRevision: 0,
  minimaxResolutionManual: false,
  tagGroups: [],
  tagEntries: [],
  selectedTagIds: new Set(),
  expandedTagGroupIds: null,
  editingTagGroupId: null,
  editingTagEntryId: null,
  currentView: "generate",
  viewScrollPositions: new Map(),
  navigationEntryId: null,
  navigationEntryIndex: 0,
  navigationEntrySequence: 0,
  navigationRevision: 0,
  pendingNavigationScroll: null,
  navigationScrollFrame: null,
  outputFilter: null,
  outputsPage: 1,
  outputsLoadRevision: 0,
  outputsRenderSignature: null,
  visibleOutputs: [],
  outputSelectionMode: false,
  outputSelectionScope: null,
  selectedOutputIds: new Set(),
  selectableOutputIds: new Set(),
  deletableOutputIds: new Set(),
  selectingEveryOutput: false,
  deletingSelectedOutputs: false,
  deletingOutputId: null,
  movingOutputPath: null,
  movingSelectedOutputs: false,
  movingJobId: null,
  jobsPage: 1,
  jobFilterId: null,
  jobFolderId: "",
  jobSearch: "",
  selectableJobIds: new Set(),
  jobsLoadRevision: 0,
  visibleJobs: [],
  jobsLoadPromise: null,
  jobsReloadRequested: false,
  jobsLoading: false,
  jobsLoadedOnce: false,
  jobsMatchedCount: 0,
  jobsLoadError: null,
  jobsRenderSignature: null,
  jobDetails: new Map(),
  cancellingJobIds: new Set(),
  jobsSelectionScope: null,
  jobSelectionMode: false,
  selectedJobIds: new Set(),
  expandedJobPromptIds: new Set(),
  expandedRequestPromptIds: new Set(),
  deletableJobIds: new Set(),
  selectingEveryJob: false,
  updatingJobProtectionId: null,
  updatingJobDescriptionId: null,
  deletingSelectedJobs: false,
  restoringJobId: null,
  noticeHideTimer: null,
  pollingTimer: null,
  resourcePollingTimer: null,
  resourceLoadPromise: null,
  resourceSessionRevision: 0,
};

const outputFolderPickerState = {
  selectionMode: "move",
  images: [],
  selectedImageIds: new Set(),
  resolveSelection: null,
  path: "",
  parentPath: null,
  directories: [],
  loading: false,
  creating: false,
  loaded: false,
  error: "",
  loadRevision: 0,
  sessionRevision: 0,
  openingElement: null,
};

const jobInputPickerState = {
  revision: 0, resolveSelection: null, openingElement: null,
  page: 1, totalPages: 1, jobs: [], jobIdentifier: null, job: null,
  images: [], selectedImageIds: new Set(), loading: false, error: "",
};

/** 식별자로 HTML 요소를 가져옵니다. */
function element(identifier) {
  return document.getElementById(identifier);
}

/** 사용자 입력을 HTML 문자열에 안전하게 넣습니다. */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 저장된 시각을 단말 시간대와 무관한 KST로 표시하고 시각이 없는 값은 그대로 둡니다. */
function formatKoreanTimestamp(timestamp) {
  if (typeof timestamp !== "string" || !timestamp.trim()) return "—";
  const timestampText = timestamp.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(timestampText)) return timestampText;
  const timestampWithoutTimezone = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
  const normalizedTimestamp = timestampWithoutTimezone.test(timestampText)
    ? `${timestampText.replace(" ", "T")}Z` : timestampText;
  const timestampDate = new Date(normalizedTimestamp);
  if (Number.isNaN(timestampDate.getTime())) return timestampText;
  const dateTimeParts = Object.fromEntries(KOREAN_DATE_TIME_FORMATTER.formatToParts(timestampDate)
    .map(part => [part.type, part.value]));
  return `${dateTimeParts.year}-${dateTimeParts.month}-${dateTimeParts.day} ${dateTimeParts.hour}:${dateTimeParts.minute}:${dateTimeParts.second} KST`;
}

/** 표시 그룹을 한국어 이름순으로 정렬하고 같은 이름은 ID로 순서를 고정합니다. */
function sortedTagGroups() {
  return [...applicationState.tagGroups].sort((leftGroup, rightGroup) => {
    const nameOrder = TAG_NAME_COLLATOR.compare(leftGroup.name, rightGroup.name);
    return nameOrder || leftGroup.group_id.localeCompare(rightGroup.group_id);
  });
}

/** 한 그룹의 태그 항목을 화면 이름순으로 정렬합니다. */
function sortedTagEntriesInGroup(groupId) {
  return applicationState.tagEntries
    .filter((entry) => entry.group_id === groupId)
    .sort((leftEntry, rightEntry) => {
      const nameOrder = TAG_NAME_COLLATOR.compare(leftEntry.name, rightEntry.name);
      if (nameOrder) return nameOrder;
      return leftEntry.tag_id.localeCompare(rightEntry.tag_id);
    });
}

/** 너비와 높이를 약분한 비율과 해상도 문자열로 만듭니다. */
function formatDimensions(width, height) {
  const normalizedWidth = Number(width);
  const normalizedHeight = Number(height);
  if (!Number.isInteger(normalizedWidth) || !Number.isInteger(normalizedHeight) ||
      normalizedWidth <= 0 || normalizedHeight <= 0) {
    return { ratio: "—", resolution: "—" };
  }
  let dividend = normalizedWidth;
  let divisor = normalizedHeight;
  while (divisor !== 0) {
    const remainder = dividend % divisor;
    dividend = divisor;
    divisor = remainder;
  }
  return {
    ratio: `${normalizedWidth / dividend}:${normalizedHeight / dividend}`,
    resolution: `${normalizedWidth} × ${normalizedHeight}`,
  };
}

/** 인증 cookie를 포함해 JSON API를 호출합니다. */
async function apiRequest(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error("로그인이 필요합니다.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errorDetail = Array.isArray(data.detail)
      ? data.detail.map((error) => error.msg).join(" · ")
      : data.detail;
    const requestError = new Error(errorDetail || `요청 실패: HTTP ${response.status}`);
    requestError.status = response.status;
    throw requestError;
  }
  return data;
}

/** 화면에 고정된 알림을 잠시 표시합니다. */
function showNotice(message, isError = false, action = null) {
  const notice = element("video-preview-dialog").open ? element("video-preview-notice")
    : element("image-preview-dialog").open ? element("image-preview-notice") : element("notice");
  notice.textContent = message;
  if (action) {
    const actionButton = document.createElement("button");
    actionButton.type = "button";
    actionButton.className = "button subtle";
    actionButton.textContent = action.label;
    actionButton.addEventListener("click", action.run, { once: true });
    notice.append(" ", actionButton);
  }
  notice.classList.toggle("error", isError);
  notice.classList.remove("hidden");
  window.clearTimeout(applicationState.noticeHideTimer);
  applicationState.noticeHideTimer = window.setTimeout(() => notice.classList.add("hidden"), 6500);
}

/** 로그인 화면만 표시합니다. */
function showLogin() {
  promptEditorState.editorRevision += 1;
  promptEditorState.versionsRevision += 1;
  promptEditorState.saving = false;
  promptEditorState.versionsLoading = false;
  renderPromptEditorStatus();
  closeTagEditor({ discard: true, restoreFocus: false, force: true });
  window.clearInterval(applicationState.resourcePollingTimer);
  applicationState.resourcePollingTimer = null;
  applicationState.resourceSessionRevision += 1;
  closeJobHistoryFolderDialogs();
  closeJobDescriptionEditor(false);
  closeVideoPreview(false);
  closeImagePreview(false);
  finishJobInputSelection(null, true);
  finishOutputFolderSelection(null, true);
  window.clearTimeout(applicationState.pollingTimer);
  applicationState.pollingTimer = null;
  element("application").classList.add("hidden");
  element("login-screen").classList.remove("hidden");
}

/** 앱 화면을 표시하고 필요한 목록을 읽습니다. */
async function showApplication() {
  element("login-screen").classList.add("hidden");
  element("application").classList.remove("hidden");
  if (!applicationState.resourcePollingTimer) {
    applicationState.resourcePollingTimer = window.setInterval(loadSystemResources, RESOURCE_POLL_INTERVAL_MILLISECONDS);
  }
  await Promise.allSettled([
    loadSystemResources(),
    loadPresets(),
    loadTags(),
    loadLoras(),
    loadLoraPresets(),
    loadJobs(),
    applicationState.currentView === "outputs" ? loadOutputs() : Promise.resolve(),
    loadStatus(),
  ]);
  saveCurrentNavigationEntry();
  if (!applicationState.pollingTimer) {
    scheduleJobsPolling();
  }
}

/** 이전 조회가 끝난 뒤 현재 탭에 필요한 다음 상태 조회를 예약합니다. */
function scheduleJobsPolling() {
  window.clearTimeout(applicationState.pollingTimer);
  applicationState.pollingTimer = window.setTimeout(async () => {
    if (element("application").classList.contains("hidden")) return;
    try {
      if (applicationState.currentView === "jobs") {
        await loadJobs({ refreshAfterCurrentRequest: false });
      } else {
        const activity = await apiRequest("/api/jobs/activity");
        element("active-count").textContent = `작업 ${activity.active_count}`;
      }
    } catch (error) {
      if (applicationState.currentView === "jobs") showNotice(error.message, true);
    } finally {
      if (!element("application").classList.contains("hidden")) scheduleJobsPolling();
    }
  }, applicationState.currentView === "jobs" ? 1000 : 5000);
}

/** Prompt의 탐색 위치만 기록하며 편집 중인 본문은 History에 넣지 않습니다. */
function capturePromptNavigation() {
  return {
    pane: promptEditorState.mobilePane, presetId: promptEditorState.selectedPresetId,
    sourceVersion: promptEditorState.sourceVersion, contextId: promptEditorState.contextId,
    workflow: promptEditorState.workflow, tab: promptEditorState.activeTab,
    previewVersion: promptEditorState.previewVersion,
    search: promptEditorState.search, workflowFilter: promptEditorState.workflowFilter,
    listScrollTop: element("preset-list").scrollTop, listHistoryIndex: promptEditorState.listHistoryIndex,
  };
}

/** 태그 관리의 그룹·Dialog·검색 위치만 기록하고 편집 입력은 제외합니다. */
function captureTagNavigation() {
  const editorKind = tagManagerState.editorKind;
  return {
    pane: tagManagerState.mobilePane, groupId: tagManagerState.selectedGroupId,
    groupSearch: tagManagerState.groupSearch, referenceFilter: tagManagerState.referenceFilter,
    entrySearch: tagManagerState.entrySearch,
    groupScrollTop: element("tag-group-list").scrollTop, entryScrollTop: element("tag-entry-list").scrollTop,
    editorKind, editorId: editorKind === "group" ? applicationState.editingTagGroupId
      : editorKind === "entry" ? applicationState.editingTagEntryId : null,
    dialogScrollTop: editorKind ? element(`tag-${editorKind}-dialog`).scrollTop : 0,
    listHistoryIndex: tagManagerState.listHistoryIndex, editorParentHistoryIndex: tagManagerState.editorParentHistoryIndex,
  };
}

/** 현재 화면의 이동 조건과 스크롤만 기록하며 입력값이나 목록 데이터는 복사하지 않습니다. */
function captureNavigationState() {
  const viewName = applicationState.currentView;
  const openJobIds = [];
  if (viewName === "jobs") {
    for (const details of element("jobs-list").querySelectorAll("details[open]")) {
      openJobIds.push(details.dataset.jobDetails);
    }
  }
  return {
    version: 1,
    entryId: applicationState.navigationEntryId,
    entryIndex: applicationState.navigationEntryIndex,
    viewName,
    pageNumber: viewName === "jobs" ? applicationState.jobsPage : applicationState.outputsPage,
    jobFilterId: viewName === "jobs" ? applicationState.jobFilterId : null,
    jobFolderId: viewName === "jobs" ? applicationState.jobFolderId : "",
    jobSearch: viewName === "jobs" ? applicationState.jobSearch : "",
    outputFilter: viewName === "outputs" ? applicationState.outputFilter : null,
    scrollPosition: window.scrollY,
    openJobIds,
    promptNavigation: viewName === "prompts" ? capturePromptNavigation() : null,
    tagNavigation: viewName === "tags" ? captureTagNavigation() : null,
  };
}

/** 이 앱이 저장한 유효한 History 항목인지 확인합니다. */
function isNavigationStateValid(navigationState) {
  if (!navigationState || navigationState.version !== 1 ||
      typeof navigationState.entryId !== "string" || !NAVIGATION_VIEW_NAMES.includes(navigationState.viewName)) return false;
  if (navigationState.entryIndex !== undefined && !Number.isSafeInteger(navigationState.entryIndex)) return false;
  if (!isManagerNavigationValid(navigationState)) return false;
  if (!Number.isSafeInteger(navigationState.pageNumber) || navigationState.pageNumber < 1 ||
      !Number.isFinite(navigationState.scrollPosition) || navigationState.scrollPosition < 0) return false;
  if (navigationState.jobFilterId !== null && typeof navigationState.jobFilterId !== "string") return false;
  if (navigationState.jobFolderId !== undefined && typeof navigationState.jobFolderId !== "string") return false;
  if (navigationState.jobSearch !== undefined && typeof navigationState.jobSearch !== "string") return false;
  const outputFilter = navigationState.outputFilter;
  if (outputFilter !== null && (!outputFilter || !["job", "request"].includes(outputFilter.type) ||
      typeof outputFilter.id !== "string")) return false;
  return Array.isArray(navigationState.openJobIds) &&
    navigationState.openJobIds.every(jobIdentifier => typeof jobIdentifier === "string");
}

/** 새 브라우저 탭에서도 열 수 있도록 조회 조건을 URL로 만듭니다. */
function navigationUrl(navigationState) {
  const query = new URLSearchParams({ view: navigationState.viewName });
  if (["jobs", "outputs"].includes(navigationState.viewName)) {
    query.set("page", String(navigationState.pageNumber));
  }
  if (navigationState.viewName === "jobs" && navigationState.jobFilterId) {
    query.set("job_id", navigationState.jobFilterId);
  }
  if (navigationState.viewName === "jobs") {
    if (navigationState.jobFolderId) query.set("folder_id", navigationState.jobFolderId);
    if (navigationState.jobSearch) query.set("search", navigationState.jobSearch);
  }
  if (navigationState.viewName === "outputs" && navigationState.outputFilter) {
    const outputFilter = navigationState.outputFilter;
    query.set(outputFilter.type === "job" ? "job_id" : "request_id", outputFilter.id);
  }
  return `${window.location.pathname}?${query}`;
}

/** URL에서 조회 조건만 읽고 잘못된 화면이나 페이지는 기본값으로 보정합니다. */
function navigationStateFromUrl(url) {
  const query = new URL(url, window.location.href).searchParams;
  const requestedView = query.get("view");
  const viewName = NAVIGATION_VIEW_NAMES.includes(requestedView) ? requestedView : "generate";
  const requestedPage = Number(query.get("page"));
  const pageNumber = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const jobIdentifier = query.get("job_id") || null;
  const requestIdentifier = query.get("request_id") || null;
  let outputFilter = null;
  if (viewName === "outputs") {
    if (jobIdentifier) outputFilter = { type: "job", id: jobIdentifier };
    else if (requestIdentifier) outputFilter = { type: "request", id: requestIdentifier };
  }
  return { viewName, pageNumber, jobFilterId: viewName === "jobs" ? jobIdentifier : null, outputFilter,
    jobFolderId: viewName === "jobs" ? (query.get("folder_id") || "") : "",
    jobSearch: viewName === "jobs" ? (query.get("search") || "") : "" };
}

/** 탭 링크의 새 탭 목적지를 해당 탭의 마지막 페이지와 필터로 갱신합니다. */
function updateNavigationLinks() {
  for (const navigationLink of document.querySelectorAll("a[data-view]")) {
    const viewName = navigationLink.dataset.view;
    navigationLink.href = navigationUrl({
      viewName,
      pageNumber: viewName === "jobs" ? applicationState.jobsPage : applicationState.outputsPage,
      jobFilterId: applicationState.jobFilterId,
      jobFolderId: applicationState.jobFolderId,
      jobSearch: applicationState.jobSearch,
      outputFilter: applicationState.outputFilter,
    });
  }
}

/** 일반 클릭은 앱 안에서 이동하고 가운데 버튼·수정키 클릭은 브라우저에 맡깁니다. */
function handleNavigationLinkClick(event) {
  const navigationLink = event.target.closest("a[data-navigation]");
  if (!navigationLink) return;
  if (navigationLink.getAttribute("aria-disabled") === "true" ||
      (navigationLink.hasAttribute("data-jobs-page") && jobSelectionIsBusy()) ||
      (navigationLink.hasAttribute("data-outputs-page") && outputSelectionIsBusy())) {
    event.preventDefault();
    return;
  }
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const tabView = navigationLink.dataset.view || navigationLink.dataset.navigationTab;
  if (tabView) {
    switchView(tabView);
    return;
  }
  const navigationState = navigationStateFromUrl(navigationLink.href);
  switchView(navigationState.viewName, { ...navigationState, resetScroll: true });
}

/** 같은 화면의 중복 History를 막기 위해 탭과 조회 조건을 비교합니다. */
function navigationRoutesMatch(previousState, nextState) {
  if (previousState.viewName !== nextState.viewName) return false;
  if (nextState.viewName === "jobs") {
    return previousState.pageNumber === nextState.pageNumber && previousState.jobFilterId === nextState.jobFilterId &&
      (previousState.jobFolderId || "") === (nextState.jobFolderId || "") &&
      (previousState.jobSearch || "") === (nextState.jobSearch || "");
  }
  if (nextState.viewName === "outputs") {
    return previousState.pageNumber === nextState.pageNumber &&
      previousState.outputFilter?.type === nextState.outputFilter?.type &&
      previousState.outputFilter?.id === nextState.outputFilter?.id;
  }
  if (["prompts", "tags"].includes(nextState.viewName)) {
    return JSON.stringify(managerNavigationRoute(previousState)) === JSON.stringify(managerNavigationRoute(nextState));
  }
  return true;
}

/** 현재 항목만 갱신하여 스크롤이나 Polling이 새 History를 만들지 않게 합니다. */
function saveCurrentNavigationEntry() {
  if (applicationState.pendingNavigationScroll || managerHistoryState.restoring || managerHistoryState.traversalPending ||
      window.history.state?.homeServerNavigation?.entryId !== applicationState.navigationEntryId) return;
  const navigationState = captureNavigationState();
  window.history.replaceState({ homeServerNavigation: navigationState }, "", navigationUrl(navigationState));
  updateNavigationLinks();
}

/** Prompt의 조회 상태만 복원하며 같은 편집 대상의 현재 입력은 그대로 둡니다. */
async function restorePromptNavigation(navigationState, navigationRevision) {
  const target = navigationState.promptNavigation;
  if (!target) return;
  if (target.pane === "detail" && !promptEditorMatchesNavigation(target)) {
    const preset = applicationState.presets.find(item => item.preset_id === target.presetId);
    let body = preset?.body;
    if (preset && target.sourceVersion !== preset.version) {
      promptEditorState.navigationLoading = true;
      renderPromptEditorStatus();
      try {
        const versions = await apiRequest(`/api/presets/${encodeURIComponent(preset.preset_id)}/versions`);
        if (navigationRevision !== applicationState.navigationRevision) return;
        body = versions.find(version => version.version === target.sourceVersion)?.body;
        if (!body) throw new Error("이전 Prompt 버전을 찾을 수 없습니다.");
      } catch (error) {
        if (navigationRevision !== applicationState.navigationRevision) return;
        promptEditorState.mobilePane = "list";
        element("prompt-manager-layout").dataset.mobilePane = "list";
        throw error;
      } finally {
        if (navigationRevision === applicationState.navigationRevision) {
          promptEditorState.navigationLoading = false;
          renderPromptEditorStatus();
        }
      }
    }
    if (navigationRevision !== applicationState.navigationRevision) return;
    managerHistoryState.restoring = true;
    try {
      if (preset || !target.presetId) {
        configurePromptEditor(preset || null, { workflow: target.workflow, body, sourceVersion: target.sourceVersion, showDetail: false });
        if (!target.presetId) promptEditorState.contextId = target.contextId;
      } else target.pane = "list";
    } finally {
      managerHistoryState.restoring = false;
    }
  }
  promptEditorState.search = target.search;
  promptEditorState.workflowFilter = target.workflowFilter;
  promptEditorState.listHistoryIndex = target.listHistoryIndex;
  promptEditorState.mobilePane = target.pane;
  element("preset-search").value = target.search;
  element("preset-workflow-filter").value = target.workflowFilter;
  element("prompt-manager-layout").dataset.mobilePane = target.pane;
  renderPromptManagerList();
  element("preset-list").scrollTop = target.listScrollTop;
  showPromptDetailTab(target.tab);
  promptEditorState.previewVersion = target.previewVersion;
  if (target.tab === "history" && target.pane === "detail" && promptEditorState.selectedPresetId) {
    await showPresetVersions(promptEditorState.selectedPresetId, { recordHistory: false });
  } else renderPromptVersionHistory();
}

/** 태그 관리의 목록·그룹·Dialog를 복원하고 사라진 대상은 다시 열지 않습니다. */
function restoreTagNavigation(navigationState) {
  const target = navigationState.viewName === "tags" ? navigationState.tagNavigation : null;
  const closingEditorKind = tagManagerState.editorKind;
  const closingEditorId = closingEditorKind === "entry" ? applicationState.editingTagEntryId : applicationState.editingTagGroupId;
  const sameEditor = target?.editorKind && target.editorKind === tagManagerState.editorKind &&
    target.editorId === (target.editorKind === "group" ? applicationState.editingTagGroupId : applicationState.editingTagEntryId);
  managerHistoryState.restoring = true;
  try {
    if (tagManagerState.editorKind && !sameEditor) closeTagEditor({ discard: true, restoreFocus: false, force: true, historyMode: "none" });
    if (!target) return;
    tagManagerState.selectedGroupId = target.groupId;
    tagManagerState.mobilePane = target.pane;
    tagManagerState.groupSearch = target.groupSearch;
    tagManagerState.referenceFilter = target.referenceFilter;
    tagManagerState.entrySearch = target.entrySearch;
    tagManagerState.listHistoryIndex = target.listHistoryIndex;
    tagManagerState.editorParentHistoryIndex = target.editorParentHistoryIndex;
    element("tag-manager-group-search").value = target.groupSearch;
    renderTagManager();
    element("tag-group-list").scrollTop = target.groupScrollTop;
    element("tag-entry-list").scrollTop = target.entryScrollTop;
    if (target.editorKind && !sameEditor) {
      if (target.editorKind === "group") editTagGroup(target.editorId);
      else editTagEntry(target.editorId);
      tagManagerState.editorParentHistoryIndex = target.editorParentHistoryIndex;
    }
    if (tagManagerState.editorKind) element(`tag-${tagManagerState.editorKind}-dialog`).scrollTop = target.dialogScrollTop;
    else if (closingEditorKind) {
      const entryButton = closingEditorKind === "entry" && closingEditorId
        ? element("tag-entry-list").querySelector(`[data-edit-tag-entry="${CSS.escape(closingEditorId)}"]`) : null;
      const groupButton = closingEditorId ? element("edit-selected-tag-group") : element("new-tag-group-button");
      (entryButton || (closingEditorKind === "entry" ? element("new-tag-entry-button") : groupButton)).focus({ preventScroll: true });
    }
  } finally {
    managerHistoryState.restoring = false;
  }
}

/** 조회 조건과 탭 표시를 바꾸며 생성 입력이나 변경 요청은 실행하지 않습니다. */
function displayNavigationState(navigationState) {
  const previousJobScope = currentJobHistoryScope();
  element("jobs-folder-menu").open = false;
  closeJobHistoryFolderDialogs();
  closeJobDescriptionEditor(false);
  closeVideoPreview(false);
  closeImagePreview(false);
  finishJobInputSelection(null, true);
  const viewName = navigationState.viewName;
  if (viewName === "jobs") {
    applicationState.jobsPage = navigationState.pageNumber;
    applicationState.jobFilterId = navigationState.jobFilterId;
    applicationState.jobFolderId = navigationState.jobFolderId || "";
    applicationState.jobSearch = navigationState.jobSearch || "";
    if (previousJobScope !== currentJobHistoryScope()) applicationState.selectedJobIds.clear();
    element("jobs-search").value = applicationState.jobSearch;
    updateJobSelectionControls();
  }
  if (viewName === "outputs") {
    applicationState.outputsPage = navigationState.pageNumber;
    applicationState.outputFilter = navigationState.outputFilter;
  }
  applicationState.currentView = viewName;
  document
    .querySelectorAll(".view")
    .forEach((view) =>
      view.classList.toggle("hidden", view.id !== `view-${viewName}`),
    );
  document
    .querySelectorAll("[data-view]")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.view === viewName),
    );
  const titles = {
    generate: "생성",
    jobs: "작업",
    outputs: "결과물",
    prompts: "Prompt",
    tags: "태그 관리",
    "lora-presets": "LoRA 조합",
  };
  element("page-title").textContent = titles[viewName];
  updateNavigationLinks();
}

/** 목록과 펼친 요청을 다시 조회한 후 해당 이동의 스크롤만 복원합니다. */
async function loadNavigationState(navigationState, restoreOpenJobs) {
  const navigationRevision = ++applicationState.navigationRevision;
  const pendingScroll = { position: navigationState.scrollPosition };
  applicationState.pendingNavigationScroll = pendingScroll;
  applicationState.outputsLoadRevision += 1;
  applicationState.jobsLoadRevision += 1;
  promptEditorState.navigationLoading = false;
  displayNavigationState(navigationState);
  window.scrollTo({ top: navigationState.scrollPosition, behavior: "instant" });
  scheduleJobsPolling();
  try {
    restoreTagNavigation(navigationState);
    if (navigationState.viewName === "prompts") await restorePromptNavigation(navigationState, navigationRevision);
    if (navigationRevision !== applicationState.navigationRevision) return;
    if (navigationState.viewName === "jobs") {
      await loadJobs();
      if (navigationRevision !== applicationState.navigationRevision) return;
      if (restoreOpenJobs) {
        const openJobIds = new Set(navigationState.openJobIds);
        for (const details of element("jobs-list").querySelectorAll(".job-requests")) {
          details.open = openJobIds.has(details.dataset.jobDetails);
        }
        await Promise.allSettled(navigationState.openJobIds.map(jobIdentifier => loadJobDetails(jobIdentifier)));
      }
    }
    if (navigationState.viewName === "outputs") await loadOutputs();
  } finally {
    if (applicationState.pendingNavigationScroll === pendingScroll) {
      applicationState.pendingNavigationScroll = null;
      window.scrollTo({ top: pendingScroll.position, behavior: "instant" });
      saveCurrentNavigationEntry();
    }
  }
}

/** 탭·페이지·필터 이동을 기록하고 일반 탭 이동은 마지막 위치를 유지합니다. */
function switchView(viewName, { resetScroll = false, pageNumber, jobFilterId, outputFilter, jobFolderId, jobSearch } = {}) {
  if (managerHistoryState.traversalPending) return;
  const previousState = captureNavigationState();
  const nextState = {
    ...previousState,
    viewName,
    pageNumber: pageNumber ?? (viewName === "jobs" ? applicationState.jobsPage : applicationState.outputsPage),
    jobFilterId: viewName === "jobs" ? (jobFilterId === undefined ? applicationState.jobFilterId : jobFilterId) : null,
    jobFolderId: viewName === "jobs" ? (jobFolderId ?? applicationState.jobFolderId) : "",
    jobSearch: viewName === "jobs" ? (jobSearch ?? applicationState.jobSearch) : "",
    outputFilter: viewName === "outputs" ? (outputFilter === undefined ? applicationState.outputFilter : outputFilter) : null,
    scrollPosition: resetScroll ? 0 : (applicationState.viewScrollPositions.get(viewName) || 0),
    openJobIds: [],
    promptNavigation: viewName === "prompts" ? capturePromptNavigation() : null,
    tagNavigation: viewName === "tags" ? captureTagNavigation() : null,
  };
  const sameRoute = navigationRoutesMatch(previousState, nextState);
  if (sameRoute && !resetScroll) return;
  if (!canNavigateToState(nextState)) return;
  saveCurrentNavigationEntry();
  applicationState.viewScrollPositions.set(previousState.viewName, window.scrollY);
  if (previousState.viewName !== viewName) {
    if (viewName === "prompts") nextState.promptNavigation.listHistoryIndex = promptEditorState.listHistoryIndex = null;
    if (viewName === "tags") nextState.tagNavigation.listHistoryIndex = tagManagerState.listHistoryIndex = null;
  }
  if (sameRoute) window.history.replaceState({ homeServerNavigation: nextState }, "", navigationUrl(nextState));
  else pushNavigationEntry(nextState);
  loadNavigationState(nextState, false).catch(error => showNotice(error.message, true));
}

/** 사용자 스크롤·입력 이후에는 늦은 응답으로 화면 위치를 되돌리지 않습니다. */
function cancelNavigationScrollRestoration() {
  applicationState.pendingNavigationScroll = null;
}

/** 기본 화면을 History에 등록하고 브라우저의 앞으로가기·뒤로가기를 연결합니다. */
function initializeNavigationHistory() {
  window.history.scrollRestoration = "manual";
  applicationState.navigationEntryId = `${Date.now()}-initial`;
  const initialState = { ...captureNavigationState(), ...navigationStateFromUrl(window.location.href), scrollPosition: 0 };
  displayNavigationState(initialState);
  window.history.replaceState({ homeServerNavigation: initialState }, "", navigationUrl(initialState));
  window.scrollTo({ top: 0, behavior: "instant" });
  window.addEventListener("popstate", (event) => {
    const navigationState = event.state?.homeServerNavigation;
    if (!isNavigationStateValid(navigationState)) return;
    managerHistoryState.traversalPending = false;
    const rejectedEntry = managerHistoryState.rejectedEntry;
    if (rejectedEntry) {
      if (navigationState.entryId === rejectedEntry.entryId) {
        managerHistoryState.rejectedEntry = null;
        saveCurrentNavigationEntry();
      } else {
        managerHistoryState.traversalPending = true;
        window.history.go(rejectedEntry.entryIndex - (navigationState.entryIndex || 0));
      }
      return;
    }
    if (!canNavigateToState(navigationState)) {
      rejectNavigationTraversal(navigationState);
      return;
    }
    applicationState.viewScrollPositions.set(applicationState.currentView, window.scrollY);
    applicationState.navigationEntryId = navigationState.entryId;
    applicationState.navigationEntryIndex = navigationState.entryIndex || 0;
    loadNavigationState(navigationState, true).catch(error => showNotice(error.message, true));
  });
  /** 화면과 내부 목록의 연속 스크롤은 한 Frame에 한 번만 History에 반영합니다. */
  const scheduleNavigationStateSave = () => {
    if (applicationState.navigationScrollFrame !== null) return;
    applicationState.navigationScrollFrame = window.requestAnimationFrame(() => {
      applicationState.navigationScrollFrame = null;
      saveCurrentNavigationEntry();
    });
  };
  window.addEventListener("scroll", scheduleNavigationStateSave, { passive: true });
  for (const identifier of ["preset-list", "tag-group-list", "tag-entry-list", "tag-group-dialog", "tag-entry-dialog"]) {
    element(identifier).addEventListener("scroll", scheduleNavigationStateSave, { passive: true });
  }
  for (const eventName of ["wheel", "touchstart", "pointerdown"]) {
    window.addEventListener(eventName, cancelNavigationScrollRestoration, { passive: true });
  }
  window.addEventListener("keydown", (event) => {
    if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Tab"].includes(event.key)) {
      cancelNavigationScrollRestoration();
    }
  });
}

/** Workflow를 바꿀 때 기존 모델의 Prompt와 LoRA 선택을 초기화합니다. */
function resetGenerationWorkflow(workflow) {
  element("generate-workflow").value = workflow;
  applicationState.currentPresetId = null;
  applicationState.currentPresetVersion = null;
  applicationState.currentLoraPresetId = null;
  applicationState.currentBody = { prompt: "", negative: "" };
  applicationState.selectedLoras = [];
  applicationState.selectedTagIds.clear();
  for (const identifier of ["generate-anima-prompt", "generate-negative", "generate-minimax-prompt"])
    element(identifier).value = "";
  element("generation-lora-preset-form").classList.add("hidden");
  renderPresetList();
  updateWorkflowOptions();
}

/** ComfyUI 연결 상태를 표시합니다. */
async function loadStatus() {
  try {
    const status = await apiRequest("/api/status");
    const badge = element("connection-status");
    badge.classList.toggle("connected", status.comfy_connected);
    badge.classList.toggle("disconnected", !status.comfy_connected);
    badge.lastChild.textContent = status.comfy_connected
      ? "ComfyUI 연결됨"
      : "ComfyUI 연결 안 됨";
    element("output-location").textContent =
      `${status.output_directory}의 현재 파일 상태입니다.`;
  } catch (error) {
    showNotice(error.message, true);
  }
}

/** Memory 용량을 같은 GiB 단위와 고정 소수 자릿수로 표시합니다. */
function formatResourceMemory(usedBytes, totalBytes) {
  if (!Number.isFinite(usedBytes) || !Number.isFinite(totalBytes) || totalBytes <= 0) return "—";
  const bytesPerGibibyte = 1024 ** 3;
  return `${(usedBytes / bytesPerGibibyte).toFixed(1)} / ${(totalBytes / bytesPerGibibyte).toFixed(1)} GiB`;
}

/** History의 관리 화면 상태가 예상한 ID·화면·스크롤 형식인지 검사합니다. */
function isManagerNavigationValid(navigationState) {
  const promptNavigation = navigationState.promptNavigation;
  if (promptNavigation) {
    if (!["list", "detail"].includes(promptNavigation.pane) || !["edit", "history"].includes(promptNavigation.tab) ||
        !["anima", "minimax_h3"].includes(promptNavigation.workflow)) return false;
    for (const field of ["presetId", "contextId"]) {
      if (promptNavigation[field] !== null && typeof promptNavigation[field] !== "string") return false;
    }
    for (const field of ["search", "workflowFilter"]) if (typeof promptNavigation[field] !== "string") return false;
    for (const field of ["sourceVersion", "previewVersion", "listHistoryIndex"]) {
      if (promptNavigation[field] !== null && !Number.isSafeInteger(promptNavigation[field])) return false;
    }
    if (!Number.isFinite(promptNavigation.listScrollTop) || promptNavigation.listScrollTop < 0) return false;
  }
  const tagNavigation = navigationState.tagNavigation;
  if (tagNavigation) {
    if (!["groups", "entries"].includes(tagNavigation.pane) || ![null, "group", "entry"].includes(tagNavigation.editorKind)) return false;
    for (const field of ["groupId", "editorId"]) {
      if (tagNavigation[field] !== null && typeof tagNavigation[field] !== "string") return false;
    }
    for (const field of ["groupSearch", "referenceFilter", "entrySearch"]) if (typeof tagNavigation[field] !== "string") return false;
    for (const field of ["groupScrollTop", "entryScrollTop", "dialogScrollTop"]) {
      if (!Number.isFinite(tagNavigation[field]) || tagNavigation[field] < 0) return false;
    }
    for (const field of ["listHistoryIndex", "editorParentHistoryIndex"]) {
      if (tagNavigation[field] !== null && !Number.isSafeInteger(tagNavigation[field])) return false;
    }
  }
  return true;
}

/** 입력을 건드리지 않고 비교할 수 있도록 관리 화면의 이동 대상을 추립니다. */
function managerNavigationRoute(navigationState) {
  if (navigationState.viewName === "prompts") {
    const target = navigationState.promptNavigation;
    if (!target || target.pane === "list") return ["list"];
    return [target.pane, target.presetId, target.sourceVersion, target.presetId ? null : target.contextId,
      target.tab, target.tab === "history" ? target.previewVersion : null];
  }
  const target = navigationState.tagNavigation;
  return target ? [target.pane, target.pane === "entries" ? target.groupId : null, target.editorKind, target.editorId] : ["groups"];
}

/** 관리 화면 변경 전에 현재 검색·스크롤과 이동 출발점을 보관합니다. */
function beginManagerNavigation() {
  if (managerHistoryState.restoring || managerHistoryState.traversalPending ||
      !["prompts", "tags"].includes(applicationState.currentView)) return null;
  saveCurrentNavigationEntry();
  return captureNavigationState();
}

/** 선택·상세·Dialog 이동만 새 History로 기록하고 같은 대상은 중복하지 않습니다. */
function finishManagerNavigation(previousState) {
  if (!previousState || managerHistoryState.restoring) return;
  const nextState = captureNavigationState();
  if (navigationRoutesMatch(previousState, nextState)) {
    saveCurrentNavigationEntry();
    return;
  }
  if (nextState.viewName === "prompts" && previousState.promptNavigation?.pane === "list") {
    promptEditorState.listHistoryIndex = previousState.entryIndex;
    nextState.promptNavigation.listHistoryIndex = previousState.entryIndex;
  }
  if (nextState.viewName === "tags" && previousState.tagNavigation?.pane === "groups" && !previousState.tagNavigation.editorKind) {
    tagManagerState.listHistoryIndex = previousState.entryIndex;
    nextState.tagNavigation.listHistoryIndex = previousState.entryIndex;
  }
  pushNavigationEntry(nextState);
}

/** 새 History 항목에 순서를 부여하여 취소한 Back·Forward를 정확히 되돌립니다. */
function pushNavigationEntry(navigationState) {
  applicationState.navigationEntrySequence += 1;
  applicationState.navigationEntryIndex += 1;
  navigationState.entryId = `${Date.now()}-${applicationState.navigationEntrySequence}`;
  navigationState.entryIndex = applicationState.navigationEntryIndex;
  applicationState.navigationEntryId = navigationState.entryId;
  window.history.pushState({ homeServerNavigation: navigationState }, "", navigationUrl(navigationState));
}

/** 목록·닫기 버튼도 해당 화면을 연 History로 돌아가도록 연결합니다. */
function returnToManagerHistory(entryIndex) {
  if (managerHistoryState.restoring || managerHistoryState.traversalPending ||
      !Number.isSafeInteger(entryIndex) || entryIndex >= applicationState.navigationEntryIndex) return false;
  managerHistoryState.traversalPending = true;
  window.history.go(entryIndex - applicationState.navigationEntryIndex);
  return true;
}

/** 목적지가 현재 편집 입력을 다시 불러올 필요 없이 표시할 수 있는지 확인합니다. */
function promptEditorMatchesNavigation(target) {
  if (target.presetId !== promptEditorState.selectedPresetId) return false;
  return target.presetId ? target.sourceVersion === promptEditorState.sourceVersion : target.contextId === promptEditorState.contextId;
}

/** 닫히는 Dialog나 교체되는 Prompt의 미저장 변경만 확인합니다. */
function canNavigateToState(navigationState) {
  if (promptEditorState.saving || tagManagerState.editorBusy) return false;
  const tagTarget = navigationState.viewName === "tags" ? navigationState.tagNavigation : null;
  const sameTagEditor = tagTarget?.editorKind === tagManagerState.editorKind &&
    tagTarget?.editorId === (tagManagerState.editorKind === "group" ? applicationState.editingTagGroupId : applicationState.editingTagEntryId);
  if (tagManagerState.editorKind && !sameTagEditor && tagEditorHasChanges() &&
      !window.confirm("저장하지 않은 태그 변경 내용을 버리고 이동하시겠습니까?")) return false;
  const promptTarget = navigationState.viewName === "prompts" ? navigationState.promptNavigation : null;
  if (promptTarget?.pane === "detail" && !promptEditorMatchesNavigation(promptTarget) && promptEditorHasChanges() &&
      !window.confirm("저장하지 않은 Prompt 변경 내용을 버리고 이동하시겠습니까?")) return false;
  return true;
}

/** 취소되거나 저장 중인 History 이동을 원래 항목으로 되돌립니다. */
function rejectNavigationTraversal(targetState) {
  const currentState = { ...captureNavigationState(), entryId: applicationState.navigationEntryId };
  const distance = currentState.entryIndex - targetState.entryIndex;
  if (Number.isSafeInteger(distance) && distance !== 0) {
    managerHistoryState.rejectedEntry = currentState;
    managerHistoryState.traversalPending = true;
    window.history.go(distance);
  } else {
    pushNavigationEntry(currentState);
    managerHistoryState.traversalPending = false;
  }
}

/** 서버 상태 숫자와 작은 Bar만 갱신하며 열어 둔 상세 패널은 유지합니다. */
function renderSystemResources(snapshot = {}) {
  const metrics = [
    { name: "cpu", percent: snapshot.cpu_percent, text: Number.isFinite(snapshot.cpu_percent) ? `${Math.round(snapshot.cpu_percent)}%` : "—" },
    { name: "ram", percent: snapshot.ram_percent, text: formatResourceMemory(snapshot.ram_used_bytes, snapshot.ram_total_bytes) },
    { name: "gpu", percent: snapshot.gpu_percent, text: Number.isFinite(snapshot.gpu_percent) ? `${Math.round(snapshot.gpu_percent)}%` : "—" },
    { name: "vram", percent: snapshot.vram_percent, text: formatResourceMemory(snapshot.vram_used_bytes, snapshot.vram_total_bytes) },
  ];
  for (const metric of metrics) {
    element(`resource-${metric.name}-value`).textContent = metric.text;
    const metricElement = element(`resource-${metric.name}`);
    metricElement.style.setProperty("--resource-percent", `${Number.isFinite(metric.percent) ? Math.max(0, Math.min(100, metric.percent)) : 0}%`);
    metricElement.classList.toggle("resource-high", metric.percent >= 90);
  }
  element("system-resources").classList.toggle("resource-unavailable", snapshot.status === "unavailable" || !snapshot.status);
  element("resource-host-description").textContent = `ComfyUI host · ${snapshot.gpu_name || "GPU 확인 불가"} · 2초 간격`;
  const statusMessage = snapshot.status === "ready" ? "CPU·GPU는 사용률, RAM·VRAM은 사용량 / 전체 용량입니다."
    : snapshot.status === "partial" ? "일부 지표를 확인할 수 없습니다. 확인되지 않은 값은 —로 표시합니다."
      : "서버 상태를 확인할 수 없습니다. ComfyUI 연결과 DaSiWa System Monitor를 확인해 주세요.";
  element("resource-status").textContent = statusMessage;
}

/** 화면·작업·해제 상태와 관계없이 동일한 주기로 공통 Snapshot을 읽으며 중복 요청은 합칩니다. */
async function loadSystemResources() {
  if (applicationState.resourceLoadPromise) return applicationState.resourceLoadPromise;
  const sessionRevision = applicationState.resourceSessionRevision;
  applicationState.resourceLoadPromise = (async () => {
    try {
      const snapshot = await apiRequest("/api/system-resources", {
        signal: AbortSignal.timeout(RESOURCE_POLL_INTERVAL_MILLISECONDS),
      });
      if (sessionRevision === applicationState.resourceSessionRevision) renderSystemResources(snapshot);
    } catch (error) {
      if (sessionRevision === applicationState.resourceSessionRevision) renderSystemResources();
    } finally {
      applicationState.resourceLoadPromise = null;
    }
  })();
  return applicationState.resourceLoadPromise;
}

/** Workflow별 입력 영역을 전환합니다. */
function updateWorkflowOptions() {
  const isAnima = element("generate-workflow").value === "anima";
  element("anima-prompt-fields").classList.toggle("hidden", !isAnima);
  element("minimax-prompt-fields").classList.toggle("hidden", isAnima);
  element("generate-tag-fields").classList.remove("hidden");
  element("anima-options").classList.toggle("hidden", !isAnima);
  element("minimax-options").classList.toggle("hidden", isAnima);
  element("minimax-input-fields").classList.toggle("hidden", isAnima);
  element("minimax-submit-summary").classList.toggle("hidden", isAnima);
  element("generate-count-field").classList.toggle("hidden", !isAnima);
  element("generate-count-hint").classList.toggle("hidden", !isAnima);
  element("generate-count").disabled = !isAnima;
  element("lora-step").textContent = "03";
  element("workflow-options-step").textContent = "04";
  element("generate-tag-description").textContent = isAnima
    ? "Prompt·Negative Prompt의 [TAG]와 선택한 항목의 하위 [TAG]를 가진 그룹을 표시합니다. 같은 참조 태그의 선택 항목은 함께 추첨됩니다."
    : "Prompt의 [TAG]와 선택한 항목의 하위 [TAG]를 가진 그룹을 표시합니다. 이미지마다 독립 추첨하고 같은 참조 태그의 선택 항목은 함께 추첨됩니다.";
  element("preview-hint").textContent = isAnima
    ? "미리보기는 선택한 항목을 조합하고 Impact wildcard를 확정한 예시입니다."
    : "미리보기는 이미지별 태그 추첨 예시입니다. 실제 제출할 때 다시 추첨하며 wildcard 문법은 그대로 유지합니다.";
  renderLoraPresetList();
  renderSelectedLoras();
  renderLoraFileOptions();
  renderGenerateTagGroups();
  updatePresetWorkflowOptions();
  renderMinimaxInputs();
}

/** 선택한 해상도를 Anima의 너비와 높이에 적용합니다. */
function applyAnimaResolution() {
  const [width, height] = element("anima-resolution").value.split("x").map(Number);
  element("anima-width").value = width;
  element("anima-height").value = height;
}

/** Anima 비율에 맞는 해상도 목록과 직접 입력 상태를 갱신합니다. */
function updateAnimaResolutionOptions() {
  const aspectRatio = element("anima-aspect-ratio").value;
  const resolutionSelect = element("anima-resolution");
  const isCustom = aspectRatio === "custom";
  element("anima-width").readOnly = !isCustom;
  element("anima-height").readOnly = !isCustom;
  resolutionSelect.disabled = isCustom;
  if (isCustom) {
    resolutionSelect.innerHTML = '<option value="custom">직접 입력</option>';
    return;
  }
  resolutionSelect.innerHTML = ANIMA_RESOLUTIONS[aspectRatio]
    .map(([width, height]) => `<option value="${width}x${height}">${width} × ${height}</option>`)
    .join("");
  resolutionSelect.selectedIndex = 0;
  applyAnimaResolution();
}

/** Prompt 편집 화면에서 Workflow별 입력 form을 전환합니다. */
function updatePresetWorkflowOptions() {
  const isAnima = element("preset-workflow").value === "anima";
  element("preset-anima-fields").classList.toggle("hidden", !isAnima);
  element("preset-minimax-fields").classList.toggle("hidden", isAnima);
  element("preset-form-description").textContent = isAnima
    ? "태그 참조가 포함된 Prompt 텍스트를 버전으로 저장합니다."
    : "MiniMax의 [TAG] 참조를 포함한 원본 Prompt를 버전으로 저장합니다.";
}

/** 저장된 preset 목록을 불러옵니다. */
async function loadPresets() {
  try {
    applicationState.presets = await apiRequest("/api/presets");
    renderPresetList();
  } catch (error) {
    showNotice(error.message, true);
  }
}

/** Workflow별 저장 대상만 비교할 수 있도록 Prompt 본문 형식을 맞춥니다. */
function normalizedPromptBody(body, workflow) {
  if (workflow === "minimax_h3") return { prompt: body.prompt || "" };
  return { prompt: body.prompt || "", negative: body.negative || "" };
}

/** 생성 화면과 독립된 편집기의 현재 값을 비교 가능한 형태로 읽습니다. */
function promptEditorSnapshot() {
  return { name: element("preset-name").value.trim(), workflow: element("preset-workflow").value, body: editorBody() };
}

/** 편집기를 연 뒤 저장하지 않은 변경이 있는지 확인합니다. */
function promptEditorHasChanges() {
  return promptEditorState.baselineFingerprint !== null &&
    JSON.stringify(promptEditorSnapshot()) !== promptEditorState.baselineFingerprint;
}

/** 입력을 대체하는 동작에만 미저장 내용 버리기를 확인합니다. */
function canReplacePromptEditor() {
  if (promptEditorState.saving || promptEditorState.navigationLoading || managerHistoryState.traversalPending) return false;
  return !promptEditorHasChanges() || window.confirm("저장하지 않은 Prompt 변경 내용을 버리고 계속하시겠습니까?");
}

/** 생성 화면에는 실제 불러온 버전과 원본 대비 수정 여부를 표시합니다. */
function renderGenerationPromptStatus() {
  const workflow = element("generate-workflow").value;
  const preset = applicationState.presets.find(item => item.preset_id === applicationState.currentPresetId && item.workflow === workflow);
  let description = "직접 작성";
  if (preset) {
    const versionNumber = applicationState.currentPresetVersion || preset.version;
    const modified = JSON.stringify(normalizedPromptBody(generateBody(), workflow)) !==
      JSON.stringify(normalizedPromptBody(applicationState.currentBody, workflow));
    description = `${preset.name} · v${versionNumber}${modified ? "에서 수정됨" : " 사용 중"}`;
    if (versionNumber !== preset.version) description += ` · 최신 v${preset.version}`;
  }
  element("generate-prompt-status").textContent = description;
}

/** 생성 선택 목록과 Prompt 관리 목록을 각자의 선택 상태로 표시합니다. */
function renderPresetList() {
  const workflow = element("generate-workflow").value;
  const options = applicationState.presets.filter(preset => preset.workflow === workflow).map(preset => {
    const selectedVersion = preset.preset_id === applicationState.currentPresetId
      ? applicationState.currentPresetVersion || preset.version : preset.version;
    const latestLabel = selectedVersion !== preset.version ? ` 사용 중 · 최신 v${preset.version}` : "";
    return `<option value="${escapeHtml(preset.preset_id)}">${escapeHtml(preset.name)} · v${selectedVersion}${latestLabel}</option>`;
  }).join("");
  element("generate-preset").innerHTML = `<option value="">직접 작성</option>${options}`;
  element("generate-preset").value = applicationState.currentPresetId || "";
  renderGenerationPromptStatus();
  renderPromptManagerList();
  renderPromptEditorStatus();
}

/** 검색 조건과 선택 상태를 보존하며 Prompt 목록을 갱신합니다. */
function renderPromptManagerList() {
  const list = element("preset-list");
  const previousScrollPosition = list.scrollTop;
  const searchText = tagSearchText(promptEditorState.search.trim());
  const filteredPresets = applicationState.presets.filter(preset => {
    if (promptEditorState.workflowFilter && preset.workflow !== promptEditorState.workflowFilter) return false;
    return !searchText || tagSearchText(`${preset.name}\n${preset.body.prompt || ""}\n${preset.body.negative || ""}`).includes(searchText);
  });
  list.innerHTML = filteredPresets.length ? filteredPresets.map(preset => {
    const selected = promptEditorState.selectedPresetId === preset.preset_id;
    const workflowLabel = preset.workflow === "anima" ? "Anima Turbo V9" : "MiniMax H3";
    return `<article class="prompt-list-row"${selected ? ' aria-current="true"' : ""}>
      <button type="button" class="prompt-list-open" data-load-preset="${escapeHtml(preset.preset_id)}"${promptEditorState.saving ? " disabled" : ""}>
        <strong>${escapeHtml(preset.name)}</strong><small>${workflowLabel} · v${preset.version}${selected ? " · 편집 대상" : ""}</small>
        <small>${escapeHtml(formatKoreanTimestamp(preset.updated_at))}</small></button>
      <button type="button" class="button subtle small" data-show-versions="${escapeHtml(preset.preset_id)}" aria-label="${escapeHtml(preset.name)} 버전 기록"${promptEditorState.saving ? " disabled" : ""}>버전</button></article>`;
  }).join("") : '<p class="empty-state">조건에 맞는 Prompt가 없습니다.</p>';
  list.scrollTop = previousScrollPosition;
  element("preset-list-count").textContent = `${filteredPresets.length} / ${applicationState.presets.length}개 Prompt`;
}

/** 저장 상태와 다음 버전의 대상 이름을 편집기 위아래에 표시합니다. */
function renderPromptEditorStatus() {
  const snapshot = promptEditorSnapshot();
  const preset = applicationState.presets.find(item => item.preset_id === promptEditorState.selectedPresetId);
  const changed = promptEditorHasChanges();
  element("prompt-editor-title").textContent = preset?.name || "새 Prompt";
  let status = "새 Prompt · 아직 저장하지 않음";
  if (preset) {
    status = promptEditorState.sourceVersion === preset.version
      ? `v${preset.version} 편집 중` : `v${promptEditorState.sourceVersion}에서 시작 · 최신 v${preset.version}`;
  }
  if (changed) status += " · 변경됨";
  if (promptEditorState.saving) status += " · 저장 중…";
  if (promptEditorState.navigationLoading) status += " · 이전 화면 불러오는 중…";
  element("preset-version").textContent = status;
  const sameAsLatest = preset && JSON.stringify(snapshot) === JSON.stringify({
    name: preset.name, workflow: preset.workflow, body: normalizedPromptBody(preset.body, preset.workflow),
  });
  const saving = promptEditorState.saving || promptEditorState.navigationLoading;
  for (const identifier of ["preset-name", "preset-anima-prompt", "preset-negative", "preset-minimax-prompt",
    "new-preset-button", "new-preset-detail-button", "copy-preset-button", "prompt-list-back", "preset-edit-tab"]) {
    element(identifier).disabled = saving;
  }
  element("preset-workflow").disabled = saving || Boolean(preset);
  element("preset-history-tab").disabled = saving || !preset;
  element("save-preset-button").disabled = saving || !snapshot.name || !snapshot.body.prompt.trim() || Boolean(sameAsLatest);
  element("save-preset-button").textContent = saving ? "저장 중…" : preset ? `v${preset.version + 1}으로 저장` : "새 Prompt 저장";
  element("use-preset-button").disabled = saving || !snapshot.body.prompt.trim();
  element("copy-preset-button").disabled = saving || !snapshot.body.prompt.trim();
  element("preset-save-target").textContent = preset
    ? `‘${preset.name}’의 v${preset.version + 1}로 저장합니다.${snapshot.name !== preset.name ? ` 이름: ${snapshot.name || "미입력"}` : ""}`
    : `‘${snapshot.name || "이름 미입력"}’을 새 Prompt v1으로 저장합니다.`;
  element("preset-history-title").textContent = preset ? `‘${preset.name}’의 버전 기록 · 최신 v${preset.version}` : "먼저 Prompt를 저장해 주세요.";
}

/** 생성 화면에만 Prompt를 채우고 필요한 경우 태그 선택을 초기화합니다. */
function fillGenerationPromptFields(body, resetSelectedTags = false) {
  if (resetSelectedTags) applicationState.selectedTagIds.clear();
  element("generate-anima-prompt").value = body.prompt || "";
  element("generate-negative").value = body.negative || "";
  element("generate-minimax-prompt").value = body.prompt || "";
}

/** 편집기 입력만 채우고 생성 화면과 태그 선택은 유지합니다. */
function fillPromptEditorFields(body) {
  element("preset-anima-prompt").value = body.prompt || "";
  element("preset-negative").value = body.negative || "";
  element("preset-minimax-prompt").value = body.prompt || "";
}

/** 확인을 마친 대상을 편집기에 설정하고 이전 버전 응답을 무효화합니다. */
function configurePromptEditor(preset, options = {}) {
  const workflow = preset?.workflow || options.workflow || element("generate-workflow").value;
  const body = normalizedPromptBody(options.body || preset?.body || {}, workflow);
  const previousPresetId = promptEditorState.selectedPresetId;
  promptEditorState.editorRevision += 1;
  promptEditorState.contextId = `${Date.now()}-prompt-${promptEditorState.editorRevision}`;
  promptEditorState.versionsRevision += 1;
  promptEditorState.selectedPresetId = preset?.preset_id || null;
  promptEditorState.sourceVersion = preset ? options.sourceVersion || preset.version : null;
  promptEditorState.sourceBody = normalizedPromptBody(options.sourceBody || body, workflow);
  promptEditorState.workflow = workflow;
  promptEditorState.versionsLoading = false;
  promptEditorState.versionsError = "";
  if (previousPresetId !== promptEditorState.selectedPresetId || options.invalidateVersions) {
    promptEditorState.versions = [];
    promptEditorState.versionsPresetId = null;
    promptEditorState.previewVersion = null;
  }
  element("preset-name").value = preset?.name || options.name || "";
  element("preset-workflow").value = workflow;
  fillPromptEditorFields(body);
  element("preset-editor-error").textContent = "";
  element("preset-save-message").textContent = "";
  promptEditorState.baselineFingerprint = JSON.stringify(preset ? {
    name: preset.name, workflow, body: promptEditorState.sourceBody,
  } : { name: "", workflow, body: normalizedPromptBody({}, workflow) });
  updatePresetWorkflowOptions();
  showPromptDetailTab("edit");
  renderPromptManagerList();
  renderPromptVersionHistory();
  if (options.showDetail !== false) showPromptDetail();
}

/** 미저장 입력을 보호하면서 기존 Prompt의 최신 본문을 엽니다. */
function loadPresetIntoEditor(presetId) {
  const preset = applicationState.presets.find(item => item.preset_id === presetId);
  if (!preset || !canReplacePromptEditor()) return false;
  const previousState = beginManagerNavigation();
  configurePromptEditor(preset);
  finishManagerNavigation(previousState);
  return true;
}

/** 기존 연결이 없는 새 Prompt를 빈 내용 또는 현재 편집 내용의 복제로 시작합니다. */
function startNewPrompt(copyCurrent = false) {
  const snapshot = promptEditorSnapshot();
  if (promptEditorState.saving || (!copyCurrent && !canReplacePromptEditor())) return;
  const previousState = beginManagerNavigation();
  configurePromptEditor(null, copyCurrent ? {
    name: `${snapshot.name || "Prompt"} 복사`, workflow: snapshot.workflow, body: snapshot.body,
  } : { workflow: snapshot.workflow });
  finishManagerNavigation(previousState);
  element("preset-name").focus({ preventScroll: true });
}

/** 모바일에서 상세 화면을 열고 Desktop에서는 편집기 위치로 이동합니다. */
function showPromptDetail() {
  const mobileLayout = window.matchMedia("(max-width: 800px)").matches;
  if (mobileLayout && promptEditorState.mobilePane === "list") {
    promptEditorState.listScrollPosition = window.scrollY;
  }
  promptEditorState.mobilePane = "detail";
  element("prompt-manager-layout").dataset.mobilePane = "detail";
  if (applicationState.currentView === "prompts") {
    const scrollTarget = mobileLayout ? element("prompt-list-back") : element("prompt-editor-title");
    scrollTarget.scrollIntoView({ block: "start" });
  }
}

/** 목록의 검색 조건과 이전 스크롤을 보존하여 모바일 목록으로 돌아갑니다. */
function showPromptList() {
  if (promptEditorState.saving) return;
  if (returnToManagerHistory(promptEditorState.listHistoryIndex)) return;
  promptEditorState.mobilePane = "list";
  element("prompt-manager-layout").dataset.mobilePane = "list";
  window.scrollTo(0, promptEditorState.listScrollPosition);
  saveCurrentNavigationEntry();
}

/** 선택 Prompt의 편집 화면과 버전 기록 화면을 전환합니다. */
function showPromptDetailTab(tabName) {
  promptEditorState.activeTab = tabName;
  for (const name of ["edit", "history"]) {
    const selected = name === tabName;
    element(`preset-${name}-tab`).setAttribute("aria-selected", String(selected));
    element(`preset-${name}-panel`).classList.toggle("hidden", !selected);
  }
  renderPromptEditorStatus();
}

/** 사용자가 선택한 편집·버전 화면 전환을 History에 기록합니다. */
function navigatePromptDetailTab(tabName) {
  const previousState = beginManagerNavigation();
  showPromptDetailTab(tabName);
  finishManagerNavigation(previousState);
}

/** 현재 Prompt에 속한 버전과 선택한 버전의 읽기 전용 본문을 표시합니다. */
function renderPromptVersionHistory() {
  const preset = applicationState.presets.find(item => item.preset_id === promptEditorState.selectedPresetId);
  const versions = promptEditorState.versionsPresetId === preset?.preset_id ? promptEditorState.versions : [];
  element("preset-history-status").textContent = promptEditorState.versionsLoading ? "버전 기록을 불러오는 중…"
    : promptEditorState.versionsError || (versions.length ? `${versions.length}개 버전 · 본문을 미리본 뒤 편집을 시작하세요.` : "저장된 버전이 없습니다.");
  element("retry-preset-versions").classList.toggle("hidden", !promptEditorState.versionsError);
  element("preset-version-history").innerHTML = versions.map(version =>
    `<button type="button" class="prompt-version-button" data-preview-version="${version.version}" aria-pressed="${version.version === promptEditorState.previewVersion}">
      <strong>v${version.version}${version.version === preset.version ? " · 최신" : ""}</strong><small>${escapeHtml(formatKoreanTimestamp(version.saved_at))}</small></button>`).join("");
  const preview = versions.find(version => version.version === promptEditorState.previewVersion);
  element("preset-version-preview").classList.toggle("hidden", !preview);
  if (!preview) return;
  element("preset-preview-title").textContent = `${preset.name} · v${preview.version}`;
  element("preset-preview-prompt").textContent = preview.body.prompt || "";
  element("preset-preview-negative").textContent = preview.body.negative || "";
  element("preset-preview-negative-section").classList.toggle("hidden", preset.workflow !== "anima");
}

/** 선택한 Prompt의 버전을 불러오고 늦게 도착한 다른 대상의 응답은 버립니다. */
async function showPresetVersions(presetId, { recordHistory = true } = {}) {
  if (promptEditorState.saving) return;
  if (promptEditorState.selectedPresetId !== presetId && !loadPresetIntoEditor(presetId)) return;
  if (recordHistory && promptEditorState.mobilePane !== "detail") {
    const previousState = beginManagerNavigation();
    showPromptDetail();
    finishManagerNavigation(previousState);
  }
  const previousState = recordHistory ? beginManagerNavigation() : null;
  showPromptDetailTab("history");
  finishManagerNavigation(previousState);
  if (promptEditorState.versionsLoading) return;
  const revision = ++promptEditorState.versionsRevision;
  promptEditorState.versionsLoading = true;
  promptEditorState.versionsError = "";
  renderPromptVersionHistory();
  try {
    const versions = await apiRequest(`/api/presets/${encodeURIComponent(presetId)}/versions`);
    if (revision !== promptEditorState.versionsRevision || presetId !== promptEditorState.selectedPresetId) return;
    promptEditorState.versions = versions;
    promptEditorState.versionsPresetId = presetId;
    if (!versions.some(version => version.version === promptEditorState.previewVersion)) {
      promptEditorState.previewVersion = versions[0]?.version || null;
    }
  } catch (error) {
    if (revision === promptEditorState.versionsRevision) promptEditorState.versionsError = error.message;
  } finally {
    if (revision === promptEditorState.versionsRevision) {
      promptEditorState.versionsLoading = false;
      renderPromptVersionHistory();
      saveCurrentNavigationEntry();
    }
  }
}

/** 미리본 버전을 편집 시작점으로 가져오며 저장 대상은 같은 Prompt로 유지합니다. */
function loadPresetVersion() {
  const preset = applicationState.presets.find(item => item.preset_id === promptEditorState.selectedPresetId);
  const version = promptEditorState.versions.find(item => item.version === promptEditorState.previewVersion);
  if (!preset || !version || promptEditorState.versionsPresetId !== preset.preset_id || !canReplacePromptEditor()) return;
  const previousState = beginManagerNavigation();
  configurePromptEditor(preset, { body: version.body, sourceVersion: version.version });
  finishManagerNavigation(previousState);
}

/** 명시적으로 선택한 Prompt만 생성 화면에 적용합니다. */
function applyPromptToGeneration(workflow, body, preset = null, sourceVersion = null, sourceBody = body) {
  if (element("generate-workflow").value !== workflow) resetGenerationWorkflow(workflow);
  applicationState.currentPresetId = preset?.preset_id || null;
  applicationState.currentPresetVersion = preset ? sourceVersion || preset.version : null;
  applicationState.currentBody = structuredClone(sourceBody);
  fillGenerationPromptFields(body, true);
  renderPresetList();
  updateWorkflowOptions();
}

/** 생성 화면의 현재 본문을 기존 수정 또는 새 Prompt 작성으로 가져옵니다. */
function editGenerationPrompt(copyAsNew = false) {
  if (!canReplacePromptEditor()) return;
  const workflow = element("generate-workflow").value;
  const preset = copyAsNew ? null : applicationState.presets.find(item =>
    item.preset_id === applicationState.currentPresetId && item.workflow === workflow);
  configurePromptEditor(preset, { workflow, body: generateBody(),
    sourceVersion: applicationState.currentPresetVersion, sourceBody: applicationState.currentBody });
  switchView("prompts", { resetScroll: true });
}

/** 편집기 내용을 저장과 별개로 생성 화면에 명시적으로 적용합니다. */
function usePromptEditorInGeneration() {
  if (promptEditorState.saving) return;
  const preset = applicationState.presets.find(item => item.preset_id === promptEditorState.selectedPresetId);
  applyPromptToGeneration(element("preset-workflow").value, editorBody(), preset,
    promptEditorState.sourceVersion, promptEditorState.sourceBody);
  switchView("generate", { resetScroll: true });
}

/** Prompt 편집 화면의 현재 입력값을 객체로 만듭니다. */
function editorBody() {
  if (element("preset-workflow").value === "minimax_h3") {
    return { prompt: element("preset-minimax-prompt").value };
  }
  return {
    prompt: element("preset-anima-prompt").value,
    negative: element("preset-negative").value,
  };
}

/** 현재 화면 경로를 유지하며 새로운 주소로 HTML과 화면 파일을 다시 요청합니다. */
function reloadWebAssets() {
  const reloadUrl = new URL(window.location.href);
  reloadUrl.searchParams.set("reload_assets", "true");
  reloadUrl.searchParams.set("reload_request", `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  window.location.replace(reloadUrl.href);
}

/** 현재 Workflow의 Prompt 본문만 비우고 바로 붙여넣을 수 있도록 입력란에 초점을 둡니다. */
function clearGenerationPrompt() {
  const promptFieldIdentifier = element("generate-workflow").value === "minimax_h3"
    ? "generate-minimax-prompt" : "generate-anima-prompt";
  const promptField = element(promptFieldIdentifier);
  promptField.value = "";
  promptField.dispatchEvent(new Event("input", { bubbles: true }));
  promptField.focus();
}

/** 생성 화면의 현재 Prompt를 객체로 만듭니다. */
function generateBody() {
  if (element("generate-workflow").value === "minimax_h3") {
    return { prompt: element("generate-minimax-prompt").value };
  }
  return {
    prompt: element("generate-anima-prompt").value,
    negative: element("generate-negative").value,
  };
}

/** 태그와 표시 그룹을 다시 읽고 현재 선택을 유지합니다. */
async function loadTags() {
  try {
    const catalog = await apiRequest("/api/tags");
    applicationState.tagGroups = catalog.groups;
    applicationState.tagEntries = catalog.entries;
    if (applicationState.expandedTagGroupIds === null)
      applicationState.expandedTagGroupIds = new Set(
        catalog.groups.filter((group) => group.default_expanded).map((group) => group.group_id),
      );
    const existingGroupIds = new Set(catalog.groups.map((group) => group.group_id));
    for (const group of catalog.groups) {
      if (!applicationState.knownTagGroupIds?.has(group.group_id) && group.default_expanded) {
        applicationState.expandedTagGroupIds.add(group.group_id);
      }
    }
    applicationState.knownTagGroupIds = existingGroupIds;
    const existingTagIds = new Set(catalog.entries.map((entry) => entry.tag_id));
    for (const tagId of applicationState.selectedTagIds) {
      if (!existingTagIds.has(tagId))
        applicationState.selectedTagIds.delete(tagId);
    }
    renderGenerateTagGroups();
    renderTagManager();
  } catch (error) {
    showNotice(error.message, true);
  }
}

/** 현재 Workflow의 Prompt와 선택된 태그 본문에서 필요한 참조 키를 재귀적으로 찾습니다. */
function requiredTagKeys() {
  const requiredKeys = new Set();
  const visitedTagIds = new Set();
  const currentBody = generateBody();
  const pendingTexts = [currentBody.prompt];
  if (element("generate-workflow").value === "anima") pendingTexts.push(currentBody.negative || "");
  while (pendingTexts.length) {
    const templateText = pendingTexts.shift();
    for (const match of templateText.matchAll(/\[([A-Z][A-Z0-9_]*)\]/g)) {
      const tagKey = match[1];
      requiredKeys.add(tagKey);
      const matchingGroups = applicationState.tagGroups.filter((group) => group.tag_key === tagKey);
      for (const group of matchingGroups) {
        for (const entry of sortedTagEntriesInGroup(group.group_id)) {
          if (!applicationState.selectedTagIds.has(entry.tag_id) || visitedTagIds.has(entry.tag_id)) continue;
          visitedTagIds.add(entry.tag_id);
          pendingTexts.push(entry.content);
        }
      }
    }
  }
  return requiredKeys;
}

/** 현재 Prompt에서 도달 가능한 선택 항목만 제출 목록으로 반환합니다. */
function activeSelectedTagIds() {
  const requiredKeys = requiredTagKeys();
  const relevantGroupIds = new Set(applicationState.tagGroups
    .filter((group) => requiredKeys.has(group.tag_key))
    .map((group) => group.group_id));
  return applicationState.tagEntries
    .filter((entry) => relevantGroupIds.has(entry.group_id) && applicationState.selectedTagIds.has(entry.tag_id))
    .map((entry) => entry.tag_id);
}

/** 필요한 참조의 선택 상태와 관련 그룹의 checkbox만 표시합니다. */
function renderGenerateTagGroups() {
  const container = element("generate-tag-groups");
  const requiredKeys = requiredTagKeys();
  if (!requiredKeys.size) {
    element("tag-selection-status").textContent = element("generate-workflow").value === "anima"
      ? "Prompt와 Negative Prompt에 [TAG] 참조가 없습니다. 태그 선택이 필요하지 않습니다."
      : "Prompt에 [TAG] 참조가 없습니다. 태그 선택이 필요하지 않습니다.";
    container.innerHTML = "";
    return;
  }

  const relevantGroups = sortedTagGroups().filter((group) => requiredKeys.has(group.tag_key));
  const missingKeys = [...requiredKeys].filter((tagKey) =>
    !relevantGroups.some((group) => group.tag_key === tagKey &&
      sortedTagEntriesInGroup(group.group_id).some((entry) => applicationState.selectedTagIds.has(entry.tag_id))));
  element("tag-selection-status").textContent = [...requiredKeys]
    .map((tagKey) => `[${tagKey}] ${missingKeys.includes(tagKey) ? "선택 필요" : "선택됨"}`)
    .join(" · ");

  const missingDefinitions = [...requiredKeys].filter((tagKey) =>
    !relevantGroups.some((group) => group.tag_key === tagKey && sortedTagEntriesInGroup(group.group_id).length > 0));
  const missingMarkup = missingDefinitions.length
    ? `<p class="empty-state">${missingDefinitions.map((key) => `[${escapeHtml(key)}]`).join(", ")} 참조 태그를 가진 그룹과 하위 항목을 태그 관리 탭에서 추가해 주세요.</p>`
    : "";
  container.innerHTML = missingMarkup + relevantGroups.map((group) => {
    const entries = sortedTagEntriesInGroup(group.group_id);
    const selectedCount = entries.filter((entry) => applicationState.selectedTagIds.has(entry.tag_id)).length;
    const selectionRequired = missingKeys.includes(group.tag_key);
    let selectionStateClass = "";
    if (selectionRequired) selectionStateClass = " tag-selection-required";
    else if (selectedCount > 0) selectionStateClass = " tag-selection-active";
    const openAttribute = applicationState.expandedTagGroupIds?.has(group.group_id) ? " open" : "";
    const entryMarkup = entries.map((entry) => `
      <label class="tag-choice">
        <input type="checkbox" data-select-tag="${escapeHtml(entry.tag_id)}" ${applicationState.selectedTagIds.has(entry.tag_id) ? "checked" : ""}>
        <span><strong>${escapeHtml(entry.name)}</strong><small>weight ${escapeHtml(entry.weight)}</small></span>
      </label>`).join("");
    return `<details class="tag-group${selectionStateClass}" data-tag-group-open="${escapeHtml(group.group_id)}"${openAttribute}>
      <summary>${escapeHtml(group.name)} [${escapeHtml(group.tag_key)}] <span>${selectionRequired ? "선택 필요 · " : ""}${selectedCount}개 선택 · ${entries.length}개 항목</span></summary>
      <div class="tag-group-options">
        <div class="inline-actions">
          <button class="button subtle small" type="button" data-select-visible-tag-group="${escapeHtml(group.group_id)}">전체 선택</button>
          <button class="button subtle small" type="button" data-clear-visible-tag-group="${escapeHtml(group.group_id)}">전체 해제</button>
        </div>
        ${entryMarkup || '<p class="hint">이 그룹에 태그 항목이 없습니다.</p>'}
      </div>
    </details>`;
  }).join("");
}

/** 지정한 목록에 표시된 태그 그룹을 함께 펼치거나 접고 화면별 상태를 유지합니다. */
function setTagGroupsExpanded(containerIdentifier, expandedGroupIdentifiers, shouldExpand) {
  if (!expandedGroupIdentifiers) return;
  const visibleGroups = element(containerIdentifier).querySelectorAll("details.tag-group");
  for (const group of visibleGroups) {
    const groupIdentifier = group.dataset.tagGroupOpen || group.dataset.manageTagGroupOpen;
    if (shouldExpand) expandedGroupIdentifiers.add(groupIdentifier);
    else expandedGroupIdentifiers.delete(groupIdentifier);
    group.open = shouldExpand;
  }
}

/** 이름과 본문 검색에 사용할 Unicode 문자열의 표기와 대소문자를 맞춥니다. */
function tagSearchText(value) {
  return String(value).normalize("NFC").toLocaleLowerCase("ko-KR");
}

/** 선택한 그룹만 표시하고 탐색 조건·목록의 스크롤·열린 편집 입력을 유지합니다. */
function renderTagManager() {
  const groups = sortedTagGroups();
  const groupList = element("tag-group-list");
  const entryList = element("tag-entry-list");
  const groupScrollTop = groupList.scrollTop;
  const entryScrollTop = entryList.scrollTop;
  if (!groups.some(group => group.group_id === tagManagerState.selectedGroupId)) {
    tagManagerState.selectedGroupId = groups[0]?.group_id || null;
    tagManagerState.entrySearch = "";
    tagManagerState.mobilePane = "groups";
  }
  const referenceKeys = [...new Set(groups.map(group => group.tag_key).filter(Boolean))].sort(TAG_NAME_COLLATOR.compare);
  if (!referenceKeys.includes(tagManagerState.referenceFilter)) tagManagerState.referenceFilter = "";
  element("tag-manager-reference-filter").innerHTML = '<option value="">전체 참조 태그</option>' + referenceKeys.map(referenceKey =>
    `<option value="${escapeHtml(referenceKey)}">[${escapeHtml(referenceKey)}]</option>`).join("");
  element("tag-manager-reference-filter").value = tagManagerState.referenceFilter;
  const groupQuery = tagSearchText(tagManagerState.groupSearch.trim());
  const matchingGroups = groups.filter(group =>
    (!tagManagerState.referenceFilter || group.tag_key === tagManagerState.referenceFilter) &&
    tagSearchText(`${group.name} [${group.tag_key}]`).includes(groupQuery));
  const entryCounts = new Map();
  for (const entry of applicationState.tagEntries) entryCounts.set(entry.group_id, (entryCounts.get(entry.group_id) || 0) + 1);
  groupList.innerHTML = matchingGroups.map(group => `<button class="tag-manager-group-button" type="button" data-select-managed-group="${escapeHtml(group.group_id)}" aria-current="${group.group_id === tagManagerState.selectedGroupId ? "true" : "false"}">
    <span><strong>${escapeHtml(group.name)}</strong><small>${group.tag_key ? `[${escapeHtml(group.tag_key)}]` : "참조 태그 없음"}</small></span><span class="tag-manager-group-size">${entryCounts.get(group.group_id) || 0}</span></button>`).join("") ||
    `<p class="empty-state">${groups.length ? "조건에 맞는 그룹이 없습니다." : "새 그룹을 만들어 주세요."}</p>`;
  element("tag-manager-group-count").textContent = `${matchingGroups.length} / ${groups.length}개 그룹 · 전체 ${applicationState.tagEntries.length}개 항목`;
  const selectedGroup = groups.find(group => group.group_id === tagManagerState.selectedGroupId);
  const entries = selectedGroup ? sortedTagEntriesInGroup(selectedGroup.group_id) : [];
  const entryQuery = tagSearchText(tagManagerState.entrySearch.trim());
  const matchingEntries = entries.filter(entry => tagSearchText(`${entry.name}\n${entry.content}`).includes(entryQuery));
  element("tag-manager-selected-name").textContent = selectedGroup?.name || "그룹을 선택해 주세요.";
  element("tag-manager-selected-reference").textContent = selectedGroup
    ? `[${selectedGroup.tag_key}] · 생성 화면에서 기본 ${selectedGroup.default_expanded ? "펼침" : "접힘"}` : "그룹을 만들고 항목을 추가할 수 있습니다.";
  element("tag-manager-entry-count").textContent = selectedGroup ? `${matchingEntries.length} / ${entries.length}개 항목` : "";
  element("tag-manager-entry-search").value = tagManagerState.entrySearch;
  for (const identifier of ["edit-selected-tag-group", "new-tag-entry-button", "tag-manager-entry-search"]) element(identifier).disabled = !selectedGroup;
  entryList.innerHTML = matchingEntries.map(entry => `<article class="tag-manager-entry-row">
    <div><div class="tag-manager-entry-title"><strong>${escapeHtml(entry.name)}</strong><span>weight ${escapeHtml(entry.weight)}</span></div><p class="tag-content-preview">${escapeHtml(entry.content)}</p></div>
    <div class="inline-actions"><button class="button subtle small" type="button" data-edit-tag-entry="${escapeHtml(entry.tag_id)}">편집</button></div></article>`).join("") ||
    `<p class="empty-state">${entryQuery ? "조건에 맞는 항목이 없습니다." : selectedGroup ? "이 그룹에 항목이 없습니다. 새 항목을 추가해 주세요." : "왼쪽에서 그룹을 선택해 주세요."}</p>`;
  element("tag-manager-layout").dataset.mobilePane = tagManagerState.mobilePane;
  groupList.scrollTop = groupScrollTop;
  entryList.scrollTop = entryScrollTop;
  if (!element("tag-entry-dialog").open) updateTagEntryGroupOptions();
}

/** 편집 중인 선택값은 유지하면서 현재 그룹 목록으로 항목 이동 선택지를 구성합니다. */
function updateTagEntryGroupOptions(selectedGroupId = tagManagerState.selectedGroupId) {
  element("tag-entry-group").innerHTML = sortedTagGroups().map(group =>
    `<option value="${escapeHtml(group.group_id)}">${escapeHtml(group.name)} [${escapeHtml(group.tag_key)}]</option>`).join("");
  if (selectedGroupId) element("tag-entry-group").value = selectedGroupId;
  updateTagEntryGroupReference();
}

/** 그룹을 선택하고 모바일에서는 마지막 항목 목록 위치를 복원합니다. */
function selectManagedTagGroup(groupId) {
  if (!applicationState.tagGroups.some(group => group.group_id === groupId)) return;
  if (managerHistoryState.traversalPending) return;
  const previousState = beginManagerNavigation();
  const mobileLayout = window.matchMedia("(max-width: 800px)").matches;
  if (mobileLayout && tagManagerState.mobilePane === "groups") tagManagerState.groupScrollPosition = window.scrollY;
  const groupChanged = tagManagerState.selectedGroupId !== groupId;
  if (groupChanged) tagManagerState.entrySearch = "";
  tagManagerState.selectedGroupId = groupId;
  tagManagerState.mobilePane = "entries";
  renderTagManager();
  if (mobileLayout) {
    const managerTop = element("tag-manager-layout").getBoundingClientRect().top + window.scrollY - 12;
    window.scrollTo({ top: tagManagerState.entryScrollPositions.get(groupId) ?? managerTop, behavior: "instant" });
  } else if (groupChanged) element("tag-entry-list").scrollTop = 0;
  finishManagerNavigation(previousState);
}

/** 모바일의 그룹 탐색 조건과 이전 목록 위치로 돌아갑니다. */
function showManagedTagGroups() {
  if (returnToManagerHistory(tagManagerState.listHistoryIndex)) return;
  tagManagerState.entryScrollPositions.set(tagManagerState.selectedGroupId, window.scrollY);
  tagManagerState.mobilePane = "groups";
  element("tag-manager-layout").dataset.mobilePane = "groups";
  window.scrollTo({ top: tagManagerState.groupScrollPosition, behavior: "instant" });
  element("tag-group-list").querySelector(`[data-select-managed-group="${CSS.escape(tagManagerState.selectedGroupId || "")}"]`)?.focus({ preventScroll: true });
  saveCurrentNavigationEntry();
}

/** 편집 입력을 API payload와 변경 감지에 공통으로 사용합니다. */
function tagEditorValues(kind) {
  if (kind === "group") return {
    name: element("tag-group-name").value, tag_key: element("tag-group-key").value,
    default_expanded: element("tag-group-default-expanded").checked,
  };
  return { group_id: element("tag-entry-group").value, name: element("tag-entry-name").value,
    content: element("tag-entry-content").value, weight: Number(element("tag-entry-weight").value) };
}

/** 이미 채운 편집 양식의 초기 상태와 Focus 복귀 대상을 보관합니다. */
function openTagEditor(kind) {
  const previousState = beginManagerNavigation();
  tagManagerState.editorParentHistoryIndex = previousState?.entryIndex ?? tagManagerState.editorParentHistoryIndex;
  tagManagerState.editorKind = kind;
  tagManagerState.editorRevision += 1;
  tagManagerState.editorOpener = document.activeElement;
  tagManagerState.editorFingerprint = JSON.stringify(tagEditorValues(kind));
  element(`tag-${kind}-editor-status`).textContent = "";
  element(`tag-${kind}-dialog`).showModal();
  element(`tag-${kind}-name`).focus();
  finishManagerNavigation(previousState);
}

/** 열려 있는 태그 편집기의 입력이 초기 값과 다른지 확인합니다. */
function tagEditorHasChanges() {
  return Boolean(tagManagerState.editorKind) &&
    JSON.stringify(tagEditorValues(tagManagerState.editorKind)) !== tagManagerState.editorFingerprint;
}

/** 변경된 입력만 버리기 확인을 하고 저장 중에는 닫지 않습니다. */
function closeTagEditor({ discard = false, restoreFocus = true, force = false, historyMode = "back" } = {}) {
  const kind = tagManagerState.editorKind;
  if (!kind || (tagManagerState.editorBusy && !force)) return false;
  const changed = tagEditorHasChanges();
  if (!discard && changed && !window.confirm("저장하지 않은 변경 사항을 버리고 닫으시겠습니까?")) return false;
  element(`tag-${kind}-dialog`).close();
  tagManagerState.editorKind = null;
  tagManagerState.editorRevision += 1;
  tagManagerState.editorBusy = false;
  setTagEditorBusy(kind, false);
  if (restoreFocus) {
    const opener = tagManagerState.editorOpener;
    if (opener?.isConnected && opener.getClientRects().length) opener.focus({ preventScroll: true });
    else {
      const entryId = applicationState.editingTagEntryId;
      const entryButton = kind === "entry" && entryId
        ? element("tag-entry-list").querySelector(`[data-edit-tag-entry="${CSS.escape(entryId)}"]`) : null;
      (entryButton || element(kind === "group" ? "new-tag-group-button" : "new-tag-entry-button")).focus({ preventScroll: true });
    }
  }
  if (historyMode !== "none" && !force && !managerHistoryState.restoring) {
    if (discard || historyMode === "replace" || !returnToManagerHistory(tagManagerState.editorParentHistoryIndex)) saveCurrentNavigationEntry();
  }
  return true;
}

/** 저장 중인 Dialog의 입력과 버튼을 한 번에 잠그거나 복구합니다. */
function setTagEditorBusy(kind, busy) {
  tagManagerState.editorBusy = busy;
  for (const control of element(`tag-${kind}-form`).querySelectorAll("input,select,textarea,button")) control.disabled = busy;
  if (kind === "group" && !busy) {
    element("delete-selected-tag-group").disabled = applicationState.tagEntries.some(entry => entry.group_id === applicationState.editingTagGroupId);
  }
}

/** 새 그룹 또는 기존 그룹의 설정을 현재 화면의 Dialog로 엽니다. */
function editTagGroup(groupId = null) {
  const group = applicationState.tagGroups.find((item) => item.group_id === groupId);
  if (groupId && !group) return;
  applicationState.editingTagGroupId = group?.group_id || null;
  element("tag-group-form").reset();
  element("tag-group-name").value = group?.name || "";
  element("tag-group-key").value = group?.tag_key || "";
  element("tag-group-default-expanded").checked = group ? group.default_expanded : true;
  element("tag-group-dialog-title").textContent = group ? "그룹 설정" : "새 그룹";
  element("delete-selected-tag-group").hidden = !group;
  element("delete-selected-tag-group").title = "항목이 없는 그룹만 삭제할 수 있습니다.";
  setTagEditorBusy("group", false);
  openTagEditor("group");
}

/** 선택한 그룹에서 상속하는 참조 태그를 항목 편집 양식에 표시합니다. */
function updateTagEntryGroupReference() {
  const selectedGroup = applicationState.tagGroups.find((group) => group.group_id === element("tag-entry-group").value);
  element("tag-entry-reference").textContent = selectedGroup?.tag_key
    ? `그룹의 참조 태그 [${selectedGroup.tag_key}]가 적용됩니다.`
    : "그룹의 참조 태그를 표시 그룹 관리에서 먼저 설정해 주세요.";
}

/** 선택 그룹의 새 항목이나 기존 항목을 이동 가능한 편집 Dialog로 엽니다. */
function editTagEntry(tagId = null) {
  const entry = applicationState.tagEntries.find((item) => item.tag_id === tagId);
  if ((tagId && !entry) || !tagManagerState.selectedGroupId) return;
  applicationState.editingTagEntryId = entry?.tag_id || null;
  element("tag-entry-form").reset();
  updateTagEntryGroupOptions(entry?.group_id || tagManagerState.selectedGroupId);
  element("tag-entry-name").value = entry?.name || "";
  element("tag-entry-content").value = entry?.content || "";
  element("tag-entry-weight").value = entry?.weight ?? 1;
  element("tag-entry-dialog-title").textContent = entry ? "태그 항목 편집" : "새 항목";
  element("delete-selected-tag-entry").hidden = !entry;
  setTagEditorBusy("entry", false);
  openTagEditor("entry");
}

/** 저장 실패 시 입력을 보존하고 성공 시 선택 그룹과 검색·스크롤을 유지합니다. */
async function saveTagEditor(kind) {
  if (tagManagerState.editorBusy || tagManagerState.editorKind !== kind) return;
  const identifier = kind === "group" ? applicationState.editingTagGroupId : applicationState.editingTagEntryId;
  const revision = tagManagerState.editorRevision;
  const values = tagEditorValues(kind);
  if (kind === "group") values.tag_key = values.tag_key.trim().toUpperCase();
  const basePath = kind === "group" ? "/api/tags/groups" : "/api/tags/entries";
  element(`tag-${kind}-editor-status`).textContent = "";
  setTagEditorBusy(kind, true);
  try {
    const saved = await apiRequest(identifier ? `${basePath}/${encodeURIComponent(identifier)}` : basePath, {
      method: identifier ? "PUT" : "POST", body: JSON.stringify(values),
    });
    if (revision !== tagManagerState.editorRevision) return;
    if (kind === "group" && !identifier) {
      tagManagerState.selectedGroupId = saved.group_id;
      tagManagerState.mobilePane = "entries";
      tagManagerState.groupSearch = "";
      tagManagerState.referenceFilter = "";
      tagManagerState.entrySearch = "";
      element("tag-manager-group-search").value = "";
    }
    if (kind === "entry" && !identifier) tagManagerState.selectedGroupId = saved.group_id;
    await loadTags();
    if (revision !== tagManagerState.editorRevision) return;
    setTagEditorBusy(kind, false);
    closeTagEditor({ discard: true });
    showNotice(kind === "group" ? "그룹을 저장했습니다." : "태그 항목을 저장했습니다.");
  } catch (error) {
    if (revision === tagManagerState.editorRevision) element(`tag-${kind}-editor-status`).textContent = error.message;
  } finally {
    if (revision === tagManagerState.editorRevision) setTagEditorBusy(kind, false);
  }
}

/** 현재 그룹 설정에서 비어 있는 그룹만 확인 후 삭제합니다. */
async function deleteTagGroup(groupId) {
  const group = applicationState.tagGroups.find(item => item.group_id === groupId);
  if (!group || tagManagerState.editorBusy || !window.confirm(`"${group.name}" 그룹을 삭제하시겠습니까?`)) return;
  const revision = tagManagerState.editorRevision;
  setTagEditorBusy("group", true);
  try {
    await apiRequest(`/api/tags/groups/${encodeURIComponent(groupId)}`, { method: "DELETE" });
    if (revision !== tagManagerState.editorRevision) return;
    await loadTags();
    if (revision !== tagManagerState.editorRevision) return;
    setTagEditorBusy("group", false);
    closeTagEditor({ discard: true });
    showNotice("그룹을 삭제했습니다.");
  } catch (error) {
    if (revision === tagManagerState.editorRevision) element("tag-group-editor-status").textContent = error.message;
  } finally {
    if (revision === tagManagerState.editorRevision) setTagEditorBusy("group", false);
  }
}

/** 태그 항목의 현재 정의를 삭제합니다. */
async function deleteTagEntry(tagId) {
  const entry = applicationState.tagEntries.find((item) => item.tag_id === tagId);
  if (!entry || tagManagerState.editorBusy || !window.confirm(`"${entry.name}" 태그 항목을 삭제하시겠습니까?`)) return;
  const revision = tagManagerState.editorRevision;
  setTagEditorBusy("entry", true);
  try {
    await apiRequest(`/api/tags/entries/${encodeURIComponent(tagId)}`, { method: "DELETE" });
    if (revision !== tagManagerState.editorRevision) return;
    await loadTags();
    if (revision !== tagManagerState.editorRevision) return;
    setTagEditorBusy("entry", false);
    closeTagEditor({ discard: true });
    showNotice("태그 항목을 삭제했습니다.");
  } catch (error) {
    if (revision === tagManagerState.editorRevision) element("tag-entry-editor-status").textContent = error.message;
  } finally {
    if (revision === tagManagerState.editorRevision) setTagEditorBusy("entry", false);
  }
}

/** 현재 Prompt를 새 버전으로 저장합니다. */
async function savePreset() {
  if (promptEditorState.saving || element("save-preset-button").disabled) return;
  const snapshot = promptEditorSnapshot();
  const revision = promptEditorState.editorRevision;
  promptEditorState.saving = true;
  element("preset-editor-error").textContent = "";
  renderPromptEditorStatus();
  renderPromptManagerList();
  try {
    const result = await apiRequest("/api/presets", {
      method: "POST", body: JSON.stringify({ preset_id: promptEditorState.selectedPresetId, ...snapshot }),
    });
    if (revision !== promptEditorState.editorRevision) return;
    const previousIndex = applicationState.presets.findIndex(preset => preset.preset_id === result.preset_id);
    if (previousIndex >= 0) applicationState.presets.splice(previousIndex, 1);
    applicationState.presets.unshift(result);
    promptEditorState.saving = false;
    configurePromptEditor(result, { invalidateVersions: true, showDetail: false });
    renderPresetList();
    element("preset-save-message").textContent = `${result.name} v${result.version}을 저장했습니다.`;
    saveCurrentNavigationEntry();
  } catch (error) {
    if (revision === promptEditorState.editorRevision) element("preset-editor-error").textContent = error.message;
  } finally {
    if (revision === promptEditorState.editorRevision) {
      promptEditorState.saving = false;
      renderPromptEditorStatus();
      renderPromptManagerList();
    }
  }
}

/** ComfyUI의 현재 LoRA 목록을 읽습니다. */
async function loadLoras() {
  try {
    const response = await apiRequest("/api/loras");
    applicationState.availableLoras = response.files;
    applicationState.loraProfiles = response.profiles || [];
    applicationState.loraCatalogAvailable = true;
  } catch (error) {
    applicationState.loraCatalogAvailable = false;
  }
  renderLoraFileOptions();
  renderSelectedLoras();
  renderLoraPresetEditor();
}

/** 선택한 LoRA 카드의 공통 편집 UI를 구성합니다. */
function loraCardsMarkup(selectedLoras, workflow, showProfileSave) {
  const isAnima = workflow === "anima";
  return selectedLoras
    .map(
      (lora, index) => `
    <div class="selected-lora" data-lora-index="${index}"><div><strong>${escapeHtml(lora.name)}</strong>${showProfileSave ? `<button class="text-button lora-save-button" data-save-lora="${index}" type="button">이 강도를 기본값으로 저장</button>` : ""}${applicationState.loraCatalogAvailable && !applicationState.availableLoras.includes(lora.name) ? '<span class="missing-lora">ComfyUI에서 찾을 수 없는 LoRA</span>' : ""}</div>
    <label>STR<input data-lora-field="strength" type="number" step="0.05" value="${escapeHtml(lora.strength)}"></label>
    <label>${isAnima ? "CLIP" : "V×"}<input data-lora-field="${isAnima ? "clip_strength" : "video_strength"}" type="number" step="0.05" value="${escapeHtml(isAnima ? lora.clip_strength : lora.video_strength)}"></label>
    ${isAnima ? "<span></span>" : `<label class="audio-strength">A×<input data-lora-field="audio_strength" type="number" step="0.05" value="${escapeHtml(lora.audio_strength)}"></label>`}
    <button class="icon-button" data-remove-lora="${index}" title="LoRA 제거">×</button></div>`,
    )
    .join("");
}

/** 현재 선택한 LoRA와 preset 수정 여부를 생성 화면에 표시합니다. */
function renderSelectedLoras() {
  const workflow = element("generate-workflow").value;
  element("selected-loras").innerHTML = loraCardsMarkup(applicationState.selectedLoras, workflow, true);
  renderGenerationLoraPresetStatus();
}

/** 기본값 추가와 preset snapshot 비교에 사용할 공통 항목 형식을 만듭니다. */
function normalizeLoraEntries(selectedLoras, workflow) {
  return selectedLoras.map((lora) => {
    const entry = { name: lora.name, strength: Number(lora.strength ?? 1) };
    if (workflow === "anima") entry.clip_strength = Number(lora.clip_strength ?? 1);
    else {
      entry.video_strength = Number(lora.video_strength ?? 1);
      entry.audio_strength = Number(lora.audio_strength ?? 1);
    }
    return entry;
  });
}

/** 저장 전에 빈 조합과 유효하지 않은 weight를 확인합니다. */
function validateLoraEntries(selectedLoras, workflow) {
  if (!selectedLoras.length) throw new Error("LoRA를 한 개 이상 선택해 주세요.");
  if (selectedLoras.length > 100) throw new Error("LoRA 조합은 최대 100개까지 저장할 수 있습니다.");
  if (workflow === "minimax_h3" && selectedLoras.length > 10)
    throw new Error("MiniMax에는 LoRA를 최대 10개 적용할 수 있습니다.");
  for (const selectedLora of normalizeLoraEntries(selectedLoras, workflow)) {
    for (const [field, value] of Object.entries(selectedLora)) {
      if (field !== "name" && !Number.isFinite(value))
        throw new Error(`${selectedLora.name}의 weight를 숫자로 입력해 주세요.`);
    }
  }
}

/** 두 화면의 추가 목록에 workflow별 개별 LoRA 기본값 여부를 표시합니다. */
function renderLoraFileOptions() {
  for (const [selectIdentifier, workflowIdentifier] of [
    ["available-loras", "generate-workflow"],
    ["lora-preset-available-files", "lora-preset-workflow"],
  ]) {
    const selectedFile = element(selectIdentifier).value;
    if (!applicationState.loraCatalogAvailable) {
      element(selectIdentifier).innerHTML = '<option value="">ComfyUI 연결을 확인해 주세요</option>';
      continue;
    }
    const workflow = element(workflowIdentifier).value;
    let options = `<option value="">LoRA 선택 · ${applicationState.availableLoras.length}개</option>`;
    for (const filename of applicationState.availableLoras) {
      const hasProfile = applicationState.loraProfiles.some((profile) => profile.name === filename && profile.workflow === workflow);
      options += `<option value="${escapeHtml(filename)}">${escapeHtml(hasProfile ? filename : `${filename} · 새 LoRA`)}</option>`;
    }
    element(selectIdentifier).innerHTML = options;
    if (applicationState.availableLoras.includes(selectedFile)) element(selectIdentifier).value = selectedFile;
  }
}

/** 개별 LoRA 기본 강도를 사용해 선택 목록에 새 파일을 추가합니다. */
function addLoraEntry(selectedLoras, workflow, filename) {
  if (!filename || selectedLoras.some((lora) => lora.name === filename)) return;
  const savedProfile = applicationState.loraProfiles.find((profile) => profile.name === filename && profile.workflow === workflow);
  selectedLoras.push({
    name: filename, strength: savedProfile?.settings.strength ?? 1,
    clip_strength: savedProfile?.settings.clip_strength ?? 1,
    video_strength: savedProfile?.settings.video_strength ?? 1,
    audio_strength: savedProfile?.settings.audio_strength ?? 1,
  });
}

/** 조합 목록은 ComfyUI 연결과 독립적으로 불러옵니다. */
async function loadLoraPresets() {
  applicationState.loraPresets = await apiRequest("/api/loras/presets");
  renderLoraPresetList();
  renderLoraPresetEditor();
}

/** Workflow별 선택 목록과 관리 화면의 저장된 조합들을 표시합니다. */
function renderLoraPresetList() {
  const workflow = element("generate-workflow").value;
  let options = '<option value="">직접 구성</option>';
  for (const preset of applicationState.loraPresets) {
    if (preset.workflow === workflow)
      options += `<option value="${escapeHtml(preset.preset_id)}">${escapeHtml(preset.name)} · ${preset.loras.length} LoRA</option>`;
  }
  element("generate-lora-preset").innerHTML = options;
  renderGenerationLoraPresetStatus();
  element("lora-preset-list").innerHTML = applicationState.loraPresets.length
    ? applicationState.loraPresets.map((preset) => `
      <article class="preset-row lora-preset-row"><div><strong>${escapeHtml(preset.name)}</strong><small>${preset.workflow === "anima" ? "Anima Turbo V9" : "MiniMax H3"} · ${preset.loras.length} LoRA</small><small>${escapeHtml(preset.loras.map((lora) => lora.name).join(" · "))}</small></div>
      <div class="inline-actions"><button class="button subtle small" type="button" data-edit-lora-preset="${escapeHtml(preset.preset_id)}">열기</button><button class="button subtle small" type="button" data-rename-lora-preset="${escapeHtml(preset.preset_id)}">이름 변경</button><button class="button subtle small" type="button" data-use-lora-preset="${escapeHtml(preset.preset_id)}">생성에서 사용</button><button class="button subtle small" type="button" data-copy-lora-preset="${escapeHtml(preset.preset_id)}">복제</button><button class="button subtle small" type="button" data-delete-lora-preset="${escapeHtml(preset.preset_id)}">삭제</button></div></article>`).join("")
    : '<p class="empty-state">저장된 LoRA 조합이 없습니다.</p>';
}

/** 실제 선택 조합이 원본과 일치할 때만 표시용 preset명을 제출합니다. */
function generationLoraPresetName() {
  if (!applicationState.selectedLoras.length) return null;
  const workflow = element("generate-workflow").value;
  const selectedPreset = applicationState.loraPresets.find((preset) =>
    preset.preset_id === applicationState.currentLoraPresetId && preset.workflow === workflow,
  );
  if (!selectedPreset) return null;
  const selectedCombination = normalizeLoraEntries(applicationState.selectedLoras, workflow);
  const presetCombination = normalizeLoraEntries(selectedPreset.loras, workflow);
  return JSON.stringify(selectedCombination) === JSON.stringify(presetCombination) ? selectedPreset.name : null;
}

/** 생성 화면의 카드 변경이 원본 preset과 다른지 표시합니다. */
function renderGenerationLoraPresetStatus() {
  const workflow = element("generate-workflow").value;
  const preset = applicationState.loraPresets.find((item) => item.preset_id === applicationState.currentLoraPresetId && item.workflow === workflow);
  const modified = preset && generationLoraPresetName() === null;
  element("generate-lora-preset").value = preset?.preset_id || "";
  element("generate-lora-preset-status").textContent = `${preset?.name || "직접 구성"} · ${applicationState.selectedLoras.length} LoRA${modified ? " · 수정됨" : ""}`;
  element("save-generation-lora-preset-button").disabled = !applicationState.selectedLoras.length;
}

/** 저장된 조합을 복사하여 생성 카드에 채우고 원본은 유지합니다. */
function applyLoraCombination(workflow, selectedLoras, presetId = null) {
  if (element("generate-workflow").value !== workflow) resetGenerationWorkflow(workflow);
  applicationState.currentLoraPresetId = presetId;
  applicationState.selectedLoras = normalizeLoraEntries(selectedLoras, workflow);
  element("generation-lora-preset-form").classList.add("hidden");
  renderLoraPresetList();
  renderSelectedLoras();
}

/** 조합 관리 화면의 편집 내용을 새 조합으로 초기화합니다. */
function resetLoraPresetEditor(workflow = element("lora-preset-workflow").value) {
  applicationState.loraEditorPresetId = null;
  applicationState.loraEditorEntries = [];
  element("lora-preset-name").value = "";
  element("lora-preset-workflow").value = workflow;
  renderLoraFileOptions();
  renderLoraPresetEditor();
}

/** 관리 편집기에 조합을 복사하며 복제 시 새 preset 상태로 엽니다. */
function loadLoraPresetEditor(presetId, copyAsNew = false) {
  const preset = applicationState.loraPresets.find((item) => item.preset_id === presetId);
  if (!preset) return;
  applicationState.loraEditorPresetId = copyAsNew ? null : preset.preset_id;
  applicationState.loraEditorEntries = normalizeLoraEntries(preset.loras, preset.workflow);
  element("lora-preset-workflow").value = preset.workflow;
  element("lora-preset-name").value = copyAsNew ? `${preset.name} 복사` : preset.name;
  renderLoraFileOptions();
  renderLoraPresetEditor();
}

/** 관리 편집기의 이름과 구성 변경 여부를 계산합니다. */
function renderLoraPresetEditorStatus() {
  const workflow = element("lora-preset-workflow").value;
  const preset = applicationState.loraPresets.find((item) => item.preset_id === applicationState.loraEditorPresetId);
  const modified = preset && (
    element("lora-preset-name").value.trim() !== preset.name || workflow !== preset.workflow ||
    JSON.stringify(normalizeLoraEntries(applicationState.loraEditorEntries, workflow)) !== JSON.stringify(normalizeLoraEntries(preset.loras, workflow))
  );
  element("lora-preset-editor-status").textContent = `${preset?.name || "새 조합"} · ${applicationState.loraEditorEntries.length} LoRA${modified ? " · 수정됨" : ""}`;
  element("update-lora-preset-button").disabled = !preset || !modified || !applicationState.loraEditorEntries.length;
  element("create-lora-preset-button").disabled = !applicationState.loraEditorEntries.length;
  element("use-lora-preset-editor-button").disabled = !applicationState.loraEditorEntries.length;
}

/** 관리 편집기의 LoRA 카드와 변경 상태를 표시합니다. */
function renderLoraPresetEditor() {
  element("lora-preset-selected-files").innerHTML = loraCardsMarkup(applicationState.loraEditorEntries, element("lora-preset-workflow").value, false);
  renderLoraPresetEditorStatus();
}

/** 생성 중인 조합을 새 preset으로 저장하며 개별 기본값은 변경하지 않습니다. */
async function saveGenerationLoraPreset() {
  const workflow = element("generate-workflow").value;
  validateLoraEntries(applicationState.selectedLoras, workflow);
  const presetName = element("generation-lora-preset-name").value.trim();
  if (!presetName) throw new Error("LoRA preset 이름을 입력해 주세요.");
  const preset = await apiRequest("/api/loras/presets", {
    method: "POST", body: JSON.stringify({ name: presetName, workflow, loras: normalizeLoraEntries(applicationState.selectedLoras, workflow) }),
  });
  applicationState.currentLoraPresetId = preset.preset_id;
  await loadLoraPresets();
  element("generation-lora-preset-form").classList.add("hidden");
  showNotice(`${preset.name} 조합을 저장했습니다.`);
}

/** 관리 편집 내용을 새 조합으로 저장하거나 선택한 원본을 갱신합니다. */
async function saveLoraPresetEditor(updateExisting) {
  const workflow = element("lora-preset-workflow").value;
  validateLoraEntries(applicationState.loraEditorEntries, workflow);
  const presetName = element("lora-preset-name").value.trim();
  if (!presetName) throw new Error("LoRA preset 이름을 입력해 주세요.");
  const presetId = applicationState.loraEditorPresetId;
  if (updateExisting && !presetId) throw new Error("갱신할 LoRA preset을 선택해 주세요.");
  const preset = await apiRequest(updateExisting ? `/api/loras/presets/${encodeURIComponent(presetId)}` : "/api/loras/presets", {
    method: updateExisting ? "PUT" : "POST",
    body: JSON.stringify({ name: presetName, workflow, loras: normalizeLoraEntries(applicationState.loraEditorEntries, workflow) }),
  });
  await loadLoraPresets();
  loadLoraPresetEditor(preset.preset_id);
  renderGenerationLoraPresetStatus();
  showNotice(`${preset.name} 조합을 ${updateExisting ? "갱신" : "저장"}했습니다.`);
}

/** 저장된 구성과 편집 중인 강도를 보존하면서 조합 이름을 변경합니다. */
async function renameLoraPreset(presetIdentifier) {
  const preset = applicationState.loraPresets.find(item => item.preset_id === presetIdentifier);
  if (!preset) return;
  const enteredName = window.prompt("LoRA 조합의 새 이름을 입력해 주세요.", preset.name);
  if (enteredName === null) return;
  const presetName = enteredName.trim();
  if (!presetName) throw new Error("LoRA preset 이름을 입력해 주세요.");
  if (presetName.length > 120) throw new Error("LoRA preset 이름은 120자 이내로 입력해 주세요.");
  if (presetName === preset.name) return;

  const renamedPreset = await apiRequest(`/api/loras/presets/${encodeURIComponent(presetIdentifier)}`, {
    method: "PUT",
    body: JSON.stringify({ name: presetName, workflow: preset.workflow, loras: preset.loras }),
  });
  if (applicationState.loraEditorPresetId === presetIdentifier && element("lora-preset-name").value === preset.name) {
    element("lora-preset-name").value = renamedPreset.name;
  }
  await loadLoraPresets();
  showNotice(`${renamedPreset.name} 조합으로 이름을 변경했습니다.`);
}

/** 선택한 저장 조합을 삭제하고 사용 중인 카드 복사본은 유지합니다. */
async function deleteLoraPreset(presetId) {
  const preset = applicationState.loraPresets.find((item) => item.preset_id === presetId);
  if (!preset || !window.confirm(`"${preset.name}" LoRA preset을 삭제하시겠습니까?`)) return;
  await apiRequest(`/api/loras/presets/${encodeURIComponent(presetId)}`, { method: "DELETE" });
  if (applicationState.currentLoraPresetId === presetId) applicationState.currentLoraPresetId = null;
  if (applicationState.loraEditorPresetId === presetId) applicationState.loraEditorPresetId = null;
  await loadLoraPresets();
  showNotice(`${preset.name} 조합을 삭제했습니다.`);
}

/** Workflow 설정값을 요청 형식으로 만듭니다. */
function generationSettings() {
  if (element("generate-workflow").value === "anima") {
    return {
      width: Number(element("anima-width").value),
      height: Number(element("anima-height").value),
      steps: Number(element("anima-steps").value),
      cfg: Number(element("anima-cfg").value),
      seed: Math.floor(Math.random() * 2147483647),
    };
  }
  return {
    width: Number(element("minimax-width").value),
    height: Number(element("minimax-height").value),
    duration: Number(element("minimax-duration").value),
    frame_rate: Number(element("minimax-frame-rate").value),
    upscale_mode: element("minimax-upscale").value,
    upscale_model_name: element("minimax-upscale-model").value,
    auto_align: true,
    ref_image_size: "match",
    generation_mode: element("minimax-generation-mode").value,
    resolution_mode: applicationState.minimaxResolutionManual ? "manual" : "automatic",
  };
}

/** 요청별 확정 Prompt 예시를 표시합니다. */
async function previewPrompt() {
  const workflow = element("generate-workflow").value;
  const response = await apiRequest("/api/prompts/preview", {
    method: "POST",
    body: JSON.stringify({
      workflow,
      body: generateBody(),
      selected_tag_ids: activeSelectedTagIds(),
      count: 5,
    }),
  });
  element("preview-results").classList.remove("hidden");
  element("preview-results").innerHTML = response.examples.map((example) => {
    const selectedNames = example.selected_path.map((item) => item.name).join(" → ");
    const negativeNames = (example.negative_selected_path || []).map((item) => item.name).join(" → ");
    const negativeMarkup = example.negative
      ? `<div class="preview-negative"><strong>Negative Prompt${negativeNames ? ` · ${escapeHtml(negativeNames)}` : ""}</strong>${escapeHtml(example.negative)}</div>`
      : "";
    return `<div class="preview-item"><strong>${example.index}. ${escapeHtml(selectedNames)} · seed ${example.seed}</strong>${escapeHtml(example.prompt)}${negativeMarkup}</div>`;
  }).join("");
}

/** 상대 경로의 폴더 구분자는 유지하면서 파일명 특수문자를 URL에 안전하게 넣습니다. */
function encodedOutputPath(relativePath) {
  return relativePath.split("/").map(encodeURIComponent).join("/");
}

/** 선택을 초기화하고 이전 이미지 확인 응답을 무효화합니다. */
function clearMinimaxInputs(resetAutomatic = false) {
  applicationState.minimaxSelectionRevision += 1;
  applicationState.minimaxInputImages = [];
  applicationState.minimaxInputCandidates = [];
  applicationState.minimaxInputDirectory = null;
  applicationState.minimaxInputJob = null;
  applicationState.minimaxInputLoading = false;
  if (resetAutomatic) applicationState.minimaxResolutionManual = false;
  renderMinimaxInputs();
}

/** 실제 첫 이미지의 크기를 자동 기본값으로 적용하되 직접 수정한 값은 보존합니다. */
function applyMinimaxAutomaticResolution() {
  const referenceImage = applicationState.minimaxInputImages[0];
  if (!referenceImage || applicationState.minimaxResolutionManual) return;
  element("minimax-width").value = referenceImage.width;
  element("minimax-height").value = referenceImage.height;
}

/** 선택 이미지와 실제 크기·혼합 여부·최종 공통 해상도 및 제출 건수를 표시합니다. */
function renderMinimaxInputs() {
  const selectedImages = applicationState.minimaxInputImages;
  const inputScope = element("minimax-input-scope").value;
  const folderScope = inputScope === "folder";
  const multipleImages = inputScope !== "single";
  const sourceLabel = inputScope === "job" && applicationState.minimaxInputJob
    ? `작업 ${applicationState.minimaxInputJob.description || applicationState.minimaxInputJob.job_id} · `
    : folderScope ? `${applicationState.minimaxInputDirectory || "결과물"} · ` : "";
  element("select-minimax-input").textContent = inputScope === "job" ? "작업 결과 선택" : folderScope ? "서버 폴더 선택" : "서버 이미지 선택";
  element("selected-images").textContent = applicationState.minimaxInputLoading ? "입력 이미지의 실제 크기를 확인하는 중…"
    : selectedImages.length ? `${sourceLabel}${selectedImages.length}개 이미지 선택됨 · 이미지마다 영상 한 개`
      : "선택한 이미지가 없습니다.";
  const selectedIdentifiers = new Set(selectedImages.map(image => image.output_id));
  element("minimax-selected-images").innerHTML = applicationState.minimaxInputCandidates.map(image =>
    `<label class="input-image-card"><img src="/api/outputs/preview/${encodedOutputPath(image.path)}" alt="" loading="lazy" />${multipleImages ? `<input type="checkbox" data-minimax-selected="${image.output_id}" aria-label="${escapeHtml(image.name)} 포함" ${selectedIdentifiers.has(image.output_id) ? "checked" : ""} />` : ""}<span>${escapeHtml(image.name)} · ${image.width} × ${image.height}</span></label>`,
  ).join("");
  const referenceImage = selectedImages[0];
  const mixedDimensions = new Set(selectedImages.map(image => `${image.width}x${image.height}`)).size > 1;
  const requestedWidth = Number(element("minimax-width").value);
  const requestedHeight = Number(element("minimax-height").value);
  const executionWidth = Math.ceil(requestedWidth / 32) * 32;
  const executionHeight = Math.ceil(requestedHeight / 32) * 32;
  const dimensionsAreValid = Number.isInteger(requestedWidth) && Number.isInteger(requestedHeight) &&
    requestedWidth >= 16 && requestedHeight >= 16 && executionWidth <= 8192 && executionHeight <= 8192;
  element("minimax-resolution-reference").textContent = referenceImage
    ? `기준: ${referenceImage.name} · 원본 ${referenceImage.width} × ${referenceImage.height} · ${applicationState.minimaxResolutionManual ? "직접 입력" : "자동 입력"}${mixedDimensions ? " · 해상도가 다른 이미지가 섞여 있습니다." : ""} · ${dimensionsAreValid ? `제출 ${executionWidth} × ${executionHeight}` : "16~8192 범위의 해상도를 직접 입력해 주세요."}`
    : "입력 이미지의 실제 크기로 해상도를 자동 입력합니다.";
  element("minimax-automatic-resolution").disabled = !referenceImage || applicationState.minimaxInputLoading;
  element("minimax-submit-summary").textContent = `${element("minimax-generation-mode").value} · 이미지 ${selectedImages.length}장 → 영상 ${selectedImages.length}개 · 공통 ${executionWidth} × ${executionHeight} · 각 ${element("minimax-duration").value}초`;
}

/** 공용 서버 탐색기에서 확정한 후보만 실제 해상도를 확인하여 입력으로 사용합니다. */
async function selectMinimaxInputs() {
  if (element("submit-button").disabled) return;
  const inputScope = element("minimax-input-scope").value;
  const selection = inputScope === "job" ? await chooseJobInput()
    : await chooseOutputFolder(inputScope === "single" ? "영상에 사용할 이미지 한 장을 선택해 주세요." : "폴더의 직하위 이미지마다 영상 한 개를 생성합니다. 최대 100장을 선택해 주세요.", inputScope);
  if (selection === null) return;
  await applyMinimaxInputSelection(selection, inputScope);
}

/** 선택을 확정한 이미지의 현재 상태와 해상도를 검증하고 공통 Snapshot 입력을 준비합니다. */
async function applyMinimaxInputSelection(selection, inputScope) {
  const selectionRevision = ++applicationState.minimaxSelectionRevision;
  applicationState.minimaxInputLoading = true;
  applicationState.minimaxInputImages = [];
  applicationState.minimaxInputCandidates = [];
  applicationState.minimaxInputDirectory = null;
  applicationState.minimaxInputJob = null;
  renderMinimaxInputs();
  try {
    const inspection = await apiRequest("/api/outputs/input-images/inspect", {
      method: "POST", body: JSON.stringify({ output_ids: selection.files.map(image => image.output_id), input_job_id: selection.job?.job_id || null }),
    });
    if (selectionRevision !== applicationState.minimaxSelectionRevision) return;
    applicationState.minimaxInputImages = inspection.files;
    applicationState.minimaxInputCandidates = inspection.files;
    applicationState.minimaxInputDirectory = inputScope === "folder" ? selection.input_directory : null;
    applicationState.minimaxInputJob = inputScope === "job" ? selection.job : null;
    applyMinimaxAutomaticResolution();
    showNotice(`입력 이미지 ${inspection.files.length}장을 선택했습니다.`);
  } finally {
    if (selectionRevision === applicationState.minimaxSelectionRevision) {
      applicationState.minimaxInputLoading = false;
      renderMinimaxInputs();
    }
  }
}

/** 이력의 이미지 선택을 확정한 뒤 MiniMax로 이동하며 원본 Prompt는 복사하지 않습니다. */
async function useJobResultsAsMinimaxInput(jobIdentifier) {
  if (element("submit-button").disabled || applicationState.restoringJobId) return;
  const selection = await chooseJobInput(jobIdentifier);
  if (selection === null) return;
  if (element("generate-workflow").value !== "minimax_h3") resetGenerationWorkflow("minimax_h3");
  element("minimax-input-scope").value = "job";
  clearMinimaxInputs();
  switchView("generate", { resetScroll: true });
  await applyMinimaxInputSelection(selection, "job");
}

/** 작업 선택 창의 상태와 선택 개수를 갱신하며 Checkbox의 Focus는 유지합니다. */
function renderJobInputPicker(rebuildContents = true) {
  const pickerState = jobInputPickerState;
  const showingImages = pickerState.jobIdentifier !== null;
  const selectedCount = pickerState.selectedImageIds.size;
  element("job-input-back").classList.toggle("hidden", !showingImages);
  element("job-input-source").textContent = pickerState.job
    ? `${pickerState.job.workflow} · ${pickerState.job.description || "설명 없음"} · ${pickerState.job.job_id}` : "";
  element("job-input-status").textContent = pickerState.error || (pickerState.loading ? "불러오는 중…"
    : showingImages ? `이미지 ${pickerState.images.length}장 · 선택 ${selectedCount}장 / 최대 100장`
      : pickerState.jobs.length ? "입력으로 사용할 작업을 선택해 주세요." : "사용할 수 있는 이미지가 있는 작업이 없습니다.");
  element("job-input-retry").classList.toggle("hidden", !pickerState.error);
  element("job-input-jobs").classList.toggle("hidden", showingImages);
  element("job-input-pagination").classList.toggle("hidden", showingImages);
  element("job-input-images").classList.toggle("hidden", !showingImages);
  element("job-input-select-all").classList.toggle("hidden", !showingImages);
  element("job-input-select-all").disabled = pickerState.loading || !pickerState.images.length;
  element("job-input-select-all").textContent = selectedCount === pickerState.images.length ? "전체 해제" : "전체 선택";
  element("job-input-page").textContent = `${pickerState.page} / ${pickerState.totalPages}`;
  element("job-input-previous").disabled = pickerState.loading || pickerState.page <= 1;
  element("job-input-next").disabled = pickerState.loading || pickerState.page >= pickerState.totalPages;
  element("job-input-confirm").disabled = pickerState.loading || Boolean(pickerState.error) || !pickerState.job || selectedCount < 1 || selectedCount > 100;
  if (!rebuildContents) return;
  element("job-input-jobs").innerHTML = pickerState.jobs.map(job =>
    `<li><button class="button subtle" type="button" data-pick-input-job="${escapeHtml(job.job_id)}" ${pickerState.loading ? "disabled" : ""}>${escapeHtml(job.description || "설명 없음")}<br>${escapeHtml(job.workflow)} · ${escapeHtml(formatKoreanTimestamp(job.created_at))} · 이미지 ${job.image_count}장<br>${escapeHtml(job.job_id)}</button></li>`).join("");
  element("job-input-images").innerHTML = pickerState.images.map(image =>
    `<label class="input-image-card"><img src="/api/outputs/preview/${encodedOutputPath(image.path)}" loading="lazy" alt="" /><input type="checkbox" data-pick-job-input="${image.output_id}" aria-label="${escapeHtml(image.name)} 포함" ${pickerState.selectedImageIds.has(image.output_id) ? "checked" : ""} /><span>${escapeHtml(image.path)}</span></label>`).join("");
}

/** 작은 작업 요약만 페이지 조회하며 닫히거나 다른 조회로 바뀐 응답은 무시합니다. */
async function loadJobInputJobs(page = 1) {
  const pickerState = jobInputPickerState;
  const revision = ++pickerState.revision;
  Object.assign(pickerState, { page, jobIdentifier: null, job: null, jobs: [], images: [], selectedImageIds: new Set(), loading: true, error: "" });
  renderJobInputPicker();
  try {
    const result = await apiRequest(`/api/outputs/input-jobs?page=${page}&page_size=10`);
    if (revision !== pickerState.revision) return;
    Object.assign(pickerState, { jobs: result.items, totalPages: result.total_pages });
  } catch (error) {
    if (revision === pickerState.revision) pickerState.error = error.message;
  } finally {
    if (revision === pickerState.revision) {
      pickerState.loading = false;
      renderJobInputPicker();
    }
  }
}

/** 작업 소속의 현재 이미지 목록을 조회하고 전체 후보를 표시하여 임의로 100장만 자르지 않습니다. */
async function loadJobInputImages(jobIdentifier) {
  const pickerState = jobInputPickerState;
  const revision = ++pickerState.revision;
  Object.assign(pickerState, { jobIdentifier, job: null, images: [], selectedImageIds: new Set(), loading: true, error: "" });
  renderJobInputPicker();
  try {
    const result = await apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}/input-images`);
    if (revision !== pickerState.revision) return;
    pickerState.job = result.job;
    pickerState.images = result.files;
    pickerState.selectedImageIds = new Set(result.files.map(image => image.output_id));
  } catch (error) {
    if (revision === pickerState.revision) pickerState.error = error.message;
  } finally {
    if (revision === pickerState.revision) {
      pickerState.loading = false;
      renderJobInputPicker();
    }
  }
}

/** 작업 결과 선택 창을 열고 확정된 명시적 이미지 목록 또는 취소 결과를 기다립니다. */
function chooseJobInput(initialJobIdentifier = null) {
  finishJobInputSelection(null, true);
  const pickerState = jobInputPickerState;
  pickerState.openingElement = document.activeElement;
  pickerState.page = 1;
  pickerState.totalPages = 1;
  const selectionPromise = new Promise(resolve => { pickerState.resolveSelection = resolve; });
  element("job-input-picker").showModal();
  if (initialJobIdentifier) loadJobInputImages(initialJobIdentifier);
  else loadJobInputJobs();
  return selectionPromise;
}

/** 선택 창을 닫고 대기 중인 조회를 무효화하며 필요한 경우 원래 버튼으로 Focus를 돌립니다. */
function finishJobInputSelection(selection, skipFocus = false) {
  const pickerState = jobInputPickerState;
  pickerState.revision += 1;
  const resolveSelection = pickerState.resolveSelection;
  pickerState.resolveSelection = null;
  const openingElement = pickerState.openingElement;
  pickerState.openingElement = null;
  if (element("job-input-picker").open) element("job-input-picker").close();
  if (resolveSelection) resolveSelection(selection);
  if (!skipFocus && openingElement?.isConnected) openingElement.focus();
}

/** 작업 목록·이미지 선택·페이지 이동과 Escape 취소를 공용 선택 흐름에 연결합니다. */
function bindJobInputPickerEvents() {
  element("job-input-jobs").addEventListener("click", event => {
    const jobButton = event.target.closest("[data-pick-input-job]");
    if (jobButton && !jobButton.disabled) loadJobInputImages(jobButton.dataset.pickInputJob);
  });
  element("job-input-images").addEventListener("change", event => {
    const checkbox = event.target.closest("[data-pick-job-input]");
    if (!checkbox || jobInputPickerState.loading) return;
    const outputIdentifier = Number(checkbox.dataset.pickJobInput);
    if (checkbox.checked) jobInputPickerState.selectedImageIds.add(outputIdentifier);
    else jobInputPickerState.selectedImageIds.delete(outputIdentifier);
    renderJobInputPicker(false);
  });
  element("job-input-select-all").addEventListener("click", () => {
    const pickerState = jobInputPickerState;
    pickerState.selectedImageIds = pickerState.selectedImageIds.size === pickerState.images.length
      ? new Set() : new Set(pickerState.images.map(image => image.output_id));
    renderJobInputPicker();
  });
  element("job-input-back").addEventListener("click", () => loadJobInputJobs(jobInputPickerState.page));
  element("job-input-previous").addEventListener("click", () => loadJobInputJobs(jobInputPickerState.page - 1));
  element("job-input-next").addEventListener("click", () => loadJobInputJobs(jobInputPickerState.page + 1));
  element("job-input-retry").addEventListener("click", () => jobInputPickerState.jobIdentifier
    ? loadJobInputImages(jobInputPickerState.jobIdentifier) : loadJobInputJobs(jobInputPickerState.page));
  element("job-input-cancel").addEventListener("click", () => finishJobInputSelection(null));
  element("job-input-picker").addEventListener("cancel", event => {
    event.preventDefault();
    finishJobInputSelection(null);
  });
  element("job-input-picker").addEventListener("close", () => {
    if (!element("job-input-picker").open) finishJobInputSelection(null);
  });
  element("job-input-confirm").addEventListener("click", () => {
    if (element("job-input-confirm").disabled) return;
    const pickerState = jobInputPickerState;
    finishJobInputSelection({ job: pickerState.job, files: pickerState.images.filter(image => pickerState.selectedImageIds.has(image.output_id)) });
  });
}

/** Batch를 서버에 제출합니다. */
async function submitBatch() {
  const workflow = element("generate-workflow").value;
  if (applicationState.selectedLoras.length) {
    validateLoraEntries(applicationState.selectedLoras, workflow);
    const missingLoras = applicationState.loraCatalogAvailable
      ? applicationState.selectedLoras.filter((lora) => !applicationState.availableLoras.includes(lora.name))
      : [];
    if (missingLoras.length)
      throw new Error(`ComfyUI에서 LoRA를 찾을 수 없습니다: ${missingLoras.map((lora) => lora.name).join(", ")}`);
  }
  if (
    workflow === "minimax_h3" &&
    applicationState.minimaxInputImages.length === 0
  ) {
    throw new Error("MiniMax 입력 이미지를 선택해 주세요.");
  }
  if (workflow === "minimax_h3" && applicationState.minimaxInputLoading) throw new Error("입력 이미지 확인이 끝난 뒤 제출해 주세요.");
  const submitButton = element("submit-button");
  submitButton.disabled = true;
  submitButton.textContent = "제출 중...";
  try {
    const response = await apiRequest("/api/batches", {
      method: "POST",
      body: JSON.stringify({
        workflow,
        description: element("job-description").value,
        folder_id: element("job-history-folder").value || null,
        body: generateBody(),
        selected_tag_ids: activeSelectedTagIds(),
        count: workflow === "anima" ? Number(element("generate-count").value) : 1,
        settings: generationSettings(),
        loras: applicationState.selectedLoras,
        prompt_preset_id: applicationState.currentPresetId,
        lora_preset_id: applicationState.currentLoraPresetId,
        lora_preset_name: generationLoraPresetName(),
        output_ids: workflow === "minimax_h3" ? applicationState.minimaxInputImages.map(image => image.output_id) : [],
        input_scope: workflow === "minimax_h3" ? element("minimax-input-scope").value : null,
        input_directory: workflow === "minimax_h3" ? applicationState.minimaxInputDirectory : null,
        input_job_id: workflow === "minimax_h3" ? applicationState.minimaxInputJob?.job_id || null : null,
      }),
    });
    showNotice(
      `작업 접수 완료 · 요청 ${response.request_ids.length}건. 진행 상태는 작업 목록에서 확인하세요.`,
    );
    applicationState.jobsPage = 1;
    await loadJobs();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "작업 제출";
  }
}

/** 저장된 실제 LoRA 목록과 표시용 이름으로 작업 요약의 조합 출처를 반환합니다. */
function jobLoraSummary(jobInputs) {
  if (!Array.isArray(jobInputs.loras) || jobInputs.loras.length === 0) return "lora없음";
  return `LoRA ${jobInputs.lora_preset_name || "custom"}`;
}

/** 상위 작업에 속한 ComfyUI 요청의 상태와 조작 버튼을 표시합니다. */
function requestCardMarkup(request, statusNames, commonInputs) {
  const sourceImage = request.result.source_image;
  const promptText = request.result.prompt || "확정 전";
  const negativeText = request.result.negative ?? commonInputs.body?.negative ?? "";
  const selectedLoras = Array.isArray(commonInputs.loras) ? commonInputs.loras : [];
  const loraDescriptions = [];
  for (const selectedLora of selectedLoras) {
    if (!selectedLora.name) continue;
    loraDescriptions.push(`${selectedLora.name} (STR ${selectedLora.strength ?? 1})`);
  }
  const loraText = loraDescriptions.join(", ") || "lora없음";
  const selectedPath = request.result.selected_path || [];
  const selectedTagNames = selectedPath.map((item) => item.name).join(" → ");
  const negativeSelectedPath = request.result.negative_selected_path || [];
  const negativeTagNames = negativeSelectedPath.map((item) => item.name).join(" → ");
  const promptIsExpanded = applicationState.expandedRequestPromptIds.has(request.request_id);
  const requestPromptDetailsMarkup = [
    `<div class="job-detail"><strong>Prompt</strong> ${escapeHtml(promptText)}</div>`,
    selectedTagNames ? `<div class="job-detail"><strong>태그 경로</strong> ${escapeHtml(selectedTagNames)}</div>` : "",
    negativeText ? `<div class="job-detail"><strong>Negative Prompt</strong> ${escapeHtml(negativeText)}</div>` : "",
    negativeTagNames ? `<div class="job-detail"><strong>Negative 태그 경로</strong> ${escapeHtml(negativeTagNames)}</div>` : "",
  ].join("");
  return `
    <div class="job-request" data-request-prompt-card="${escapeHtml(request.request_id)}">
      <div>
        <strong>요청 ${request.request_index} · ${escapeHtml(request.request_id)}</strong>
        <p>prompt_id ${escapeHtml(request.prompt_id || "대기 중")}</p>
      </div>
      <span class="status-badge ${escapeHtml(request.status)}">${escapeHtml(statusNames[request.status] || request.status)}</span>
      <div class="job-prompts request-prompts" role="button" tabindex="0" data-toggle-request-prompt="${escapeHtml(request.request_id)}" aria-expanded="${promptIsExpanded}" title="${promptIsExpanded ? "하위 요청 카드를 눌러 Prompt·태그 경로 접기" : "하위 요청 카드를 눌러 전체 Prompt·태그 경로 보기"}">${requestPromptDetailsMarkup}</div>
      <div class="job-detail"><strong>LoRA</strong> ${escapeHtml(loraText)}</div>
      ${sourceImage ? `<div class="job-detail"><strong>입력 이미지</strong> ${sourceImage.job_id ? `작업 ${escapeHtml(sourceImage.job_id)} · ` : ""}${escapeHtml(sourceImage.path)} · ${sourceImage.width} × ${sourceImage.height}</div>` : ""}
      ${request.error_message ? `<div class="job-detail"><strong>오류</strong> ${escapeHtml(request.error_message)}</div>` : ""}
      <div class="job-actions inline-actions">
        ${["submitting", "pending", "running"].includes(request.status) ? `<button class="button subtle small" data-cancel-request="${escapeHtml(request.request_id)}">요청 취소</button>` : ""}
        <a class="button subtle small" data-navigation data-show-request-results="${escapeHtml(request.request_id)}" href="${escapeHtml(navigationUrl({ viewName: "outputs", pageNumber: 1, outputFilter: { type: "request", id: request.request_id } }))}">요청 결과 보기</a>
      </div>
    </div>`;
}

/** 보호되지 않고 활성 요청이 없는 작업만 삭제 대상으로 허용합니다. */
function canDeleteJobHistory(job) {
  const activeStatuses = ["submitting", "pending", "running", "cancelling"];
  const hasActiveRequests = job.requests
    ? job.requests.some(request => activeStatuses.includes(request.status))
    : activeStatuses.some(status => job.status_counts[status]);
  return !job.deletion_protected && !hasActiveRequests;
}

/** 선택 모드의 카드 본문·썸네일 클릭을 기존 Checkbox 동작으로 연결합니다. */
function toggleSelectionFromCardClick(event, cardSelector, checkboxSelector, previewSelector, selectionIsBusy) {
  const selectionCard = event.target.closest(cardSelector);
  const selectionCheckbox = selectionCard?.querySelector(checkboxSelector);
  if (!selectionCheckbox) return;
  const interactiveTarget = event.target.closest("a, button, input, select, textarea, label, summary");
  if (interactiveTarget && !interactiveTarget.matches(previewSelector)) return;

  event.preventDefault();
  event.stopImmediatePropagation();
  if (!selectionIsBusy && !selectionCheckbox.disabled && !window.getSelection()?.toString()) {
    selectionCheckbox.click();
  }
}

/** 선택·삭제·보호 설정을 변경 중인지 확인합니다. */
function jobSelectionIsBusy() {
  return jobHistoryFolderState.busy || outputFolderPickerState.resolveSelection !== null || applicationState.deletingSelectedJobs || applicationState.selectingEveryJob ||
    applicationState.updatingJobProtectionId !== null || applicationState.updatingJobDescriptionId !== null || applicationState.movingJobId !== null;
}

/** 선택 모드, 선택 건수와 삭제 처리 상태에 맞춰 일괄 조작 버튼을 갱신합니다. */
function updateJobSelectionControls() {
  const selectionMode = applicationState.jobSelectionMode;
  const deletingJobs = applicationState.deletingSelectedJobs;
  const selectionIsBusy = jobSelectionIsBusy();
  const selectedCount = applicationState.selectedJobIds.size;
  const selectableJobs = applicationState.visibleJobs;
  const allSelected = selectableJobs.length > 0 && selectableJobs.every((job) =>
    applicationState.selectedJobIds.has(job.job_id),
  );
  element("toggle-job-selection").textContent = selectionMode ? "선택 취소" : "선택";
  element("toggle-job-selection").setAttribute("aria-expanded", String(selectionMode));
  element("toggle-job-selection").disabled = selectionIsBusy;
  element("job-selection-actions").classList.toggle("hidden", !selectionMode);
  element("select-all-jobs").textContent = allSelected ? "현재 페이지 선택 해제" : "현재 페이지 선택";
  element("select-all-jobs").disabled = selectionIsBusy || selectableJobs.length === 0;
  const everyJobSelected = applicationState.selectableJobIds.size > 0 &&
    [...applicationState.selectableJobIds].every((jobIdentifier) => applicationState.selectedJobIds.has(jobIdentifier));
  element("select-every-job").textContent = applicationState.selectingEveryJob
    ? "작업 조회 중…" : everyJobSelected ? "범위 전체 선택 해제" : "현재 범위 전체 선택";
  element("select-every-job").disabled = selectionIsBusy || applicationState.selectableJobIds.size === 0;
  element("selected-job-count").textContent = deletingJobs ? "삭제 중…" : `${selectedCount}개 선택`;
  const deletableSelectedCount = [...applicationState.selectedJobIds].filter(identifier => applicationState.deletableJobIds.has(identifier)).length;
  element("move-selected-job-folder").disabled = selectionIsBusy || selectedCount === 0;
  element("delete-selected-job-history").disabled = selectionIsBusy || deletableSelectedCount === 0;
  element("delete-selected-job-outputs").disabled = selectionIsBusy || deletableSelectedCount === 0;
  element("delete-selected-job-history").textContent = `이력만 삭제 (${deletableSelectedCount})`;
  element("delete-selected-job-outputs").textContent = `이력·결과물 삭제 (${deletableSelectedCount})`;
  const clearJobsFilterLink = element("clear-jobs-filter");
  clearJobsFilterLink.setAttribute("aria-disabled", String(selectionIsBusy));
  if (selectionIsBusy) clearJobsFilterLink.removeAttribute("href");
  else clearJobsFilterLink.href = navigationUrl({ viewName: "jobs", pageNumber: 1,
    jobFolderId: applicationState.jobFolderId, jobSearch: applicationState.jobSearch });
  element("jobs-pagination").toggleAttribute("inert", selectionIsBusy);
  element("jobs-folder-tree").toggleAttribute("inert", selectionIsBusy);
  element("jobs-search-form").toggleAttribute("inert", selectionIsBusy);
  const scopeIsChanging = applicationState.jobsSelectionScope !== null && applicationState.jobsSelectionScope !== currentJobHistoryScope();
  element("jobs-list").toggleAttribute("inert", scopeIsChanging);
  element("job-selection-actions").toggleAttribute("inert", scopeIsChanging);
  for (const checkbox of element("jobs-list").querySelectorAll("[data-select-job]")) {
    checkbox.checked = applicationState.selectedJobIds.has(checkbox.dataset.selectJob);
    checkbox.closest(".job-card").classList.toggle("job-selected", checkbox.checked);
  }
  renderJobHistoryFolders();
}

/** 현재 페이지의 작업을 상태·보호 여부와 무관하게 선택하거나 해제합니다. */
function toggleAllJobSelections() {
  if (!applicationState.jobSelectionMode || jobSelectionIsBusy()) return;
  const selectableJobs = applicationState.visibleJobs;
  const allSelected = selectableJobs.every((job) => applicationState.selectedJobIds.has(job.job_id));
  for (const job of selectableJobs) {
    if (allSelected) applicationState.selectedJobIds.delete(job.job_id);
    else applicationState.selectedJobIds.add(job.job_id);
  }
  renderJobsList();
}

/** 현재 분류·검색의 모든 페이지에서 작업을 선택하고 삭제 후보는 별도로 유지합니다. */
async function toggleEveryJobSelection() {
  if (!applicationState.jobSelectionMode || jobSelectionIsBusy()) return;
  const everyJobSelected = applicationState.selectableJobIds.size > 0 &&
    [...applicationState.selectableJobIds].every((jobIdentifier) => applicationState.selectedJobIds.has(jobIdentifier));
  if (everyJobSelected) {
    applicationState.selectedJobIds.clear();
    renderJobsList();
    return;
  }
  applicationState.selectingEveryJob = true;
  applicationState.jobsLoadRevision += 1;
  const selectionScope = currentJobHistoryScope();
  renderJobsList();
  try {
    const query = jobHistoryQuery();
    const candidates = await apiRequest(`/api/jobs/selection-candidates?${query}`);
    if (!applicationState.jobSelectionMode || selectionScope !== currentJobHistoryScope()) return;
    applicationState.selectableJobIds = new Set(candidates.job_ids);
    applicationState.deletableJobIds = new Set(candidates.deletable_job_ids);
    applicationState.selectedJobIds = new Set(candidates.job_ids);
  } finally {
    applicationState.selectingEveryJob = false;
    renderJobsList();
  }
}

/** 선택한 작업의 현재 설명을 독립된 Dialog에서 편집하여 Polling에 덮어쓰이지 않게 합니다. */
function openJobDescriptionEditor(jobIdentifier, openingElement) {
  if (jobSelectionIsBusy()) return;
  const job = applicationState.visibleJobs.find(candidate => candidate.job_id === jobIdentifier);
  if (!job) return;
  closeJobDescriptionEditor(false);
  jobDescriptionEditorState.jobIdentifier = jobIdentifier;
  jobDescriptionEditorState.openingElement = openingElement;
  element("job-description-input").value = job.description || "";
  element("job-description-input").disabled = false;
  element("job-description-save").disabled = false;
  element("job-description-save").textContent = "저장";
  element("job-description-status").textContent = "";
  element("job-description-dialog").showModal();
  element("job-description-input").select();
}

/** 편집을 닫고 늦은 저장 응답이 Dialog를 다시 조작하지 않도록 세대를 변경합니다. */
function closeJobDescriptionEditor(restoreFocus = true) {
  const editorState = jobDescriptionEditorState;
  const jobIdentifier = editorState.jobIdentifier;
  const openingElement = editorState.openingElement;
  editorState.revision += 1;
  editorState.jobIdentifier = null;
  editorState.openingElement = null;
  const dialog = element("job-description-dialog");
  if (dialog.open) dialog.close();
  if (!restoreFocus) return;
  const currentButton = jobIdentifier ? document.querySelector(`[data-edit-job-description="${CSS.escape(jobIdentifier)}"]`) : null;
  if (currentButton) currentButton.focus({ preventScroll: true });
  else if (openingElement?.isConnected) openingElement.focus({ preventScroll: true });
}

/** 설명만 저장하고 현재 페이지·펼침·선택·생성 폼을 유지한 채 작업 목록을 갱신합니다. */
async function saveJobDescription() {
  const editorState = jobDescriptionEditorState;
  const jobIdentifier = editorState.jobIdentifier;
  if (!jobIdentifier || applicationState.updatingJobDescriptionId !== null) return;
  const revision = editorState.revision;
  let descriptionSaved = false;
  applicationState.updatingJobDescriptionId = jobIdentifier;
  applicationState.jobsLoadRevision += 1;
  element("job-description-input").disabled = true;
  element("job-description-save").disabled = true;
  element("job-description-save").textContent = "저장 중…";
  element("job-description-status").textContent = "";
  renderJobsList();
  try {
    const result = await apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}/description`, {
      method: "PATCH", body: JSON.stringify({ description: element("job-description-input").value }),
    });
    const job = applicationState.visibleJobs.find(candidate => candidate.job_id === jobIdentifier);
    if (job) job.description = result.description;
    const cachedJob = applicationState.jobDetails.get(jobIdentifier)?.job;
    if (cachedJob) cachedJob.description = result.description;
    if (applicationState.minimaxInputJob?.job_id === jobIdentifier) {
      applicationState.minimaxInputJob.description = result.description;
      renderMinimaxInputs();
    }
    applicationState.jobsRenderSignature = null;
    await loadJobs();
    descriptionSaved = true;
    showNotice("작업 설명을 수정했습니다.");
  } catch (error) {
    if (revision === editorState.revision) element("job-description-status").textContent = error.message;
    else showNotice(error.message, true);
  } finally {
    applicationState.updatingJobDescriptionId = null;
    renderJobsList();
    if (revision === editorState.revision) {
      if (descriptionSaved) closeJobDescriptionEditor();
      else {
        element("job-description-input").disabled = false;
        element("job-description-save").disabled = false;
        element("job-description-save").textContent = "저장";
        element("job-description-input").focus({ preventScroll: true });
      }
    }
  }
}

/** 삭제 보호만 변경하며 분류 변경에 사용할 선택은 유지합니다. */
async function toggleJobDeletionProtection(jobIdentifier) {
  if (jobSelectionIsBusy()) return;
  const job = applicationState.visibleJobs.find((candidate) => candidate.job_id === jobIdentifier);
  if (!job) return;
  applicationState.updatingJobProtectionId = jobIdentifier;
  renderJobsList();
  try {
    const result = await apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}/protection`, {
      method: "PATCH", body: JSON.stringify({ deletion_protected: !job.deletion_protected }),
    });
    applicationState.outputsRenderSignature = null;
    await loadJobs();
    showNotice(result.deletion_protected ? "작업의 삭제 보호를 설정했습니다." : "작업의 삭제 보호를 해제했습니다.");
  } finally {
    applicationState.updatingJobProtectionId = null;
    renderJobsList();
  }
}

/** 기록된 Prompt preset이 현재 본문과 같은 경우에만 연결합니다. */
function matchingJobPromptPreset(workflow, jobInputs) {
  let candidatePresets = applicationState.presets.filter((candidate) => candidate.workflow === workflow);
  if (jobInputs.prompt_preset_id) {
    candidatePresets = candidatePresets.filter((candidate) => candidate.preset_id === jobInputs.prompt_preset_id);
  }
  const originalBody = jobInputs.body;
  const matchingPresets = candidatePresets.filter((candidate) =>
    candidate.body.prompt === originalBody.prompt &&
    (workflow !== "anima" || (candidate.body.negative || "") === (originalBody.negative || "")),
  );
  return matchingPresets.length === 1 ? matchingPresets[0] : null;
}

/** 현재 LoRA preset과 기록된 파일 순서 및 강도가 같을 때만 연결합니다. */
function matchingJobLoraPreset(workflow, jobInputs) {
  const selectedLoras = jobInputs.loras || [];
  if (!selectedLoras.length) return null;
  let preset = null;
  if (jobInputs.lora_preset_id) {
    preset = applicationState.loraPresets.find((candidate) =>
      candidate.preset_id === jobInputs.lora_preset_id && candidate.workflow === workflow,
    );
  } else if (jobInputs.lora_preset_name) {
    const namedPresets = applicationState.loraPresets.filter((candidate) =>
      candidate.name === jobInputs.lora_preset_name && candidate.workflow === workflow,
    );
    if (namedPresets.length === 1) preset = namedPresets[0];
  }
  if (!preset) return null;
  const originalCombination = normalizeLoraEntries(selectedLoras, workflow);
  const currentCombination = normalizeLoraEntries(preset.loras, workflow);
  return JSON.stringify(originalCombination) === JSON.stringify(currentCombination) ? preset : null;
}

/** 기록된 옵션을 채우고 목록에 없는 Anima 해상도는 사용자 지정으로 표시합니다. */
function restoreGenerationSettings(workflow, settings) {
  if (workflow === "anima") {
    const width = Number(settings.width ?? element("anima-width").defaultValue);
    const height = Number(settings.height ?? element("anima-height").defaultValue);
    let matchingRatio = "custom";
    for (const [aspectRatio, resolutions] of Object.entries(ANIMA_RESOLUTIONS)) {
      if (resolutions.some(([candidateWidth, candidateHeight]) => candidateWidth === width && candidateHeight === height)) {
        matchingRatio = aspectRatio;
        break;
      }
    }
    element("anima-aspect-ratio").value = matchingRatio;
    updateAnimaResolutionOptions();
    if (matchingRatio !== "custom") element("anima-resolution").value = `${width}x${height}`;
    element("anima-width").value = width;
    element("anima-height").value = height;
    element("anima-steps").value = settings.steps ?? element("anima-steps").defaultValue;
    element("anima-cfg").value = settings.cfg ?? element("anima-cfg").defaultValue;
    return;
  }
  for (const [inputIdentifier, settingKey] of [
    ["minimax-width", "width"], ["minimax-height", "height"],
    ["minimax-duration", "duration"], ["minimax-frame-rate", "frame_rate"],
    ["minimax-upscale-model", "upscale_model_name"],
  ]) {
    const inputElement = element(inputIdentifier);
    inputElement.value = settings[settingKey] ?? inputElement.defaultValue;
  }
  element("minimax-upscale").value = settings.upscale_mode || "off";
  element("minimax-generation-mode").value = settings.generation_mode || "FL2VA";
  element("minimax-input-scope").value = settings.input_scope || "single";
  applicationState.minimaxResolutionManual = true;
}

/** 상위 작업의 공통 입력을 현재 목록에 맞춰 복원하며 새 요청은 제출하지 않습니다. */
async function restoreJobGeneration(jobIdentifier) {
  if (applicationState.restoringJobId) return;
  if (element("submit-button").disabled) throw new Error("작업 제출이 끝난 뒤 복원해 주세요.");
  applicationState.restoringJobId = jobIdentifier;
  element("submit-button").disabled = true;
  renderJobsList();
  try {
    const job = await apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}/inputs`);
    const jobInputs = job?.inputs;
    if (!job || !["anima", "minimax_h3"].includes(job.workflow) || typeof jobInputs?.body?.prompt !== "string")
      throw new Error("이 작업에는 복원할 원본 Prompt 기록이 없습니다.");
    const [currentPresets, currentLoraPresets, currentTags] = await Promise.all([
      apiRequest("/api/presets"), apiRequest("/api/loras/presets"), apiRequest("/api/tags"),
    ]);
    applicationState.presets = currentPresets;
    applicationState.loraPresets = currentLoraPresets;
    applicationState.tagGroups = currentTags.groups;
    applicationState.tagEntries = currentTags.entries;
    resetGenerationWorkflow(job.workflow);
    applicationState.currentBody = structuredClone(jobInputs.body);
    fillGenerationPromptFields(jobInputs.body, true);
    const promptPreset = matchingJobPromptPreset(job.workflow, jobInputs);
    applicationState.currentPresetId = promptPreset?.preset_id || null;
    applicationState.currentPresetVersion = promptPreset?.version || null;
    renderPresetList();
    const loraPreset = matchingJobLoraPreset(job.workflow, jobInputs);
    applyLoraCombination(job.workflow, jobInputs.loras || [], loraPreset?.preset_id || null);

    // 과거 정의는 되살리지 않고 현재 참조에서 체크할 수 있는 항목만 남깁니다.
    const currentTagIds = new Set(currentTags.entries.map((entry) => entry.tag_id));
    for (const selectedTag of jobInputs.selected_tags || []) {
      if (currentTagIds.has(selectedTag.tag_id)) applicationState.selectedTagIds.add(selectedTag.tag_id);
    }
    applicationState.selectedTagIds = new Set(activeSelectedTagIds());
    applicationState.expandedTagGroupIds = new Set(
      currentTags.groups.filter((group) => group.default_expanded).map((group) => group.group_id),
    );
    renderGenerateTagGroups();
    renderTagManager();
    restoreGenerationSettings(job.workflow, jobInputs.settings || {});
    element("generate-count").value = job.workflow === "anima" ? job.request_count : 1;
    element("job-description").value = job.description || "";
    element("job-history-folder").value = job.folder_id || "";
    clearMinimaxInputs(false);
    element("preview-results").innerHTML = "";
    element("preview-results").classList.add("hidden");
    switchView("generate", { resetScroll: true });
    showNotice(job.workflow === "minimax_h3"
      ? "작업의 입력값을 복원했습니다. MiniMax 입력 이미지를 다시 선택해 주세요."
      : "작업의 입력값을 복원했습니다.");
    await loadLoras();
  } finally {
    applicationState.restoringJobId = null;
    element("submit-button").disabled = false;
    renderJobsList();
  }
}

/** 한 번의 제출을 하나의 상위 작업 카드로 표시합니다. */
function jobCardMarkup(job, statusNames, openJobIds) {
  const summaryDetail = job.summary || job.inputs;
  const originalBody = summaryDetail.body || {};
  const originalPrompt = typeof originalBody.prompt === "string" ? originalBody.prompt : "기록 없음";
  const originalNegative = typeof originalBody.negative === "string" ? originalBody.negative : "";
  const promptIsExpanded = applicationState.expandedJobPromptIds.has(job.job_id);
  const loraSummary = jobLoraSummary(summaryDetail);
  const requestSettings = { ...summaryDetail.settings, ...summaryDetail.resolved?.settings };
  const dimensions = formatDimensions(requestSettings.width, requestSettings.height);
  const completedCount = job.status_counts.completed || 0;
  const failedCount = job.status_counts.failed || 0;
  const countUnit = job.workflow === "anima" ? "장" : "건";
  const progressText = `완료 ${completedCount}/${job.request_count}${countUnit}` +
    (failedCount ? ` · 실패 ${failedCount}` : "") +
    (job.status_counts.cancelled ? ` · 취소 ${job.status_counts.cancelled}` : "") +
    (job.status_counts.cancelling ? ` · 취소 중 ${job.status_counts.cancelling}` : "") +
    (job.cancellation_failures ? ` · 취소 전송 실패 ${job.cancellation_failures} · 재시도 중` : "");
  const openAttribute = openJobIds.has(job.job_id) ? " open" : "";
  const canCancel = ["submitting", "pending", "running", "cancelling"].some(status => job.status_counts[status]);
  const cancellationIsBusy = applicationState.cancellingJobIds.has(job.job_id) ||
    (job.cancellation_requested && !job.cancellation_failures);
  const cachedDetails = applicationState.jobDetails.get(job.job_id);
  const requests = job.requests || cachedDetails?.job?.requests;
  const requestMarkup = openJobIds.has(job.job_id) && requests
    ? requests.map(request => requestCardMarkup(request, statusNames, cachedDetails?.job?.inputs || summaryDetail)).join("")
    : `<p class="hint">${cachedDetails?.error ? escapeHtml(cachedDetails.error) : "하위 요청을 불러오는 중입니다."}</p>`;
  const canDelete = canDeleteJobHistory(job);
  const selectionCheckbox = applicationState.jobSelectionMode
    ? `<input class="job-selection-checkbox" type="checkbox" data-select-job="${escapeHtml(job.job_id)}"
        aria-label="작업 ${escapeHtml(job.job_id)} 선택" ${applicationState.selectedJobIds.has(job.job_id) ? "checked" : ""}
        ${jobSelectionIsBusy() ? "disabled" : ""}>`
    : "";
  return `
    <article class="job-card" data-job-prompt-card="${escapeHtml(job.job_id)}">
      <div class="job-selection-heading">
        ${selectionCheckbox}
        <div>
        <h3>${escapeHtml(job.workflow)}${job.workflow === "minimax_h3" ? ` · ${escapeHtml(requestSettings.generation_mode || "FL2VA")} · ${requestSettings.input_scope === "job" ? "작업 결과 일괄" : requestSettings.input_scope === "folder" ? "폴더 일괄" : "이미지 입력"}` : ""} · 작업 ${escapeHtml(job.job_id)}</h3>
        <p>${escapeHtml(formatKoreanTimestamp(job.created_at))} · ${dimensions.ratio} · ${dimensions.resolution} · CFG ${escapeHtml(requestSettings.cfg ?? "—")} · Steps ${escapeHtml(requestSettings.steps ?? "—")} · ${escapeHtml(progressText)} · ${escapeHtml(loraSummary)}</p>
        <p class="job-description"><span class="job-description-text">${job.description ? escapeHtml(job.description) : "(작업 설명 없음)"}</span><button class="job-description-edit" type="button" data-edit-job-description="${escapeHtml(job.job_id)}" aria-label="작업 설명 수정" title="작업 설명 수정" ${jobSelectionIsBusy() ? "disabled" : ""}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m16 3 5 5-12 12-6 1 1-6Z"></path><path d="m14 5 5 5"></path></svg></button></p>
        <button class="job-folder-location" data-move-job-folder="${escapeHtml(job.job_id)}" type="button" title="분류 변경" ${jobSelectionIsBusy() ? "disabled" : ""}>📁 ${escapeHtml(jobHistoryFolderLabel(job.folder_id))} <span aria-hidden="true">↗</span></button>
        ${requestSettings.input_scope === "job" ? `<p class="hint">입력 출처: 작업 ${escapeHtml(requestSettings.input_job_id)}</p>` : ""}
        </div>
      </div>
      <span class="status-badge ${escapeHtml(job.status)}">${escapeHtml(statusNames[job.status] || job.status)}</span>
      ${job.deletion_protected ? '<span class="job-protection-badge">삭제 보호됨</span>' : ""}
      ${jobHistoryPreviewMarkup(job)}
      <div class="job-prompts" role="button" tabindex="0" data-toggle-job-prompt="${escapeHtml(job.job_id)}" aria-expanded="${promptIsExpanded}" title="${promptIsExpanded ? "카드를 눌러 Prompt 접기" : "카드를 눌러 전체 Prompt 보기"}"><div class="job-detail job-original-prompt"><strong>입력 Prompt</strong> ${escapeHtml(originalPrompt)}</div>${originalNegative ? `<div class="job-detail job-original-negative-prompt"><strong>입력 Negative Prompt</strong> ${escapeHtml(originalNegative)}</div>` : ""}</div>
      <div class="job-actions inline-actions">
        ${job.workflow === "anima" && completedCount > 0 ? `<button class="button subtle small" data-use-job-input="${escapeHtml(job.job_id)}" ${jobSelectionIsBusy() || applicationState.restoringJobId || element("submit-button").disabled ? "disabled" : ""}>MiniMax 입력으로 사용</button>` : ""}
        <a class="button subtle small" data-navigation data-show-job-results="${escapeHtml(job.job_id)}" href="${escapeHtml(navigationUrl({ viewName: "outputs", pageNumber: 1, outputFilter: { type: "job", id: job.job_id } }))}">작업 결과 보기</a>
        <button class="button subtle small" data-move-job-outputs="${escapeHtml(job.job_id)}" ${canCancel || jobSelectionIsBusy() || outputSelectionIsBusy() ? "disabled" : ""} ${canCancel ? 'title="생성이 끝난 뒤 결과물을 이동할 수 있습니다."' : ""}>${applicationState.movingJobId === job.job_id ? "파일 이동 중…" : "파일 이동"}</button>
        <button class="button ${job.deletion_protected ? "job-protected" : "subtle"} small" data-toggle-job-protection="${escapeHtml(job.job_id)}" aria-pressed="${Boolean(job.deletion_protected)}" ${jobSelectionIsBusy() ? "disabled" : ""}>${job.deletion_protected ? "보호 해제" : "삭제 보호"}</button>
        ${canCancel ? `<button class="button subtle small" data-cancel-job="${escapeHtml(job.job_id)}" ${cancellationIsBusy ? "disabled" : ""}>${cancellationIsBusy ? "취소 처리 중" : job.cancellation_requested ? "취소 재시도" : "작업 취소"}</button>` : ""}
        ${canDelete && !applicationState.jobSelectionMode ? `<button class="button subtle small" data-delete-job="${escapeHtml(job.job_id)}">이력만 삭제</button><button class="button danger small" data-delete-job-outputs="${escapeHtml(job.job_id)}">이력·결과물 삭제</button>` : ""}
        <button class="button job-restore small" data-restore-job="${escapeHtml(job.job_id)}" ${applicationState.restoringJobId ? "disabled" : ""}>생성 탭에서 복원</button>
      </div>
      <details class="job-requests" data-job-details="${escapeHtml(job.job_id)}"${openAttribute}>
        <summary>하위 요청 ${job.request_count}건</summary>
        <div class="job-request-list">${requestMarkup}</div>
      </details>
    </article>`;
}

/** 카드 전체를 다시 그리지 않고 원본 Positive·Negative Prompt의 공통 접힘 상태를 바꿉니다. */
function toggleJobPromptExpansion(jobIdentifier) {
  const promptContainer = document.querySelector(`[data-toggle-job-prompt="${CSS.escape(jobIdentifier)}"]`);
  if (!promptContainer) return;
  const promptIsExpanded = !applicationState.expandedJobPromptIds.has(jobIdentifier);
  if (promptIsExpanded) applicationState.expandedJobPromptIds.add(jobIdentifier);
  else applicationState.expandedJobPromptIds.delete(jobIdentifier);
  promptContainer.setAttribute("aria-expanded", String(promptIsExpanded));
  promptContainer.title = promptIsExpanded ? "카드를 눌러 Prompt 접기" : "카드를 눌러 전체 Prompt 보기";
}

/** 하위 요청의 Prompt·태그 경로를 상위 카드 및 다른 요청과 독립적으로 펼치거나 접습니다. */
function toggleRequestPromptExpansion(requestIdentifier) {
  const promptContainer = document.querySelector(`[data-toggle-request-prompt="${CSS.escape(requestIdentifier)}"]`);
  if (!promptContainer) return;
  const promptIsExpanded = !applicationState.expandedRequestPromptIds.has(requestIdentifier);
  if (promptIsExpanded) applicationState.expandedRequestPromptIds.add(requestIdentifier);
  else applicationState.expandedRequestPromptIds.delete(requestIdentifier);
  promptContainer.setAttribute("aria-expanded", String(promptIsExpanded));
  promptContainer.title = promptIsExpanded ? "하위 요청 카드를 눌러 Prompt·태그 경로 접기" : "하위 요청 카드를 눌러 전체 Prompt·태그 경로 보기";
}

/** 작업 카드를 다시 그리면서 상위·하위 Prompt의 펼침 상태와 Keyboard focus를 유지합니다. */
function renderJobsList() {
  const statusNames = {
    submitting: "제출 중", pending: "대기", running: "실행 중", cancelling: "취소 중",
    completed: "완료", failed: "실패", partial: "일부 완료", cancelled: "취소", stopped: "중단",
  };
  const focusedJobId = document.activeElement?.dataset.selectJob;
  const focusedPromptJobId = document.activeElement?.dataset.toggleJobPrompt;
  const focusedPromptRequestId = document.activeElement?.dataset.toggleRequestPrompt;
  const focusedDescriptionJobId = document.activeElement?.dataset.editJobDescription;
  const openJobIds = new Set();
  for (const details of element("jobs-list").querySelectorAll("details[open]")) {
    openJobIds.add(details.dataset.jobDetails);
  }
  element("jobs-list").innerHTML = applicationState.visibleJobs.length
    ? applicationState.visibleJobs.map((job) => jobCardMarkup(job, statusNames, openJobIds)).join("")
    : `<p class="empty-state">${applicationState.jobsLoading && !applicationState.jobsLoadedOnce
      ? "작업을 불러오는 중입니다." : applicationState.jobsLoadError
        ? "작업 목록을 불러오지 못했습니다. 다시 조회해 주세요."
        : applicationState.jobFilterId ? "해당 작업 이력이 없습니다." : "제출한 작업이 없습니다."}</p>`;
  if (focusedJobId) {
    for (const checkbox of element("jobs-list").querySelectorAll("[data-select-job]")) {
      if (checkbox.dataset.selectJob === focusedJobId) checkbox.focus({ preventScroll: true });
    }
  }
  if (focusedPromptJobId) {
    document.querySelector(`[data-toggle-job-prompt="${CSS.escape(focusedPromptJobId)}"]`)?.focus({ preventScroll: true });
  }
  updateJobSelectionControls();
  for (const jobIdentifier of openJobIds) loadJobDetails(jobIdentifier);
  if (focusedPromptRequestId) {
    document.querySelector(`[data-toggle-request-prompt="${CSS.escape(focusedPromptRequestId)}"]`)?.focus({ preventScroll: true });
  }
  if (focusedDescriptionJobId) {
    document.querySelector(`[data-edit-job-description="${CSS.escape(focusedDescriptionJobId)}"]`)?.focus({ preventScroll: true });
  }
}

/** 상태 집계가 바뀌었는지 확인할 작은 상세 갱신 기준을 만듭니다. */
function jobDetailsSignature(job) {
  return JSON.stringify([job.updated_at, job.status_counts, job.cancellation_failures]);
}

/** 펼친 작업만 상세를 조회하고 동일 작업의 중복 요청은 합칩니다. */
async function loadJobDetails(jobIdentifier) {
  const job = applicationState.visibleJobs.find(candidate => candidate.job_id === jobIdentifier);
  if (!job) return;
  if (job.requests) {
    const requestList = document.querySelector(`[data-job-details="${CSS.escape(jobIdentifier)}"] .job-request-list`);
    if (requestList) {
      const statusNames = { submitting: "제출 중", pending: "대기", running: "실행 중", cancelling: "취소 중",
        completed: "완료", failed: "실패", partial: "일부 완료", cancelled: "취소", stopped: "중단" };
      requestList.innerHTML = job.requests.map(request => requestCardMarkup(request, statusNames, job.inputs)).join("");
    }
    return;
  }
  const signature = jobDetailsSignature(job);
  const cachedDetails = applicationState.jobDetails.get(jobIdentifier);
  if (cachedDetails?.loading) return cachedDetails.loadPromise.catch(() => {});
  if (cachedDetails?.signature === signature) return;
  const details = { job: cachedDetails?.job, signature, loading: true, error: null };
  applicationState.jobDetails.set(jobIdentifier, details);
  try {
    details.loadPromise = apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}`);
    details.job = await details.loadPromise;
  } catch (error) {
    details.error = error.message;
  } finally {
    details.loading = false;
    renderJobsList();
  }
}

/** 유효한 페이지는 링크로, 범위를 벗어난 이전·다음은 비활성 버튼으로 만듭니다. */
function paginationLinkMarkup(viewName, pageNumber, label, { current = false, disabled = false } = {}) {
  const pageAttribute = `data-${viewName}-page="${pageNumber}"`;
  const classAttribute = 'class="button subtle small"';
  if (disabled) return `<button ${classAttribute} ${pageAttribute} disabled>${escapeHtml(label)}</button>`;
  const currentAttribute = current ? ' aria-current="page"' : "";
  const destination = {
    viewName, pageNumber,
    jobFilterId: applicationState.jobFilterId,
    jobFolderId: applicationState.jobFolderId,
    jobSearch: applicationState.jobSearch,
    outputFilter: applicationState.outputFilter,
  };
  return `<a ${classAttribute} ${pageAttribute}${currentAttribute} data-navigation href="${escapeHtml(navigationUrl(destination))}">${escapeHtml(label)}</a>`;
}

/** 현재 페이지와 인접한 페이지로 이동할 링크를 표시합니다. */
function renderJobsPagination(page, totalPages) {
  const pagination = element("jobs-pagination");
  pagination.classList.toggle("hidden", totalPages <= 1);
  if (totalPages <= 1) {
    pagination.innerHTML = "";
    return;
  }
  const pageButtons = [];
  const firstPage = Math.max(1, page - 2);
  const lastPage = Math.min(totalPages, page + 2);
  for (let pageNumber = firstPage; pageNumber <= lastPage; pageNumber += 1) {
    pageButtons.push(paginationLinkMarkup("jobs", pageNumber, pageNumber, { current: pageNumber === page }));
  }
  pagination.innerHTML = `
    ${paginationLinkMarkup("jobs", page - 1, "이전", { disabled: page === 1 })}
    ${pageButtons.join("")}
    ${paginationLinkMarkup("jobs", page + 1, "다음", { disabled: page === totalPages })}`;
}

/** 앱이 제출한 상위 작업과 하위 요청의 최신 상태를 표시합니다. */
async function loadJobs({ refreshAfterCurrentRequest = true } = {}) {
  if (element("application").classList.contains("hidden") || applicationState.deletingSelectedJobs || applicationState.selectingEveryJob || applicationState.movingJobId !== null) return;
  if (applicationState.jobsLoadPromise) {
    if (refreshAfterCurrentRequest) applicationState.jobsReloadRequested = true;
    return applicationState.jobsLoadPromise;
  }
  applicationState.jobsLoadPromise = refreshJobPages();
  return applicationState.jobsLoadPromise;
}

/** 사용자 조작 중 조회 조건이 바뀌면 현재 요청 완료 후 최신 조건으로 다시 읽습니다. */
async function refreshJobPages() {
  applicationState.jobsLoading = true;
  if (!applicationState.jobsLoadedOnce) renderJobsList();
  let loadRevision = applicationState.jobsLoadRevision;
  try {
    do {
      applicationState.jobsReloadRequested = false;
      loadRevision = ++applicationState.jobsLoadRevision;
      const selectionMode = applicationState.jobSelectionMode;
      const jobsPage = applicationState.jobsPage;
      const jobFilterId = applicationState.jobFilterId;
      const selectionScope = currentJobHistoryScope();
      const query = jobHistoryQuery();
      query.set("page", String(jobsPage));
      query.set("page_size", "10");
      query.set("summary", "true");
      const [response, candidates, folders] = await Promise.all([
        apiRequest(`/api/jobs?${query}`).catch(error => ({ error })),
        selectionMode ? apiRequest(`/api/jobs/selection-candidates?${jobHistoryQuery()}`).catch(error => ({ error })) : Promise.resolve(null),
        apiRequest("/api/job-folders"),
      ]);
      if (loadRevision !== applicationState.jobsLoadRevision || selectionMode !== applicationState.jobSelectionMode ||
          jobsPage !== applicationState.jobsPage || selectionScope !== currentJobHistoryScope()) {
        applicationState.jobsReloadRequested = true;
        continue;
      }
      if (response.error) {
        const folderWasRemoved = response.error.status === 404 && applicationState.jobFolderId &&
          applicationState.jobFolderId !== "unassigned" && !folders.items.some(folder => folder.folder_id === applicationState.jobFolderId);
        if (!folderWasRemoved) throw response.error;
        applyJobHistoryFolders(folders);
        applicationState.jobFolderId = "unassigned";
        applicationState.jobsPage = 1;
        applicationState.jobsReloadRequested = true;
        saveCurrentNavigationEntry();
        showNotice("선택한 분류가 삭제되어 미분류로 변경했습니다.");
        continue;
      }
      if (candidates?.error) throw candidates.error;
      if (jobsPage > response.total_pages) {
        applicationState.jobsPage = response.total_pages;
        applicationState.jobsReloadRequested = true;
        continue;
      }
      applicationState.jobsLoadedOnce = true;
      applicationState.jobsLoadError = null;
      applicationState.jobsMatchedCount = response.total;
      applyJobHistoryFolders(folders);
      element("active-count").textContent = `작업 ${response.active_count}`;
      element("jobs-filter").classList.toggle("hidden", !jobFilterId);
      element("jobs-filter-label").textContent = jobFilterId ? `작업 ${jobFilterId}만 표시 중` : "";
      if (selectionScope !== applicationState.jobsSelectionScope) applicationState.selectedJobIds.clear();
      applicationState.jobsSelectionScope = selectionScope;
      applicationState.visibleJobs = response.items;
      const visibleJobIds = new Set(response.items.map(job => job.job_id));
      for (const cachedJobId of applicationState.jobDetails.keys()) {
        if (!visibleJobIds.has(cachedJobId)) applicationState.jobDetails.delete(cachedJobId);
      }
      applicationState.selectableJobIds = new Set(candidates?.job_ids || []);
      applicationState.deletableJobIds = new Set(candidates?.deletable_job_ids || []);
      for (const selectedJobId of applicationState.selectedJobIds) {
        if (!applicationState.selectableJobIds.has(selectedJobId)) applicationState.selectedJobIds.delete(selectedJobId);
      }
      const renderSignature = JSON.stringify([response.items, candidates, jobsPage, selectionScope, folders.items]);
      if (renderSignature !== applicationState.jobsRenderSignature) {
        applicationState.jobsRenderSignature = renderSignature;
        renderJobsPagination(response.page, response.total_pages);
        renderJobsList();
      }
    } while (applicationState.jobsReloadRequested && !applicationState.deletingSelectedJobs && !applicationState.selectingEveryJob);
  } catch (error) {
    if (loadRevision === applicationState.jobsLoadRevision) {
      applicationState.jobsLoadError = error.message;
      if (applicationState.currentView === "jobs") showNotice(error.message, true);
      if (!applicationState.visibleJobs.length) renderJobsList();
    }
  } finally {
    applicationState.jobsLoading = false;
    applicationState.jobsLoadPromise = null;
    element("jobs-loading-status").textContent = applicationState.jobsLoadError
      ? "조회에 실패했습니다. 자동 재시도 중이며 마지막 목록을 유지합니다." : "";
    if (!applicationState.jobsLoadedOnce) renderJobsList();
  }
  if (applicationState.jobsReloadRequested && !applicationState.deletingSelectedJobs && !applicationState.selectingEveryJob) {
    return loadJobs();
  }
}

/** 한 번의 확인 후 선택된 작업을 삭제하고 실패한 이력은 다시 시도할 수 있도록 남깁니다. */
async function deleteSelectedJobHistory(deleteOutputs) {
  if (!applicationState.jobSelectionMode || jobSelectionIsBusy()) return;
  const selectedJobIds = [...applicationState.selectedJobIds].filter(identifier => applicationState.deletableJobIds.has(identifier));
  if (selectedJobIds.length === 0) return;
  const confirmation = deleteOutputs
    ? `선택한 작업 ${selectedJobIds.length}개의 이력과 원래 생성 위치에 남은 결과물을 영구 삭제하시겠습니까? 이동된 파일은 삭제하지 않습니다. 이 작업은 되돌릴 수 없습니다.`
    : `선택한 작업 ${selectedJobIds.length}개의 이력을 영구 삭제하시겠습니까? 결과물 파일은 유지됩니다. 이 작업은 되돌릴 수 없습니다.`;
  if (!window.confirm(confirmation)) return;
  applicationState.deletingSelectedJobs = true;
  applicationState.jobsLoadRevision += 1;
  renderJobsList();
  let deletedJobsCount = 0;
  let deletedFilesCount = 0;
  const deletionFailures = [];
  try {
    const outputOption = deleteOutputs ? "?delete_outputs=true" : "";
    for (const selectedJobId of selectedJobIds) {
      try {
        const result = await apiRequest(`/api/jobs/${encodeURIComponent(selectedJobId)}${outputOption}`, {
          method: "DELETE",
        });
        deletedJobsCount += 1;
        deletedFilesCount += result.deleted_files;
        applicationState.selectedJobIds.delete(selectedJobId);
      } catch (error) {
        deletionFailures.push(`작업 ${selectedJobId}: ${error.message}`);
      }
    }
    if (deletedJobsCount > 0) applicationState.outputFilter = null;
  } finally {
    applicationState.deletingSelectedJobs = false;
    await loadJobs();
    renderJobsList();
  }
  const deletionSummary = deleteOutputs
    ? `작업 이력 ${deletedJobsCount}개와 결과물 ${deletedFilesCount}개를 삭제했습니다.`
    : `작업 이력 ${deletedJobsCount}개를 삭제했습니다. 결과물 파일은 유지됩니다.`;
  showNotice(deletionFailures.length
    ? `${deletionSummary} 삭제 실패 ${deletionFailures.length}개 · ${deletionFailures[0]}`
    : deletionSummary, deletionFailures.length > 0);
}

/** 선택한 작업의 이력과 요청한 경우 원래 위치의 결과물을 삭제합니다. */
async function deleteJobHistory(jobId, deleteOutputs) {
  if (jobSelectionIsBusy() || outputSelectionIsBusy()) return;
  const confirmation = deleteOutputs
    ? "이 작업의 이력과 원래 생성 위치에 남은 결과물을 영구 삭제하시겠습니까? 이동된 파일은 삭제하지 않습니다."
    : "이 작업의 이력만 삭제하시겠습니까? 결과물 파일은 유지됩니다.";
  if (!window.confirm(confirmation)) return;
  const outputOption = deleteOutputs ? "?delete_outputs=true" : "";
  const result = await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}${outputOption}`, {
    method: "DELETE",
  });
  applicationState.outputFilter = null;
  showNotice(deleteOutputs
    ? `이력과 원래 위치의 결과물 ${result.deleted_files}개를 삭제했습니다.`
    : "작업 이력을 삭제했습니다.");
  await loadJobs();
}

/** 현재 결과물 페이지로 이동할 링크를 표시합니다. */
function renderOutputsPagination(page, totalPages) {
  const pagination = element("outputs-pagination");
  pagination.classList.toggle("hidden", totalPages <= 1);
  if (totalPages <= 1) {
    pagination.innerHTML = "";
    return;
  }
  const pageButtons = [];
  const firstPage = Math.max(1, page - 2);
  const lastPage = Math.min(totalPages, page + 2);
  for (let pageNumber = firstPage; pageNumber <= lastPage; pageNumber += 1) {
    pageButtons.push(paginationLinkMarkup("outputs", pageNumber, pageNumber, { current: pageNumber === page }));
  }
  pagination.innerHTML = `
    ${paginationLinkMarkup("outputs", page - 1, "이전", { disabled: page === 1 })}
    ${pageButtons.join("")}
    ${paginationLinkMarkup("outputs", page + 1, "다음", { disabled: page === totalPages })}`;
}

/** 관리 폴더의 현재 결과물을 페이지 단위로 표시합니다. */
async function loadOutputs() {
  if (element("application").classList.contains("hidden") || outputSelectionIsBusy()) return;
  const loadRevision = ++applicationState.outputsLoadRevision;
  try {
    const outputFilter = applicationState.outputFilter;
    const selectionMode = applicationState.outputSelectionMode;
    const selectionScope = JSON.stringify(outputFilter);
    if (applicationState.outputSelectionScope !== selectionScope) {
      applicationState.selectedOutputIds.clear();
      applicationState.selectableOutputIds.clear();
      applicationState.deletableOutputIds.clear();
      applicationState.outputSelectionScope = selectionScope;
      updateOutputSelectionControls();
    }
    const query = new URLSearchParams({ page: String(applicationState.outputsPage), page_size: "64" });
    const candidateQuery = new URLSearchParams();
    if (outputFilter)
      query.set(outputFilter.type === "job" ? "job_id" : "request_id", outputFilter.id);
    if (outputFilter)
      candidateQuery.set(outputFilter.type === "job" ? "job_id" : "request_id", outputFilter.id);
    const [response, candidates] = await Promise.all([
      apiRequest(`/api/outputs?${query}`),
      selectionMode ? apiRequest(`/api/outputs/selection-candidates?${candidateQuery}`) : Promise.resolve(null),
    ]);
    if (loadRevision !== applicationState.outputsLoadRevision) return;
    if (applicationState.outputsPage > response.total_pages) {
      applicationState.outputsPage = response.total_pages;
      return loadOutputs();
    }
    applicationState.visibleOutputs = response.files;
    applicationState.selectableOutputIds = new Set((candidates?.output_ids || []).map(String));
    applicationState.deletableOutputIds = new Set((candidates?.deletable_output_ids || []).map(String));
    for (const selectedOutputId of applicationState.selectedOutputIds) {
      if (!applicationState.selectableOutputIds.has(selectedOutputId)) {
        applicationState.selectedOutputIds.delete(selectedOutputId);
      }
    }
    const renderSignature = JSON.stringify([response, candidates, query.toString(), selectionMode]);
    if (renderSignature === applicationState.outputsRenderSignature) return;
    element("output-count").textContent = outputFilter
      ? `${outputFilter.type === "job" ? "이 작업" : "이 요청"}의 결과 ${response.total}개`
      : `${response.total}개 파일`;
    element("clear-output-filter").classList.toggle(
      "hidden",
      !outputFilter,
    );
    renderOutputsPagination(response.page, response.total_pages);
    renderOutputsList();
    applicationState.outputsRenderSignature = renderSignature;
  } catch (error) {
    if (loadRevision === applicationState.outputsLoadRevision) showNotice(error.message, true);
  }
}

/** 작업 상태·파일 종류와 무관하게 삭제 보호 여부로 단건·다중 삭제를 판단합니다. */
function canDeleteOutput(outputFile) {
  return !outputFile.deletion_protected;
}

/** 결과물 선택·삭제·이동 중 다른 조작을 잠글지 확인합니다. */
function outputSelectionIsBusy() {
  return outputFolderPickerState.resolveSelection !== null || applicationState.selectingEveryOutput || applicationState.deletingSelectedOutputs ||
    applicationState.deletingOutputId !== null || applicationState.movingOutputPath !== null ||
    applicationState.movingSelectedOutputs || applicationState.movingJobId !== null;
}

/** 현재 페이지와 전체 선택 상태에 맞춰 이동·삭제 조작부를 갱신합니다. */
function updateOutputSelectionControls() {
  const selectionIsBusy = outputSelectionIsBusy();
  const selectableOutputs = applicationState.visibleOutputs;
  const currentPageSelected = selectableOutputs.length > 0 && selectableOutputs.every(outputFile =>
    applicationState.selectedOutputIds.has(String(outputFile.output_id)),
  );
  const everyOutputSelected = applicationState.selectableOutputIds.size > 0 &&
    [...applicationState.selectableOutputIds].every(outputIdentifier => applicationState.selectedOutputIds.has(outputIdentifier));
  element("toggle-output-selection").textContent = applicationState.outputSelectionMode ? "다중 선택 취소" : "다중 선택";
  element("toggle-output-selection").setAttribute("aria-expanded", String(applicationState.outputSelectionMode));
  element("toggle-output-selection").disabled = selectionIsBusy;
  element("output-selection-actions").classList.toggle("hidden", !applicationState.outputSelectionMode);
  element("select-all-outputs").textContent = currentPageSelected ? "현재 페이지 선택 해제" : "현재 페이지 선택";
  element("select-all-outputs").disabled = selectionIsBusy || selectableOutputs.length === 0;
  element("select-every-output").textContent = applicationState.selectingEveryOutput
    ? "전체 결과물 조회 중…" : everyOutputSelected ? "전체 선택 해제" : "결과물 전체 선택";
  element("select-every-output").disabled = selectionIsBusy || applicationState.selectableOutputIds.size === 0;
  element("selected-output-count").textContent = applicationState.deletingSelectedOutputs
    ? "삭제 중…" : applicationState.movingSelectedOutputs ? "이동 중…" : `${applicationState.selectedOutputIds.size}개 선택`;
  const selectedDeletableOutputs = [...applicationState.selectedOutputIds].filter(outputIdentifier =>
    applicationState.deletableOutputIds.has(outputIdentifier),
  );
  element("delete-selected-outputs").disabled = selectionIsBusy || selectedDeletableOutputs.length === 0;
  element("move-selected-outputs").disabled = selectionIsBusy || applicationState.selectedOutputIds.size === 0;
  element("refresh-outputs-button").disabled = selectionIsBusy;
  element("outputs-pagination").toggleAttribute("inert", selectionIsBusy);
  const clearOutputFilterLink = element("clear-output-filter");
  clearOutputFilterLink.setAttribute("aria-disabled", String(selectionIsBusy));
  if (selectionIsBusy) clearOutputFilterLink.removeAttribute("href");
  else clearOutputFilterLink.href = navigationUrl({ viewName: "outputs", pageNumber: 1 });
  for (const checkbox of element("outputs-grid").querySelectorAll("[data-select-output]")) {
    checkbox.checked = applicationState.selectedOutputIds.has(checkbox.dataset.selectOutput);
    checkbox.closest(".output-card").classList.toggle("output-selected", checkbox.checked);
  }
}

/** 현재 결과물과 선택 상태를 표시하고 삭제 보호된 파일의 삭제 버튼을 비활성화합니다. */
function renderOutputsList() {
  const selectionIsBusy = outputSelectionIsBusy();
  const visibleFiles = applicationState.visibleOutputs;
  element("outputs-grid").innerHTML = visibleFiles.length
      ? visibleFiles
          .map((outputFile) => {
            const url = `/media/${outputFile.path.split("/").map(encodeURIComponent).join("/")}`;
            const dimensions = formatDimensions(outputFile.width, outputFile.height);
            const dimensionSource = outputFile.dimensions_source === "settings" ? " (설정)" : "";
            const media =
              outputFile.kind === "video"
                ? `<button type="button" class="video-preview-trigger" data-video-preview="${outputFile.output_id}" aria-label="${escapeHtml(outputFile.name)} 저용량 미리보기" ${selectionIsBusy ? "disabled" : ""}><img src="/api/outputs/preview/${outputFile.path.split("/").map(encodeURIComponent).join("/")}" alt="${escapeHtml(outputFile.name)}" loading="lazy"><span class="video-preview-play" aria-hidden="true">▶</span></button>`
                : `<button type="button" class="image-preview-trigger" data-image-preview="${outputFile.output_id}" aria-label="${escapeHtml(outputFile.name)} 이미지 미리보기" ${selectionIsBusy ? "disabled" : ""}><img src="/api/outputs/preview/${encodedOutputPath(outputFile.path)}" alt="${escapeHtml(outputFile.name)}" loading="lazy"></button>`;
            const jobButton = outputFile.job_id
              ? `<a class="button job-link" data-navigation data-output-job="${escapeHtml(outputFile.job_id)}" href="${escapeHtml(navigationUrl({ viewName: "jobs", pageNumber: 1, jobFilterId: outputFile.job_id }))}" aria-label="작업 ${escapeHtml(outputFile.job_id)} 보기">작업</a>`
              : "";
            const deleteButton = `<button class="button danger" data-delete-output="${outputFile.output_id}" data-output-path="${escapeHtml(outputFile.path)}" ${selectionIsBusy || !canDeleteOutput(outputFile) ? "disabled" : ""} ${outputFile.deletion_protected ? 'title="삭제 보호된 작업의 결과물입니다."' : ""}>삭제</button>`;
            const isSelected = applicationState.selectedOutputIds.has(String(outputFile.output_id));
            const selectionCheckbox = applicationState.outputSelectionMode
              ? `<label class="output-selection-control"><input class="output-selection-checkbox" type="checkbox" data-select-output="${outputFile.output_id}" aria-label="결과물 ${escapeHtml(outputFile.name)} 선택" ${isSelected ? "checked" : ""} ${selectionIsBusy ? "disabled" : ""}>선택</label>`
              : "";
            const protectionLabel = outputFile.deletion_protected ? '<span class="output-protection-label">삭제 보호</span>' : "";
            return `<article class="output-card${isSelected ? " output-selected" : ""}"><div class="output-preview">${media}${selectionCheckbox}</div><div class="output-info"><strong>${escapeHtml(outputFile.name)}</strong>${protectionLabel}<small>${escapeHtml(outputFile.path)} · ${dimensions.ratio} · ${dimensions.resolution}${dimensionSource}</small><div class="inline-actions"><a class="button subtle" href="${url}" target="_blank" rel="noopener">열기</a><button class="button subtle" data-move-output="${escapeHtml(outputFile.path)}" ${selectionIsBusy ? "disabled" : ""}>파일 이동</button>${deleteButton}${jobButton}</div></div></article>`;
          })
          .join("")
      : `<p class="empty-state">관리 폴더에 결과물이 없습니다.</p>`;
  updateOutputSelectionControls();
}

/** 재생 연결과 Polling을 해제하고 이전 소스의 늦은 응답을 무효화합니다. */
function resetVideoPreviewPlayback() {
  videoPreviewState.revision += 1;
  window.clearTimeout(videoPreviewState.timer);
  videoPreviewState.controller?.abort();
  videoPreviewState.controller = null;
  videoPreviewState.attachedIdentifier = null;
  videoPreviewState.lastStatus = null;
  const video = element("video-preview-player");
  video.pause();
  video.removeAttribute("src");
  video.removeAttribute("poster");
  video.load();
  element("video-preview-notice").classList.add("hidden");
}

/** 미리보기 창을 닫고 서버 Queue와 변환은 유지합니다. */
function closeVideoPreview(restoreFocus = true, preserveNavigation = false) {
  if (!preserveNavigation) resetOutputPreviewNavigation();
  videoPreviewState.pointerStartedOutside = false;
  resetVideoPreviewPlayback();
  videoPreviewState.outputId = null;
  const dialog = element("video-preview-dialog");
  if (dialog.open) dialog.close();
  if (restoreFocus && videoPreviewState.opener?.isConnected) videoPreviewState.opener.focus({ preventScroll: true });
  videoPreviewState.opener = null;
}

/** 토글 상태에 맞춰 압축 미리보기 또는 원본 이미지 파일을 읽습니다. */
function loadImagePreviewSource(outputFile) {
  const showOriginalFiles = outputPreviewNavigationState.showOriginalFiles;
  const encodedPath = encodedOutputPath(outputFile.path);
  element("image-preview-status").textContent = showOriginalFiles ? "원본 이미지를 불러오는 중…" : "미리보기를 불러오는 중…";
  const image = element("image-preview-content");
  image.alt = outputFile.name;
  image.src = showOriginalFiles ? `/media/${encodedPath}` : `/api/outputs/preview/${encodedPath}`;
}

/** 선택한 보기 모드로 이미지 창을 열고 원본의 별도 탭 링크도 제공합니다. */
function openImagePreview(outputFile, opener) {
  closeVideoPreview(false, true);
  closeImagePreview(false, true);
  imagePreviewState.outputId = outputFile.output_id;
  imagePreviewState.opener = opener;
  const encodedPath = encodedOutputPath(outputFile.path);
  element("image-preview-title").textContent = outputFile.name;
  element("image-preview-original").href = `/media/${encodedPath}`;
  element("image-preview-notice").classList.add("hidden");
  loadImagePreviewSource(outputFile);
  element("image-preview-dialog").showModal();
}

/** 이미지 연결과 표시 상태를 정리하고 원래 Thumbnail 버튼으로 Focus를 돌립니다. */
function closeImagePreview(restoreFocus = true, preserveNavigation = false) {
  if (!preserveNavigation) resetOutputPreviewNavigation();
  imagePreviewState.pointerStartedOutside = false;
  imagePreviewState.outputId = null;
  const image = element("image-preview-content");
  image.removeAttribute("src");
  image.alt = "";
  element("image-preview-original").removeAttribute("href");
  element("image-preview-status").textContent = "";
  element("image-preview-notice").classList.add("hidden");
  const dialog = element("image-preview-dialog");
  if (dialog.open) dialog.close();
  if (restoreFocus && imagePreviewState.opener?.isConnected) imagePreviewState.opener.focus({ preventScroll: true });
  imagePreviewState.opener = null;
}

/** 열린 목록 범위를 해제하고 늦게 도착한 인접 파일 응답을 무효화합니다. */
function resetOutputPreviewNavigation() {
  const navigationState = outputPreviewNavigationState;
  navigationState.revision += 1;
  navigationState.controller?.abort();
  Object.assign(navigationState, { controller: null, outputId: null, currentFile: null, filter: null, opener: null,
    previous: null, next: null, loading: false, error: "", showOriginalFiles: false });
  renderOutputPreviewNavigation();
}

/** 현재 범위와 인접 파일 상태를 이미지·영상의 공통 이동 버튼에 표시합니다. */
function renderOutputPreviewNavigation() {
  const navigationState = outputPreviewNavigationState;
  const currentFile = navigationState.currentFile;
  for (const mediaKind of ["image", "video"]) {
    const originalToggle = element(`${mediaKind}-preview-original-toggle`);
    originalToggle.checked = navigationState.showOriginalFiles;
    originalToggle.disabled = outputSelectionIsBusy() || !currentFile;
    const deleteButton = element(`${mediaKind}-preview-delete`);
    deleteButton.disabled = navigationState.loading || Boolean(navigationState.error) || outputSelectionIsBusy() ||
      !currentFile || currentFile.deletion_protected !== false;
    deleteButton.textContent = applicationState.deletingOutputId === String(navigationState.outputId) ? "삭제 중…" : "삭제";
    deleteButton.title = currentFile?.deletion_protected ? "삭제 보호된 작업의 결과물입니다." : "";
    element(`${mediaKind}-preview-previous`).disabled = navigationState.loading || outputSelectionIsBusy() || !navigationState.previous;
    element(`${mediaKind}-preview-next`).disabled = navigationState.loading || outputSelectionIsBusy() || !navigationState.next;
    element(`${mediaKind}-preview-navigation-status`).textContent = navigationState.error || (navigationState.loading
      ? "이전·다음 결과물 확인 중…"
      : navigationState.outputId === null ? "" : navigationState.filter?.type === "job" ? "이 작업의 결과물" : navigationState.filter ? "이 요청의 결과물" : "전체 결과물");
  }
}

/** 현재 결과물 범위를 고정하여 열고 이미지·영상 전환에서도 원래 목록의 Focus를 유지합니다. */
function openOutputPreview(outputFile, opener, preserveScope = false, scopeFilter = applicationState.outputFilter) {
  const navigationState = outputPreviewNavigationState;
  if (!preserveScope) {
    resetOutputPreviewNavigation();
    navigationState.filter = scopeFilter ? { ...scopeFilter } : null;
    navigationState.opener = opener;
  }
  navigationState.controller?.abort();
  navigationState.revision += 1;
  navigationState.outputId = outputFile.output_id;
  navigationState.currentFile = outputFile;
  navigationState.controller = new AbortController();
  navigationState.previous = null;
  navigationState.next = null;
  navigationState.loading = true;
  navigationState.error = "";
  if (outputFile.kind === "video") runAction(() => openVideoPreview(outputFile, navigationState.opener));
  else openImagePreview(outputFile, navigationState.opener);
  renderOutputPreviewNavigation();
  loadOutputPreviewNeighbors(outputFile.output_id, navigationState.revision);
}

/** 같은 작업·요청 필터 안의 인접 파일만 읽고 닫거나 이동한 뒤의 응답은 무시합니다. */
async function loadOutputPreviewNeighbors(outputIdentifier, revision) {
  const navigationState = outputPreviewNavigationState;
  const query = new URLSearchParams();
  if (navigationState.filter) query.set(navigationState.filter.type === "job" ? "job_id" : "request_id", navigationState.filter.id);
  try {
    const neighbors = await apiRequest(`/api/outputs/${outputIdentifier}/neighbors?${query}`, { signal: navigationState.controller.signal });
    if (revision !== navigationState.revision) return;
    navigationState.previous = neighbors.previous;
    navigationState.next = neighbors.next;
    navigationState.currentFile = neighbors.current;
  } catch (error) {
    if (revision !== navigationState.revision || error.name === "AbortError") return;
    navigationState.error = "이전·다음 결과물을 불러올 수 없습니다. 닫은 뒤 다시 열어 주세요.";
  } finally {
    if (revision === navigationState.revision) {
      navigationState.loading = false;
      renderOutputPreviewNavigation();
    }
  }
}

/** 페이지 경계와 무관하게 현재 필터 안의 이전 또는 다음 결과물을 미리봅니다. */
function navigateOutputPreview(direction) {
  const navigationState = outputPreviewNavigationState;
  if (navigationState.loading || outputSelectionIsBusy() || !navigationState[direction]) return;
  openOutputPreview(navigationState[direction], navigationState.opener, true);
}

/** 열린 범위와 Focus를 유지하며 원본 보기 모드를 이전·다음 결과물에도 적용합니다. */
function setOutputPreviewOriginalMode(showOriginalFiles) {
  const navigationState = outputPreviewNavigationState;
  const currentFile = navigationState.currentFile;
  if (!currentFile || outputSelectionIsBusy()) {
    renderOutputPreviewNavigation();
    return;
  }
  navigationState.showOriginalFiles = showOriginalFiles;
  if (currentFile.kind === "video") {
    resetVideoPreviewPlayback();
    runAction(() => loadVideoPreviewSource(currentFile));
  } else loadImagePreviewSource(currentFile);
  renderOutputPreviewNavigation();
}

/** Dialog 자체로 전달된 Pointer가 실제 미리보기 바깥에 있는지 확인합니다. */
function isPreviewBackdropEvent(event) {
  if (event.target !== event.currentTarget) return false;
  const dialogBounds = event.currentTarget.getBoundingClientRect();
  return event.clientX < dialogBounds.left || event.clientX > dialogBounds.right ||
    event.clientY < dialogBounds.top || event.clientY > dialogBounds.bottom;
}

/** 이미지·영상의 닫기·Escape·외부 클릭을 연결하며 내부에서 시작한 드래그는 유지합니다. */
function bindPreviewDialogEvents(dialogIdentifier, closeButtonIdentifier, previewState, closePreview) {
  const dialog = element(dialogIdentifier);
  dialog.querySelector("[data-preview-original-toggle]").addEventListener("change", event => {
    setOutputPreviewOriginalMode(event.target.checked);
  });
  dialog.querySelector("[data-preview-previous]").addEventListener("click", () => navigateOutputPreview("previous"));
  dialog.querySelector("[data-preview-next]").addEventListener("click", () => navigateOutputPreview("next"));
  dialog.addEventListener("keydown", event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest("video, input, textarea, select")) return;
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    navigateOutputPreview(event.key === "ArrowLeft" ? "previous" : "next");
  });
  element(closeButtonIdentifier).addEventListener("click", () => closePreview());
  dialog.addEventListener("pointerdown", event => {
    previewState.pointerStartedOutside = isPreviewBackdropEvent(event);
  });
  dialog.addEventListener("pointercancel", () => {
    previewState.pointerStartedOutside = false;
  });
  dialog.addEventListener("click", event => {
    const clickedBackdrop = previewState.pointerStartedOutside && isPreviewBackdropEvent(event);
    previewState.pointerStartedOutside = false;
    if (clickedBackdrop) closePreview();
  });
  dialog.addEventListener("cancel", event => {
    event.preventDefault();
    closePreview();
  });
  dialog.addEventListener("close", () => {
    if (!dialog.open && previewState.outputId !== null) closePreview();
  });
}

/** 영상 창을 열고 현재 보기 모드에 맞는 재생 소스를 연결합니다. */
async function openVideoPreview(outputFile, opener, retry = false) {
  closeImagePreview(false, true);
  closeVideoPreview(false, true);
  videoPreviewState.outputId = outputFile.output_id;
  videoPreviewState.opener = opener;
  const encodedPath = outputFile.path.split("/").map(encodeURIComponent).join("/");
  element("video-preview-title").textContent = outputFile.name;
  element("video-preview-original").href = `/media/${encodedPath}`;
  element("video-preview-dialog").showModal();
  await loadVideoPreviewSource(outputFile, retry);
}

/** 원본 모드에서는 파일을 직접 읽고 기본 모드에서는 기존 변환·Polling을 사용합니다. */
async function loadVideoPreviewSource(outputFile, retry = false) {
  if (videoPreviewState.outputId !== outputFile.output_id || !element("video-preview-dialog").open) return;
  const revision = videoPreviewState.revision;
  const encodedPath = encodedOutputPath(outputFile.path);
  const video = element("video-preview-player");
  video.poster = `/api/outputs/preview/${encodedPath}`;
  if (outputPreviewNavigationState.showOriginalFiles) {
    video.src = `/media/${encodedPath}`;
    video.play().catch(() => {});
    return;
  }
  videoPreviewState.controller = new AbortController();
  try {
    const status = await apiRequest(`/api/outputs/${outputFile.output_id}/video-preview`, {
      method: "POST", body: JSON.stringify({ retry }), signal: videoPreviewState.controller.signal,
    });
    if (revision !== videoPreviewState.revision) return;
    updateVideoPreviewStatus(outputFile, status, revision);
  } catch (error) {
    if (revision === videoPreviewState.revision && error.name !== "AbortError") showNotice(error.message, true);
  }
}

/** 활성 영상의 상태 전이에만 Toast를 띄우고 중복 재생 연결을 만들지 않습니다. */
function updateVideoPreviewStatus(outputFile, status, revision) {
  if (revision !== videoPreviewState.revision || !element("video-preview-dialog").open) return;
  const messages = {
    queued: "미리보기 변환 대기 중입니다.",
    converting: "미리보기 변환 중입니다.",
    retry_wait: "미리보기 변환에 실패해 재시도를 기다리고 있습니다.",
    failed: "미리보기 변환에 실패했습니다.",
    missing: "미리보기 파일이 없습니다. 다시 열어 주세요.",
  };
  if (videoPreviewState.lastStatus !== status.state && messages[status.state]) {
    const retryAction = status.state === "failed" ? {
      label: "재시도",
      run: () => {
        if (revision === videoPreviewState.revision) runAction(() => openVideoPreview(outputFile, videoPreviewState.opener, true));
      },
    } : null;
    showNotice(messages[status.state], status.state === "failed", retryAction);
  }
  videoPreviewState.lastStatus = status.state;
  if (["retry_wait", "failed"].includes(status.state) && videoPreviewState.attachedIdentifier) {
    const video = element("video-preview-player");
    video.pause();
    video.removeAttribute("src");
    video.load();
    videoPreviewState.attachedIdentifier = null;
  }
  if ((status.stream_ready || status.state === "ready") && videoPreviewState.attachedIdentifier !== status.identifier) {
    const video = element("video-preview-player");
    videoPreviewState.attachedIdentifier = status.identifier;
    video.src = `/api/outputs/${outputFile.output_id}/video-preview/stream?version=${encodeURIComponent(status.identifier)}`;
    video.play().catch(() => {});
  }
  if (["queued", "converting", "retry_wait"].includes(status.state)) {
    videoPreviewState.timer = window.setTimeout(() => pollVideoPreview(outputFile, revision), 750);
  }
}

/** 한 번에 하나의 상태 조회만 수행하고 닫거나 교체한 영상의 늦은 응답을 무시합니다. */
async function pollVideoPreview(outputFile, revision) {
  if (revision !== videoPreviewState.revision) return;
  try {
    const status = await apiRequest(`/api/outputs/${outputFile.output_id}/video-preview`, {
      signal: videoPreviewState.controller.signal,
    });
    updateVideoPreviewStatus(outputFile, status, revision);
  } catch (error) {
    if (revision === videoPreviewState.revision && error.name !== "AbortError") showNotice(error.message, true);
  }
}

/** 현재 페이지의 결과물을 모두 선택하거나 해제합니다. */
function toggleAllOutputSelections() {
  if (!applicationState.outputSelectionMode || outputSelectionIsBusy()) return;
  const selectableOutputs = applicationState.visibleOutputs;
  const currentPageSelected = selectableOutputs.every(outputFile => applicationState.selectedOutputIds.has(String(outputFile.output_id)));
  for (const outputFile of selectableOutputs) {
    const outputIdentifier = String(outputFile.output_id);
    if (currentPageSelected) applicationState.selectedOutputIds.delete(outputIdentifier);
    else applicationState.selectedOutputIds.add(outputIdentifier);
  }
  updateOutputSelectionControls();
}

/** 현재 필터의 모든 페이지에서 이동할 결과물을 선택하거나 해제합니다. */
async function toggleEveryOutputSelection() {
  if (!applicationState.outputSelectionMode || outputSelectionIsBusy()) return;
  const everyOutputSelected = applicationState.selectableOutputIds.size > 0 &&
    [...applicationState.selectableOutputIds].every(outputIdentifier => applicationState.selectedOutputIds.has(outputIdentifier));
  if (everyOutputSelected) {
    applicationState.selectedOutputIds.clear();
    updateOutputSelectionControls();
    return;
  }
  applicationState.selectingEveryOutput = true;
  applicationState.outputsLoadRevision += 1;
  const selectionScope = JSON.stringify(applicationState.outputFilter);
  renderOutputsList();
  try {
    const query = new URLSearchParams();
    if (applicationState.outputFilter) {
      const outputFilter = applicationState.outputFilter;
      query.set(outputFilter.type === "job" ? "job_id" : "request_id", outputFilter.id);
    }
    const candidates = await apiRequest(`/api/outputs/selection-candidates?${query}`);
    if (selectionScope === JSON.stringify(applicationState.outputFilter)) {
      applicationState.selectedOutputIds = new Set(candidates.output_ids.map(String));
    }
  } finally {
    applicationState.selectingEveryOutput = false;
    await loadOutputs();
    renderOutputsList();
  }
}

/** 한 번 확인한 결과물들을 개별 API로 삭제하고 실패한 선택만 재시도할 수 있게 남깁니다. */
async function deleteSelectedOutputs() {
  if (!applicationState.outputSelectionMode || outputSelectionIsBusy()) return;
  const selectedOutputIds = [...applicationState.selectedOutputIds].filter(outputIdentifier =>
    applicationState.deletableOutputIds.has(outputIdentifier),
  );
  if (selectedOutputIds.length === 0) return;
  if (!window.confirm(`선택한 결과물 ${selectedOutputIds.length}개를 영구 삭제하시겠습니까? 삭제 보호 결과물은 제외됩니다. 작업 이력은 유지되며 파일은 복구할 수 없습니다.`)) return;
  applicationState.deletingSelectedOutputs = true;
  applicationState.outputsLoadRevision += 1;
  renderOutputsList();
  let deletedOutputsCount = 0;
  const deletionFailures = [];
  try {
    for (const outputIdentifier of selectedOutputIds) {
      try {
        await apiRequest(`/api/outputs/${encodeURIComponent(outputIdentifier)}`, { method: "DELETE" });
        deletedOutputsCount += 1;
        applicationState.selectedOutputIds.delete(outputIdentifier);
        applicationState.deletableOutputIds.delete(outputIdentifier);
        applicationState.visibleOutputs = applicationState.visibleOutputs.filter(outputFile => String(outputFile.output_id) !== outputIdentifier);
      } catch (error) {
        deletionFailures.push(`결과물 ${outputIdentifier}: ${error.message}`);
      }
    }
  } finally {
    applicationState.deletingSelectedOutputs = false;
    applicationState.outputsRenderSignature = null;
    renderOutputsList();
    await loadOutputs();
  }
  const deletionSummary = `결과물 ${deletedOutputsCount}개를 삭제했습니다.`;
  showNotice(deletionFailures.length
    ? `${deletionSummary} 삭제 실패 ${deletionFailures.length}개 · ${deletionFailures[0]}` : deletionSummary,
    deletionFailures.length > 0);
}

/** 탐색기의 경로·하위 폴더·진행 상태를 표시하고 조작 가능 범위를 갱신합니다. */
function renderOutputFolderPicker() {
  const pickerState = outputFolderPickerState;
  const directoryIsBusy = pickerState.loading || pickerState.creating;
  const selectingImages = pickerState.selectionMode !== "move";
  element("folder-picker-create-form").classList.toggle("hidden", selectingImages);
  element("folder-picker-creation-hint").classList.toggle("hidden", selectingImages);
  element("folder-picker-images").classList.toggle("hidden", !selectingImages);
  const breadcrumbParts = [{ name: "결과물", path: "" }];
  let breadcrumbPath = "";
  for (const directoryName of pickerState.path.split("/").filter(Boolean)) {
    breadcrumbPath = breadcrumbPath ? `${breadcrumbPath}/${directoryName}` : directoryName;
    breadcrumbParts.push({ name: directoryName, path: breadcrumbPath });
  }
  element("folder-picker-breadcrumb").innerHTML = breadcrumbParts.map((directory, directoryIndex) =>
    `${directoryIndex ? '<span aria-hidden="true">/</span>' : ""}<button type="button" class="button subtle small" data-folder-path="${escapeHtml(directory.path)}" ${directoryIsBusy ? "disabled" : ""} ${directory.path === pickerState.path ? 'aria-current="location"' : ""}>${escapeHtml(directory.name)}</button>`,
  ).join("");
  element("folder-picker-parent").disabled = directoryIsBusy || pickerState.parentPath === null;
  element("folder-picker-directories").innerHTML = pickerState.directories.map(directory =>
    `<li><button type="button" class="button subtle" data-folder-path="${escapeHtml(directory.path)}" ${directoryIsBusy ? "disabled" : ""}>▸ ${escapeHtml(directory.name)}</button></li>`,
  ).join("");
  const status = pickerState.loading ? "폴더를 불러오는 중…" : pickerState.creating ? "폴더를 만드는 중…"
    : pickerState.error || (pickerState.directories.length ? "하위 폴더를 열거나 현재 폴더를 선택해 주세요." : "하위 폴더가 없습니다.");
  element("folder-picker-status").textContent = status;
  if (selectingImages && pickerState.loaded && !pickerState.error) {
    element("folder-picker-status").textContent = `직하위 이미지 ${pickerState.images.length}장 · ${pickerState.selectedImageIds.size}장 선택 · 최대 100장${pickerState.selectionMode === "single" ? " · 한 장을 선택해 주세요." : " · 제외할 이미지를 해제해 주세요."}`;
  }
  element("folder-picker-images").innerHTML = pickerState.images.map(image =>
    `<label class="input-image-card"><img src="/api/outputs/preview/${encodedOutputPath(image.path)}" alt="" loading="lazy" /><input type="${pickerState.selectionMode === "single" ? "radio" : "checkbox"}" name="picker-input-image" data-pick-input="${image.output_id}" ${pickerState.selectedImageIds.has(String(image.output_id)) ? "checked" : ""} ${directoryIsBusy ? "disabled" : ""} /><span>${escapeHtml(image.name)}</span></label>`,
  ).join("");
  element("folder-picker-retry").classList.toggle("hidden", directoryIsBusy || pickerState.loaded || !pickerState.error);
  element("folder-picker-name").disabled = directoryIsBusy || !pickerState.loaded;
  element("folder-picker-create").disabled = directoryIsBusy || !pickerState.loaded;
  element("folder-picker-confirm").disabled = directoryIsBusy || !pickerState.loaded ||
    (selectingImages && (pickerState.selectedImageIds.size === 0 || pickerState.selectedImageIds.size > 100));
  element("folder-picker-cancel").disabled = pickerState.creating;
}

/** 직하위 폴더만 요청하고 닫힌 창이나 이전 요청의 응답은 무시합니다. */
async function loadOutputFolder(directoryPath) {
  const pickerState = outputFolderPickerState;
  if (!pickerState.resolveSelection) return;
  const loadRevision = ++pickerState.loadRevision;
  pickerState.path = directoryPath;
  pickerState.parentPath = directoryPath ? directoryPath.split("/").slice(0, -1).join("/") : null;
  pickerState.directories = [];
  pickerState.images = [];
  pickerState.selectedImageIds.clear();
  pickerState.loaded = false;
  pickerState.loading = true;
  pickerState.error = "";
  renderOutputFolderPicker();
  try {
    const directoryQuery = new URLSearchParams({ path: directoryPath });
    const [directoryListing, imageListing] = await Promise.all([
      apiRequest(`/api/outputs/directories?${directoryQuery}`),
      pickerState.selectionMode === "move" ? Promise.resolve({ files: [] }) : apiRequest(`/api/outputs/input-images?${directoryQuery}`),
    ]);
    if (loadRevision !== pickerState.loadRevision || !pickerState.resolveSelection) return;
    pickerState.path = directoryListing.path;
    pickerState.parentPath = directoryListing.parent_path;
    pickerState.directories = directoryListing.directories;
    pickerState.images = imageListing.files;
    if (pickerState.selectionMode === "folder") pickerState.selectedImageIds = new Set(imageListing.files.map(image => String(image.output_id)));
    pickerState.loaded = true;
  } catch (error) {
    if (loadRevision !== pickerState.loadRevision || !pickerState.resolveSelection) return;
    pickerState.error = error.message;
  } finally {
    if (loadRevision === pickerState.loadRevision && pickerState.resolveSelection) {
      pickerState.loading = false;
      renderOutputFolderPicker();
      if (!element("output-folder-picker").contains(document.activeElement)) element("folder-picker-cancel").focus();
    }
  }
}

/** 이동 목적지를 공용 Modal로 선택하며 취소는 null, 루트 선택은 빈 문자열로 반환합니다. */
function chooseOutputFolder(description, selectionMode = "move") {
  if (outputFolderPickerState.resolveSelection) return Promise.resolve(null);
  outputFolderPickerState.sessionRevision += 1;
  outputFolderPickerState.openingElement = document.activeElement;
  outputFolderPickerState.creating = false;
  outputFolderPickerState.selectionMode = selectionMode;
  element("folder-picker-title").textContent = selectionMode === "move" ? "파일을 옮길 폴더 선택" : selectionMode === "single" ? "입력 이미지 선택" : "입력 폴더와 이미지 선택";
  element("folder-picker-confirm").textContent = selectionMode === "move" ? "이 폴더로 파일 이동" : "선택한 이미지 사용";
  element("folder-picker-description").textContent = description;
  element("folder-picker-name").value = "";
  const selectionPromise = new Promise(resolve => { outputFolderPickerState.resolveSelection = resolve; });
  element("output-folder-picker").showModal();
  loadOutputFolder("");
  element("folder-picker-cancel").focus();
  return selectionPromise;
}

/** 선택을 한 번만 완료하고 진행 중인 폴더 조회 응답을 무효화합니다. */
function finishOutputFolderSelection(directoryPath, forceClose = false) {
  const pickerState = outputFolderPickerState;
  if (!pickerState.resolveSelection || (pickerState.creating && !forceClose)) return;
  if (directoryPath !== null && (pickerState.loading || !pickerState.loaded)) return;
  const resolveSelection = pickerState.resolveSelection;
  pickerState.resolveSelection = null;
  pickerState.sessionRevision += 1;
  pickerState.loadRevision += 1;
  element("output-folder-picker").close();
  // 조회 응답이 Modal 뒤에서 카드를 다시 그렸어도 취소 후 버튼이 잠긴 채 남지 않게 합니다.
  renderJobsList();
  renderOutputsList();
  let openingElement = pickerState.openingElement;
  if (openingElement?.id) openingElement = element(openingElement.id);
  else {
    for (const movementButton of document.querySelectorAll("[data-move-output], [data-move-job-outputs]")) {
      if ((openingElement?.dataset.moveOutput && movementButton.dataset.moveOutput === openingElement.dataset.moveOutput) ||
          (openingElement?.dataset.moveJobOutputs && movementButton.dataset.moveJobOutputs === openingElement.dataset.moveJobOutputs)) {
        openingElement = movementButton;
        break;
      }
    }
  }
  if (openingElement?.isConnected && !openingElement.disabled) openingElement.focus({ preventScroll: true });
  resolveSelection(directoryPath);
}

/** 현재 위치에 폴더 하나를 만들고 명시적인 이동 확정 전에 새 폴더를 엽니다. */
async function createOutputPickerDirectory(event) {
  event.preventDefault();
  const pickerState = outputFolderPickerState;
  if (!pickerState.resolveSelection || !pickerState.loaded || pickerState.loading || pickerState.creating) return;
  const loadRevision = pickerState.loadRevision;
  const sessionRevision = pickerState.sessionRevision;
  pickerState.creating = true;
  pickerState.error = "";
  renderOutputFolderPicker();
  try {
    const createdDirectory = await apiRequest("/api/outputs/directories", {
      method: "POST", body: JSON.stringify({ parent_path: pickerState.path, name: element("folder-picker-name").value }),
    });
    if (loadRevision !== pickerState.loadRevision || !pickerState.resolveSelection) return;
    element("folder-picker-name").value = "";
    pickerState.creating = false;
    await loadOutputFolder(createdDirectory.path);
  } catch (error) {
    if (loadRevision !== pickerState.loadRevision || !pickerState.resolveSelection) return;
    pickerState.error = error.message;
  } finally {
    if (pickerState.resolveSelection && sessionRevision === pickerState.sessionRevision) {
      pickerState.creating = false;
      renderOutputFolderPicker();
    }
  }
}

/** 공용 탐색기의 키보드 취소·폴더 이동·새 폴더 생성 이벤트를 연결합니다. */
function bindOutputFolderPickerEvents() {
  const folderPicker = element("output-folder-picker");
  folderPicker.addEventListener("cancel", event => { event.preventDefault(); finishOutputFolderSelection(null); });
  folderPicker.addEventListener("close", () => { if (!folderPicker.open) finishOutputFolderSelection(null, true); });
  folderPicker.addEventListener("click", event => {
    const directoryButton = event.target.closest("[data-folder-path]");
    if (directoryButton && !directoryButton.disabled) loadOutputFolder(directoryButton.dataset.folderPath);
  });
  element("folder-picker-images").addEventListener("change", event => {
    const checkbox = event.target.closest("[data-pick-input]");
    if (!checkbox) return;
    if (outputFolderPickerState.selectionMode === "single") outputFolderPickerState.selectedImageIds.clear();
    if (checkbox.checked) outputFolderPickerState.selectedImageIds.add(checkbox.dataset.pickInput);
    else outputFolderPickerState.selectedImageIds.delete(checkbox.dataset.pickInput);
    renderOutputFolderPicker();
    element("folder-picker-images").querySelector(`[data-pick-input="${checkbox.dataset.pickInput}"]`)?.focus();
  });
  element("folder-picker-parent").addEventListener("click", () => loadOutputFolder(outputFolderPickerState.parentPath));
  element("folder-picker-retry").addEventListener("click", () => loadOutputFolder(outputFolderPickerState.path));
  element("folder-picker-create-form").addEventListener("submit", createOutputPickerDirectory);
  element("folder-picker-cancel").addEventListener("click", () => finishOutputFolderSelection(null));
  element("folder-picker-confirm").addEventListener("click", () => {
    const pickerState = outputFolderPickerState;
    if (pickerState.selectionMode === "move") finishOutputFolderSelection(pickerState.path);
    else finishOutputFolderSelection({
      input_directory: pickerState.path,
      files: pickerState.images.filter(image => pickerState.selectedImageIds.has(String(image.output_id))),
    });
  });
}

/** 이동 결과의 성공·이미 같은 폴더·실패 건수를 사용자에게 알립니다. */
function showOutputMoveSummary(movement) {
  const failureCount = movement.failures.length;
  const summary = `결과물 ${movement.moved_count}개를 이동했습니다. 같은 폴더 ${movement.skipped_count}개`;
  showNotice(failureCount
    ? `${summary} · 이동 실패 ${failureCount}개 · ${movement.failures[0].detail}` : summary,
    failureCount > 0);
}

/** 선택한 결과물의 현재 경로를 서버에서 확인하여 한 목적지 폴더로 이동합니다. */
async function moveSelectedOutputs() {
  if (!applicationState.outputSelectionMode || outputSelectionIsBusy()) return;
  const selectedOutputIds = [...applicationState.selectedOutputIds];
  if (selectedOutputIds.length === 0) return;
  const destinationFolder = await chooseOutputFolder(`선택한 결과물 ${selectedOutputIds.length}개를 이동할 위치를 선택해 주세요.`);
  if (destinationFolder === null) return;
  applicationState.movingSelectedOutputs = true;
  applicationState.outputsLoadRevision += 1;
  renderOutputsList();
  try {
    const movement = await apiRequest("/api/outputs/move-batch", {
      method: "POST",
      body: JSON.stringify({ output_ids: selectedOutputIds.map(Number), destination_folder: destinationFolder }),
    });
    for (const outputIdentifier of [...movement.moved_output_ids, ...movement.skipped_output_ids]) {
      applicationState.selectedOutputIds.delete(String(outputIdentifier));
    }
    showOutputMoveSummary(movement);
  } finally {
    applicationState.movingSelectedOutputs = false;
    applicationState.outputsRenderSignature = null;
    await loadOutputs();
    renderOutputsList();
  }
}

/** 생성이 끝난 작업에 연결된 결과물 전체를 현재 위치에서 한 폴더로 이동합니다. */
async function moveJobOutputs(jobIdentifier) {
  if (jobSelectionIsBusy() || outputSelectionIsBusy()) return;
  const destinationFolder = await chooseOutputFolder(`작업 ${jobIdentifier}의 결과물 전체를 이동할 위치를 선택해 주세요.`);
  if (destinationFolder === null) return;
  applicationState.movingJobId = jobIdentifier;
  applicationState.jobsLoadRevision += 1;
  applicationState.outputsLoadRevision += 1;
  renderJobsList();
  try {
    const movement = await apiRequest(`/api/jobs/${encodeURIComponent(jobIdentifier)}/outputs/move`, {
      method: "POST", body: JSON.stringify({ destination_folder: destinationFolder }),
    });
    showOutputMoveSummary(movement);
  } finally {
    applicationState.movingJobId = null;
    applicationState.outputsRenderSignature = null;
    await loadJobs();
    renderJobsList();
    if (applicationState.currentView === "outputs") await loadOutputs();
  }
}

/** 관리 output 안에서 결과물을 다른 폴더로 이동합니다. */
async function moveOutput(sourcePath) {
  if (outputSelectionIsBusy()) return;
  const destinationFolder = await chooseOutputFolder(`${sourcePath} 파일을 이동할 위치를 선택해 주세요.`);
  if (destinationFolder === null) return;
  applicationState.movingOutputPath = sourcePath;
  applicationState.outputsLoadRevision += 1;
  renderOutputsList();
  try {
    const movement = await apiRequest("/api/outputs/move", {
      method: "POST",
      body: JSON.stringify({
        source: sourcePath,
        destination_folder: destinationFolder,
      }),
    });
    showNotice(movement.moved === false ? "이미 같은 폴더에 있는 파일입니다." : "파일을 이동했습니다.");
    applicationState.outputsPage = 1;
  } finally {
    applicationState.movingOutputPath = null;
    await loadOutputs();
    renderOutputsList();
  }
}

/** 영구 삭제할 실제 결과물 경로와 이력 유지 여부를 사용자에게 확인합니다. */
function confirmOutputFileDeletion(outputPath) {
  return window.confirm(`결과물 파일을 영구 삭제하시겠습니까?\n${outputPath}\n작업 이력은 유지되며 파일은 복구할 수 없습니다.`);
}

/** 미리보기의 현재 결과물만 삭제하고 같은 범위의 다음·이전 파일로 이동합니다. */
async function deletePreviewOutput() {
  const navigationState = outputPreviewNavigationState;
  const currentFile = navigationState.currentFile;
  if (!currentFile || element(`${currentFile.kind}-preview-delete`).disabled || outputSelectionIsBusy()) return;
  if (!confirmOutputFileDeletion(currentFile.path)) return;
  const revision = navigationState.revision;
  const adjacentFile = navigationState.next || navigationState.previous;
  const originalOpenerIdentifier = navigationState.opener?.dataset.imagePreview || navigationState.opener?.dataset.videoPreview;
  const previewJobIdentifier = navigationState.opener?.dataset.previewJob || null;
  let deletionSucceeded = false;
  applicationState.deletingOutputId = String(currentFile.output_id);
  applicationState.outputsLoadRevision += 1;
  renderOutputsList();
  renderOutputPreviewNavigation();
  try {
    await apiRequest(`/api/outputs/${currentFile.output_id}`, { method: "DELETE" });
    applicationState.selectedOutputIds.delete(String(currentFile.output_id));
    applicationState.visibleOutputs = applicationState.visibleOutputs.filter(output => output.output_id !== currentFile.output_id);
    deletionSucceeded = true;
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    applicationState.deletingOutputId = null;
    if (previewJobIdentifier) await loadJobs();
    else await loadOutputs();
    renderOutputsList();
    if (revision === navigationState.revision && navigationState.outputId === currentFile.output_id) {
      if (deletionSucceeded) {
        navigationState.opener = previewJobIdentifier
          ? document.querySelector(`[data-preview-job="${CSS.escape(previewJobIdentifier)}"][data-job-result-preview="${adjacentFile?.output_id || ""}"]`) ||
            document.querySelector(`[data-move-job-folder="${CSS.escape(previewJobIdentifier)}"]`) || element("jobs-folder-location")
          : document.querySelector(`[data-image-preview="${CSS.escape(originalOpenerIdentifier || "")}"], [data-video-preview="${CSS.escape(originalOpenerIdentifier || "")}"]`) ||
            element("outputs-grid").querySelector("[data-image-preview], [data-video-preview]") || element("refresh-outputs-button");
        if (adjacentFile) openOutputPreview(adjacentFile, navigationState.opener, true);
        else {
          const focusTarget = navigationState.opener;
          closeVideoPreview(false);
          closeImagePreview(false);
          focusTarget.focus({ preventScroll: true });
        }
      } else {
        navigationState.loading = true;
        await loadOutputPreviewNeighbors(currentFile.output_id, revision);
      }
    }
    renderOutputPreviewNavigation();
    if (deletionSucceeded) {
      await Promise.resolve();
      showNotice("결과물을 삭제했습니다.");
    }
  }
}

/** 확인한 결과물 하나를 삭제하고 현재 필터와 페이지의 목록을 다시 표시합니다. */
async function deleteOutput(deleteButton) {
  if (deleteButton.disabled || outputSelectionIsBusy()) return;
  const outputPath = deleteButton.dataset.outputPath;
  if (!confirmOutputFileDeletion(outputPath)) return;
  applicationState.deletingOutputId = deleteButton.dataset.deleteOutput;
  applicationState.outputsLoadRevision += 1;
  renderOutputsList();
  try {
    await apiRequest(`/api/outputs/${encodeURIComponent(deleteButton.dataset.deleteOutput)}`, { method: "DELETE" });
    showNotice("결과물을 삭제했습니다.");
    applicationState.selectedOutputIds.delete(deleteButton.dataset.deleteOutput);
  } finally {
    applicationState.deletingOutputId = null;
    await loadOutputs();
    renderOutputsList();
  }
}

/** 경고 확인 후 ComfyUI model과 cache 해제를 요청하고 중복 전송을 막습니다. */
async function freeComfyMemory() {
  const freeMemoryButton = element("free-vram-button");
  if (freeMemoryButton.disabled) return;
  const confirmationMessage = "ComfyUI의 model과 cache를 모두 비우시겠습니까?\n\n다음 생성 시 model 로딩과 cache 재계산으로 시간이 더 걸릴 수 있습니다.\n생성 중인 작업은 중단하지 않으며, 현재 작업 이후에 해제됩니다.";
  if (!window.confirm(confirmationMessage)) return;

  freeMemoryButton.disabled = true;
  freeMemoryButton.textContent = "요청 중…";
  try {
    await apiRequest("/api/comfy/free-memory", { method: "POST" });
    showNotice("VRAM 비우기를 요청했습니다. 생성 중이면 현재 작업 이후 model과 cache가 해제됩니다.");
  } finally {
    freeMemoryButton.disabled = false;
    freeMemoryButton.textContent = "VRAM 비우기";
  }
}

/** 비동기 UI 동작에서 발생한 오류를 알림으로 표시합니다. */
function runAction(action) {
  Promise.resolve()
    .then(action)
    .catch((error) => showNotice(error.message, true));
}

/** 사용자 조작과 메뉴 이동을 연결합니다. */
function bindEvents() {
  element("job-description-form").addEventListener("submit", event => {
    event.preventDefault();
    runAction(saveJobDescription);
  });
  element("job-description-cancel").addEventListener("click", () => closeJobDescriptionEditor());
  element("job-description-dialog").addEventListener("cancel", event => {
    event.preventDefault();
    closeJobDescriptionEditor();
  });
  element("job-description-dialog").addEventListener("close", () => {
    if (!element("job-description-dialog").open && jobDescriptionEditorState.jobIdentifier !== null) closeJobDescriptionEditor();
  });
  bindPreviewDialogEvents("video-preview-dialog", "video-preview-close", videoPreviewState, closeVideoPreview);
  bindPreviewDialogEvents("image-preview-dialog", "image-preview-close", imagePreviewState, closeImagePreview);
  element("image-preview-delete").addEventListener("click", () => runAction(deletePreviewOutput));
  element("video-preview-delete").addEventListener("click", () => runAction(deletePreviewOutput));
  element("image-preview-content").addEventListener("load", () => {
    if (imagePreviewState.outputId !== null) element("image-preview-status").textContent = "";
  });
  element("image-preview-content").addEventListener("error", () => {
    if (imagePreviewState.outputId !== null)
      element("image-preview-status").textContent = outputPreviewNavigationState.showOriginalFiles
        ? "원본 이미지를 불러올 수 없습니다."
        : "이미지 미리보기를 불러올 수 없습니다. 원본 보기로 확인해 주세요.";
  });
  element("video-preview-player").addEventListener("error", () => {
    if (videoPreviewState.outputId !== null) showNotice(outputPreviewNavigationState.showOriginalFiles
      ? "원본 영상을 재생할 수 없습니다. 원본을 새 탭으로 열거나 미리보기로 전환해 주세요."
      : "미리보기를 재생하지 못했습니다. 닫은 뒤 다시 열어 주세요.", true);
  });
  document.addEventListener("click", handleNavigationLinkClick);
  element("jobs-list").addEventListener("toggle", (event) => {
    saveCurrentNavigationEntry();
    if (event.target.matches(".job-requests") && event.target.open) {
      const cachedDetails = applicationState.jobDetails.get(event.target.dataset.jobDetails);
      if (cachedDetails?.error) cachedDetails.signature = null;
      loadJobDetails(event.target.dataset.jobDetails);
    }
  }, true);
  element("anima-aspect-ratio").addEventListener("change", updateAnimaResolutionOptions);
  element("anima-resolution").addEventListener("change", applyAnimaResolution);
  element("login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(async () => {
      try {
        await apiRequest("/api/login", {
          method: "POST",
          body: JSON.stringify({ password: element("login-password").value }),
        });
        element("login-password").value = "";
        element("login-error").textContent = "";
        await showApplication();
      } catch (error) {
        element("login-error").textContent = error.message;
      }
    });
  });
  element("logout-button").addEventListener("click", () =>
    runAction(async () => {
      await apiRequest("/api/logout", { method: "POST" });
      showLogin();
    }),
  );
  element("refresh-button").addEventListener("click", () =>
    runAction(async () => {
      await Promise.all([loadStatus(), loadJobs(), loadOutputs(), loadLoras(), loadLoraPresets(), loadTags()]);
      showNotice("새로고침했습니다.");
    }),
  );
  element("free-vram-button").addEventListener("click", () => runAction(freeComfyMemory));
  element("reload-web-assets-button").addEventListener("click", reloadWebAssets);
  element("generate-workflow").addEventListener("change", () => {
    resetGenerationWorkflow(element("generate-workflow").value);
    runAction(loadLoras);
  });
  element("generate-anima-prompt").addEventListener("input", renderGenerateTagGroups);
  element("generate-negative").addEventListener("input", renderGenerateTagGroups);
  element("generate-minimax-prompt").addEventListener("input", renderGenerateTagGroups);
  for (const identifier of ["generate-anima-prompt", "generate-negative", "generate-minimax-prompt"]) {
    element(identifier).addEventListener("input", renderGenerationPromptStatus);
  }
  element("expand-generate-tag-groups-button").addEventListener("click", () =>
    setTagGroupsExpanded("generate-tag-groups", applicationState.expandedTagGroupIds, true));
  element("collapse-generate-tag-groups-button").addEventListener("click", () =>
    setTagGroupsExpanded("generate-tag-groups", applicationState.expandedTagGroupIds, false));
  element("generate-tag-groups").addEventListener("change", (event) => {
    const tagId = event.target.dataset.selectTag;
    if (!tagId) return;
    if (event.target.checked) applicationState.selectedTagIds.add(tagId);
    else applicationState.selectedTagIds.delete(tagId);
    renderGenerateTagGroups();
  });
  element("generate-tag-groups").addEventListener("click", (event) => {
    const selectButton = event.target.closest("[data-select-visible-tag-group]");
    const clearButton = event.target.closest("[data-clear-visible-tag-group]");
    if (!selectButton && !clearButton) return;
    const groupId = selectButton?.dataset.selectVisibleTagGroup || clearButton.dataset.clearVisibleTagGroup;
    const selectedGroup = applicationState.tagGroups.find((group) => group.group_id === groupId);
    if (!selectedGroup || !requiredTagKeys().has(selectedGroup.tag_key)) return;
    const visibleEntries = sortedTagEntriesInGroup(groupId);
    for (const entry of visibleEntries) {
      if (selectButton) applicationState.selectedTagIds.add(entry.tag_id);
      else applicationState.selectedTagIds.delete(entry.tag_id);
    }
    renderGenerateTagGroups();
  });
  element("generate-tag-groups").addEventListener("toggle", (event) => {
    const groupId = event.target.dataset.tagGroupOpen;
    if (!groupId || !applicationState.expandedTagGroupIds) return;
    if (event.target.open) applicationState.expandedTagGroupIds.add(groupId);
    else applicationState.expandedTagGroupIds.delete(groupId);
  }, true);
  element("new-tag-group-button").addEventListener("click", () => editTagGroup());
  element("edit-selected-tag-group").addEventListener("click", () => editTagGroup(tagManagerState.selectedGroupId));
  element("delete-selected-tag-group").addEventListener("click", () => runAction(() => deleteTagGroup(applicationState.editingTagGroupId)));
  element("tag-entry-group").addEventListener("change", updateTagEntryGroupReference);
  element("tag-group-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(() => saveTagEditor("group"));
  });
  element("tag-group-list").addEventListener("click", (event) => {
    const groupButton = event.target.closest("[data-select-managed-group]");
    if (groupButton) selectManagedTagGroup(groupButton.dataset.selectManagedGroup);
  });
  element("tag-manager-group-search").addEventListener("input", event => {
    tagManagerState.groupSearch = event.target.value;
    element("tag-group-list").scrollTop = 0;
    renderTagManager();
  });
  element("tag-manager-reference-filter").addEventListener("change", event => {
    tagManagerState.referenceFilter = event.target.value;
    element("tag-group-list").scrollTop = 0;
    renderTagManager();
  });
  element("tag-manager-entry-search").addEventListener("input", event => {
    tagManagerState.entrySearch = event.target.value;
    element("tag-entry-list").scrollTop = 0;
    renderTagManager();
  });
  element("tag-manager-back").addEventListener("click", showManagedTagGroups);
  element("new-tag-entry-button").addEventListener("click", () => editTagEntry());
  element("delete-selected-tag-entry").addEventListener("click", () => runAction(() => deleteTagEntry(applicationState.editingTagEntryId)));
  element("tag-entry-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(() => saveTagEditor("entry"));
  });
  element("tag-entry-list").addEventListener("click", (event) => {
    const editButton = event.target.closest("[data-edit-tag-entry]");
    if (editButton) editTagEntry(editButton.dataset.editTagEntry);
  });
  for (const kind of ["group", "entry"]) {
    element(`tag-${kind}-cancel`).addEventListener("click", () => closeTagEditor());
    element(`tag-${kind}-dialog`).addEventListener("cancel", event => {
      event.preventDefault();
      closeTagEditor();
    });
  }
  element("generate-preset").addEventListener("change", (event) => {
    const preset = applicationState.presets.find(item => item.preset_id === event.target.value);
    if (preset) applyPromptToGeneration(preset.workflow, preset.body, preset);
    else {
      applicationState.currentPresetId = null;
      applicationState.currentPresetVersion = null;
      renderGenerationPromptStatus();
    }
  });
  element("edit-preset-button").addEventListener("click", () => editGenerationPrompt());
  element("save-current-preset-button").addEventListener("click", () => editGenerationPrompt(true));
  element("clear-generation-prompt-button").addEventListener("click", clearGenerationPrompt);
  for (const identifier of ["new-preset-button", "new-preset-detail-button"]) {
    element(identifier).addEventListener("click", () => startNewPrompt());
  }
  element("copy-preset-button").addEventListener("click", () => startNewPrompt(true));
  element("prompt-list-back").addEventListener("click", showPromptList);
  element("preset-search").addEventListener("input", event => {
    promptEditorState.search = event.target.value;
    element("preset-list").scrollTop = 0;
    renderPromptManagerList();
  });
  element("preset-workflow-filter").addEventListener("change", event => {
    promptEditorState.workflowFilter = event.target.value;
    element("preset-list").scrollTop = 0;
    renderPromptManagerList();
  });
  element("preset-edit-tab").addEventListener("click", () => navigatePromptDetailTab("edit"));
  element("preset-history-tab").addEventListener("click", () => runAction(() => showPresetVersions(promptEditorState.selectedPresetId)));
  element("retry-preset-versions").addEventListener("click", () => runAction(() => showPresetVersions(promptEditorState.selectedPresetId)));
  element("load-preset-version-button").addEventListener("click", loadPresetVersion);
  element("use-preset-button").addEventListener("click", usePromptEditorInGeneration);
  for (const identifier of ["preset-name", "preset-anima-prompt", "preset-negative", "preset-minimax-prompt"]) {
    element(identifier).addEventListener("input", () => {
      element("preset-editor-error").textContent = "";
      element("preset-save-message").textContent = "";
      renderPromptEditorStatus();
    });
  }
  element("preset-workflow").addEventListener("change", () => {
    const previousPrompt = promptEditorState.workflow === "anima"
      ? element("preset-anima-prompt").value : element("preset-minimax-prompt").value;
    element("preset-anima-prompt").value = previousPrompt;
    element("preset-minimax-prompt").value = previousPrompt;
    promptEditorState.workflow = element("preset-workflow").value;
    updatePresetWorkflowOptions();
    renderPromptEditorStatus();
  });
  element("save-preset-button").addEventListener("click", () =>
    runAction(savePreset),
  );
  element("preset-list").addEventListener("click", (event) => {
    const loadButton = event.target.closest("[data-load-preset]");
    const versionsButton = event.target.closest("[data-show-versions]");
    if (loadButton) loadPresetIntoEditor(loadButton.dataset.loadPreset);
    if (versionsButton)
      runAction(() => showPresetVersions(versionsButton.dataset.showVersions));
  });
  element("preset-version-history").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preview-version]");
    if (!button) return;
    const previousState = beginManagerNavigation();
    promptEditorState.previewVersion = Number(button.dataset.previewVersion);
    renderPromptVersionHistory();
    finishManagerNavigation(previousState);
  });
  window.addEventListener("beforeunload", event => {
    if (!promptEditorHasChanges() && !promptEditorState.saving && !tagEditorHasChanges() && !tagManagerState.editorBusy) return;
    event.preventDefault();
    event.returnValue = "";
  });
  element("refresh-loras-button").addEventListener("click", () =>
    runAction(loadLoras),
  );
  element("add-lora-button").addEventListener("click", () => {
    addLoraEntry(applicationState.selectedLoras, element("generate-workflow").value, element("available-loras").value);
    renderSelectedLoras();
  });
  element("selected-loras").addEventListener("input", (event) => {
    const row = event.target.closest("[data-lora-index]");
    if (row && event.target.dataset.loraField) {
      applicationState.selectedLoras[Number(row.dataset.loraIndex)][
        event.target.dataset.loraField
      ] = event.target.valueAsNumber;
      renderGenerationLoraPresetStatus();
    }
  });
  element("selected-loras").addEventListener("click", (event) => {
    const saveButton = event.target.closest("[data-save-lora]");
    if (saveButton) {
      runAction(async () => {
        const selectedLora =
          applicationState.selectedLoras[Number(saveButton.dataset.saveLora)];
        await apiRequest("/api/loras/profiles", {
          method: "POST",
          body: JSON.stringify({
            ...selectedLora,
            workflow: element("generate-workflow").value,
          }),
        });
        await loadLoras();
        showNotice("LoRA 기본 강도를 저장했습니다.");
      });
    }
    const button = event.target.closest("[data-remove-lora]");
    if (button) {
      applicationState.selectedLoras.splice(
        Number(button.dataset.removeLora),
        1,
      );
      renderSelectedLoras();
    }
  });
  element("select-minimax-input").addEventListener("click", () => runAction(selectMinimaxInputs));
  element("minimax-input-scope").addEventListener("change", () => clearMinimaxInputs());
  element("minimax-selected-images").addEventListener("change", event => {
    const checkbox = event.target.closest("[data-minimax-selected]");
    if (!checkbox) return;
    const selectedIdentifiers = new Set(applicationState.minimaxInputImages.map(image => String(image.output_id)));
    if (checkbox.checked) selectedIdentifiers.add(checkbox.dataset.minimaxSelected);
    else selectedIdentifiers.delete(checkbox.dataset.minimaxSelected);
    applicationState.minimaxInputImages = applicationState.minimaxInputCandidates.filter(image => selectedIdentifiers.has(String(image.output_id)));
    applyMinimaxAutomaticResolution();
    renderMinimaxInputs();
  });
  for (const inputIdentifier of ["minimax-width", "minimax-height"]) {
    element(inputIdentifier).addEventListener("input", () => {
      applicationState.minimaxResolutionManual = true;
      renderMinimaxInputs();
    });
  }
  element("minimax-automatic-resolution").addEventListener("click", () => {
    applicationState.minimaxResolutionManual = false;
    applyMinimaxAutomaticResolution();
    renderMinimaxInputs();
  });
  for (const inputIdentifier of ["minimax-generation-mode", "minimax-duration"]) {
    element(inputIdentifier).addEventListener("input", renderMinimaxInputs);
  }
  element("preview-button").addEventListener("click", () =>
    runAction(previewPrompt),
  );
  element("submit-button").addEventListener("click", () =>
    runAction(submitBatch),
  );
  element("toggle-job-selection").addEventListener("click", () => {
    if (jobSelectionIsBusy()) return;
    applicationState.jobSelectionMode = !applicationState.jobSelectionMode;
    applicationState.selectedJobIds.clear();
    renderJobsList();
    runAction(loadJobs);
  });
  element("select-all-jobs").addEventListener("click", toggleAllJobSelections);
  element("select-every-job").addEventListener("click", () => runAction(toggleEveryJobSelection));
  element("delete-selected-job-history").addEventListener("click", () =>
    runAction(() => deleteSelectedJobHistory(false)),
  );
  element("delete-selected-job-outputs").addEventListener("click", () =>
    runAction(() => deleteSelectedJobHistory(true)),
  );
  element("jobs-list").addEventListener("click", (event) => {
    toggleSelectionFromCardClick(
      event, ".job-card", "[data-select-job]", "[data-job-result-preview]", jobSelectionIsBusy(),
    );
  }, { capture: true });
  element("jobs-list").addEventListener("change", (event) => {
    const selectionCheckbox = event.target.closest("[data-select-job]");
    if (!selectionCheckbox || selectionCheckbox.disabled || jobSelectionIsBusy()) return;
    const selectedJobId = selectionCheckbox.dataset.selectJob;
    if (selectionCheckbox.checked) applicationState.selectedJobIds.add(selectedJobId);
    else applicationState.selectedJobIds.delete(selectedJobId);
    updateJobSelectionControls();
  });
  element("jobs-list").addEventListener("click", (event) => {
    const promptCard = event.target.closest("[data-job-prompt-card]");
    const requestPromptCard = event.target.closest("[data-request-prompt-card]");
    const interactiveTarget = event.target.closest("a, button, input, select, textarea, label, summary");
    if (!interactiveTarget && !window.getSelection()?.toString() && !jobSelectionIsBusy()) {
      if (requestPromptCard) toggleRequestPromptExpansion(requestPromptCard.dataset.requestPromptCard);
      else if (promptCard && !event.target.closest("details")) toggleJobPromptExpansion(promptCard.dataset.jobPromptCard);
    }
    const moveOutputsButton = event.target.closest("[data-move-job-outputs]");
    if (moveOutputsButton && !moveOutputsButton.disabled)
      runAction(() => moveJobOutputs(moveOutputsButton.dataset.moveJobOutputs));
    const editDescriptionButton = event.target.closest("[data-edit-job-description]");
    if (editDescriptionButton && !editDescriptionButton.disabled)
      openJobDescriptionEditor(editDescriptionButton.dataset.editJobDescription, editDescriptionButton);
    const protectionButton = event.target.closest("[data-toggle-job-protection]");
    if (protectionButton && !protectionButton.disabled)
      runAction(() => toggleJobDeletionProtection(protectionButton.dataset.toggleJobProtection));
    const restoreJobButton = event.target.closest("[data-restore-job]");
    if (restoreJobButton && !restoreJobButton.disabled)
      runAction(() => restoreJobGeneration(restoreJobButton.dataset.restoreJob));
    const useJobInputButton = event.target.closest("[data-use-job-input]");
    if (useJobInputButton && !useJobInputButton.disabled)
      runAction(() => useJobResultsAsMinimaxInput(useJobInputButton.dataset.useJobInput));
    const cancelButton = event.target.closest("[data-cancel-request]");
    const cancelJobButton = event.target.closest("[data-cancel-job]");
    const deleteJobButton = event.target.closest("[data-delete-job]");
    const deleteOutputsButton = event.target.closest("[data-delete-job-outputs]");
    if (cancelButton)
      runAction(async () => {
        await apiRequest(`/api/requests/${cancelButton.dataset.cancelRequest}/cancel`, {
          method: "POST",
        });
        await loadJobs();
      });
    if (cancelJobButton)
      runAction(async () => {
        const jobIdentifier = cancelJobButton.dataset.cancelJob;
        if (applicationState.cancellingJobIds.has(jobIdentifier)) return;
        applicationState.cancellingJobIds.add(jobIdentifier);
        renderJobsList();
        showNotice("추가 제출 중단과 작업 취소를 요청하는 중입니다.");
        try {
          const result = await apiRequest(`/api/jobs/${jobIdentifier}/cancel`, { method: "POST" });
          showNotice(`${result.requested_count ?? result.cancelled_count}건의 취소를 접수했습니다. 진행 상태를 확인해 주세요.`);
          await loadJobs();
        } finally {
          applicationState.cancellingJobIds.delete(jobIdentifier);
          renderJobsList();
        }
      });
    if (deleteJobButton)
      runAction(() => deleteJobHistory(deleteJobButton.dataset.deleteJob, false));
    if (deleteOutputsButton)
      runAction(() => deleteJobHistory(deleteOutputsButton.dataset.deleteJobOutputs, true));
  });
  element("jobs-list").addEventListener("keydown", event => {
    const promptContainer = event.target.closest("[data-toggle-job-prompt], [data-toggle-request-prompt]");
    if (!promptContainer || !["Enter", " "].includes(event.key) || jobSelectionIsBusy()) return;
    event.preventDefault();
    if (promptContainer.hasAttribute("data-toggle-request-prompt")) toggleRequestPromptExpansion(promptContainer.dataset.toggleRequestPrompt);
    else toggleJobPromptExpansion(promptContainer.dataset.toggleJobPrompt);
  });
  element("toggle-output-selection").addEventListener("click", () => {
    if (outputSelectionIsBusy()) return;
    applicationState.outputSelectionMode = !applicationState.outputSelectionMode;
    applicationState.outputsLoadRevision += 1;
    applicationState.selectedOutputIds.clear();
    applicationState.selectableOutputIds.clear();
    applicationState.deletableOutputIds.clear();
    renderOutputsList();
    runAction(loadOutputs);
  });
  element("select-all-outputs").addEventListener("click", toggleAllOutputSelections);
  element("select-every-output").addEventListener("click", () => runAction(toggleEveryOutputSelection));
  element("delete-selected-outputs").addEventListener("click", () => runAction(deleteSelectedOutputs));
  element("move-selected-outputs").addEventListener("click", () => runAction(moveSelectedOutputs));
  element("outputs-grid").addEventListener("click", (event) => {
    toggleSelectionFromCardClick(
      event, ".output-card", "[data-select-output]", "[data-image-preview], [data-video-preview]", outputSelectionIsBusy(),
    );
  }, { capture: true });
  element("outputs-grid").addEventListener("change", (event) => {
    const selectionCheckbox = event.target.closest("[data-select-output]");
    if (!selectionCheckbox || selectionCheckbox.disabled || outputSelectionIsBusy()) return;
    if (selectionCheckbox.checked) applicationState.selectedOutputIds.add(selectionCheckbox.dataset.selectOutput);
    else applicationState.selectedOutputIds.delete(selectionCheckbox.dataset.selectOutput);
    updateOutputSelectionControls();
  });
  element("refresh-outputs-button").addEventListener("click", () => {
    if (outputSelectionIsBusy()) return;
    applicationState.outputsPage = 1;
    saveCurrentNavigationEntry();
    runAction(async () => {
      await apiRequest("/api/outputs/sync", { method: "POST" });
      await loadOutputs();
    });
  });
  element("outputs-grid").addEventListener("click", (event) => {
    const imagePreviewButton = event.target.closest("[data-image-preview]");
    if (imagePreviewButton && !imagePreviewButton.disabled && !outputSelectionIsBusy()) {
      const outputFile = applicationState.visibleOutputs.find(output => String(output.output_id) === imagePreviewButton.dataset.imagePreview);
      if (outputFile) openOutputPreview(outputFile, imagePreviewButton);
      return;
    }
    const previewButton = event.target.closest("[data-video-preview]");
    if (previewButton && !previewButton.disabled && !outputSelectionIsBusy()) {
      const outputFile = applicationState.visibleOutputs.find(output => String(output.output_id) === previewButton.dataset.videoPreview);
      if (outputFile) openOutputPreview(outputFile, previewButton);
      return;
    }
    const button = event.target.closest("[data-move-output]");
    if (button && !button.disabled) runAction(() => moveOutput(button.dataset.moveOutput));
    const deleteButton = event.target.closest("[data-delete-output]");
    if (deleteButton && !deleteButton.disabled) runAction(() => deleteOutput(deleteButton));
  });
  bindLoraPresetEvents();
}

/** LoRA 조합의 불러오기, 편집, 저장과 관리 화면 이동을 연결합니다. */
function bindLoraPresetEvents() {
  element("generate-lora-preset").addEventListener("change", (event) => {
    const preset = applicationState.loraPresets.find((item) => item.preset_id === event.target.value);
    applyLoraCombination(element("generate-workflow").value, preset?.loras || [], preset?.preset_id || null);
  });
  element("manage-lora-presets-button").addEventListener("click", () => {
    if (applicationState.currentLoraPresetId) loadLoraPresetEditor(applicationState.currentLoraPresetId);
    else resetLoraPresetEditor(element("generate-workflow").value);
    applicationState.loraEditorEntries = normalizeLoraEntries(applicationState.selectedLoras, element("generate-workflow").value);
    renderLoraPresetEditor();
    switchView("lora-presets", { resetScroll: true });
  });
  element("save-generation-lora-preset-button").addEventListener("click", () => {
    const preset = applicationState.loraPresets.find((item) => item.preset_id === applicationState.currentLoraPresetId);
    element("generation-lora-preset-name").value = preset ? `${preset.name} 변형` : "";
    element("generation-lora-preset-form").classList.remove("hidden");
    element("generation-lora-preset-name").focus();
  });
  element("generation-lora-preset-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(saveGenerationLoraPreset);
  });
  element("cancel-generation-lora-preset-button").addEventListener("click", () => element("generation-lora-preset-form").classList.add("hidden"));
  element("new-lora-preset-button").addEventListener("click", () => resetLoraPresetEditor());
  element("lora-preset-workflow").addEventListener("change", () => resetLoraPresetEditor());
  element("lora-preset-name").addEventListener("input", renderLoraPresetEditorStatus);
  element("refresh-lora-preset-files-button").addEventListener("click", () => runAction(loadLoras));
  element("add-lora-preset-entry-button").addEventListener("click", () => {
    addLoraEntry(applicationState.loraEditorEntries, element("lora-preset-workflow").value, element("lora-preset-available-files").value);
    renderLoraPresetEditor();
  });
  element("lora-preset-selected-files").addEventListener("input", (event) => {
    const card = event.target.closest("[data-lora-index]");
    if (!card || !event.target.dataset.loraField) return;
    applicationState.loraEditorEntries[Number(card.dataset.loraIndex)][event.target.dataset.loraField] = event.target.valueAsNumber;
    renderLoraPresetEditorStatus();
  });
  element("lora-preset-selected-files").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-lora]");
    if (!button) return;
    applicationState.loraEditorEntries.splice(Number(button.dataset.removeLora), 1);
    renderLoraPresetEditor();
  });
  element("create-lora-preset-button").addEventListener("click", () => runAction(() => saveLoraPresetEditor(false)));
  element("update-lora-preset-button").addEventListener("click", () => runAction(() => saveLoraPresetEditor(true)));
  element("use-lora-preset-editor-button").addEventListener("click", () => {
    applyLoraCombination(element("lora-preset-workflow").value, applicationState.loraEditorEntries, applicationState.loraEditorPresetId);
    switchView("generate", { resetScroll: true });
  });
  element("lora-preset-list").addEventListener("click", (event) => {
    const editButton = event.target.closest("[data-edit-lora-preset]");
    const renameButton = event.target.closest("[data-rename-lora-preset]");
    const useButton = event.target.closest("[data-use-lora-preset]");
    const copyButton = event.target.closest("[data-copy-lora-preset]");
    const deleteButton = event.target.closest("[data-delete-lora-preset]");
    if (editButton) loadLoraPresetEditor(editButton.dataset.editLoraPreset);
    if (renameButton) runAction(() => renameLoraPreset(renameButton.dataset.renameLoraPreset));
    if (copyButton) loadLoraPresetEditor(copyButton.dataset.copyLoraPreset, true);
    if (useButton) {
      const preset = applicationState.loraPresets.find((item) => item.preset_id === useButton.dataset.useLoraPreset);
      if (!preset) return;
      applyLoraCombination(preset.workflow, preset.loras, preset.preset_id);
      switchView("generate", { resetScroll: true });
    }
    if (deleteButton) runAction(() => deleteLoraPreset(deleteButton.dataset.deleteLoraPreset));
  });
}

/** 작업 조회·전체 선택에서 분류·설명·특정 작업 범위를 동일하게 전달합니다. */
function jobHistoryQuery() {
  const query = new URLSearchParams();
  if (applicationState.jobFilterId) query.set("job_id", applicationState.jobFilterId);
  if (applicationState.jobFolderId) query.set("folder_id", applicationState.jobFolderId);
  if (applicationState.jobSearch) query.set("search", applicationState.jobSearch);
  return query;
}

/** 페이지와 무관한 선택 범위를 직렬화해 늦게 도착한 응답과 선택 누출을 막습니다. */
function currentJobHistoryScope() {
  return jobHistoryQuery().toString();
}

/** 작업 소속의 전체 경로를 표시하며 미분류는 시스템 이름으로 통일합니다. */
function jobHistoryFolderLabel(folderIdentifier) {
  if (!folderIdentifier) return "미분류";
  return jobHistoryFolderState.folders.find(folder => folder.folder_id === folderIdentifier)?.path || "분류 확인 중…";
}

/** 분류 응답을 저장하고 제출 폼의 현재 선택은 유효한 동안 유지합니다. */
function applyJobHistoryFolders(response) {
  jobHistoryFolderState.folders = response.items;
  jobHistoryFolderState.totalCount = response.total_count;
  jobHistoryFolderState.unassignedCount = response.unassigned_count;
  jobHistoryFolderState.loaded = true;
  const submissionSelect = element("job-history-folder");
  const selectedIdentifier = submissionSelect.value;
  const optionMarkup = '<option value="">미분류</option>' + response.items.map(folder =>
    `<option value="${escapeHtml(folder.folder_id)}">${escapeHtml(folder.path)}</option>`).join("");
  if (submissionSelect.innerHTML !== optionMarkup) {
    submissionSelect.innerHTML = optionMarkup;
    submissionSelect.value = response.items.some(folder => folder.folder_id === selectedIdentifier) ? selectedIdentifier : "";
  }
  renderJobHistoryFolders();
}

/** 중첩 들여쓰기·펼침·작업 수가 있는 분류 행을 만들고 선택은 Navigation 링크로 처리합니다. */
function jobHistoryFolderTreeMarkup(parentIdentifier = null) {
  const childFolders = jobHistoryFolderState.folders.filter(folder => folder.parent_id === parentIdentifier);
  childFolders.sort((leftFolder, rightFolder) => TAG_NAME_COLLATOR.compare(leftFolder.name, rightFolder.name));
  return childFolders.map(folder => {
    const isCollapsed = jobHistoryFolderState.collapsedFolderIds.has(folder.folder_id);
    const hasChildren = folder.descendant_folder_count > 0;
    const folderUrl = navigationUrl({ viewName: "jobs", pageNumber: 1, jobFolderId: folder.folder_id });
    const isSelected = applicationState.jobFolderId === folder.folder_id;
    return `<li><div class="job-folder-row ${isSelected ? "active" : ""}" style="--folder-depth:${folder.depth - 1}">
      ${hasChildren ? `<button class="job-folder-expand" type="button" data-toggle-history-folder="${escapeHtml(folder.folder_id)}" aria-label="${escapeHtml(folder.name)} ${isCollapsed ? "펼치기" : "접기"}" aria-expanded="${!isCollapsed}">${isCollapsed ? "▸" : "▾"}</button>` : '<span class="job-folder-expand" aria-hidden="true"></span>'}
      <a data-navigation data-history-folder="${escapeHtml(folder.folder_id)}" href="${escapeHtml(folderUrl)}" ${isSelected ? 'aria-current="location"' : ""} title="${escapeHtml(folder.path)}"><span>📁 ${escapeHtml(folder.name)}</span><small>${folder.job_count}</small></a>
    </div>${hasChildren && !isCollapsed ? `<ul>${jobHistoryFolderTreeMarkup(folder.folder_id)}</ul>` : ""}</li>`;
  }).join("");
}

/** 변경된 트리만 다시 그려 Polling 중 Focus와 모바일 패널 펼침 상태를 유지합니다. */
function renderJobHistoryFolders() {
  const state = jobHistoryFolderState;
  const currentFolder = state.folders.find(folder => folder.folder_id === applicationState.jobFolderId);
  const currentLabel = applicationState.jobFolderId === "unassigned" ? "미분류"
    : currentFolder?.path || "전체 작업";
  const currentIcon = applicationState.jobFolderId === "unassigned" ? "📥" : currentFolder ? "📁" : "📋";
  const count = currentFolder?.job_count ?? (applicationState.jobFolderId === "unassigned" ? state.unassignedCount : state.totalCount);
  element("jobs-folder-location").textContent = currentLabel;
  element("jobs-folder-panel-title").textContent = window.matchMedia("(max-width: 800px)").matches ? `${currentIcon} ${currentLabel}` : "작업 분류";
  element("jobs-folder-count").textContent = state.loaded
    ? `${count}개 작업${currentFolder?.descendant_folder_count ? " · 하위 분류 포함" : ""}${applicationState.jobSearch ? ` · 검색 결과 ${applicationState.jobsMatchedCount}개` : ""}` : "";
  element("jobs-folder-menu").classList.toggle("hidden", !currentFolder);
  element("edit-job-folder").classList.toggle("hidden", !currentFolder);
  element("edit-job-folder").disabled = jobSelectionIsBusy() || !state.loaded;
  element("create-job-folder").disabled = jobSelectionIsBusy() || !state.loaded || currentFolder?.depth === 3;
  element("create-job-folder").title = currentFolder?.depth === 3 ? "최대 3단계입니다. 상위 분류를 선택해 주세요." : "선택한 분류 아래에 새 분류 만들기";
  element("clear-jobs-search").classList.toggle("hidden", !applicationState.jobSearch);
  element("jobs-folder-status").textContent = !state.loaded ? "분류를 불러오는 중입니다." : currentFolder?.depth === 3 ? "최대 깊이 3단계입니다." : "";
  const signature = JSON.stringify([state.folders, state.totalCount, state.unassignedCount,
    applicationState.jobFolderId, [...state.collapsedFolderIds]]);
  if (signature === state.renderSignature) return;
  state.renderSignature = signature;
  const systemFolders = [{ identifier: "", icon: "📋", name: "전체 작업", count: state.totalCount },
    { identifier: "unassigned", icon: "📥", name: "미분류", count: state.unassignedCount }];
  element("jobs-folder-tree").innerHTML = `<ul>${systemFolders.map(folder => {
    const selected = applicationState.jobFolderId === folder.identifier;
    const folderUrl = navigationUrl({ viewName: "jobs", pageNumber: 1, jobFolderId: folder.identifier });
    return `<li><div class="job-folder-row system-folder ${selected ? "active" : ""}"><a data-navigation data-history-folder="${folder.identifier}" href="${escapeHtml(folderUrl)}" ${selected ? 'aria-current="location"' : ""}><span>${folder.icon} ${folder.name}</span><small>${folder.count}</small></a></div></li>`;
  }).join("")}${jobHistoryFolderTreeMarkup()}</ul>`;
}

/** 생성·이름 변경·부모 이동을 한 Dialog에 모으고 입력은 Polling과 독립적으로 유지합니다. */
function openJobHistoryFolderEditor(folderIdentifier = null) {
  if (jobSelectionIsBusy()) return;
  const folder = jobHistoryFolderState.folders.find(item => item.folder_id === folderIdentifier);
  if (folderIdentifier && !folder) return;
  const currentFolder = jobHistoryFolderState.folders.find(item => item.folder_id === applicationState.jobFolderId);
  jobHistoryFolderState.editingFolderId = folderIdentifier;
  element("jobs-folder-menu").open = false;
  element("job-folder-editor-title").textContent = folder ? "작업 분류 이름·위치 변경" : "새 분류";
  element("job-folder-name").value = folder?.name || "";
  const descendants = jobHistoryFolderState.folders.filter(item => item.path_ids.includes(folderIdentifier));
  const subtreeHeight = folder ? Math.max(...descendants.map(item => item.depth - folder.depth + 1)) : 1;
  const parentOptions = jobHistoryFolderState.folders.filter(item =>
    item.depth + subtreeHeight <= 3 && !item.path_ids.includes(folderIdentifier));
  element("job-folder-parent").innerHTML = '<option value="">최상위</option>' + parentOptions.map(item =>
    `<option value="${escapeHtml(item.folder_id)}">${escapeHtml(item.path)}</option>`).join("");
  element("job-folder-parent").value = folder ? (folder.parent_id || "") : (currentFolder?.depth < 3 ? currentFolder.folder_id : "");
  element("job-folder-editor-status").textContent = "";
  element("job-folder-editor").showModal();
  element("job-folder-name").focus();
}

/** Folder Mutation 동안 중복 제출을 막으며 다른 탭 이동 후에도 현재 화면만 갱신합니다. */
function setJobHistoryFolderBusy(busy) {
  jobHistoryFolderState.busy = busy;
  for (const identifier of ["job-folder-name", "job-folder-parent", "job-folder-editor-save", "job-folder-editor-cancel",
    "job-folder-move-save", "job-folder-move-cancel", "edit-job-folder", "delete-job-folder"]) {
    element(identifier).disabled = busy;
  }
  element("job-folder-move-tree").toggleAttribute("inert", busy);
  updateJobSelectionControls();
}

/** 저장한 분류를 다시 읽되 기존 생성 입력·선택·페이지는 그대로 유지합니다. */
async function saveJobHistoryFolder(event) {
  event.preventDefault();
  if (jobSelectionIsBusy()) return;
  const folderIdentifier = jobHistoryFolderState.editingFolderId;
  setJobHistoryFolderBusy(true);
  element("job-folder-editor-status").textContent = "저장 중…";
  try {
    await apiRequest(folderIdentifier ? `/api/job-folders/${encodeURIComponent(folderIdentifier)}` : "/api/job-folders", {
      method: folderIdentifier ? "PUT" : "POST",
      body: JSON.stringify({ name: element("job-folder-name").value, parent_id: element("job-folder-parent").value || null }),
    });
    applyJobHistoryFolders(await apiRequest("/api/job-folders"));
    element("job-folder-editor").close();
    showNotice(folderIdentifier ? "작업 분류를 변경했습니다." : "작업 분류를 만들었습니다.");
  } catch (error) {
    element("job-folder-editor-status").textContent = error.message;
  } finally {
    setJobHistoryFolderBusy(false);
    applicationState.jobsRenderSignature = null;
    await loadJobs();
  }
}

/** 삭제 범위와 미분류로 변경하는 작업 수를 먼저 확인하고 실제 파일은 건드리지 않습니다. */
async function deleteJobHistoryFolder() {
  if (jobSelectionIsBusy()) return;
  const folder = jobHistoryFolderState.folders.find(item => item.folder_id === applicationState.jobFolderId);
  if (!folder) return;
  const confirmation = `‘${folder.name}’ 분류와 하위 분류 ${folder.descendant_folder_count}개를 삭제하시겠습니까?\n작업 ${folder.job_count}개는 ‘미분류’로 변경합니다.\n작업 이력과 결과물 파일은 유지됩니다.`;
  if (!window.confirm(confirmation)) return;
  const navigationRevision = applicationState.navigationRevision;
  setJobHistoryFolderBusy(true);
  try {
    const response = await apiRequest(`/api/job-folders/${encodeURIComponent(folder.folder_id)}`, { method: "DELETE" });
    applyJobHistoryFolders(await apiRequest("/api/job-folders"));
    element("jobs-folder-menu").open = false;
    if (navigationRevision === applicationState.navigationRevision && applicationState.currentView === "jobs") {
      switchView("jobs", { resetScroll: true, pageNumber: 1, jobFolderId: "unassigned", jobFilterId: null, jobSearch: "" });
    }
    showNotice(`분류 ${response.deleted_folder_count}개를 삭제하고 작업 ${response.moved_job_count}개를 미분류로 변경했습니다.`);
  } finally {
    setJobHistoryFolderBusy(false);
    await loadJobs();
  }
}

/** 개별 또는 여러 작업에 대해 시스템 미분류와 3단계 분류를 같은 선택창으로 제공합니다. */
async function openJobHistoryFolderMove(jobIdentifiers) {
  if (jobSelectionIsBusy() || !jobIdentifiers.length) return;
  const dialogRevision = ++jobHistoryFolderState.dialogRevision;
  const selectionScope = currentJobHistoryScope();
  const folders = await apiRequest("/api/job-folders");
  if (dialogRevision !== jobHistoryFolderState.dialogRevision || applicationState.currentView !== "jobs" ||
      selectionScope !== currentJobHistoryScope() || jobSelectionIsBusy()) return;
  applyJobHistoryFolders(folders);
  jobHistoryFolderState.movingJobIds = [...jobIdentifiers];
  const firstJob = applicationState.visibleJobs.find(job => job.job_id === jobIdentifiers[0]);
  const initialFolder = firstJob?.folder_id || "";
  const choices = [{ folder_id: "", path: "미분류", depth: 1 }, ...jobHistoryFolderState.folders];
  element("job-folder-move-tree").innerHTML = choices.map(folder =>
    `<label class="job-folder-destination" style="--folder-depth:${folder.depth - 1}"><input type="radio" name="history-folder-destination" value="${escapeHtml(folder.folder_id)}" ${folder.folder_id === initialFolder ? "checked" : ""} /><span>📁 ${escapeHtml(folder.path)}</span></label>`).join("");
  element("job-folder-move-summary").textContent = `작업 ${jobIdentifiers.length}개의 분류를 변경합니다.`;
  element("job-folder-move-status").textContent = "";
  element("job-folder-move-dialog").showModal();
}

/** 이동 성공 후 현재 범위를 다시 조회하고 사라진 작업은 선택에서 자연스럽게 제거합니다. */
async function saveJobHistoryFolderMove(event) {
  event.preventDefault();
  if (jobSelectionIsBusy()) return;
  const jobIdentifiers = [...jobHistoryFolderState.movingJobIds];
  const destination = element("job-folder-move-tree").querySelector("input:checked");
  if (!destination || !jobIdentifiers.length) return;
  setJobHistoryFolderBusy(true);
  element("job-folder-move-status").textContent = "분류 변경 중…";
  try {
    const response = await apiRequest("/api/jobs/folder", {
      method: "POST", body: JSON.stringify({ job_ids: jobIdentifiers, folder_id: destination.value || null }),
    });
    element("job-folder-move-dialog").close();
    showNotice(`작업 ${response.moved_job_count}개의 분류를 변경했습니다.`);
    applicationState.jobsRenderSignature = null;
  } catch (error) {
    element("job-folder-move-status").textContent = error.message;
  } finally {
    setJobHistoryFolderBusy(false);
    await loadJobs();
  }
}

/** History 이동·로그아웃 시 남아 있는 분류 편집창을 닫습니다. */
function closeJobHistoryFolderDialogs() {
  jobHistoryFolderState.dialogRevision += 1;
  element("job-folder-editor").close();
  element("job-folder-move-dialog").close();
}

/** Catalog 대표 결과물을 기존 Thumbnail API로 지연 로드합니다. */
function jobHistoryPreviewMarkup(job) {
  const files = job.preview_files || [];
  if (!files.length) return "";
  return `<div class="job-result-thumbnails" aria-label="작업 결과물 미리보기">${files.map(file => {
    const isVideo = /\.(mp4|webm|mkv|mov)$/i.test(file.path);
    return `<button class="job-result-thumbnail" type="button" data-job-result-preview="${file.output_id}" data-preview-job="${escapeHtml(job.job_id)}" aria-label="${escapeHtml(file.path)} 미리보기"><img loading="lazy" src="/api/outputs/preview/${encodedOutputPath(file.path)}" alt="${escapeHtml(file.path.split("/").pop())}" />${isVideo ? '<span aria-hidden="true">▶</span>' : ""}</button>`;
  }).join("")}</div>`;
}

/** 분류·검색·이동 이벤트를 연결하고 모바일에서는 처음에 트리를 접습니다. */
function bindJobHistoryFolderEvents() {
  const mobileLayout = window.matchMedia("(max-width: 800px)");
  element("jobs-folder-panel").open = !mobileLayout.matches;
  mobileLayout.addEventListener("change", () => {
    element("jobs-folder-panel").open = !mobileLayout.matches;
    renderJobHistoryFolders();
  });
  element("create-job-folder").addEventListener("click", () => openJobHistoryFolderEditor());
  element("edit-job-folder").addEventListener("click", () => openJobHistoryFolderEditor(applicationState.jobFolderId));
  element("delete-job-folder").addEventListener("click", () => runAction(deleteJobHistoryFolder));
  element("job-folder-editor-form").addEventListener("submit", event => {
    event.preventDefault();
    runAction(() => saveJobHistoryFolder(event));
  });
  element("job-folder-move-form").addEventListener("submit", event => {
    event.preventDefault();
    runAction(() => saveJobHistoryFolderMove(event));
  });
  for (const dialogName of ["editor", "move"]) {
    const dialog = element(dialogName === "editor" ? "job-folder-editor" : "job-folder-move-dialog");
    element(`job-folder-${dialogName}-cancel`).addEventListener("click", () => dialog.close());
    dialog.addEventListener("cancel", event => { if (jobHistoryFolderState.busy) event.preventDefault(); });
  }
  element("move-selected-job-folder").addEventListener("click", () =>
    runAction(() => openJobHistoryFolderMove([...applicationState.selectedJobIds])));
  element("jobs-folder-tree").addEventListener("click", event => {
    const expandButton = event.target.closest("[data-toggle-history-folder]");
    if (expandButton) {
      const identifier = expandButton.dataset.toggleHistoryFolder;
      const collapsed = jobHistoryFolderState.collapsedFolderIds;
      if (collapsed.has(identifier)) collapsed.delete(identifier);
      else collapsed.add(identifier);
      renderJobHistoryFolders();
      element("jobs-folder-tree").querySelector(`[data-toggle-history-folder="${CSS.escape(identifier)}"]`)?.focus();
    }
    if (event.target.closest("a") && mobileLayout.matches) element("jobs-folder-panel").open = false;
  });
  element("jobs-list").addEventListener("click", event => {
    const folderButton = event.target.closest("[data-move-job-folder]");
    if (folderButton) runAction(() => openJobHistoryFolderMove([folderButton.dataset.moveJobFolder]));
    const previewButton = event.target.closest("[data-job-result-preview]");
    if (!previewButton) return;
    const job = applicationState.visibleJobs.find(item => item.job_id === previewButton.dataset.previewJob);
    const file = job?.preview_files?.find(item => String(item.output_id) === previewButton.dataset.jobResultPreview);
    if (!file) return;
    const outputFile = { ...file, name: file.path.split("/").pop(), kind: /\.(mp4|webm|mkv|mov)$/i.test(file.path) ? "video" : "image",
      job_id: job.job_id, deletion_protected: job.deletion_protected };
    openOutputPreview(outputFile, previewButton, false, { type: "job", id: job.job_id });
  });
  element("jobs-search-form").addEventListener("submit", event => {
    event.preventDefault();
    if (jobSelectionIsBusy()) return;
    switchView("jobs", { resetScroll: true, pageNumber: 1, jobSearch: element("jobs-search").value.trim() });
  });
  element("clear-jobs-search").addEventListener("click", () => {
    if (!jobSelectionIsBusy()) switchView("jobs", { resetScroll: true, pageNumber: 1, jobSearch: "" });
  });
}

/** 첫 화면을 준비하고 기존 session을 확인합니다. */
async function initializeApplication() {
  bindJobHistoryFolderEvents();
  bindOutputFolderPickerEvents();
  bindJobInputPickerEvents();
  bindEvents();
  configurePromptEditor(null, { workflow: "anima", showDetail: false });
  initializeNavigationHistory();
  updateAnimaResolutionOptions();
  try {
    const session = await apiRequest("/api/session");
    if (session.authenticated) await showApplication();
    else showLogin();
  } catch (error) {
    showLogin();
  }
}

initializeApplication();
