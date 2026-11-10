"use strict";

/** 새 세대와 부모의 상태를 읽되 이미 접수한 화면 명령과 Polling을 섞지 않습니다. */
async function refreshStyleEvolution(projectIdentifier, force = false) {
  const state = currentStyleGenerationState(projectIdentifier);
  if (state.evolutionCommandBusy && !force) return;
  const project = previewState.projects.find(item => item.identifier === projectIdentifier);
  if (!project?.evaluationIdentifier) return;
  const sequence = (state.evolutionRefreshSequence || 0) + 1;
  state.evolutionRefreshSequence = sequence;
  const parameters = new URLSearchParams({ evaluationIdentifier: project.evaluationIdentifier });
  const evolution = await styleProjectApi(`/api/style-projects/${projectIdentifier}/evolution?${parameters}`);
  if (sequence !== state.evolutionRefreshSequence || (state.evolutionCommandBusy && !force)) return;
  state.evolution = evolution;
  if (evolution.batch) state.pendingEvolutionPreparation = null;
  project.generation = evolution.currentGeneration;
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const container = document.querySelector("#style-evolution-controls");
  const markup = styleEvolutionPanelMarkup();
  if (container && container.innerHTML !== markup && !container.contains(document.activeElement)) container.innerHTML = markup;
}

/** 세대 진행 상태와 다음 행동만 표시하고 자녀의 성분 Preview는 만들지 않습니다. */
function styleEvolutionPanelMarkup() {
  const state = currentStyleGenerationState();
  const evolution = state.evolution;
  if (!evolution) return '<section class="panel"><h2>다음 세대</h2><p>선별 상태를 확인하는 중입니다.</p></section>';
  const batch = evolution.batch;
  if (!batch) {
    const count = state.evolutionChildCount ?? 6;
    const reasons = evolution.blockers.map(message => `<li>${escapeMarkup(message)}</li>`).join("");
    const latest = evolution.lastConfirmed;
    return `<section class="panel evolution-panel"><h2>현재 ${evolution.currentGeneration}세대 · 다음 세대 만들기</h2><p>평가된 상위 30%를 부모로 선택하고 Mutate·Crossover·Random으로 자녀를 만듭니다. 모든 Prompt에 같은 조합과 Seed를 사용합니다.</p>${latest ? `<p class="evolution-summary">지난 진화: 자녀 ${latest.enteredCount}개 진입 · 자녀 ${latest.failedCount}개 탈락 · 기존 ${latest.retiredExistingCount}개 퇴역</p>` : ""}<label for="style-evolution-child-count">자녀 조합 수 (1 ~ 32개)</label><input id="style-evolution-child-count" type="number" min="1" max="32" step="1" value="${escapeMarkup(count)}" /><p class="form-note">평가 완료 ${evolution.evaluatedCount}개 · 최소 ${evolution.minimumEvaluatedCount}개 필요</p>${reasons ? `<ul class="evolution-blockers">${reasons}</ul>` : ""}<button class="primary" data-style-evolution-action="prepare" ${!evolution.canPrepare ? "disabled" : ""}>다음 세대 이미지 생성</button></section>`;
  }
  const phaseLabels = { planned: "생성 확인 대기", generating: "자녀 이미지 생성 중", selecting: "자녀 선별 중", failed: "생성 상태 확인 필요", ready: "선별 완료 · 확정 대기" };
  const resume = batch.status === "planned" ? '<button class="primary" data-style-evolution-action="resume">자녀 이미지 생성</button>' : '<button data-action="navigate" data-screen="compare">자녀 선별하기</button>';
  const confirmation = batch.status === "active" ? `<button class="primary" data-style-evolution-action="confirm" ${!batch.canConfirm ? "disabled" : ""}>${batch.targetGeneration}세대로 확정</button>` : "";
  return `<section class="panel evolution-panel"><h2>${batch.sourceGeneration} → ${batch.targetGeneration}세대 · ${phaseLabels[batch.phase] || "진행 중"}</h2><p>자녀 ${batch.childCount}개 중 이미지 준비 ${batch.readyChildCount}개 · 배치 완료 ${batch.completedSelectionCount}개</p><p class="form-note">선별 중 부모의 Elo·전적은 유지됩니다. 모든 자녀를 확인한 뒤 세대를 확정합니다.</p>${batch.failedRequestCount ? '<p class="error">실패·취소한 생성이 있습니다. 아래 생성 결과에서 해당 항목만 재시도하거나 이번 진화를 취소해 주세요.</p>' : ""}<div class="form-actions">${resume}${confirmation}<button data-style-evolution-action="cancel">이번 진화 취소</button></div><p class="form-note">확정 후 탈락·퇴역한 그림체도 이미지와 이력을 보존합니다.</p></section>`;
}

/** 현재 세대 화면에 같은 진행 Panel을 배치해 새 탭 없이 생성·선별을 이어갑니다. */
function styleEvolutionContainerMarkup() {
  return `<div id="style-evolution-controls">${styleEvolutionPanelMarkup()}</div>`;
}

/** 자녀 수 초안은 Polling이 바꾸지 못하도록 프로젝트별 화면 상태에 저장합니다. */
function handleStyleEvolutionInput(event) {
  if (event.target.id === "style-evolution-child-count") currentStyleGenerationState().evolutionChildCount = event.target.value;
}

/** 생성 장수 외의 확인도 같은 Dialog에서 처리하고 Escape는 항상 취소로 봅니다. */
function confirmStyleEvolutionAction(action, generationNumber) {
  const dialog = document.querySelector("#style-generation-confirmation-dialog");
  const title = action === "confirm" ? `${generationNumber}세대로 확정할까요?` : "이번 진화를 취소할까요?";
  const description = action === "confirm"
    ? "살아남은 자녀가 들어오고 진입 수만큼 하위 기존 조합을 가능한 범위에서 퇴역시킵니다. 이미지와 이력은 보존됩니다. 확정하면 이번 진화의 Undo는 종료됩니다."
    : "자녀 조합을 선별에서 제외하고 부모 세대의 평가 상태로 돌아갑니다. 생성한 이미지와 작업 이력은 보존하며, 진행 중인 자녀 생성에는 취소를 요청합니다.";
  dialog.innerHTML = `<form method="dialog"><h2>${title}</h2><p>${description}</p><div class="form-actions"><button value="cancel">돌아가기</button><button class="primary" value="confirm">확인</button></div></form>`;
  dialog.returnValue = "cancel";
  return new Promise(resolve => {
    /** 닫기·Escape와 확인을 한 번만 구분해 반환합니다. */
    function resolveEvolutionConfirmation() {
      resolve(dialog.returnValue === "confirm");
    }
    dialog.addEventListener("close", resolveEvolutionConfirmation, { once: true });
    dialog.showModal();
  });
}

/** 응답 유실 때 같은 Operation을 재전송해 확정·취소의 중복 처리를 방지합니다. */
async function submitStyleEvolutionAction(projectIdentifier, action, batchIdentifier, votingRevision) {
  const state = currentStyleGenerationState(projectIdentifier);
  const previous = state.pendingEvolutionAction;
  if (!previous || previous.action !== action || previous.batchIdentifier !== batchIdentifier) {
    state.pendingEvolutionAction = { action, batchIdentifier, payload: { operationIdentifier: newStyleClientIdentifier(), expectedVotingRevision: votingRevision } };
  }
  const pending = state.pendingEvolutionAction;
  try {
    const result = await styleProjectApi(`/api/style-projects/${projectIdentifier}/evolution-batches/${batchIdentifier}/${action}`, { method: "POST", body: JSON.stringify(pending.payload) });
    state.pendingEvolutionAction = null;
    return result;
  } catch (error) {
    if ([404, 409, 422].includes(error.status)) state.pendingEvolutionAction = null;
    throw error;
  }
}

/** 명시적 사용자 확인으로만 자녀 생성·세대 확정·취소를 실행합니다. */
async function handleStyleEvolutionAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-evolution-action]");
  if (!button || button.disabled || styleGenerationViewState.busy) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const action = button.dataset.styleEvolutionAction;
  const countInput = document.querySelector("#style-evolution-child-count");
  if (action === "prepare" && (!countInput.reportValidity() || !countInput.value)) return;
  styleGenerationViewState.busy = true;
  state.evolutionCommandBusy = true;
  state.evolutionRefreshSequence = (state.evolutionRefreshSequence || 0) + 1;
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.error = "";
  const contentContainer = document.querySelector("#preview-content");
  contentContainer.inert = true;
  try {
    await refreshStyleEvolution(projectIdentifier, true);
    let evolution = state.evolution;
    if (action === "prepare" || action === "resume") {
      let plan = evolution.batch?.plan;
      if (action === "prepare") {
        state.pendingEvolutionPreparation ??= { operationIdentifier: newStyleClientIdentifier(), expectedProjectRevision: evolution.projectRevision, expectedVotingRevision: evolution.votingRevision, childCount: Number(state.evolutionChildCount ?? 6) };
        plan = await styleProjectApi(`/api/style-projects/${projectIdentifier}/evolution-plans`, { method: "POST", body: JSON.stringify(state.pendingEvolutionPreparation) });
        state.pendingEvolutionPreparation = null;
      }
      const batchIdentifier = plan.selection.batchIdentifier;
      if (await confirmStyleGeneration(plan)) {
        await submitConfirmedStyleGeneration(projectIdentifier, plan);
        state.comparisonPlanIdentifier = plan.planIdentifier;
      } else {
        await submitStyleEvolutionAction(projectIdentifier, "cancel", batchIdentifier, evolution.votingRevision);
      }
    } else if (await confirmStyleEvolutionAction(action, evolution.batch.targetGeneration)) {
      const result = await submitStyleEvolutionAction(projectIdentifier, action, evolution.batch.identifier, evolution.votingRevision);
      showToast(action === "confirm" ? `${result.generationNumber}세대로 확정했습니다.` : "진화를 취소하고 부모 세대로 돌아왔습니다.");
      state.pendingRandomPlan = null;
      state.pendingRandomRequest = null;
      state.pendingEvolutionPreparation = null;
    }
  } catch (error) {
    if ([409, 422].includes(error.status)) state.pendingEvolutionPreparation = null;
    state.error = error.message;
  } finally {
    styleGenerationViewState.busy = false;
    state.evolutionCommandBusy = false;
    contentContainer.inert = false;
    try {
      await refreshStyleGenerationResults(projectIdentifier);
    } catch (error) {
      state.error ||= error.message;
    }
    if (projectIdentifier === previewState.currentProjectIdentifier) renderPreview(false);
  }
}

document.addEventListener("input", handleStyleEvolutionInput);
document.addEventListener("click", handleStyleEvolutionAction);
