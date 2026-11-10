"use strict";

const styleGenerationViewState = { projects: {}, busy: false, timer: null };

/** 한 프로젝트의 조합 편집과 생성 결과를 다른 작업 대상과 분리합니다. */
function currentStyleGenerationState(projectIdentifier = previewState.currentProjectIdentifier) {
  styleGenerationViewState.projects[projectIdentifier] ??= { options: null, plan: null, results: null, error: "", lastResultMarkup: "" };
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

/** 고정 계획 확인과 실제 GPU 제출을 별도 버튼으로 제공합니다. */
function renderStyleGeneration() {
  const project = currentProject();
  const state = currentStyleGenerationState();
  let controls = '<section class="panel"><p>Workflow 연결 확인용 고정 A/B 조합을 준비합니다. Random 초기 조합 생성은 아직 연결하지 않았습니다.</p><button class="primary" data-generation-action="prepare">생성 조합 준비</button></section>';
  if (state.options && !state.plan) {
    controls = `<div class="form-row"><label>확인할 조합 수<select id="style-generation-count"><option value="2" ${state.options.combinations.length === 2 ? "selected" : ""}>2개</option><option value="1" ${state.options.combinations.length === 1 ? "selected" : ""}>1개</option></select></label></div>${state.options.combinations.map((combination, index) => styleCombinationEditorMarkup(combination, index, state.options.settings)).join("")}<button class="primary" data-generation-action="preview" ${styleGenerationViewState.busy ? "disabled" : ""}>생성 계획 확인</button>`;
  }
  if (state.plan) {
    const plan = state.plan;
    controls = `<section class="panel"><h2>생성 계획</h2><p>${plan.candidates.length}개 조합 × ${plan.cases.length}개 Prompt = <strong>${plan.imageCount}장</strong></p><p>${plan.sampling.width} × ${plan.sampling.height} · Steps ${plan.sampling.steps} · CFG ${plan.sampling.cfg} · 공통 Seed ${plan.sampling.seed}</p>${plan.candidates.map(candidate => `<details><summary>조합 ${escapeMarkup(candidate.label)} · 성분 ${candidate.components.length}개</summary><ul>${candidate.components.map(component => `<li>${escapeMarkup(component.identifier)} · STR ${component.strength}</li>`).join("")}</ul></details>`).join("")}<p class="form-note">저장한 Workflow와 같은 Adapter로 제출합니다. 출력 형식은 Workflow 설정을 유지합니다.</p><div class="form-actions"><button data-generation-action="prepare">다른 조합 준비</button><button class="primary" data-generation-action="submit" ${plan.jobIdentifiers.length || styleGenerationViewState.busy ? "disabled" : ""}>${plan.jobIdentifiers.length ? "제출한 생성 계획" : `${plan.imageCount}장 이미지 생성`}</button></div></section>`;
  }
  return `<div class="page-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>프로젝트 이미지 생성</h1><p class="muted">저장한 조건으로 소량 생성해 Workflow와 조합을 확인합니다.</p></div><button data-action="navigate" data-screen="project-settings">프로젝트 설정</button></div>${controls}<p id="style-generation-error" class="error" role="alert">${escapeMarkup(state.error)}</p><div id="style-render-results">${initialStyleResultsMarkup(state.results)}</div>`;
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
  if (!results?.candidates.length) return '<section class="panel empty-state"><p>아직 생성한 이미지가 없습니다.</p></section>';
  const project = currentProject();
  const statusLabels = { submitting: "제출 준비 중", pending: "대기 중", running: "생성 중", completed: "완료", failed: "실패", stopped: "중단·접수 미확인", cancelled: "취소됨", cancelling: "취소 중" };
  return (results.plans || []).map(plan => {
    const candidates = results.candidates.filter(candidate => candidate.planIdentifier === plan.planIdentifier);
    const renders = candidates.flatMap(candidate => candidate.renders);
    const latestRenders = candidates.flatMap(candidate => plan.cases.map(promptCase => candidate.renders.filter(render => render.caseIdentifier === promptCase.identifier).at(-1))).filter(Boolean);
    const hasRetryTargets = latestRenders.some(render => ["failed", "cancelled"].includes(render.status));
    const activeJobs = [...new Set(renders.filter(render => ["submitting", "pending", "running", "cancelling"].includes(render.status)).map(render => render.jobIdentifier))];
    return `<section class="panel generation-results"><div class="settings-section-heading"><h2>${plan.candidates.length}개 조합 · ${plan.cases.length}개 Prompt</h2>${!plan.jobIdentifiers.length ? `<button data-generation-action="open-plan" data-plan="${plan.planIdentifier}">생성 계획 열기</button>` : ""}</div>${plan.cases.map(promptCase => `<section><h3>${escapeMarkup(persistentPromptCaseName(promptCase))}</h3><div class="generation-result-grid">${candidates.map(candidate => {
      const render = candidate.renders.filter(item => item.caseIdentifier === promptCase.identifier).at(-1);
      const file = render?.files.find(item => item.is_available && !item.is_deleted);
      return `<article class="generation-result"><strong>조합 ${escapeMarkup(candidate.label)}</strong>${file ? `<button class="image-button" data-generation-action="enlarge" data-path="${escapeMarkup(file.path)}"><img loading="lazy" src="${styleImageUrl(file.path)}" alt="${escapeMarkup(persistentPromptCaseName(promptCase))} · 조합 ${escapeMarkup(candidate.label)}" style="aspect-ratio:${plan.sampling.width}/${plan.sampling.height}" /></button>` : `<div class="empty-state">${render ? escapeMarkup(statusLabels[render.status] || render.status) : "계획 확인 완료 · 미제출"}</div>`}${render?.error ? `<p class="error">${escapeMarkup(render.error)}</p>` : ""}<details><summary>성분·실제 생성 조건</summary><ul>${candidate.components.map(component => `<li>${escapeMarkup(component.identifier)} · STR ${component.strength}</li>`).join("")}</ul>${render?.settings ? `<p>Seed ${render.settings.seed} · ${render.settings.width}×${render.settings.height} · Steps ${render.settings.steps} · CFG ${render.settings.cfg}</p>` : ""}${render?.prompt ? `<p class="form-note">${escapeMarkup(render.prompt)}</p>` : ""}</details></article>`;
    }).join("")}</div></section>`).join("")}<div class="form-actions">${hasRetryTargets && !activeJobs.length ? `<button data-generation-action="retry" data-plan="${plan.planIdentifier}">실패·취소 항목만 재시도</button>` : ""}${activeJobs.map(jobIdentifier => `<button data-generation-action="cancel" data-job="${jobIdentifier}">이 생성 작업 취소</button>`).join("")}</div></section>`;
  }).join("") + `<p class="form-note">${escapeMarkup(project.name)}의 실제 결과입니다. 선별·Elo는 후속 단계에서 연결합니다.</p>`;
}

/** Polling은 결과 영역만 바꾸며 작성 중 조합·Scroll·다른 프로젝트를 덮어쓰지 않습니다. */
async function refreshStyleGenerationResults(projectIdentifier = previewState.currentProjectIdentifier) {
  if (!PERSISTENT_STYLE_WORKSPACE || !projectIdentifier) return;
  const results = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-results`);
  const state = currentStyleGenerationState(projectIdentifier);
  state.results = results;
  const project = previewState.projects.find(project => project.identifier === projectIdentifier);
  if (project) project.candidateCount = results.candidates.filter(candidate => candidate.renders.length > 0).length;
  if (state.plan) state.plan = results.plans.find(plan => plan.planIdentifier === state.plan.planIdentifier) || state.plan;
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const resultContainer = document.querySelector("#style-render-results");
  if (resultContainer) {
    const markup = styleResultsMarkupForCurrentScreen(results);
    if (markup !== state.lastResultMarkup) {
      resultContainer.innerHTML = markup;
      state.lastResultMarkup = markup;
    }
  }
}

/** 조합 입력을 프로젝트 허용 범위의 초안에만 반영합니다. */
function handleStyleGenerationInput(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const field = event.target;
  if (!field.isConnected) return;
  const state = currentStyleGenerationState();
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
    if (action === "prepare") {
      state.options = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-options`);
      state.plan = null;
    }
    if (action === "preview") {
      state.plan = await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-plans`, { method: "POST", body: JSON.stringify({ expectedRevision: state.options.projectRevision, operationIdentifier: newStyleClientIdentifier(), combinations: state.options.combinations }) });
    }
    if (action === "open-plan") state.plan = state.results.plans.find(plan => plan.planIdentifier === button.dataset.plan);
    if (action === "submit" || action === "retry") {
      const planIdentifier = action === "retry" ? button.dataset.plan : state.plan.planIdentifier;
      await styleProjectApi(`/api/style-projects/${projectIdentifier}/generation-plans/${planIdentifier}/submit`, { method: "POST", body: JSON.stringify({ operationIdentifier: newStyleClientIdentifier(), retryFailedOnly: action === "retry" }) });
      showToast("프로젝트 설정으로 이미지 생성을 접수했습니다.");
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
