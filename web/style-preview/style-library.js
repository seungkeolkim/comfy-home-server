"use strict";

let styleLibraryViewerState = null;
const styleLibraryDialogState = { outputId: null, opener: null, pointerStartedOutside: false };

/** 같은 조합의 Prompt 순서와 최신 생성 결과를 카드·상세 보기에서 공유합니다. */
function styleCandidateCaseResults(candidate, plan) {
  const caseResults = [];
  for (const promptCase of plan.cases) {
    const render = candidate.renders.filter(item => item.caseIdentifier === promptCase.identifier).at(-1);
    const file = render?.files.find(item => item.is_available && !item.is_deleted);
    caseResults.push({ promptCase, render, file });
  }
  return caseResults;
}

/** Prompt 개수와 관계없이 조합 하나를 작은 이미지가 있는 카드 하나로 표시합니다. */
function styleCandidateCardMarkup(candidate, plan) {
  const caseResults = styleCandidateCaseResults(candidate, plan);
  const availableCount = caseResults.filter(result => result.file).length;
  const artistCount = candidate.components.filter(component => component.identifier.startsWith("artist:")).length;
  const loraCount = candidate.components.filter(component => component.identifier.startsWith("lora:")).length;
  const thumbnails = caseResults.map((result, caseIndex) => {
    const caseName = persistentPromptCaseName(result.promptCase);
    const imageMarkup = result.file
      ? `<img loading="lazy" src="${styleImageUrl(result.file.path)}" alt="${escapeMarkup(caseName)}" />`
      : `<span class="style-thumbnail-status">${escapeMarkup(result.render ? styleRenderStatusLabel(result.render.status) : "미제출")}</span>`;
    return `<span class="style-card-thumbnail" data-library-case-index="${caseIndex}">${imageMarkup}<span class="style-thumbnail-name">${escapeMarkup(caseName)}</span></span>`;
  }).join("");
  const generationErrors = [...new Set(caseResults.map(result => result.render?.error).filter(Boolean))];
  const errorMarkup = generationErrors.length
    ? `<details class="style-card-generation-errors"><summary>생성 오류</summary>${generationErrors.map(message => `<p class="error">${escapeMarkup(message)}</p>`).join("")}</details>`
    : "";
  const selected = (currentStyleGenerationState().selectedCandidateIdentifiers || []).includes(candidate.identifier);
  return `<article class="style-library-card" data-style-candidate="${candidate.identifier}"><label class="style-card-selection"><input type="checkbox" data-style-candidate-select="${candidate.identifier}" ${selected ? "checked" : ""} aria-label="${escapeMarkup(persistentCandidateLabel(candidate))} 선택" />선택</label><button class="style-card-open" data-style-library-action="open" data-candidate="${candidate.identifier}" aria-label="${escapeMarkup(persistentCandidateLabel(candidate))} 자세히 보기"><span class="style-card-heading"><strong>${escapeMarkup(persistentCandidateLabel(candidate))}</strong><span>${availableCount} / ${caseResults.length}장</span></span>${styleCandidateRankingMarkup(candidate)}<span class="style-card-thumbnails">${thumbnails}</span><span class="style-card-summary">${candidate.generationNumber || 1}세대 · ${{active: "활성", evolving: "진화 중", retired: "퇴역", cancelled: "취소"}[candidate.lifecycle] || "활성"} · 작가 ${artistCount}개 · LoRA ${loraCount}개</span><span class="style-card-open-label">이미지 자세히 보기 ↗</span></button>${errorMarkup}<div class="style-card-actions">${styleCandidateManagementButtonsMarkup(candidate)}${styleCandidateFavoriteButtonMarkup(candidate)}</div></article>`;
}

/** 현재 생성 중인 최신 Prompt 요청만 세어 완료된 카드와 함께 진행을 표시합니다. */
function styleLibraryGenerationProgressMarkup(results) {
  let pendingImageCount = 0;
  for (const candidate of results?.candidates || []) {
    const plan = results.plans.find(item => item.planIdentifier === candidate.planIdentifier);
    if (!plan) continue;
    for (const result of styleCandidateCaseResults(candidate, plan)) {
      if (["submitting", "pending", "running", "cancelling"].includes(result.render?.status)) pendingImageCount += 1;
    }
  }
  return pendingImageCount ? `<p class="style-library-generation-progress" role="status">이미지 ${pendingImageCount}장 생성 중</p>` : "";
}

/** 생성 묶음의 취소·부분 실패 재시도는 조합 카드와 별도로 유지합니다. */
function styleLibraryBatchActionsMarkup(candidates, plan) {
  if (!candidates.length || ["cancelled", "confirmed"].includes(plan.evolutionStatus)) return "";
  const latestRenders = [];
  for (const candidate of candidates) {
    latestRenders.push(...styleCandidateCaseResults(candidate, plan).map(result => result.render).filter(Boolean));
  }
  const activeJobs = [...new Set(latestRenders.filter(render => ["submitting", "pending", "running", "cancelling"].includes(render.status)).map(render => render.jobIdentifier))];
  if (activeJobs.length) return activeJobs.map(jobIdentifier => `<button data-generation-action="cancel" data-job="${jobIdentifier}">이 생성 작업 취소</button>`).join("");
  if (latestRenders.some(render => ["failed", "cancelled"].includes(render.status))) return `<button data-generation-action="retry" data-plan="${plan.planIdentifier}">이 묶음의 실패·취소 항목만 재시도</button>`;
  return "";
}

/** 서버가 계산한 실제 순위·Elo·전적을 조합 카드에 표시합니다. */
function styleCandidateRankingMarkup(candidate) {
  if (previewState.blind) return '<span class="style-card-statistics">그림체 정보 숨김</span>';
  const statistics = candidate.statistics;
  if (statistics?.placementPending && ['active', 'evolving'].includes(candidate.lifecycle)) return '<span class="style-card-statistics"><strong>평가 중 · Elo —</strong><small>자동으로 순위표에서 자리를 찾는 중</small></span>';
  const rankLabel = candidate.lifecycle === "retired" ? "퇴역" : candidate.lifecycle === "cancelled" ? "취소" : statistics?.rank ? `${statistics.rank}위` : "미평가";
  const ratingLabel = statistics?.rated ? statistics.rating.toLocaleString("ko-KR") : "—";
  return `<span class="style-card-statistics"><strong>${rankLabel} · Elo <span data-style-rating="${candidate.identifier}">${ratingLabel}</span></strong><small>${statistics?.wins || 0}승 ${statistics?.losses || 0}패 · ${statistics?.matches || 0}회 평가 · Skip ${statistics?.skips || 0}</small></span>`;
}

/** 같은 평가 조건 안에서만 순위를 정렬하고 이전 Seed의 점수를 섞지 않습니다. */
function styleLibraryResultsMarkup(results) {
  if (previewState.blind) return rankingBlindNoticeMarkup();
  const groups = [];
  const favoritesOnly = styleLibraryFavoritesOnly();
  const lifecycleFilter = favoritesOnly ? "all" : currentStyleGenerationState().libraryLifecycle || "active";
  const plans = (results?.plans || []).filter(plan => results.candidates.some(candidate => candidate.planIdentifier === plan.planIdentifier && candidate.renders.length));
  const evaluations = plans.filter((plan, index) => plans.findIndex(item => item.evaluationIdentifier === plan.evaluationIdentifier) === index);
  for (const plan of evaluations) {
    const candidates = results.candidates.filter(candidate => candidate.evaluationIdentifier === plan.evaluationIdentifier && candidate.renders.length && (!favoritesOnly || candidate.isFavorite) && (lifecycleFilter === "all" || (lifecycleFilter === "active" ? ["active", "evolving"].includes(candidate.lifecycle) : candidate.lifecycle === lifecycleFilter)));
    if (!candidates.length) continue;
    const orderedCandidates = [...candidates];
    if (previewState.candidateSortOrder === "matches") orderedCandidates.sort((first, second) => (second.statistics?.matches || 0) - (first.statistics?.matches || 0) || (first.statistics?.rank || Infinity) - (second.statistics?.rank || Infinity));
    else if (previewState.candidateSortOrder !== "creation") orderedCandidates.sort((first, second) => (first.statistics?.rank || Infinity) - (second.statistics?.rank || Infinity));
    const actions = plans.filter(item => item.evaluationIdentifier === plan.evaluationIdentifier).map(item => styleLibraryBatchActionsMarkup(candidates.filter(candidate => candidate.planIdentifier === item.planIdentifier), item)).join("");
    const cards = orderedCandidates.map(candidate => styleCandidateCardMarkup(candidate, plans.find(item => item.planIdentifier === candidate.planIdentifier))).join("");
    groups.push(`<section class="style-library-batch"><div class="settings-section-heading"><h2>${plan.evaluationIdentifier === currentProject().evaluationIdentifier ? "현재 조건" : "이전 조건"} · Seed ${plan.sampling.seed} · ${candidates.length}개 그림체</h2><div class="form-actions">${actions}</div></div><div class="style-library-grid">${cards}</div></section>`);
  }
  const emptyState = favoritesOnly
    ? '<section class="panel empty-state"><p>즐겨찾기한 그림체가 없습니다.</p></section>'
    : '<section class="panel empty-state"><p>아직 생성한 이미지가 없습니다.</p><button data-generation-action="open-generator">조합 생성</button></section>';
  return styleLibraryGenerationProgressMarkup(results) + styleCandidateSelectionToolbarMarkup(results) + (groups.join("") || emptyState);
}

/** 상세 보기는 열린 프로젝트와 후보 ID로만 조회해 다른 조합으로 넘어가지 않습니다. */
function currentStyleLibraryViewerResults() {
  if (!styleLibraryViewerState) return null;
  const results = currentStyleGenerationState(styleLibraryViewerState.projectIdentifier).results;
  const candidate = results?.candidates.find(item => item.identifier === styleLibraryViewerState.candidateIdentifier);
  const plan = results?.plans.find(item => item.planIdentifier === candidate?.planIdentifier);
  if (!candidate || !plan) return null;
  return { candidate, caseResults: styleCandidateCaseResults(candidate, plan) };
}

/** CHS 공통 이미지 Viewer에 사진 식별 정보와 보기 기능만 붙입니다. */
function prepareStyleLibraryViewer() {
  const dialog = document.querySelector("#illustration-dialog");
  const comparisonCandidateIdentifiers = styleLibraryViewerState.comparisonCandidateIdentifiers;
  const promptNavigationMarkup = `
    <button data-style-library-action="previous" data-preview-previous aria-label="이전 Prompt">${comparisonCandidateIdentifiers ? "이전" : "← 이전"}</button>
    <span role="status" aria-live="polite"></span>
    <button data-style-library-action="next" data-preview-next aria-label="다음 Prompt">${comparisonCandidateIdentifiers ? "다음" : "다음 →"}</button>`;
  dialog.classList.add("style-library-viewer");
  dialog.innerHTML = `
    <div class="dialog-heading">
      <div class="style-viewer-heading-text">
        <h2 id="style-viewer-title"></h2>
        <p id="style-viewer-case-name" class="style-viewer-case-name"></p>
      </div>
      ${styleLibraryViewerState.originalFilesOnly ? "" : styleCandidateFavoriteButtonMarkup(currentStyleLibraryViewerResults().candidate)}
      <button data-style-library-action="close" aria-label="그림체 상세 닫기">닫기</button>
    </div>
    <div class="style-viewer-image-frame">
      <img id="style-viewer-image" class="style-viewer-image" alt="" />
      <div id="style-viewer-placeholder" class="empty-state" hidden></div>
    </div>
    <p id="style-viewer-image-status" role="status"></p>
    <div class="style-viewer-toolbar">
      <div class="style-viewer-navigation ${comparisonCandidateIdentifiers ? "style-viewer-comparison-navigation" : ""}">
        ${comparisonCandidateIdentifiers ? `
          <div class="style-viewer-prompt-navigation">${promptNavigationMarkup}</div>
          <div class="style-viewer-combination-navigation" role="group" aria-label="비교 조합">
            <button data-style-library-action="switch-combination" data-style-viewer-comparison-side="a" aria-pressed="false">조합 A</button>
            <button data-style-library-action="switch-combination" data-style-viewer-comparison-side="b" aria-pressed="false">조합 B</button>
          </div>` : promptNavigationMarkup}
      </div>
      <div class="style-viewer-source-actions">
        ${styleLibraryViewerState.originalFilesOnly ? "" : '<label class="settings-checkbox"><input id="style-viewer-original-toggle" type="checkbox" role="switch" data-preview-original-toggle /><span>원본 보기</span></label>'}
        <a id="style-viewer-original-link" class="button" target="_blank" rel="noopener">원본 새 탭으로 보기</a>
      </div>
    </div>`;
  styleLibraryViewerState.controller = window.ComfyHomeImagePreview.createImagePreviewController({
    dialog, image: document.querySelector("#style-viewer-image"), title: document.querySelector("#style-viewer-title"),
    originalLink: document.querySelector("#style-viewer-original-link"), status: document.querySelector("#style-viewer-image-status"),
    originalToggle: document.querySelector("#style-viewer-original-toggle"), state: styleLibraryDialogState,
  });
}

/** 같은 Viewer 안에서 Prompt만 이동하며 열 때 선택한 원본 표시 방식을 유지합니다. */
function renderStyleLibraryViewer() {
  const viewerResults = currentStyleLibraryViewerResults();
  if (!viewerResults) return closeStyleLibraryViewer();
  if (!styleLibraryViewerState.controller) prepareStyleLibraryViewer();
  const { candidate, caseResults } = viewerResults;
  const caseIndex = Math.max(0, Math.min(styleLibraryViewerState.caseIndex, caseResults.length - 1));
  styleLibraryViewerState.caseIndex = caseIndex;
  const result = caseResults[caseIndex];
  styleLibraryViewerState.displayedPath = result.file?.path || null;
  const caseName = persistentPromptCaseName(result.promptCase);
  document.querySelector("#style-viewer-case-name").textContent = caseName;
  document.querySelector("#style-viewer-case-name").title = caseName;
  const placeholder = document.querySelector("#style-viewer-placeholder");
  placeholder.hidden = Boolean(result.file);
  document.querySelector("#style-viewer-image").hidden = !result.file;
  const originalToggle = document.querySelector("#style-viewer-original-toggle");
  if (originalToggle) originalToggle.disabled = !result.file;
  if (result.file) {
    styleLibraryViewerState.controller.openImage({ ...result.file, name: persistentCandidateLabel(candidate) }, styleLibraryDialogState.opener, styleLibraryViewerState.showOriginalFiles);
    document.querySelector("#style-viewer-original-link").title = result.file.path.split("/").at(-1);
  } else {
    styleLibraryViewerState.controller.clearImage();
    document.querySelector("#style-viewer-title").textContent = persistentCandidateLabel(candidate);
    placeholder.textContent = result.render ? styleRenderStatusLabel(result.render.status) : "미제출";
  }
  document.querySelector("[data-style-library-action=previous]").disabled = caseIndex === 0;
  document.querySelector("[data-style-library-action=next]").disabled = caseIndex === caseResults.length - 1;
  document.querySelector(".style-viewer-navigation [role=status]").textContent = `${caseIndex + 1} / ${caseResults.length}`;
  updateStyleComparisonViewerControls();
  if (!document.querySelector("#illustration-dialog").open) document.querySelector("#illustration-dialog").showModal();
}

/** 확대할 때 고정한 A/B 위치를 표시하고 사라진 조합으로의 이동은 막습니다. */
function updateStyleComparisonViewerControls() {
  const comparisonCandidateIdentifiers = styleLibraryViewerState?.comparisonCandidateIdentifiers;
  if (!comparisonCandidateIdentifiers) return;
  const results = currentStyleGenerationState(styleLibraryViewerState.projectIdentifier).results;
  for (const button of document.querySelectorAll("[data-style-library-action=switch-combination]")) {
    const candidateIdentifier = comparisonCandidateIdentifiers[button.dataset.styleViewerComparisonSide === "a" ? 0 : 1];
    button.setAttribute("aria-pressed", String(candidateIdentifier === styleLibraryViewerState.candidateIdentifier));
    button.disabled = !results?.candidates.some(candidate => candidate.identifier === candidateIdentifier);
  }
}

/** Polling은 이미지 소스를 유지하며 현재 사진의 정보와 삭제 여부만 반영합니다. */
function refreshOpenStyleLibraryViewer() {
  if (!styleLibraryViewerState) return;
  const results = currentStyleLibraryViewerResults();
  if (!results) return closeStyleLibraryViewer();
  updateStyleComparisonViewerControls();
  const result = results.caseResults[styleLibraryViewerState.caseIndex];
  if (styleLibraryViewerState.displayedPath !== (result?.file?.path || null)) return renderStyleLibraryViewer();
  const caseName = persistentPromptCaseName(result.promptCase);
  document.querySelector("#style-viewer-title").textContent = persistentCandidateLabel(results.candidate);
  document.querySelector("#style-viewer-case-name").textContent = caseName;
  document.querySelector("#style-viewer-case-name").title = caseName;
}

/** 선별은 항상 원본으로 열고 다른 화면은 CHS의 기기별 기본값을 사용합니다. */
function openStyleLibraryViewer(candidateIdentifier, caseIndex, opener = document.activeElement) {
  const originalFilesOnly = previewState.screen === "compare";
  const comparisonCandidateIdentifiers = originalFilesOnly ? currentPersistentComparison().candidates.map(candidate => candidate.identifier) : [];
  styleLibraryViewerState = { projectIdentifier: previewState.currentProjectIdentifier, candidateIdentifier, caseIndex,
    comparisonCandidateIdentifiers: comparisonCandidateIdentifiers.length === 2 && comparisonCandidateIdentifiers.includes(candidateIdentifier) ? comparisonCandidateIdentifiers : null,
    originalFilesOnly, showOriginalFiles: originalFilesOnly || window.ComfyHomeImagePreview.defaultOriginalMode(), controller: null };
  styleLibraryDialogState.opener = opener;
  if (!currentStyleLibraryViewerResults()) {
    styleLibraryViewerState = null;
    return;
  }
  renderStyleLibraryViewer();
}

/** 선별·생성 화면에서 연 이미지도 기존 조합 Viewer와 Cache를 사용합니다. */
function openStyleLibraryViewerByPath(relativePath, opener) {
  const results = currentStyleGenerationState().results;
  for (const candidate of results?.candidates || []) {
    const plan = results.plans.find(item => item.planIdentifier === candidate.planIdentifier);
    const caseIndex = plan.cases.findIndex(promptCase => candidate.renders.some(render => render.caseIdentifier === promptCase.identifier && render.files.some(file => file.path === relativePath)));
    if (caseIndex >= 0) return openStyleLibraryViewer(candidate.identifier, caseIndex, opener);
  }
  showToast("이미지의 조합을 찾을 수 없습니다. 목록을 다시 불러와 주세요.");
}

/** 원본 토글은 현재 Prompt와 이동 위치를 바꾸지 않고 소스만 전환합니다. */
function setStyleLibraryOriginalMode(showOriginalFiles) {
  const results = currentStyleLibraryViewerResults();
  if (!results) return;
  const result = results.caseResults[styleLibraryViewerState.caseIndex];
  if (!result.file) return;
  styleLibraryViewerState.showOriginalFiles = showOriginalFiles;
  styleLibraryViewerState.controller.loadImageSource(result.file, showOriginalFiles);
}

/** CHS와 같은 소스 정리·닫기·Focus 복원을 사용합니다. */
function closeStyleLibraryViewer(restoreFocus = true) {
  const opener = styleLibraryDialogState.opener;
  styleLibraryViewerState?.controller?.clearImage();
  styleLibraryDialogState.outputId = null;
  styleLibraryDialogState.opener = null;
  styleLibraryViewerState = null;
  const dialog = document.querySelector("#illustration-dialog");
  if (dialog.open) dialog.close();
  dialog.classList.remove("style-library-viewer");
  if (restoreFocus && opener?.isConnected) opener.focus({ preventScroll: true });
}

/** 이전/다음은 해당 조합 안의 Prompt 범위에서만 이동합니다. */
function moveStyleLibraryViewer(direction) {
  const viewerResults = currentStyleLibraryViewerResults();
  if (!viewerResults) return;
  const nextIndex = styleLibraryViewerState.caseIndex + direction;
  if (nextIndex < 0 || nextIndex >= viewerResults.caseResults.length) return;
  styleLibraryViewerState.caseIndex = nextIndex;
  renderStyleLibraryViewer();
}

/** 같은 Prompt의 이미지를 유지하며 확대할 때의 A/B 조합만 전환합니다. */
function switchStyleComparisonViewerCandidate(comparisonSide) {
  const comparisonCandidateIdentifiers = styleLibraryViewerState?.comparisonCandidateIdentifiers;
  if (!comparisonCandidateIdentifiers || !["a", "b"].includes(comparisonSide)) return;
  const candidateIdentifier = comparisonCandidateIdentifiers[comparisonSide === "a" ? 0 : 1];
  if (candidateIdentifier === styleLibraryViewerState.candidateIdentifier) return;
  const viewerResults = currentStyleLibraryViewerResults();
  if (!viewerResults) return;
  const promptCaseIdentifier = viewerResults.caseResults[styleLibraryViewerState.caseIndex].promptCase.identifier;
  const results = currentStyleGenerationState(styleLibraryViewerState.projectIdentifier).results;
  const candidate = results.candidates.find(candidate => candidate.identifier === candidateIdentifier);
  const plan = results.plans.find(plan => plan.planIdentifier === candidate?.planIdentifier);
  const caseIndex = plan?.cases.findIndex(promptCase => promptCase.identifier === promptCaseIdentifier) ?? -1;
  if (caseIndex < 0) return;
  styleLibraryViewerState.candidateIdentifier = candidateIdentifier;
  styleLibraryViewerState.caseIndex = caseIndex;
  renderStyleLibraryViewer();
}

/** 카드 상세의 버튼을 처리하며 생성·투표 요청을 발생시키지 않습니다. */
function handleStyleLibraryAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-library-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.styleLibraryAction;
  if (action === "open") openStyleLibraryViewer(button.dataset.candidate, Number(event.target.closest("[data-library-case-index]")?.dataset.libraryCaseIndex || 0), button);
  if (action === "switch-combination") switchStyleComparisonViewerCandidate(button.dataset.styleViewerComparisonSide);
  if (action === "close") closeStyleLibraryViewer();
}

document.addEventListener("click", handleStyleLibraryAction);

if (PERSISTENT_STYLE_WORKSPACE) {
  window.ComfyHomeImagePreview.bindDialogEvents({
    dialog: document.querySelector("#illustration-dialog"), state: styleLibraryDialogState,
    onClose: closeStyleLibraryViewer,
    onNavigate: direction => moveStyleLibraryViewer(direction === "previous" ? -1 : 1),
    onOriginalChange: setStyleLibraryOriginalMode,
  });
}

/** 퇴역·취소 조합도 파일을 지우지 않고 명시적으로 찾아볼 수 있게 합니다. */
function handleStyleLibraryLifecycleFilter(event) {
  if (event.target.id !== "style-library-lifecycle") return;
  currentStyleGenerationState().libraryLifecycle = event.target.value;
  renderPreview(false);
}

document.addEventListener("change", handleStyleLibraryLifecycleFilter);

/** 조합 단위 관리 기능을 카드·상세·선별에서 같은 버튼으로 제공합니다. */
function styleCandidateManagementButtonsMarkup(candidate) {
  const evolution = currentStyleGenerationState().evolution?.batch;
  const protectedByEvolution = evolution?.plan.evaluationIdentifier === candidate.evaluationIdentifier;
  const cannotDelete = protectedByEvolution;
  return `<button data-style-candidate-action="rating" data-candidate="${candidate.identifier}" ${previewState.blind || candidate.lifecycle === "cancelled" ? "disabled" : ""} title="조합의 승패를 유지하고 Elo를 수정합니다.">Elo 수정</button><button class="danger" data-style-candidate-action="delete" data-candidate="${candidate.identifier}" ${cannotDelete ? "disabled" : ""} title="${cannotDelete ? "진화를 확정하거나 취소한 뒤 조합을 폐기할 수 있습니다." : "모든 Prompt의 이미지와 함께 조합을 폐기합니다."}">조합 폐기</button>`;
}

/** 선택한 조합·폐기 복구 동작을 프로젝트 범위 안에서 표시합니다. */
function styleCandidateSelectionToolbarMarkup(results) {
  const state = currentStyleGenerationState();
  const knownIdentifiers = new Set((results?.candidates || []).map(candidate => candidate.identifier));
  state.selectedCandidateIdentifiers = (state.selectedCandidateIdentifiers || []).filter(identifier => knownIdentifiers.has(identifier));
  const count = state.selectedCandidateIdentifiers.length;
  const recoveries = (results?.pendingCandidateDeletions || []).map(operation => `<section class="panel"><p class="error">${escapeMarkup(operation.error || "완료되지 않은 조합 폐기가 있습니다.")}</p><button data-style-candidate-action="retry-deletion" data-operation="${operation.operationIdentifier}">남은 이미지 폐기 다시 시도</button></section>`).join("");
  return `${recoveries}<div class="style-candidate-selection-toolbar"><strong>${count}개 선택</strong><button data-style-candidate-action="select-visible">현재 목록 선택</button><button data-style-candidate-action="rating" ${!count ? "disabled" : ""}>선택 Elo 수정</button><button class="danger" data-style-candidate-action="delete" ${!count ? "disabled" : ""}>선택 조합 폐기</button><button data-style-candidate-action="clear-selection" ${!count ? "disabled" : ""}>선택 해제</button></div><p id="style-candidate-management-error" class="error" role="alert">${escapeMarkup(state.error)}</p>`;
}

/** Checkbox는 여러 Prompt 이미지 대신 조합 하나를 선택합니다. */
function handleStyleCandidateSelection(event) {
  const identifier = event.target.dataset.styleCandidateSelect;
  if (!identifier) return;
  const state = currentStyleGenerationState();
  const selected = new Set(state.selectedCandidateIdentifiers || []);
  if (event.target.checked) selected.add(identifier);
  else selected.delete(identifier);
  state.selectedCandidateIdentifiers = [...selected];
  renderPreview(false);
}

/** 직접 수정은 한 번의 값 입력, 폐기는 전체 Prompt 범위를 알리는 확인창을 사용합니다. */
function confirmStyleCandidateManagement(action, candidates) {
  const dialog = document.querySelector("#component-dialog");
  const rating = candidates[0].statistics?.rating ?? 10000;
  const content = action === "rating"
    ? `<p>선택한 ${candidates.length}개 조합의 Elo를 바꿉니다. 승패는 유지하며 이전 선택의 Undo는 종료됩니다. 진화 중 직접 수정한 부모 Elo는 자녀 배치의 기준점에도 반영됩니다.</p><label for="style-candidate-rating">Elo</label><input id="style-candidate-rating" type="number" min="0" max="1000000" step="1" value="${rating}" required />`
    : `<p>선택한 ${candidates.length}개 조합의 <strong>모든 Prompt 이미지·Elo·비교 상태와 CHS 생성 요청을 삭제</strong>합니다. 비어 있는 작업도 삭제하며 Undo할 수 없습니다.</p><p>다른 조합의 이미지와 프로젝트 설정은 유지됩니다.</p>`;
  dialog.innerHTML = `<form method="dialog"><div class="dialog-heading"><h2 id="component-dialog-title">${action === "rating" ? "Elo 수정" : "조합 폐기"}</h2></div>${content}<div class="form-actions"><button type="button" value="cancel">취소</button><button class="${action === "delete" ? "danger" : "primary"}" value="confirm">${action === "rating" ? "저장" : "폐기"}</button></div></form>`;
  dialog.querySelector("button[value=cancel]").addEventListener("click", () => dialog.close("cancel"), { once: true });
  dialog.returnValue = "cancel";
  return new Promise(resolve => {
    /** Escape·취소에서는 어떤 명령도 보내지 않습니다. */
    function resolveCandidateManagementConfirmation() {
      const accepted = dialog.returnValue === "confirm";
      resolve({ accepted, rating: accepted && action === "rating" ? Number(dialog.querySelector("#style-candidate-rating").value) : null });
    }
    dialog.addEventListener("close", resolveCandidateManagementConfirmation, { once: true });
    dialog.showModal();
  });
}

/** 현재 조합·평가 조건을 고정하고 영속 명령의 응답 유실에도 같은 요청을 재사용합니다. */
async function executeStyleCandidateManagement(action, candidates, rating, recovery = null) {
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const route = action === "rating" ? "candidate-ratings" : "candidate-deletions";
  let pending = recovery ? { route, payload: recovery.requestPayload } : state.pendingCandidateCommand;
  const identifiers = candidates.map(candidate => candidate.identifier);
  if (!recovery && (!pending || pending.route !== route || JSON.stringify(pending.payload.candidateIdentifiers) !== JSON.stringify(identifiers) || pending.payload.rating !== (action === "rating" ? rating : undefined))) {
    const evaluationIdentifier = candidates[0].evaluationIdentifier;
    const query = new URLSearchParams({ evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier() });
    const selection = await styleProjectApi(`/api/style-projects/${projectIdentifier}/selection?${query}`);
    pending = { route, payload: { evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier(), operationIdentifier: newStyleClientIdentifier(),
      expectedRevision: selection.revision, candidateIdentifiers: identifiers, ...(action === "rating" ? { rating } : {}) } };
    state.pendingCandidateCommand = pending;
  }
  try {
    const response = await styleProjectApi(`/api/style-projects/${projectIdentifier}/${route}`, { method: "POST", body: JSON.stringify(pending.payload) });
    state.pendingCandidateCommand = null;
    if (action === "rating") applyStyleVotingResponse(projectIdentifier, response);
    else {
      const deletedIdentifiers = response.candidateIdentifiers;
      state.selectedCandidateIdentifiers = (state.selectedCandidateIdentifiers || []).filter(identifier => !deletedIdentifiers.includes(identifier));
      state.results.candidates = state.results.candidates.filter(candidate => !deletedIdentifiers.includes(candidate.identifier));
      for (const selection of Object.values(state.votingEvaluations || {})) {
        selection.rankings = selection.rankings.filter(candidate => !deletedIdentifiers.includes(candidate.identifier));
        selection.readyCandidateIdentifiers = selection.readyCandidateIdentifiers.filter(identifier => !deletedIdentifiers.includes(identifier));
        if (selection.match && [selection.match.a, selection.match.b].some(identifier => deletedIdentifiers.includes(identifier))) selection.match = null;
      }
    }
    showToast(action === "rating" ? "조합 Elo를 수정했습니다." : "조합과 모든 Prompt 이미지를 폐기했습니다.");
  } catch (error) {
    if ([404, 409, 422].includes(error.status)) state.pendingCandidateCommand = null;
    throw error;
  }
}

/** 관리 명령 동안 Polling·연타를 잠그고 마지막에 해당 프로젝트 결과만 갱신합니다. */
async function handleStyleCandidateManagement(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-candidate-action]");
  if (!button || button.disabled || styleGenerationViewState.busy) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const action = button.dataset.styleCandidateAction;
  if (action === "select-visible") {
    state.selectedCandidateIdentifiers = [...document.querySelectorAll(".style-library-card")].map(card => card.dataset.styleCandidate);
    return renderPreview(false);
  }
  if (action === "clear-selection") {
    state.selectedCandidateIdentifiers = [];
    return renderPreview(false);
  }
  if (blockStyleMutationDuringVoting(projectIdentifier)) return;
  styleGenerationViewState.busy = true;
  state.candidateCommandBusy = true;
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.error = "";
  const content = document.querySelector("#preview-content");
  content.inert = true;
  try {
    if (action === "retry-deletion") {
      const recovery = state.results.pendingCandidateDeletions.find(operation => operation.operationIdentifier === button.dataset.operation);
      await executeStyleCandidateManagement("delete", [], null, recovery);
    } else {
      const selected = button.dataset.candidates ? button.dataset.candidates.split(",") : button.dataset.candidate ? [button.dataset.candidate] : state.selectedCandidateIdentifiers;
      const candidates = state.results.candidates.filter(candidate => selected?.includes(candidate.identifier));
      if (!candidates.length) throw new Error("관리할 조합을 먼저 선택해 주세요.");
      if (new Set(candidates.map(candidate => candidate.evaluationIdentifier)).size > 1) throw new Error("같은 평가 조건의 조합끼리 선택해 주세요.");
      const confirmation = await confirmStyleCandidateManagement(action, candidates);
      if (confirmation.accepted) await executeStyleCandidateManagement(action, candidates, confirmation.rating);
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    styleGenerationViewState.busy = false;
    state.candidateCommandBusy = false;
    content.inert = false;
    try {
      await refreshStyleGenerationResults(projectIdentifier);
    } catch (error) {
      state.error ||= error.message;
    }
    if (projectIdentifier === previewState.currentProjectIdentifier) {
      renderPreview(false);
      refreshOpenStyleLibraryViewer();
    }
  }
}

document.addEventListener("change", handleStyleCandidateSelection);
document.addEventListener("click", handleStyleCandidateManagement);
