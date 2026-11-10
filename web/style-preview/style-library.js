"use strict";

let styleLibraryViewerState = null;

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
  return `<article class="style-library-card" data-style-candidate="${candidate.identifier}"><button class="style-card-open" data-style-library-action="open" data-candidate="${candidate.identifier}" aria-label="조합 ${escapeMarkup(candidate.label)}의 이미지 ${caseResults.length}개 자세히 보기"><span class="style-card-heading"><strong>조합 ${escapeMarkup(candidate.label)}</strong><span>${availableCount} / ${caseResults.length}장</span></span>${styleCandidateRankingMarkup(candidate)}<span class="style-card-thumbnails">${thumbnails}</span><span class="style-card-summary">${candidate.generationNumber || 1}세대 · ${{active: "활성", evolving: "진화 중", retired: "퇴역", cancelled: "취소"}[candidate.lifecycle] || "활성"} · ${candidate.batchNumber}번째 생성 · 작가 ${artistCount}개 · LoRA ${loraCount}개</span><span class="style-card-open-label">이미지 자세히 보기 ↗</span></button></article>`;
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

/** 서버가 계산한 실제 순위·Elo·전적을 조합 카드와 상세에서 공유합니다. */
function styleCandidateRankingMarkup(candidate) {
  const statistics = candidate.statistics;
  const rankLabel = candidate.lifecycle === "retired" ? "퇴역" : candidate.lifecycle === "cancelled" ? "취소" : statistics?.rank ? `${statistics.rank}위` : "미평가";
  const ratingLabel = statistics?.rated ? statistics.rating.toLocaleString("ko-KR") : "—";
  return `<span class="style-card-statistics"><strong>${rankLabel} · Elo <span data-style-rating="${candidate.identifier}">${ratingLabel}</span></strong><small>${statistics?.wins || 0}승 ${statistics?.losses || 0}패 · ${statistics?.matches || 0}회 평가 · Skip ${statistics?.skips || 0}</small></span>`;
}

/** 같은 평가 조건 안에서만 순위를 정렬하고 이전 Seed의 점수를 섞지 않습니다. */
function styleLibraryResultsMarkup(results) {
  if (previewState.blind) return rankingBlindNoticeMarkup();
  const groups = [];
  const lifecycleFilter = currentStyleGenerationState().libraryLifecycle || "active";
  const plans = (results?.plans || []).filter(plan => results.candidates.some(candidate => candidate.planIdentifier === plan.planIdentifier && candidate.renders.length));
  const evaluations = plans.filter((plan, index) => plans.findIndex(item => item.evaluationIdentifier === plan.evaluationIdentifier) === index);
  for (const plan of evaluations) {
    const candidates = results.candidates.filter(candidate => candidate.evaluationIdentifier === plan.evaluationIdentifier && candidate.renders.length && (lifecycleFilter === "all" || (lifecycleFilter === "active" ? ["active", "evolving"].includes(candidate.lifecycle) : candidate.lifecycle === lifecycleFilter)));
    if (!candidates.length) continue;
    const orderedCandidates = [...candidates];
    if (previewState.candidateSortOrder === "matches") orderedCandidates.sort((first, second) => (second.statistics?.matches || 0) - (first.statistics?.matches || 0) || (first.statistics?.rank || Infinity) - (second.statistics?.rank || Infinity));
    else if (previewState.candidateSortOrder !== "creation") orderedCandidates.sort((first, second) => (first.statistics?.rank || Infinity) - (second.statistics?.rank || Infinity));
    const actions = plans.filter(item => item.evaluationIdentifier === plan.evaluationIdentifier).map(item => styleLibraryBatchActionsMarkup(candidates.filter(candidate => candidate.planIdentifier === item.planIdentifier), item)).join("");
    const cards = orderedCandidates.map(candidate => styleCandidateCardMarkup(candidate, plans.find(item => item.planIdentifier === candidate.planIdentifier))).join("");
    groups.push(`<section class="style-library-batch"><div class="settings-section-heading"><h2>${plan.evaluationIdentifier === currentProject().evaluationIdentifier ? "현재 조건" : "이전 조건"} · Seed ${plan.sampling.seed} · ${candidates.length}개 그림체</h2><div class="form-actions">${actions}</div></div><div class="style-library-grid">${cards}</div></section>`);
  }
  return styleEvolutionContainerMarkup() + (groups.join("") || '<section class="panel empty-state"><p>아직 생성한 이미지가 없습니다.</p><button data-action="navigate" data-screen="generation">이미지 생성</button></section>');
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

/** 원본 이미지·Prompt 이름·순번과 이전/다음 조작을 같은 Dialog에 표시합니다. */
function renderStyleLibraryViewer() {
  const viewerResults = currentStyleLibraryViewerResults();
  if (!viewerResults) {
    illustrationDialog.close();
    return;
  }
  const { candidate, caseResults } = viewerResults;
  const caseIndex = Math.max(0, Math.min(styleLibraryViewerState.caseIndex, caseResults.length - 1));
  styleLibraryViewerState.caseIndex = caseIndex;
  const result = caseResults[caseIndex];
  const caseName = persistentPromptCaseName(result.promptCase);
  const imageMarkup = result.file
    ? `<img class="style-viewer-image" src="${styleImageUrl(result.file.path, true)}" alt="조합 ${escapeMarkup(candidate.label)} · ${escapeMarkup(caseName)}" />`
    : `<div class="empty-state">${escapeMarkup(result.render ? styleRenderStatusLabel(result.render.status) : "미제출")}${result.render?.error ? `<p class="error">${escapeMarkup(result.render.error)}</p>` : ""}</div>`;
  illustrationDialog.classList.add("style-library-viewer");
  illustrationDialog.innerHTML = `<div class="dialog-heading"><h2>조합 ${escapeMarkup(candidate.label)}</h2><button data-style-library-action="close" aria-label="그림체 상세 닫기">닫기</button></div>${styleCandidateRankingMarkup(candidate)}<p class="style-viewer-case-name">${escapeMarkup(caseName)}</p><div class="style-viewer-image-frame">${imageMarkup}</div><div class="style-viewer-navigation"><button data-style-library-action="previous" ${caseIndex === 0 ? "disabled" : ""}>← 이전</button><span role="status" aria-live="polite">${caseIndex + 1} / ${caseResults.length}</span><button data-style-library-action="next" ${caseIndex === caseResults.length - 1 ? "disabled" : ""}>다음 →</button></div>`;
}

/** 카드나 그 안의 작은 이미지를 누른 위치에서 해당 조합의 상세 보기를 엽니다. */
function openStyleLibraryViewer(candidateIdentifier, caseIndex) {
  styleLibraryViewerState = { projectIdentifier: previewState.currentProjectIdentifier, candidateIdentifier, caseIndex };
  if (!currentStyleLibraryViewerResults()) {
    styleLibraryViewerState = null;
    return;
  }
  renderStyleLibraryViewer();
  illustrationDialog.showModal();
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

/** 카드 상세의 버튼을 처리하며 생성·투표 요청을 발생시키지 않습니다. */
function handleStyleLibraryAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-library-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.styleLibraryAction;
  if (action === "open") openStyleLibraryViewer(button.dataset.candidate, Number(event.target.closest("[data-library-case-index]")?.dataset.libraryCaseIndex || 0));
  if (action === "previous") moveStyleLibraryViewer(-1);
  if (action === "next") moveStyleLibraryViewer(1);
  if (action === "close") illustrationDialog.close();
}

/** 상세 보기가 열렸을 때만 좌우 방향키를 사용하며 다른 입력 조작은 유지합니다. */
function handleStyleLibraryViewerKey(event) {
  if (!styleLibraryViewerState || !illustrationDialog.open || event.target.closest("input, textarea, select, [contenteditable=true]")) return;
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  moveStyleLibraryViewer(event.key === "ArrowLeft" ? -1 : 1);
}

/** Escape로 닫은 경우에도 상세 상태와 전용 Style이 다음 이미지 확대에 남지 않게 합니다. */
function clearStyleLibraryViewer() {
  styleLibraryViewerState = null;
  document.querySelector("#illustration-dialog").classList.remove("style-library-viewer");
}

document.addEventListener("click", handleStyleLibraryAction);
document.addEventListener("keydown", handleStyleLibraryViewerKey);
document.querySelector("#illustration-dialog").addEventListener("close", clearStyleLibraryViewer);

/** 퇴역·취소 조합도 파일을 지우지 않고 명시적으로 찾아볼 수 있게 합니다. */
function handleStyleLibraryLifecycleFilter(event) {
  if (event.target.id !== "style-library-lifecycle") return;
  currentStyleGenerationState().libraryLifecycle = event.target.value;
  renderPreview(false);
}

document.addEventListener("change", handleStyleLibraryLifecycleFilter);
