"use strict";

/** 현재 프로젝트의 평가 조건과 일치하는 성분 통계만 설정 행에서 사용합니다. */
function currentProjectComponentStatistics() {
  const project = currentProject();
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "project-settings" || !project) return null;
  const statistics = currentStyleGenerationState(project.identifier).componentStatistics;
  return statistics?.evaluationIdentifier === project.evaluationIdentifier ? statistics : null;
}

/** 승패와 Elo 기여도를 구분해 짧은 수치만 표시합니다. */
function projectComponentStatisticsValuesMarkup(identifier) {
  const projectStatistics = currentProjectComponentStatistics();
  if (!projectStatistics) return '<span class="component-statistics-pending">통계 —</span>';
  const statistics = projectStatistics.components[identifier] || { score: 0, ratedCombinationCount: 0, wins: 0, losses: 0, winRate: null };
  const score = statistics.ratedCombinationCount ? `${statistics.score > 0 ? "+" : ""}${statistics.score.toLocaleString("ko-KR")}` : "—";
  const winRate = statistics.winRate === null ? "—" : `${Math.round(statistics.winRate * 100)}%`;
  const inheritedScore = statistics.inheritedScore > 0 ? `+${statistics.inheritedScore}` : statistics.inheritedScore;
  const inheritedCaption = statistics.inheritedMatches || statistics.inheritedScore
    ? `<small class="component-inherited-statistics">이전 Score ${inheritedScore} · ${statistics.inheritedWins}승 ${statistics.inheritedLosses}패 · 새 비교 ${statistics.localMatches}회</small>` : "";
  return `<dl class="component-statistics-values">
    <div><dt title="현재 조건의 활성·퇴역 조합 Elo와 STR로 추정한 기여 점수입니다. 다음 세대의 새 성분 선택에 0.5~2배로 반영합니다.">선호도</dt><dd class="${statistics.score > 0 ? "positive" : statistics.score < 0 ? "negative" : ""}">${score}</dd></div>
    <div><dt title="일반 대결에서 한쪽에만 포함된 성분의 전적입니다. 배치 선별·비슷함·공통 성분은 제외합니다.">승패</dt><dd>${statistics.wins}승 ${statistics.losses}패</dd></div>
    <div><dt>승률</dt><dd>${winRate}</dd></div>
    <div><dt>평가 조합</dt><dd>${statistics.ratedCombinationCount}</dd></div>
  </dl>${inheritedCaption}`;
}

/** 성분 이름 오른쪽 공간을 사용하고 STR 입력은 기존 행에 유지합니다. */
function projectComponentStatisticsMarkup(identifier) {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "project-settings") return "";
  return `<div class="project-component-statistics" data-project-component-statistics="${escapeMarkup(identifier)}">${projectComponentStatisticsValuesMarkup(identifier)}</div>`;
}

/** 등록 순서와 통계 정렬을 분리하고 같은 점수는 기존 Catalog 순서로 유지합니다. */
function sortProjectComponentEntries(entries, groupIdentifier) {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "project-settings") return entries;
  const sortOrder = currentStyleGenerationState().componentStatisticsSort?.[groupIdentifier] || "catalog";
  const statistics = currentProjectComponentStatistics()?.components || {};
  if (sortOrder === "catalog") return entries;
  return [...entries].sort((first, second) => {
    const firstValue = statistics[first[1].identifier]?.[sortOrder] ?? -Infinity;
    const secondValue = statistics[second[1].identifier]?.[sortOrder] ?? -Infinity;
    return firstValue === secondValue ? first[0] - second[0] : secondValue - firstValue;
  });
}

/** 통계가 도착해도 Form·Focus·Scroll·미저장 입력을 교체하지 않습니다. */
function updateProjectComponentStatistics() {
  if (previewState.screen !== "project-settings" || !currentProject()) return;
  for (const container of document.querySelectorAll("[data-project-component-statistics]")) {
    container.innerHTML = projectComponentStatisticsValuesMarkup(container.dataset.projectComponentStatistics);
  }
  for (const select of document.querySelectorAll("[data-component-statistics-sort]")) select.disabled = !currentProjectComponentStatistics();
  const state = currentStyleGenerationState();
  const status = document.querySelector("#style-component-statistics-status");
  if (status) status.textContent = state.componentStatisticsError || (state.componentStatisticsPromise ? "통계 불러오는 중…" : "");
}

/** 설정을 열 때만 가벼운 전용 API를 조회하고 같은 프로젝트의 진행 중 요청은 합칩니다. */
function refreshStyleComponentStatistics() {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "project-settings" || !currentProject()) return;
  const projectIdentifier = currentProject().identifier;
  const evaluationIdentifier = currentProject().evaluationIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  if (state.componentStatisticsPromise && state.componentStatisticsRequestedEvaluation === evaluationIdentifier) return state.componentStatisticsPromise;
  state.componentStatisticsRequestedEvaluation = evaluationIdentifier;
  state.componentStatisticsError = "";
  const parameters = new URLSearchParams({ evaluationIdentifier });
  const pendingRequest = styleProjectApi(`/api/style-projects/${projectIdentifier}/component-statistics?${parameters}`)
    .then(statistics => {
      if (state.componentStatisticsRequestedEvaluation === evaluationIdentifier) state.componentStatistics = statistics;
    }).catch(error => {
      if (state.componentStatisticsRequestedEvaluation === evaluationIdentifier) state.componentStatisticsError = "성분 통계를 불러오지 못했습니다. 새로고침해 주세요.";
    }).finally(() => {
      if (state.componentStatisticsPromise === pendingRequest) state.componentStatisticsPromise = null;
      if (projectIdentifier === previewState.currentProjectIdentifier) updateProjectComponentStatistics();
    });
  state.componentStatisticsPromise = pendingRequest;
  updateProjectComponentStatistics();
  return pendingRequest;
}

/** 명시적인 정렬만 해당 종류의 행을 다시 그리고 다른 설정 초안은 유지합니다. */
function handleProjectComponentStatisticsSort(event) {
  const groupIdentifier = event.target.dataset.componentStatisticsSort;
  if (!PERSISTENT_STYLE_WORKSPACE || !groupIdentifier) return;
  const state = currentStyleGenerationState();
  state.componentStatisticsSort ??= {};
  state.componentStatisticsSort[groupIdentifier] = event.target.value;
  const group = document.querySelector(`#settings-project-${groupIdentifier}`).closest(".settings-component-group");
  group.outerHTML = projectComponentGroupMarkup(groupIdentifier === "artist" ? "작가" : "LoRA", groupIdentifier === "artist" ? "작가 태그" : "LoRA", groupIdentifier);
  document.querySelector(`[data-component-statistics-sort=${groupIdentifier}]`).focus({ preventScroll: true });
}

/** 수동 갱신도 설정 저장이나 생성 요청을 발생시키지 않습니다. */
function handleProjectComponentStatisticsRefresh(event) {
  if (event.target.closest("[data-component-statistics-refresh]")) refreshStyleComponentStatistics();
}

document.addEventListener("change", handleProjectComponentStatisticsSort);
document.addEventListener("click", handleProjectComponentStatisticsRefresh);
