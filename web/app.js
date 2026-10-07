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

const applicationState = {
  presets: [],
  presetVersions: [],
  currentPresetId: null,
  currentBody: {
    prefix: "",
    suffix: "",
    negative: "",
    separator: ", ",
    scenarios: [],
  },
  availableLoras: [],
  loraProfiles: [],
  loraPresets: [],
  currentLoraPresetId: null,
  loraEditorPresetId: null,
  loraEditorEntries: [],
  loraCatalogAvailable: false,
  selectedLoras: [],
  selectedFiles: [],
  currentView: "generate",
  outputFilter: null,
  outputsPage: 1,
  outputsLoadRevision: 0,
  jobsPage: 1,
  jobsLoadRevision: 0,
  pollingTimer: null,
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

/** HTTP 접속에서도 쓸 수 있는 무작위 상황 식별자를 만듭니다. */
function createScenarioIdentifier() {
  const randomBytes = new Uint8Array(16);
  crypto.getRandomValues(randomBytes);
  return Array.from(randomBytes, (randomByte) =>
    randomByte.toString(16).padStart(2, "0")).join("");
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
    throw new Error(errorDetail || `요청 실패: HTTP ${response.status}`);
  }
  return data;
}

/** 상단 알림을 잠시 표시합니다. */
function showNotice(message, isError = false) {
  const notice = element("notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  notice.classList.remove("hidden");
  window.setTimeout(() => notice.classList.add("hidden"), 6500);
}

/** 로그인 화면만 표시합니다. */
function showLogin() {
  element("application").classList.add("hidden");
  element("login-screen").classList.remove("hidden");
}

/** 앱 화면을 표시하고 필요한 목록을 읽습니다. */
async function showApplication() {
  element("login-screen").classList.add("hidden");
  element("application").classList.remove("hidden");
  await Promise.allSettled([
    loadPresets(),
    loadLoras(),
    loadLoraPresets(),
    loadJobs(),
    loadOutputs(),
    loadStatus(),
  ]);
  if (!applicationState.pollingTimer) {
    applicationState.pollingTimer = window.setInterval(loadJobs, 1000);
  }
}

/** 현재 화면을 바꿉니다. */
function switchView(viewName) {
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
    "lora-presets": "LoRA 조합",
  };
  element("page-title").textContent = titles[viewName];
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (viewName === "outputs") loadOutputs();
  if (viewName === "jobs") loadJobs();
}

/** Workflow를 바꿀 때 기존 모델의 Prompt와 LoRA 선택을 초기화합니다. */
function resetGenerationWorkflow(workflow) {
  element("generate-workflow").value = workflow;
  applicationState.currentPresetId = null;
  applicationState.currentLoraPresetId = null;
  applicationState.currentBody = { prefix: "", suffix: "", negative: "", separator: ", ", scenarios: [] };
  applicationState.selectedLoras = [];
  for (const identifier of ["generate-prefix", "generate-suffix", "generate-negative", "generate-minimax-prompt"])
    element(identifier).value = "";
  element("generate-separator").value = ", ";
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

/** Workflow별 입력 영역을 전환합니다. */
function updateWorkflowOptions() {
  const isAnima = element("generate-workflow").value === "anima";
  element("anima-prompt-fields").classList.toggle("hidden", !isAnima);
  element("minimax-prompt-fields").classList.toggle("hidden", isAnima);
  element("generate-scenario-fields").classList.toggle("hidden", !isAnima);
  element("anima-options").classList.toggle("hidden", !isAnima);
  element("minimax-options").classList.toggle("hidden", isAnima);
  element("generate-count-field").classList.toggle("hidden", !isAnima);
  element("generate-count-hint").classList.toggle("hidden", !isAnima);
  element("generate-count").disabled = !isAnima;
  element("lora-step").textContent = isAnima ? "03" : "02";
  element("workflow-options-step").textContent = isAnima ? "04" : "03";
  element("preview-hint").textContent = isAnima
    ? "미리보기는 실제 Impact wildcard 결과를 보여줍니다."
    : "미리보기는 모든 입력 이미지에 사용할 평문을 그대로 보여줍니다.";
  renderLoraPresetList();
  renderSelectedLoras();
  renderLoraFileOptions();
  renderGenerateScenarios();
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
  resolutionSelect.selectedIndex = resolutionSelect.options.length - 1;
  applyAnimaResolution();
}

/** Prompt 편집 화면에서 Workflow별 입력 form을 전환합니다. */
function updatePresetWorkflowOptions() {
  const isAnima = element("preset-workflow").value === "anima";
  element("preset-anima-fields").classList.toggle("hidden", !isAnima);
  element("preset-minimax-fields").classList.toggle("hidden", isAnima);
  element("preset-form-description").textContent = isAnima
    ? "상황을 읽기 쉬운 단위로 편집하고 버전으로 저장합니다."
    : "MiniMax Prompt를 평문으로 편집하고 버전으로 저장합니다.";
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

/** 생성 화면과 Prompt 화면에 preset 목록을 표시합니다. */
function renderPresetList() {
  const workflow = element("generate-workflow").value;
  const options = applicationState.presets
    .filter((preset) => preset.workflow === workflow)
    .map(
      (preset) =>
        `<option value="${escapeHtml(preset.preset_id)}">${escapeHtml(preset.name)} · v${preset.version}</option>`,
    )
    .join("");
  element("generate-preset").innerHTML =
    `<option value="">직접 작성</option>${options}`;
  if (
    applicationState.currentPresetId &&
    applicationState.presets.some(
      (preset) =>
        preset.preset_id === applicationState.currentPresetId &&
        preset.workflow === workflow,
    )
  ) {
    element("generate-preset").value = applicationState.currentPresetId;
  }
  element("preset-list").innerHTML = applicationState.presets.length
    ? applicationState.presets
        .map(
          (preset) =>
            `<div class="preset-row"><div><strong>${escapeHtml(preset.name)}</strong><small>${escapeHtml(preset.workflow)} · v${preset.version} · ${escapeHtml(preset.updated_at)}</small></div><div class="inline-actions"><button class="button subtle small" data-load-preset="${escapeHtml(preset.preset_id)}">열기</button><button class="button subtle small" data-show-versions="${escapeHtml(preset.preset_id)}">버전</button></div></div>`,
        )
        .join("")
    : `<p class="empty-state">저장된 preset이 없습니다.</p>`;
}

/** 같은 Prompt 본문을 생성 화면과 편집 화면에 채웁니다. */
function fillPromptFields(body) {
  element("preset-prefix").value = body.prefix || "";
  element("preset-suffix").value = body.suffix || "";
  element("preset-negative").value = body.negative || "";
  element("preset-separator").value = body.separator ?? ", ";
  element("preset-minimax-prompt").value = body.prompt || "";
  element("generate-prefix").value = body.prefix || "";
  element("generate-suffix").value = body.suffix || "";
  element("generate-negative").value = body.negative || "";
  element("generate-separator").value = body.separator ?? ", ";
  element("generate-minimax-prompt").value = body.prompt || "";
}

/** 선택한 preset을 생성 화면과 편집 화면에 불러옵니다. */
function loadPresetIntoEditor(presetId) {
  const preset = applicationState.presets.find(
    (item) => item.preset_id === presetId,
  );
  if (!preset) return;
  if (element("generate-workflow").value !== preset.workflow)
    resetGenerationWorkflow(preset.workflow);
  applicationState.currentPresetId = preset.preset_id;
  applicationState.currentBody = structuredClone(preset.body);
  element("preset-name").value = preset.name;
  element("preset-workflow").value = preset.workflow;
  element("preset-version").textContent = `현재 v${preset.version}`;
  element("generate-workflow").value = preset.workflow;
  element("generate-preset").value = preset.preset_id;
  fillPromptFields(preset.body);
  renderScenarioEditor();
  selectAllGenerateScenarios();
  updateWorkflowOptions();
  updatePresetWorkflowOptions();
}

/** 저장된 이전 버전을 목록으로 보여줍니다. */
async function showPresetVersions(presetId) {
  applicationState.presetVersions = await apiRequest(
    `/api/presets/${encodeURIComponent(presetId)}/versions`,
  );
  element("preset-version-history").innerHTML = applicationState.presetVersions
    .map(
      (version) => `
    <div class="preset-row"><div><strong>v${version.version}</strong><small>${escapeHtml(version.saved_at)}</small></div>
    <button class="button subtle small" data-load-version="${version.version}" data-preset-id="${escapeHtml(presetId)}">이 버전 열기</button></div>`,
    )
    .join("");
}

/** 이전 버전의 본문을 편집기에 복원합니다. 저장 시 새 버전이 됩니다. */
function loadPresetVersion(presetId, versionNumber) {
  loadPresetIntoEditor(presetId);
  const version = applicationState.presetVersions.find(
    (item) => item.version === versionNumber,
  );
  if (!version) return;
  applicationState.currentBody = structuredClone(version.body);
  fillPromptFields(version.body);
  element("preset-version").textContent =
    `v${versionNumber} 열림 · 저장하면 새 버전이 됩니다.`;
  renderScenarioEditor();
  selectAllGenerateScenarios();
}

/** Prompt 편집 화면의 현재 입력값을 객체로 만듭니다. */
function editorBody() {
  if (element("preset-workflow").value === "minimax_h3") {
    return { prompt: element("preset-minimax-prompt").value };
  }
  return {
    prefix: element("preset-prefix").value,
    suffix: element("preset-suffix").value,
    negative: element("preset-negative").value,
    separator: element("preset-separator").value,
    scenarios: applicationState.currentBody.scenarios || [],
  };
}

/** 생성 화면의 현재 Prompt를 객체로 만듭니다. */
function generateBody() {
  if (element("generate-workflow").value === "minimax_h3") {
    return { prompt: element("generate-minimax-prompt").value };
  }
  return {
    prefix: element("generate-prefix").value,
    suffix: element("generate-suffix").value,
    negative: element("generate-negative").value,
    separator: element("generate-separator").value,
    scenarios: applicationState.currentBody.scenarios || [],
  };
}

/** 편집 중인 상황 카드들을 그립니다. */
function renderScenarioEditor() {
  const scenarios = applicationState.currentBody.scenarios || [];
  element("scenario-editor").innerHTML = scenarios.length
    ? scenarios
        .map(
          (scenario, index) => `
    <article class="scenario-editor-card" data-scenario-index="${index}">
      <header><input data-scenario-field="name" aria-label="상황 이름" placeholder="상황 이름" value="${escapeHtml(scenario.name || "")}"><button class="icon-button" data-remove-scenario="${index}" title="상황 제거">×</button></header>
      <div class="field-row"><div><label>캐릭터 구성</label><textarea data-scenario-field="characters" rows="2" placeholder="{캐릭터 A|캐릭터 B}">${escapeHtml(scenario.characters || "")}</textarea></div><div><label>상황 표현</label><textarea data-scenario-field="situation" rows="2">${escapeHtml(scenario.situation || "")}</textarea></div></div>
      <div class="field-row"><div><label>세부 동작 · 선택</label><textarea data-scenario-field="details" rows="2">${escapeHtml(scenario.details || "")}</textarea></div><div><label>표정·감정선</label><textarea data-scenario-field="emotion" rows="2">${escapeHtml(scenario.emotion || "")}</textarea></div></div>
      <div class="field-row"><div><label>장소 · 선택</label><textarea data-scenario-field="location" rows="2">${escapeHtml(scenario.location || "")}</textarea></div><div><label>선택 가중치</label><input data-scenario-field="weight" type="number" min="0.1" step="0.1" value="${escapeHtml(scenario.weight ?? 1)}"></div></div>
    </article>`,
        )
        .join("")
    : `<p class="empty-state">상황을 추가하면 checkbox로 선택할 수 있습니다.</p>`;
  renderGenerateScenarios();
}

/** 생성 화면에 상황 checkbox를 그립니다. */
function renderGenerateScenarios() {
  const selectedIds = new Set(
    [...element("generate-scenarios").querySelectorAll("input:checked")].map(
      (input) => input.value,
    ),
  );
  const scenarios = applicationState.currentBody.scenarios || [];
  element("generate-scenarios").classList.toggle(
    "empty-state",
    scenarios.length === 0,
  );
  element("generate-scenarios").innerHTML = scenarios.length
    ? scenarios
        .map(
          (scenario) =>
            `<label class="scenario-choice"><input type="checkbox" value="${escapeHtml(scenario.id)}" ${selectedIds.has(scenario.id) ? "checked" : ""}><span>${escapeHtml(scenario.name || "이름 없는 상황")}</span></label>`,
        )
        .join("")
    : "등록된 상황이 없습니다. Prompt 화면에서 추가하세요.";
}

/** 불러온 preset의 상황을 생성 화면에서 모두 선택합니다. */
function selectAllGenerateScenarios() {
  const checkboxes = element("generate-scenarios").querySelectorAll(
    "input[type=checkbox]",
  );
  for (const checkbox of checkboxes) {
    checkbox.checked = true;
  }
}

/** 체크한 상황 식별자를 반환합니다. */
function selectedScenarioIds() {
  return [
    ...element("generate-scenarios").querySelectorAll("input:checked"),
  ].map((input) => input.value);
}

/** 현재 Prompt를 새 버전으로 저장합니다. */
async function savePreset() {
  const name = element("preset-name").value.trim();
  if (!name) throw new Error("Preset 이름을 입력해 주세요.");
  const result = await apiRequest("/api/presets", {
    method: "POST",
    body: JSON.stringify({
      preset_id: applicationState.currentPresetId,
      name,
      workflow: element("preset-workflow").value,
      body: editorBody(),
    }),
  });
  await loadPresets();
  loadPresetIntoEditor(result.preset_id);
  showNotice(`${name} v${result.version}을 저장했습니다.`);
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
      <div class="inline-actions"><button class="button subtle small" type="button" data-edit-lora-preset="${escapeHtml(preset.preset_id)}">열기</button><button class="button subtle small" type="button" data-use-lora-preset="${escapeHtml(preset.preset_id)}">생성에서 사용</button><button class="button subtle small" type="button" data-copy-lora-preset="${escapeHtml(preset.preset_id)}">복제</button><button class="button subtle small" type="button" data-delete-lora-preset="${escapeHtml(preset.preset_id)}">삭제</button></div></article>`).join("")
    : '<p class="empty-state">저장된 LoRA 조합이 없습니다.</p>';
}

/** 생성 화면의 카드 변경이 원본 preset과 다른지 표시합니다. */
function renderGenerationLoraPresetStatus() {
  const workflow = element("generate-workflow").value;
  const preset = applicationState.loraPresets.find((item) => item.preset_id === applicationState.currentLoraPresetId && item.workflow === workflow);
  const modified = preset && JSON.stringify(normalizeLoraEntries(applicationState.selectedLoras, workflow)) !== JSON.stringify(normalizeLoraEntries(preset.loras, workflow));
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
      selected_scenario_ids: workflow === "anima" ? selectedScenarioIds() : [],
      count: 5,
    }),
  });
  element("preview-results").classList.remove("hidden");
  if (workflow === "minimax_h3") {
    element("preview-results").innerHTML =
      `<div class="preview-item"><strong>MiniMax에 전달할 평문</strong>${escapeHtml(response.combined_prompt)}</div>`;
    return;
  }
  element("preview-results").innerHTML =
    `<div class="preview-item"><strong>조립된 wildcard 문구</strong>${escapeHtml(response.combined_prompt)}</div>` +
    response.examples
      .map(
        (example) =>
          `<div class="preview-item"><strong>${example.index}. ${escapeHtml(example.scenario || "공통 Prompt")} · seed ${example.seed}</strong>${escapeHtml(example.prompt)}</div>`,
      )
      .join("");
}

/** MiniMax 입력 이미지를 임시 업로드하고 식별자를 돌려줍니다. */
async function uploadImages() {
  const uploadIds = [];
  for (const file of applicationState.selectedFiles) {
    const formData = new FormData();
    formData.append("file", file);
    const uploaded = await apiRequest("/api/uploads", {
      method: "POST",
      body: formData,
    });
    uploadIds.push(uploaded.upload_id);
  }
  return uploadIds;
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
    applicationState.selectedFiles.length === 0
  ) {
    throw new Error("MiniMax 입력 이미지를 선택해 주세요.");
  }
  const submitButton = element("submit-button");
  submitButton.disabled = true;
  submitButton.textContent = "제출 중...";
  try {
    const uploadIds = workflow === "minimax_h3" ? await uploadImages() : [];
    const response = await apiRequest("/api/batches", {
      method: "POST",
      body: JSON.stringify({
        workflow,
        description: element("job-description").value,
        body: generateBody(),
        selected_scenario_ids: workflow === "anima" ? selectedScenarioIds() : [],
        count: workflow === "anima" ? Number(element("generate-count").value) : 1,
        settings: generationSettings(),
        loras: applicationState.selectedLoras,
        upload_ids: uploadIds,
      }),
    });
    showNotice(
      `${response.request_ids.length}건을 접수했습니다. 작업 목록에서 ComfyUI 제출 상태를 확인할 수 있습니다.`,
    );
    applicationState.jobsPage = 1;
    await loadJobs();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "작업 제출";
  }
}

/** 상위 작업에 속한 ComfyUI 요청의 상태와 조작 버튼을 표시합니다. */
function requestCardMarkup(request, statusNames) {
  const requestDetail = request.error_message || request.detail.resolved?.prompt || "";
  return `
    <div class="job-request">
      <div>
        <strong>요청 ${request.request_index} · ${escapeHtml(request.request_id)}</strong>
        <p>prompt_id ${escapeHtml(request.prompt_id || "대기 중")}</p>
      </div>
      <span class="status-badge ${escapeHtml(request.status)}">${escapeHtml(statusNames[request.status] || request.status)}</span>
      <div class="job-detail">${escapeHtml(requestDetail)}</div>
      <div class="job-actions inline-actions">
        ${["pending", "running"].includes(request.status) ? `<button class="button subtle small" data-cancel-request="${escapeHtml(request.request_id)}">요청 취소</button>` : ""}
        <button class="button subtle small" data-show-request-results="${escapeHtml(request.request_id)}">요청 결과 보기</button>
      </div>
    </div>`;
}

/** 한 번의 제출을 하나의 상위 작업 카드로 표시합니다. */
function jobCardMarkup(job, statusNames, openJobIds) {
  const completedCount = job.status_counts.completed || 0;
  const failedCount = job.status_counts.failed || 0;
  const progressText = `완료 ${completedCount}/${job.request_count}` +
    (failedCount ? ` · 실패 ${failedCount}` : "");
  const openAttribute = openJobIds.has(job.job_id) ? " open" : "";
  const canCancel = job.requests.some((request) => ["pending", "running"].includes(request.status));
  const canDelete = job.requests.every((request) =>
    !["submitting", "pending", "running", "cancelling"].includes(request.status),
  );
  return `
    <article class="job-card">
      <div>
        <h3>${escapeHtml(job.workflow)} · 작업 ${escapeHtml(job.job_id)}</h3>
        <p>${escapeHtml(job.created_at)} · ${escapeHtml(progressText)}</p>
        ${job.description ? `<p class="job-description">${escapeHtml(job.description)}</p>` : ""}
      </div>
      <span class="status-badge ${escapeHtml(job.status)}">${escapeHtml(statusNames[job.status] || job.status)}</span>
      <div class="job-actions inline-actions">
        <button class="button subtle small" data-show-job-results="${escapeHtml(job.job_id)}">작업 결과 보기</button>
        ${canCancel ? `<button class="button subtle small" data-cancel-job="${escapeHtml(job.job_id)}">작업 취소</button>` : ""}
        ${canDelete ? `<button class="button subtle small" data-delete-job="${escapeHtml(job.job_id)}">이력만 삭제</button><button class="button danger small" data-delete-job-outputs="${escapeHtml(job.job_id)}">이력·결과물 삭제</button>` : ""}
      </div>
      <details class="job-requests" data-job-details="${escapeHtml(job.job_id)}"${openAttribute}>
        <summary>하위 요청 ${job.request_count}건</summary>
        <div class="job-request-list">${job.requests.map((request) => requestCardMarkup(request, statusNames)).join("")}</div>
      </details>
    </article>`;
}

/** 현재 페이지와 인접한 페이지로 이동할 버튼을 표시합니다. */
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
    const currentAttribute = pageNumber === page ? ' aria-current="page"' : "";
    pageButtons.push(`<button class="button subtle small" data-jobs-page="${pageNumber}"${currentAttribute}>${pageNumber}</button>`);
  }
  pagination.innerHTML = `
    <button class="button subtle small" data-jobs-page="${page - 1}" ${page === 1 ? "disabled" : ""}>이전</button>
    ${pageButtons.join("")}
    <button class="button subtle small" data-jobs-page="${page + 1}" ${page === totalPages ? "disabled" : ""}>다음</button>`;
}

/** 앱이 제출한 상위 작업과 하위 요청의 최신 상태를 표시합니다. */
async function loadJobs() {
  if (element("application").classList.contains("hidden")) return;
  const loadRevision = ++applicationState.jobsLoadRevision;
  try {
    const response = await apiRequest(`/api/jobs?page=${applicationState.jobsPage}&page_size=10`);
    if (loadRevision !== applicationState.jobsLoadRevision) return;
    if (applicationState.jobsPage > response.total_pages) {
      applicationState.jobsPage = response.total_pages;
      return loadJobs();
    }
    element("active-count").textContent = `작업 ${response.active_count}`;
    const statusNames = {
      submitting: "제출 중",
      pending: "대기",
      running: "실행 중",
      cancelling: "취소 중",
      completed: "완료",
      failed: "실패",
      partial: "일부 완료",
      cancelled: "취소",
      stopped: "중단",
    };
    const openJobIds = new Set(
      [...document.querySelectorAll("#jobs-list details[open]")].map((details) =>
        details.dataset.jobDetails,
      ),
    );
    element("jobs-list").innerHTML = response.items.length
      ? response.items.map((job) => jobCardMarkup(job, statusNames, openJobIds)).join("")
      : `<p class="empty-state">제출한 작업이 없습니다.</p>`;
    renderJobsPagination(response.page, response.total_pages);
  } catch (error) {
    if (applicationState.currentView === "jobs")
      showNotice(error.message, true);
  }
}

/** 선택한 작업의 이력과 요청한 경우 원래 위치의 결과물을 삭제합니다. */
async function deleteJobHistory(jobId, deleteOutputs) {
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

/** 현재 결과물 페이지로 이동할 버튼을 표시합니다. */
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
    const currentAttribute = pageNumber === page ? ' aria-current="page"' : "";
    pageButtons.push(`<button class="button subtle small" data-outputs-page="${pageNumber}"${currentAttribute}>${pageNumber}</button>`);
  }
  pagination.innerHTML = `
    <button class="button subtle small" data-outputs-page="${page - 1}" ${page === 1 ? "disabled" : ""}>이전</button>
    ${pageButtons.join("")}
    <button class="button subtle small" data-outputs-page="${page + 1}" ${page === totalPages ? "disabled" : ""}>다음</button>`;
}

/** 관리 폴더의 현재 결과물을 페이지 단위로 표시합니다. */
async function loadOutputs() {
  if (element("application").classList.contains("hidden")) return;
  const loadRevision = ++applicationState.outputsLoadRevision;
  try {
    const outputFilter = applicationState.outputFilter;
    const query = new URLSearchParams({ page: String(applicationState.outputsPage), page_size: "24" });
    if (outputFilter)
      query.set(outputFilter.type === "job" ? "job_id" : "request_id", outputFilter.id);
    const response = await apiRequest(`/api/outputs?${query}`);
    if (loadRevision !== applicationState.outputsLoadRevision) return;
    if (applicationState.outputsPage > response.total_pages) {
      applicationState.outputsPage = response.total_pages;
      return loadOutputs();
    }
    const visibleFiles = response.files;
    element("output-count").textContent = outputFilter
      ? `${outputFilter.type === "job" ? "이 작업" : "이 요청"}의 결과 ${response.total}개`
      : `${response.total}개 파일`;
    element("clear-output-filter").classList.toggle(
      "hidden",
      !outputFilter,
    );
    element("outputs-grid").innerHTML = visibleFiles.length
      ? visibleFiles
          .map((file) => {
            const url = `/media/${file.path.split("/").map(encodeURIComponent).join("/")}`;
            const media =
              file.kind === "video"
                ? `<span class="output-video-placeholder">영상 · 열기로 재생</span>`
                : `<img src="/api/outputs/preview/${file.path.split("/").map(encodeURIComponent).join("/")}" alt="${escapeHtml(file.name)}" loading="lazy">`;
            return `<article class="output-card"><div class="output-preview">${media}</div><div class="output-info"><strong>${escapeHtml(file.name)}</strong><small>${escapeHtml(file.path)} · ${(file.size / 1024 / 1024).toFixed(1)} MB</small><div class="inline-actions"><a class="button subtle" href="${url}" target="_blank" rel="noopener">열기</a><button class="button subtle" data-move-output="${escapeHtml(file.path)}">이동</button></div></div></article>`;
          })
          .join("")
      : `<p class="empty-state">관리 폴더에 결과물이 없습니다.</p>`;
    renderOutputsPagination(response.page, response.total_pages);
  } catch (error) {
    showNotice(error.message, true);
  }
}

/** 관리 output 안에서 결과물을 다른 폴더로 이동합니다. */
async function moveOutput(sourcePath) {
  const destinationFolder = window.prompt(
    "이동할 폴더를 from_home_server 기준 상대 경로로 입력하세요.",
    "sorted",
  );
  if (!destinationFolder) return;
  await apiRequest("/api/outputs/move", {
    method: "POST",
    body: JSON.stringify({
      source: sourcePath,
      destination_folder: destinationFolder,
    }),
  });
  showNotice("파일을 이동했습니다.");
  applicationState.outputsPage = 1;
  await loadOutputs();
}

/** 비동기 UI 동작에서 발생한 오류를 알림으로 표시합니다. */
function runAction(action) {
  Promise.resolve()
    .then(action)
    .catch((error) => showNotice(error.message, true));
}

/** 사용자 조작과 메뉴 이동을 연결합니다. */
function bindEvents() {
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
  document
    .querySelectorAll("[data-view]")
    .forEach((button) =>
      button.addEventListener("click", () => switchView(button.dataset.view)),
    );
  element("refresh-button").addEventListener("click", () =>
    runAction(async () => {
      await Promise.all([loadStatus(), loadJobs(), loadOutputs(), loadLoras(), loadLoraPresets()]);
      showNotice("새로고침했습니다.");
    }),
  );
  element("generate-workflow").addEventListener("change", () => {
    resetGenerationWorkflow(element("generate-workflow").value);
    runAction(loadLoras);
  });
  element("generate-preset").addEventListener("change", (event) => {
    if (event.target.value) loadPresetIntoEditor(event.target.value);
    else applicationState.currentPresetId = null;
  });
  element("edit-preset-button").addEventListener("click", () => {
    applicationState.currentBody = generateBody();
    element("preset-workflow").value = element("generate-workflow").value;
    fillPromptFields(applicationState.currentBody);
    renderScenarioEditor();
    updatePresetWorkflowOptions();
    switchView("prompts");
  });
  element("save-current-preset-button").addEventListener("click", () => {
    applicationState.currentPresetId = null;
    applicationState.currentBody = generateBody();
    element("preset-name").value = "";
    element("preset-version").textContent = "새 preset";
    element("preset-workflow").value = element("generate-workflow").value;
    fillPromptFields(applicationState.currentBody);
    updatePresetWorkflowOptions();
    renderScenarioEditor();
    switchView("prompts");
  });
  element("preset-workflow").addEventListener("change", () => {
    applicationState.currentPresetId = null;
    element("preset-version").textContent = "새 preset";
    updatePresetWorkflowOptions();
  });
  element("add-scenario-button").addEventListener("click", () => {
    const scenarios = applicationState.currentBody.scenarios || [];
    scenarios.push({
      id: createScenarioIdentifier(),
      name: "새 상황",
      characters: "",
      situation: "",
      details: "",
      emotion: "",
      location: "",
      weight: 1,
    });
    applicationState.currentBody.scenarios = scenarios;
    renderScenarioEditor();
  });
  element("scenario-editor").addEventListener("input", (event) => {
    const card = event.target.closest("[data-scenario-index]");
    if (!card || !event.target.dataset.scenarioField) return;
    applicationState.currentBody.scenarios[Number(card.dataset.scenarioIndex)][
      event.target.dataset.scenarioField
    ] =
      event.target.dataset.scenarioField === "weight"
        ? Number(event.target.value)
        : event.target.value;
    if (event.target.dataset.scenarioField === "name")
      renderGenerateScenarios();
  });
  element("scenario-editor").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-scenario]");
    if (!button) return;
    applicationState.currentBody.scenarios.splice(
      Number(button.dataset.removeScenario),
      1,
    );
    renderScenarioEditor();
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
    const button = event.target.closest("[data-load-version]");
    if (button)
      loadPresetVersion(
        button.dataset.presetId,
        Number(button.dataset.loadVersion),
      );
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
  for (const inputId of ["minimax-images", "minimax-directory"])
    element(inputId).addEventListener("change", (event) => {
      applicationState.selectedFiles = [...event.target.files].filter((file) =>
        /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name),
      );
      element("selected-images").textContent =
        `${applicationState.selectedFiles.length}개 이미지 선택됨`;
    });
  element("preview-button").addEventListener("click", () =>
    runAction(previewPrompt),
  );
  element("submit-button").addEventListener("click", () =>
    runAction(submitBatch),
  );
  element("jobs-list").addEventListener("click", (event) => {
    const cancelButton = event.target.closest("[data-cancel-request]");
    const cancelJobButton = event.target.closest("[data-cancel-job]");
    const deleteJobButton = event.target.closest("[data-delete-job]");
    const deleteOutputsButton = event.target.closest("[data-delete-job-outputs]");
    const jobResultButton = event.target.closest("[data-show-job-results]");
    const requestResultButton = event.target.closest("[data-show-request-results]");
    if (cancelButton)
      runAction(async () => {
        await apiRequest(`/api/requests/${cancelButton.dataset.cancelRequest}/cancel`, {
          method: "POST",
        });
        await loadJobs();
      });
    if (cancelJobButton)
      runAction(async () => {
        const result = await apiRequest(`/api/jobs/${cancelJobButton.dataset.cancelJob}/cancel`, {
          method: "POST",
        });
        showNotice(`${result.cancelled_count}건의 취소를 요청했습니다.`);
        await loadJobs();
      });
    if (deleteJobButton)
      runAction(() => deleteJobHistory(deleteJobButton.dataset.deleteJob, false));
    if (deleteOutputsButton)
      runAction(() => deleteJobHistory(deleteOutputsButton.dataset.deleteJobOutputs, true));
    if (jobResultButton || requestResultButton) {
      applicationState.outputFilter = jobResultButton
        ? { type: "job", id: jobResultButton.dataset.showJobResults }
        : { type: "request", id: requestResultButton.dataset.showRequestResults };
      applicationState.outputsPage = 1;
      switchView("outputs");
    }
  });
  element("jobs-pagination").addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-jobs-page]");
    if (!pageButton || pageButton.disabled) return;
    applicationState.jobsPage = Number(pageButton.dataset.jobsPage);
    runAction(loadJobs);
  });
  element("refresh-outputs-button").addEventListener("click", () => {
    applicationState.outputsPage = 1;
    runAction(loadOutputs);
  });
  element("clear-output-filter").addEventListener("click", () => {
    applicationState.outputFilter = null;
    applicationState.outputsPage = 1;
    runAction(loadOutputs);
  });
  element("outputs-pagination").addEventListener("click", (event) => {
    const pageButton = event.target.closest("[data-outputs-page]");
    if (!pageButton || pageButton.disabled) return;
    applicationState.outputsPage = Number(pageButton.dataset.outputsPage);
    runAction(loadOutputs);
  });
  element("outputs-grid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-move-output]");
    if (button) runAction(() => moveOutput(button.dataset.moveOutput));
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
    switchView("lora-presets");
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
    switchView("generate");
  });
  element("lora-preset-list").addEventListener("click", (event) => {
    const editButton = event.target.closest("[data-edit-lora-preset]");
    const useButton = event.target.closest("[data-use-lora-preset]");
    const copyButton = event.target.closest("[data-copy-lora-preset]");
    const deleteButton = event.target.closest("[data-delete-lora-preset]");
    if (editButton) loadLoraPresetEditor(editButton.dataset.editLoraPreset);
    if (copyButton) loadLoraPresetEditor(copyButton.dataset.copyLoraPreset, true);
    if (useButton) {
      const preset = applicationState.loraPresets.find((item) => item.preset_id === useButton.dataset.useLoraPreset);
      if (!preset) return;
      applyLoraCombination(preset.workflow, preset.loras, preset.preset_id);
      switchView("generate");
    }
    if (deleteButton) runAction(() => deleteLoraPreset(deleteButton.dataset.deleteLoraPreset));
  });
}

/** 첫 화면을 준비하고 기존 session을 확인합니다. */
async function initializeApplication() {
  bindEvents();
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
