"use strict";

/** CHS LoRA 등록 모아보기는 프로젝트마다 독립적으로 유지합니다. */
function styleLibraryLoraPresetsOnly() {
  return Boolean(previewState.libraryLoraPresetFilters?.[previewState.currentProjectIdentifier]);
}

/** 저장한 그림체의 모아보기에서는 퇴역을 포함해 모든 상태를 검색합니다. */
function styleLibrarySavedOnly() {
  return styleLibraryFavoritesOnly() || styleLibraryLoraPresetsOnly();
}

/** 원본 조합을 바꾸지 않는 CHS 등록·해제 버튼을 조합 보기 옆에 표시합니다. */
function styleCandidateLoraPresetButtonMarkup(candidate) {
  const registered = Boolean(candidate.loraPresetIdentifier);
  const hasLoras = candidate.components.some(component => component.identifier.startsWith("lora:"));
  const pending = currentStyleGenerationState().pendingLoraRegistrationCandidateIdentifiers?.has(candidate.identifier);
  const label = registered ? "LoRA 등록 해제" : "LoRA 조합 등록";
  return `<button type="button" class="style-candidate-lora-preset" data-style-lora-preset="${escapeMarkup(candidate.identifier)}" aria-pressed="${registered}" aria-label="${escapeMarkup(persistentCandidateLabel(candidate))} ${label}" title="${hasLoras ? label : "이 그림체에는 LoRA가 없습니다."}" ${pending || !hasLoras ? "disabled" : ""} ${pending ? 'aria-busy="true"' : ""}>${label}</button>`;
}

/** 별표와 함께 사용하면 두 필터의 교집합을 보여 줍니다. */
function styleLibraryLoraPresetsFilterMarkup(results) {
  const count = (results?.candidates || []).filter(candidate => candidate.loraPresetIdentifier && candidate.renders.length).length;
  return `<label class="style-library-favorites-filter"><input id="style-library-lora-presets-only" type="checkbox" ${styleLibraryLoraPresetsOnly() ? "checked" : ""} /><span>LoRA 등록된 것만 보기 <span id="style-library-lora-preset-count">${count}</span></span></label>`;
}

/** 등록 명령과 Polling 뒤 버튼·집계만 갱신해 현재 이미지와 Scroll을 보존합니다. */
function refreshStyleLoraPresetControls(projectIdentifier) {
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const state = currentStyleGenerationState(projectIdentifier);
  for (const button of document.querySelectorAll("[data-style-lora-preset]")) {
    const candidate = state.results?.candidates.find(candidate => candidate.identifier === button.dataset.styleLoraPreset);
    if (!candidate) continue;
    const registered = Boolean(candidate.loraPresetIdentifier);
    const pending = Boolean(state.pendingLoraRegistrationCandidateIdentifiers?.has(candidate.identifier));
    button.textContent = registered ? "LoRA 등록 해제" : "LoRA 조합 등록";
    button.setAttribute("aria-pressed", String(registered));
    button.setAttribute("aria-label", `${persistentCandidateLabel(candidate)} ${button.textContent}`);
    button.setAttribute("aria-busy", String(pending));
    button.disabled = pending || !candidate.components.some(component => component.identifier.startsWith("lora:"));
  }
  const count = document.querySelector("#style-library-lora-preset-count");
  if (count) count.textContent = (state.results?.candidates || []).filter(candidate => candidate.loraPresetIdentifier && candidate.renders.length).length;
  focusStyleLoraPresetSourceCandidate(projectIdentifier);
}

/** 등록 여부를 명시한 PUT으로 중복 클릭·응답 유실 재시도에도 같은 preset을 사용합니다. */
async function handleStyleCandidateLoraPreset(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-lora-preset]");
  if (!button || button.disabled) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const candidateIdentifier = button.dataset.styleLoraPreset;
  const candidate = state.results?.candidates.find(candidate => candidate.identifier === candidateIdentifier);
  if (!candidate) return;
  state.pendingLoraRegistrationCandidateIdentifiers ??= new Set();
  if (state.pendingLoraRegistrationCandidateIdentifiers.has(candidateIdentifier)) return;
  const isRegistered = !candidate.loraPresetIdentifier;
  state.pendingLoraRegistrationCandidateIdentifiers.add(candidateIdentifier);
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  refreshStyleLoraPresetControls(projectIdentifier);
  try {
    const response = await styleProjectApi(`/api/style-projects/${projectIdentifier}/candidates/${candidateIdentifier}/lora-preset`, {
      method: "PUT", body: JSON.stringify({ isRegistered }),
    });
    const currentCandidate = state.results?.candidates.find(candidate => candidate.identifier === candidateIdentifier);
    if (currentCandidate) currentCandidate.loraPresetIdentifier = response.loraPresetIdentifier;
    showToast(isRegistered ? "CHS LoRA 조합에 등록했습니다." : "LoRA 조합 등록을 해제했습니다.");
  } catch (error) {
    showToast(error.message);
  } finally {
    state.pendingLoraRegistrationCandidateIdentifiers.delete(candidateIdentifier);
    if (["candidates", "evolution"].includes(previewState.screen)) renderCurrentStyleGenerationResults(projectIdentifier);
    refreshStyleLoraPresetControls(projectIdentifier);
  }
}

/** 모아보기 선택만 바꾸며 생성·등록 요청은 발생시키지 않습니다. */
function handleStyleLibraryLoraPresetFilter(event) {
  if (!PERSISTENT_STYLE_WORKSPACE || event.target.id !== "style-library-lora-presets-only") return;
  previewState.libraryLoraPresetFilters ??= {};
  previewState.libraryLoraPresetFilters[previewState.currentProjectIdentifier] = event.target.checked;
  renderPreview(false);
}

/** CHS에서 명시적으로 연 원본 링크만 프로젝트와 표시 범위를 설정합니다. */
function restoreStyleLoraPresetSourceNavigation() {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const parameters = new URLSearchParams(window.location.search);
  const projectIdentifier = parameters.get("project");
  const candidateIdentifier = parameters.get("candidate");
  if (!candidateIdentifier || !previewState.projects.some(project => project.identifier === projectIdentifier)) return;
  previewState.currentProjectIdentifier = projectIdentifier;
  delete previewState.libraryFavoriteFilters?.[projectIdentifier];
  delete previewState.libraryLoraPresetFilters?.[projectIdentifier];
  const state = currentStyleGenerationState(projectIdentifier);
  state.libraryLifecycle = "all";
  state.pendingSourceCandidateIdentifier = candidateIdentifier;
  // 원본 이동은 한 번만 적용해 이후 새로고침에서 사용자의 필터를 덮지 않습니다.
  parameters.delete("project");
  parameters.delete("candidate");
  const remainingSearch = parameters.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${remainingSearch ? `?${remainingSearch}` : ""}${window.location.hash}`);
}

/** 결과가 도착한 뒤 원본 카드로 한 번 이동하고 이후 Polling은 위치를 바꾸지 않습니다. */
function focusStyleLoraPresetSourceCandidate(projectIdentifier) {
  const state = currentStyleGenerationState(projectIdentifier);
  if (!state.pendingSourceCandidateIdentifier || !state.results || previewState.screen !== "candidates") return;
  const card = document.querySelector(`.style-library-card[data-style-candidate="${CSS.escape(state.pendingSourceCandidateIdentifier)}"]`);
  delete state.pendingSourceCandidateIdentifier;
  if (!card) return showToast("원본 그림체를 찾을 수 없습니다.");
  requestAnimationFrame(() => {
    if (!card.isConnected) return;
    card.scrollIntoView({ block: "center" });
    card.querySelector(".style-card-composition")?.focus({ preventScroll: true });
  });
}

document.addEventListener("click", handleStyleCandidateLoraPreset);
document.addEventListener("change", handleStyleLibraryLoraPresetFilter);
