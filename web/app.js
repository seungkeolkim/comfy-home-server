"use strict";

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
  selectedLoras: [],
  selectedFiles: [],
  currentView: "generate",
  outputFilter: "",
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
  if (!response.ok)
    throw new Error(data.detail || `요청 실패: HTTP ${response.status}`);
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
  };
  element("page-title").textContent = titles[viewName];
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (viewName === "outputs") loadOutputs();
  if (viewName === "jobs") loadJobs();
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
  element("generate-count").disabled = !isAnima;
  element("workflow-options-step").textContent = isAnima ? "03" : "02";
  element("lora-step").textContent = isAnima ? "04" : "03";
  element("preview-hint").textContent = isAnima
    ? "미리보기는 실제 Impact wildcard 결과를 보여줍니다."
    : "미리보기는 모든 입력 이미지에 사용할 평문을 그대로 보여줍니다.";
  renderSelectedLoras();
  renderGenerateScenarios();
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
      <div class="field-row"><div><label>장소 · 선택</label><input data-scenario-field="location" value="${escapeHtml(scenario.location || "")}"></div><div><label>선택 가중치</label><input data-scenario-field="weight" type="number" min="0.1" step="0.1" value="${escapeHtml(scenario.weight ?? 1)}"></div></div>
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
    const workflow = element("generate-workflow").value;
    element("available-loras").innerHTML =
      `<option value="">LoRA 선택 · ${response.files.length}개</option>` +
      response.files
        .map((fileName) => {
          const savedProfile = applicationState.loraProfiles.some(
            (profile) =>
              profile.name === fileName && profile.workflow === workflow,
          );
          const label = savedProfile ? fileName : `${fileName} · 새 LoRA`;
          return `<option value="${escapeHtml(fileName)}">${escapeHtml(label)}</option>`;
        })
        .join("");
  } catch (error) {
    element("available-loras").innerHTML =
      `<option value="">ComfyUI 연결을 확인해 주세요</option>`;
  }
}

/** 현재 선택한 LoRA와 강도 입력을 그립니다. */
function renderSelectedLoras() {
  const isAnima = element("generate-workflow").value === "anima";
  element("selected-loras").innerHTML = applicationState.selectedLoras
    .map(
      (lora, index) => `
    <div class="selected-lora" data-lora-index="${index}"><div><strong>${escapeHtml(lora.name)}</strong><button class="text-button lora-save-button" data-save-lora="${index}" type="button">이 강도를 기본값으로 저장</button></div>
    <label>STR<input data-lora-field="strength" type="number" step="0.05" value="${escapeHtml(lora.strength)}"></label>
    <label>${isAnima ? "CLIP" : "V×"}<input data-lora-field="${isAnima ? "clip_strength" : "video_strength"}" type="number" step="0.05" value="${escapeHtml(isAnima ? lora.clip_strength : lora.video_strength)}"></label>
    ${isAnima ? "<span></span>" : `<label class="audio-strength">A×<input data-lora-field="audio_strength" type="number" step="0.05" value="${escapeHtml(lora.audio_strength)}"></label>`}
    <button class="icon-button" data-remove-lora="${index}" title="LoRA 제거">×</button></div>`,
    )
    .join("");
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
        body: generateBody(),
        selected_scenario_ids: workflow === "anima" ? selectedScenarioIds() : [],
        count: workflow === "anima" ? Number(element("generate-count").value) : 1,
        settings: generationSettings(),
        loras: applicationState.selectedLoras,
        upload_ids: uploadIds,
      }),
    });
    showNotice(
      `${response.request_ids.length}건을 접수했습니다. ComfyUI 제출 상태를 확인합니다.`,
    );
    switchView("jobs");
    await loadJobs();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Batch 제출";
  }
}

/** 앱이 제출한 작업들의 최신 상태를 표시합니다. */
async function loadJobs() {
  if (element("application").classList.contains("hidden")) return;
  try {
    const jobs = await apiRequest("/api/jobs");
    const activeCount = jobs.filter((job) =>
      ["submitting", "pending", "running"].includes(job.status),
    ).length;
    element("active-count").textContent = `작업 ${activeCount}`;
    const statusNames = {
      submitting: "제출 중",
      pending: "대기",
      running: "실행 중",
      completed: "완료",
      failed: "실패",
      cancelled: "취소",
      stopped: "중단",
    };
    element("jobs-list").innerHTML = jobs.length
      ? jobs
          .map(
            (job) => `
      <article class="job-card"><div><h3>${escapeHtml(job.workflow)} · ${escapeHtml(job.request_id)}</h3><p>${escapeHtml(job.created_at)} · prompt_id ${escapeHtml(job.prompt_id || "대기 중")}</p></div>
      <span class="status-badge ${escapeHtml(job.status)}">${escapeHtml(statusNames[job.status] || job.status)}</span>
      <div class="job-detail">${escapeHtml(job.error_message || job.detail.resolved?.prompt || "")}</div>
      <div class="job-actions inline-actions">${job.status === "pending" ? `<button class="button subtle small" data-cancel-job="${escapeHtml(job.request_id)}">대기 요청 취소</button>` : ""}<button class="button subtle small" data-show-result="${escapeHtml(job.request_id)}">결과 보기</button></div>
      </article>`,
          )
          .join("")
      : `<p class="empty-state">제출한 작업이 없습니다.</p>`;
  } catch (error) {
    if (applicationState.currentView === "jobs")
      showNotice(error.message, true);
  }
}

/** 관리 폴더의 현재 이미지와 영상을 표시합니다. */
async function loadOutputs() {
  if (element("application").classList.contains("hidden")) return;
  try {
    const outputPath = applicationState.outputFilter
      ? `/api/outputs?request_id=${encodeURIComponent(applicationState.outputFilter)}`
      : "/api/outputs";
    const response = await apiRequest(outputPath);
    const visibleFiles = response.files;
    element("output-count").textContent = applicationState.outputFilter
      ? `이 작업의 결과 ${visibleFiles.length}개`
      : `${response.total}개 파일`;
    element("clear-output-filter").classList.toggle(
      "hidden",
      !applicationState.outputFilter,
    );
    element("outputs-grid").innerHTML = visibleFiles.length
      ? visibleFiles
          .map((file) => {
            const url = `/media/${file.path.split("/").map(encodeURIComponent).join("/")}`;
            const media =
              file.kind === "video"
                ? `<video src="${url}" controls preload="metadata"></video>`
                : `<img src="${url}" alt="${escapeHtml(file.name)}" loading="lazy">`;
            return `<article class="output-card"><div class="output-preview">${media}</div><div class="output-info"><strong>${escapeHtml(file.name)}</strong><small>${escapeHtml(file.path)} · ${(file.size / 1024 / 1024).toFixed(1)} MB</small><div class="inline-actions"><a class="button subtle" href="${url}" target="_blank" rel="noopener">열기</a><button class="button subtle" data-move-output="${escapeHtml(file.path)}">이동</button></div></div></article>`;
          })
          .join("")
      : `<p class="empty-state">관리 폴더에 결과물이 없습니다.</p>`;
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
      await Promise.all([loadStatus(), loadJobs(), loadOutputs(), loadLoras()]);
      showNotice("새로고침했습니다.");
    }),
  );
  element("generate-workflow").addEventListener("change", () => {
    applicationState.currentPresetId = null;
    applicationState.currentBody = {
      prefix: "",
      suffix: "",
      negative: "",
      separator: ", ",
      scenarios: [],
    };
    applicationState.selectedLoras = [];
    for (const identifier of [
      "generate-prefix",
      "generate-suffix",
      "generate-negative",
      "generate-minimax-prompt",
    ])
      element(identifier).value = "";
    element("generate-separator").value = ", ";
    renderPresetList();
    updateWorkflowOptions();
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
      id: crypto.randomUUID(),
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
    const name = element("available-loras").value;
    if (
      !name ||
      applicationState.selectedLoras.some((lora) => lora.name === name)
    )
      return;
    const workflow = element("generate-workflow").value;
    const savedProfile = applicationState.loraProfiles.find(
      (profile) => profile.name === name && profile.workflow === workflow,
    );
    applicationState.selectedLoras.push({
      name,
      strength: savedProfile?.settings.strength ?? 1,
      clip_strength: savedProfile?.settings.clip_strength ?? 1,
      video_strength: savedProfile?.settings.video_strength ?? 1,
      audio_strength: savedProfile?.settings.audio_strength ?? 1,
    });
    renderSelectedLoras();
  });
  element("selected-loras").addEventListener("input", (event) => {
    const row = event.target.closest("[data-lora-index]");
    if (row && event.target.dataset.loraField)
      applicationState.selectedLoras[Number(row.dataset.loraIndex)][
        event.target.dataset.loraField
      ] = Number(event.target.value);
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
    const cancelButton = event.target.closest("[data-cancel-job]");
    const resultButton = event.target.closest("[data-show-result]");
    if (cancelButton)
      runAction(async () => {
        await apiRequest(`/api/jobs/${cancelButton.dataset.cancelJob}/cancel`, {
          method: "POST",
        });
        await loadJobs();
      });
    if (resultButton) {
      applicationState.outputFilter = resultButton.dataset.showResult;
      switchView("outputs");
    }
  });
  element("refresh-outputs-button").addEventListener("click", () =>
    runAction(loadOutputs),
  );
  element("clear-output-filter").addEventListener("click", () => {
    applicationState.outputFilter = "";
    runAction(loadOutputs);
  });
  element("outputs-grid").addEventListener("click", (event) => {
    const button = event.target.closest("[data-move-output]");
    if (button) runAction(() => moveOutput(button.dataset.moveOutput));
  });
}

/** 첫 화면을 준비하고 기존 session을 확인합니다. */
async function initializeApplication() {
  bindEvents();
  try {
    const session = await apiRequest("/api/session");
    if (session.authenticated) await showApplication();
    else showLogin();
  } catch (error) {
    showLogin();
  }
}

initializeApplication();
