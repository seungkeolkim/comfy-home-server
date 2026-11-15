"use strict";

/** 즐겨찾기 모아보기는 프로젝트마다 분리해 다른 화면을 다녀와도 유지합니다. */
function styleLibraryFavoritesOnly() {
  return Boolean(previewState.libraryFavoriteFilters?.[previewState.currentProjectIdentifier]);
}

/** 조합 카드와 Viewer에서 같은 별표 상태와 저장 중 표시를 사용합니다. */
function styleCandidateFavoriteButtonMarkup(candidate) {
  const pending = currentStyleGenerationState().pendingFavoriteCandidateIdentifiers?.has(candidate.identifier);
  const label = `${persistentCandidateLabel(candidate)} 즐겨찾기 ${candidate.isFavorite ? "해제" : "추가"}`;
  return `<button type="button" class="style-candidate-favorite" data-style-candidate-favorite="${escapeMarkup(candidate.identifier)}" aria-pressed="${Boolean(candidate.isFavorite)}" aria-label="${escapeMarkup(label)}" title="${candidate.isFavorite ? "즐겨찾기 해제" : "즐겨찾기 추가"}" ${pending ? 'disabled aria-busy="true"' : ""}>${candidate.isFavorite ? "★" : "☆"}</button>`;
}

/** 프로젝트 전체 조건의 좋아요 수와 모아보기 Checkbox를 표시합니다. */
function styleLibraryFavoritesFilterMarkup(results) {
  const count = (results?.candidates || []).filter(candidate => candidate.isFavorite && candidate.renders.length).length;
  return `<label class="style-library-favorites-filter"><input id="style-library-favorites-only" type="checkbox" ${styleLibraryFavoritesOnly() ? "checked" : ""} /><span><span class="style-favorite-symbol" aria-hidden="true">★</span> 즐겨찾기만 보기 <span id="style-library-favorite-count">${count}</span></span></label>`;
}

/** Polling·좋아요 저장 뒤 열려 있는 카드와 Viewer의 버튼만 동기화합니다. */
function refreshStyleFavoriteControls(projectIdentifier) {
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const state = currentStyleGenerationState(projectIdentifier);
  for (const button of document.querySelectorAll("[data-style-candidate-favorite]")) {
    const candidate = state.results?.candidates.find(item => item.identifier === button.dataset.styleCandidateFavorite);
    if (!candidate) continue;
    const pending = Boolean(state.pendingFavoriteCandidateIdentifiers?.has(candidate.identifier));
    const label = `${persistentCandidateLabel(candidate)} 즐겨찾기 ${candidate.isFavorite ? "해제" : "추가"}`;
    button.textContent = candidate.isFavorite ? "★" : "☆";
    button.setAttribute("aria-pressed", String(Boolean(candidate.isFavorite)));
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-busy", String(pending));
    button.title = candidate.isFavorite ? "즐겨찾기 해제" : "즐겨찾기 추가";
    button.disabled = pending;
  }
  const count = document.querySelector("#style-library-favorite-count");
  if (count) count.textContent = (state.results?.candidates || []).filter(candidate => candidate.isFavorite && candidate.renders.length).length;
}

/** 좋아요는 원하는 값을 PUT해 재전송에도 뒤집히지 않으며 실패하면 기존 표시를 유지합니다. */
async function handleStyleCandidateFavorite(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-candidate-favorite]");
  if (!button || button.disabled) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const candidateIdentifier = button.dataset.styleCandidateFavorite;
  const candidate = state.results?.candidates.find(item => item.identifier === candidateIdentifier);
  if (!candidate) return;
  state.pendingFavoriteCandidateIdentifiers ??= new Set();
  if (state.pendingFavoriteCandidateIdentifiers.has(candidateIdentifier)) return;
  state.pendingFavoriteCandidateIdentifiers.add(candidateIdentifier);
  // 이전 Polling 응답이 저장 완료 뒤의 별표를 덮어쓰지 않게 합니다.
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  refreshStyleFavoriteControls(projectIdentifier);
  try {
    const response = await styleProjectApi(`/api/style-projects/${projectIdentifier}/candidates/${candidateIdentifier}/favorite`, {
      method: "PUT", body: JSON.stringify({ isFavorite: !candidate.isFavorite }),
    });
    const currentCandidate = state.results?.candidates.find(item => item.identifier === candidateIdentifier);
    if (currentCandidate) currentCandidate.isFavorite = response.isFavorite;
  } catch (error) {
    showToast(error.message);
  } finally {
    state.pendingFavoriteCandidateIdentifiers.delete(candidateIdentifier);
    if (["candidates", "evolution"].includes(previewState.screen)) renderCurrentStyleGenerationResults(projectIdentifier);
    refreshStyleFavoriteControls(projectIdentifier);
  }
}

/** 모아보기에서는 퇴역을 포함한 전체 그림체를 보여 주고 원래 상태 필터는 보존합니다. */
function handleStyleLibraryFavoritesFilter(event) {
  if (!PERSISTENT_STYLE_WORKSPACE || event.target.id !== "style-library-favorites-only") return;
  previewState.libraryFavoriteFilters ??= {};
  previewState.libraryFavoriteFilters[previewState.currentProjectIdentifier] = event.target.checked;
  renderPreview(false);
}

document.addEventListener("click", handleStyleCandidateFavorite);
document.addEventListener("change", handleStyleLibraryFavoritesFilter);
