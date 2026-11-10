"use strict";

const styleGenerationViewState = { projects: {}, busy: false, timer: null };

/** 한 프로젝트의 조합 편집과 생성 결과를 다른 작업 대상과 분리합니다. */
function currentStyleGenerationState(projectIdentifier = previewState.currentProjectIdentifier) {
  styleGenerationViewState.projects[projectIdentifier] ??= { options: null, results: null, error: "", lastResultMarkup: "" };
  return styleGenerationViewState.projects[projectIdentifier];
}

/** 서버가 반환한 파일 경로만 인증된 미디어 URL로 변환합니다. */
function styleImageUrl(relativePath, original = false) {
  const encodedPath = relativePath.split("/").map(encodeURIComponent).join("/");
  return `${original ? "/media/" : "/api/outputs/preview/"}${encodedPath}`;
}

/** 조합 구성은 편집용 범위와 실제 계획의 고정값을 구분해 표시합니다. */
function styleCombinationEditorMarkup(combination, combinationIndex, settings) {
  const rows = Object.entries(settings.componentPolicies).filter(([, policy]) => policy.enabled).map(([identifier, policy]) => {
    const selected = combination.components.find(component => component.identifier === identifier);
    return `<div class="generation-component"><label class="settings-checkbox"><input type="checkbox" data-generation-combination="${combinationIndex}" data-generation-component="${escapeMarkup(identifier)}" ${selected ? "checked" : ""} /><span>${escapeMarkup(identifier.replace(/^(artist:|lora:)/, ""))}</span></label><label>STR <input type="number" step="any" min="${policy.minimumStrength}" max="${policy.maximumStrength}" value="${selected?.strength ?? policy.minimumStrength}" data-generation-strength="${escapeMarkup(identifier)}" data-generation-combination="${combinationIndex}" ${selected ? "" : "disabled"} /></label><small>${policy.minimumStrength} ~ ${policy.maximumStrength}</small></div>`;
  }).join("");
  const artistCount = combination.components.filter(component => component.identifier.startsWith("artist:")).length;
  const loraCount = combination.components.filter(component => component.identifier.startsWith("lora:")).length;
  return `<section class="panel"><h2>조합 ${String.fromCharCode(65 + combinationIndex)}</h2><p class="form-note">프로젝트에서 허용한 성분·STR 범위입니다. 이 조합은 모든 Prompt에 동일하게 사용합니다.</p><p>작가 ${artistCount}개 (${settings.artistMinimumCount} ~ ${settings.artistMaximumCount}) · LoRA ${loraCount}개 (${settings.loraMinimumCount} ~ ${settings.loraMaximumCount})</p>${rows || '<p>선택할 성분이 없습니다. 사용 개수가 0 ~ 0이면 기본 모델만 사용합니다.</p>'}</section>`;
}

/** 저장한 프로젝트 범위와 요청 장수를 추첨 전에 확인하게 합니다. */
function randomStyleGenerationControlsMarkup(project, state) {
  const settings = project.settings;
  const requestedCount = state.randomCombinationCount ?? 4;
  const enabledArtists = Object.entries(settings.componentPolicies).filter(([identifier, policy]) => identifier.startsWith("artist:") && policy.enabled).length;
  const enabledLoras = Object.entries(settings.componentPolicies).filter(([identifier, policy]) => identifier.startsWith("lora:") && policy.enabled).length;
  return `<section class="panel"><h2>Random 초기 조합</h2><p>저장한 프로젝트 설정에서 작가·LoRA와 STR을 무작위로 뽑습니다. 각 조합은 모든 Prompt에 동일하게 적용합니다.</p><p>작가 ${settings.artistMinimumCount} ~ ${settings.artistMaximumCount}개 (허용 ${enabledArtists}개) · LoRA ${settings.loraMinimumCount} ~ ${settings.loraMaximumCount}개 (허용 ${enabledLoras}개)</p><label for="style-random-combination-count">만들 조합 수 (1 ~ 32개)</label><input id="style-random-combination-count" type="number" min="1" max="32" step="1" value="${escapeMarkup(requestedCount)}" /><p id="style-random-image-count">${escapeMarkup(requestedCount)}개 조합 × ${settings.promptCases.length}개 Prompt = 최대 ${Number.isInteger(Number(requestedCount)) ? Number(requestedCount) * settings.promptCases.length : "—"}장</p><p class="form-note">STR은 최솟값부터 0.01 간격과 최댓값 중에서 선택합니다. 범위가 같으면 해당 STR을 사용합니다. 이미지 Seed는 프로젝트의 ${settings.seed}를 유지합니다.</p><button class="primary" data-generation-action="random-start">이미지 생성</button><p class="form-note">생성 장수를 확인하고 시작합니다.</p></section>`;
}

/** 통신 재시도·확인 취소 때 새 조합을 뽑지 않고 저장한 계획을 재사용합니다. */
async function prepareRandomStyleGeneration(projectIdentifier, combinationCount) {
  const state = currentStyleGenerationState(projectIdentifier);
  const expectedRevision = currentProject().revision;
  let savedPlan = state.pendingRandomPlan;
  if (!savedPlan && !state.pendingRandomRequest) {
    savedPlan = state.results?.plans.find(plan => !plan.jobIdentifiers.length && plan.selection?.mode === "random" && plan.projectRevision === expectedRevision && plan.selection.requestedCount === combinationCount);
  }
  if (savedPlan?.projectRevision === expectedRevision && savedPlan.selection.requestedCount === combinationCount) {
    state.pendingRandomPlan = savedPlan;
    return savedPlan;
  }
  if (!state.pendingRandomRequest || state.pendingRandomRequest.expectedRevision !== expectedRevision || state.pendingRandomRequest.combinationCount !== combinationCount) {
    state.pendingRandomRequest = { expectedRevision, operationIdentifier: newStyleClientIdentifier(), combinationCount };
  }
  try {
    const plan = await styleProjectApi(`/api/style-projects/${projectIdentifier}/random-generation-plans`, { method: "POST", body: JSON.stringify(state.pendingRandomRequest) });
    state.pendingRandomPlan = plan;
    state.pendingRandomRequest = null;
    return plan;
  } catch (error) {
    if (error.status === 409 || error.status === 422) state.pendingRandomRequest = null;
    throw error;
  }
}

/** 성분 목록 없이 실제 생성 장수와 확인·취소 버튼만 표시합니다. */
function confirmStyleGeneration(plan) {
  const dialog = document.querySelector("#style-generation-confirmation-dialog");
  const shortageMessage = plan.selection?.shortfallCount
    ? `<p>요청한 ${plan.selection.requestedCount}개 중 ${plan.candidates.length}개 조합을 준비했습니다.</p>`
    : "";
  dialog.innerHTML = `<form method="dialog"><h2 id="style-generation-confirmation-title">이미지를 생성할까요?</h2>${shortageMessage}<p>${plan.candidates.length}개 조합 × ${plan.cases.length}개 Prompt = <strong>${plan.imageCount}장</strong></p><div class="form-actions"><button value="cancel">취소</button><button class="primary" value="confirm" autofocus>확인</button></div></form>`;
  dialog.returnValue = "cancel";
  return new Promise(resolve => {
    /** Escape·취소와 명시적 확인을 구분하고 한 번만 결과를 전달합니다. */
    function resolveGenerationConfirmation() {
      resolve(dialog.returnValue === "confirm");
    }
    dialog.addEventListener("close", resolveGenerationConfirmation, { once: true });
    dialog.showModal();
  });
}

/** 확인한 불변 계획만 제출하며 응답 유실 때도 서버의 중복 제출 방지를 사용합니다. */
async function submitConfirmedStyleGeneration(projectIdentifier, plan) {
  await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-plans/${plan.planIdentifier}/submit`, { method: "POST", body: JSON.stringify({ operationIdentifier: newStyleClientIdentifier(), retryFailedOnly: false }) });
  showToast("프로젝트 설정으로 이미지 생성을 접수했습니다.");
}

/** 조합 목록 없이 생성 입력과 실제 결과만 표시합니다. */
function renderStyleGeneration() {
  const project = currentProject();
  const state = currentStyleGenerationState();
  let controls = randomStyleGenerationControlsMarkup(project, state) + '<details class="panel"><summary>고정 A/B 조합 직접 확인</summary><p>성분·STR을 직접 지정해 Workflow를 확인하는 기존 도구입니다.</p><button data-generation-action="prepare">생성 조합 준비</button></details>';
  if (state.options) {
    controls = `<div class="form-row"><label>확인할 조합 수<select id="style-generation-count"><option value="2" ${state.options.combinations.length === 2 ? "selected" : ""}>2개</option><option value="1" ${state.options.combinations.length === 1 ? "selected" : ""}>1개</option></select></label></div>${state.options.combinations.map((combination, index) => styleCombinationEditorMarkup(combination, index, state.options.settings)).join("")}<button class="primary" data-generation-action="preview" ${styleGenerationViewState.busy ? "disabled" : ""}>이미지 생성</button>`;
  }
  return `<div class="page-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>프로젝트 이미지 생성</h1><p class="muted">저장한 프로젝트 설정으로 모든 Prompt의 이미지를 생성합니다.</p></div><button data-action="navigate" data-screen="project-settings">프로젝트 설정</button></div>${controls}<p id="style-generation-error" class="error" role="alert">${escapeMarkup(state.error)}</p><div id="style-render-results">${initialStyleResultsMarkup(state.results)}</div>`;
}

/** 현재 화면의 결과 영역을 같은 경로로 구성해 첫 Polling의 중복 교체를 막습니다. */
function styleResultsMarkupForCurrentScreen(results) {
  if (previewState.screen === "compare") return styleComparisonResultsMarkup();
  if (previewState.screen === "candidates") return styleLibraryResultsMarkup(results);
  return styleGenerationResultsMarkup(results);
}

/** 최초로 표시한 원문을 기록해 변경 없는 조회가 Scroll·Focus를 끊지 않게 합니다. */
function initialStyleResultsMarkup(results) {
  const markup = styleResultsMarkupForCurrentScreen(results);
  currentStyleGenerationState().lastResultMarkup = markup;
  return markup;
}

/** 실패·완료·미확인을 구분하고 같은 Case의 실제 결과를 나란히 표시합니다. */
function styleGenerationResultsMarkup(results) {
  const submittedPlans = (results?.plans || []).filter(plan => plan.jobIdentifiers.length);
  if (!submittedPlans.length) return '<section class="panel empty-state"><p>아직 생성한 이미지가 없습니다.</p></section>';
  const project = currentProject();
  const statusLabels = { submitting: "제출 준비 중", pending: "대기 중", running: "생성 중", completed: "완료", failed: "실패", stopped: "중단·접수 미확인", cancelled: "취소됨", cancelling: "취소 중" };
  return submittedPlans.map(plan => {
    const candidates = results.candidates.filter(candidate => candidate.planIdentifier === plan.planIdentifier);
    const renders = candidates.flatMap(candidate => candidate.renders);
    const latestRenders = candidates.flatMap(candidate => plan.cases.map(promptCase => candidate.renders.filter(render => render.caseIdentifier === promptCase.identifier).at(-1))).filter(Boolean);
    const hasRetryTargets = latestRenders.some(render => ["failed", "cancelled"].includes(render.status));
    const activeJobs = [...new Set(renders.filter(render => ["submitting", "pending", "running", "cancelling"].includes(render.status)).map(render => render.jobIdentifier))];
    return `<section class="panel generation-results"><div class="settings-section-heading"><h2>${plan.candidates.length}개 조합 · ${plan.cases.length}개 Prompt</h2></div>${plan.cases.map(promptCase => `<section><h3>${escapeMarkup(persistentPromptCaseName(promptCase))}</h3><div class="generation-result-grid">${candidates.map(candidate => {
      const render = candidate.renders.filter(item => item.caseIdentifier === promptCase.identifier).at(-1);
      const file = render?.files.find(item => item.is_available && !item.is_deleted);
      return `<article class="generation-result"><strong>조합 ${escapeMarkup(candidate.label)}</strong>${file ? `<button class="image-button" data-generation-action="enlarge" data-path="${escapeMarkup(file.path)}"><img loading="lazy" src="${styleImageUrl(file.path)}" alt="${escapeMarkup(persistentPromptCaseName(promptCase))} · 조합 ${escapeMarkup(candidate.label)}" style="aspect-ratio:${plan.sampling.width}/${plan.sampling.height}" /></button>` : `<div class="empty-state">${render ? escapeMarkup(statusLabels[render.status] || render.status) : "계획 확인 완료 · 미제출"}</div>`}${render?.error ? `<p class="error">${escapeMarkup(render.error)}</p>` : ""}<details><summary>성분·실제 생성 조건</summary><ul>${candidate.components.map(component => `<li>${escapeMarkup(component.identifier)} · STR ${component.strength}</li>`).join("")}</ul>${render?.settings ? `<p>Seed ${render.settings.seed} · ${render.settings.width}×${render.settings.height} · Steps ${render.settings.steps} · CFG ${render.settings.cfg}</p>` : ""}${render?.prompt ? `<p class="form-note">${escapeMarkup(render.prompt)}</p>` : ""}</details></article>`;
    }).join("")}</div></section>`).join("")}<div class="form-actions">${hasRetryTargets && !activeJobs.length ? `<button data-generation-action="retry" data-plan="${plan.planIdentifier}">실패·취소 항목만 재시도</button>` : ""}${activeJobs.map(jobIdentifier => `<button data-generation-action="cancel" data-job="${jobIdentifier}">이 생성 작업 취소</button>`).join("")}</div></section>`;
  }).join("") + `<p class="form-note">${escapeMarkup(project.name)}의 실제 결과입니다. 선별에서 비교하고 그림체에서 순위·Elo를 확인할 수 있습니다.</p>`;
}

/** Polling은 결과 영역만 바꾸며 작성 중 조합·Scroll·다른 프로젝트를 덮어쓰지 않습니다. */
async function refreshStyleGenerationResults(projectIdentifier = previewState.currentProjectIdentifier) {
  if (!PERSISTENT_STYLE_WORKSPACE || !projectIdentifier) return;
  const state = currentStyleGenerationState(projectIdentifier);
  if (state.votingCommandBusy) return;
  const refreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.resultRefreshSequence = refreshSequence;
  const results = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-results`);
  if (refreshSequence !== state.resultRefreshSequence) return;
  state.results = results;
  await refreshStyleVoting(projectIdentifier);
  if (refreshSequence !== state.resultRefreshSequence) return;
  const project = previewState.projects.find(project => project.identifier === projectIdentifier);
  if (project) project.candidateCount = results.candidates.filter(candidate => candidate.renders.length > 0).length;
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const resultContainer = document.querySelector("#style-render-results");
  if (resultContainer) {
    const markup = styleResultsMarkupForCurrentScreen(results);
    if (markup !== state.lastResultMarkup) {
      resultContainer.innerHTML = markup;
      state.lastResultMarkup = markup;
    }
  }
  updateStyleVotingControls();
}

/** 조합 입력을 프로젝트 허용 범위의 초안에만 반영합니다. */
function handleStyleGenerationInput(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const field = event.target;
  if (!field.isConnected) return;
  const state = currentStyleGenerationState();
  if (field.id === "style-random-combination-count") {
    state.randomCombinationCount = field.value;
    state.pendingRandomRequest = null;
    state.pendingRandomPlan = null;
    const imageCount = Number(field.value) * currentProject().settings.promptCases.length;
    document.querySelector("#style-random-image-count").textContent = `${field.value || "—"}개 조합 × ${currentProject().settings.promptCases.length}개 Prompt = 최대 ${Number.isInteger(imageCount) && imageCount > 0 ? imageCount : "—"}장`;
    return;
  }
  if (field.id === "style-generation-count") {
    if (field.value === "1") state.options.combinations = state.options.combinations.slice(0, 1);
    else if (state.options.combinations.length < 2) state.options.combinations.push(structuredClone(state.options.combinations[0]));
    renderPreview(false);
    return;
  }
  if (field.dataset.generationCombination === undefined) return;
  const combination = state.options.combinations[Number(field.dataset.generationCombination)];
  const identifier = field.dataset.generationComponent || field.dataset.generationStrength;
  if (field.dataset.generationComponent) {
    combination.components = combination.components.filter(component => component.identifier !== identifier);
    if (field.checked) combination.components.push({ identifier, strength: state.options.settings.componentPolicies[identifier].minimumStrength });
    renderPreview(false);
  } else {
    combination.components.find(component => component.identifier === identifier).strength = Number(field.value);
  }
}

/** 명시적인 계획 확인·생성·소유 Job 취소만 서버에 전달합니다. */
async function handleStyleGenerationAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-generation-action]");
  if (!button || button.disabled || styleGenerationViewState.busy) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const action = button.dataset.generationAction;
  if (action === "enlarge") {
    illustrationDialog.innerHTML = `<div class="dialog-heading"><h2>생성 이미지</h2><button data-generation-action="close-enlarged">닫기</button></div><img src="${styleImageUrl(button.dataset.path, true)}" alt="생성 원본 이미지" />`;
    illustrationDialog.showModal();
    return;
  }
  if (action === "close-enlarged") {
    illustrationDialog.close();
    return;
  }
  styleGenerationViewState.busy = true;
  const contentContainer = document.querySelector("#preview-content");
  contentContainer.inert = true;
  button.disabled = true;
  state.error = "";
  try {
    if (action === "random-start") {
      const countInput = document.querySelector("#style-random-combination-count");
      if (!countInput.reportValidity() || !countInput.value) throw new Error("조합 수를 1 ~ 32 사이의 정수로 입력해 주세요.");
      const plan = await prepareRandomStyleGeneration(projectIdentifier, Number(countInput.value));
      if (projectIdentifier === previewState.currentProjectIdentifier && await confirmStyleGeneration(plan)) {
        await submitConfirmedStyleGeneration(projectIdentifier, plan);
        state.pendingRandomPlan = null;
      }
    }
    if (action === "prepare") {
      state.options = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-options`);
    }
    if (action === "preview") {
      const plan = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-plans`, { method: "POST", body: JSON.stringify({ expectedRevision: state.options.projectRevision, operationIdentifier: newStyleClientIdentifier(), combinations: state.options.combinations }) });
      if (await confirmStyleGeneration(plan)) await submitConfirmedStyleGeneration(projectIdentifier, plan);
    }
    if (action === "retry") {
      await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-plans/${button.dataset.plan}/submit`, { method: "POST", body: JSON.stringify({ operationIdentifier: newStyleClientIdentifier(), retryFailedOnly: true }) });
      showToast("실패·취소 항목의 생성을 접수했습니다.");
    }
    if (action === "cancel") await styleProjectApi(`/api/jobs/${button.dataset.job}/cancel`, { method: "POST" });
    await refreshStyleGenerationResults(projectIdentifier);
  } catch (error) {
    state.error = error.message;
  } finally {
    styleGenerationViewState.busy = false;
    contentContainer.inert = false;
    if (projectIdentifier === previewState.currentProjectIdentifier) renderPreview(false);
    button.disabled = false;
  }
}

/** 화면 이동 후 결과를 읽고 Browser를 닫아도 서버 감시가 계속되게 합니다. */
function scheduleStyleGenerationRefresh() {
  clearTimeout(styleGenerationViewState.timer);
  if (!PERSISTENT_STYLE_WORKSPACE || !["generation", "candidates", "compare"].includes(previewState.screen) || !currentProject()) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  refreshStyleGenerationResults(projectIdentifier).catch(error => {
    currentStyleGenerationState(projectIdentifier).error = error.message;
    if (projectIdentifier === previewState.currentProjectIdentifier) {
      const errorContainer = document.querySelector("#style-generation-error");
      if (errorContainer) errorContainer.textContent = error.message;
    }
  });
  styleGenerationViewState.timer = setTimeout(scheduleStyleGenerationRefresh, 2000);
}

document.addEventListener("change", handleStyleGenerationInput);
document.addEventListener("input", handleStyleGenerationInput);
document.addEventListener("click", handleStyleGenerationAction);
