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
  if (sequence !== state.evolutionRefreshSequence || ((state.evolutionCommandBusy || state.votingCommandBusy || state.candidateCommandBusy) && !force)) return;
  state.evolution = evolution;
  project.generation = evolution.currentGeneration;
  if (projectIdentifier !== previewState.currentProjectIdentifier) return;
  const generationBadge = document.querySelector('.generation-current-badge');
  if (generationBadge) generationBadge.textContent = `현재 ${evolution.currentGeneration}세대`;
  const container = document.querySelector("#style-evolution-controls");
  const markup = styleEvolutionPanelMarkup();
  if (container && container.innerHTML !== markup && !container.contains(document.activeElement)) container.innerHTML = markup;
}

/** 세대 진행 상태와 다음 행동만 표시하고 자녀의 성분 Preview는 만들지 않습니다. */
function styleEvolutionPanelMarkup() {
  const state = currentStyleGenerationState();
  const evolution = state.evolution;
  if (!evolution) return '';
  const batch = evolution.batch;
  if (!batch) {
    if (previewState.screen === "compare") return evolution.canPrepare ? '<div class="cycle-next-action"><button data-action="navigate" data-screen="evolution">다음 세대 후보 만들기 →</button></div>' : '';
    const initialPool = evolution.candidateCount < evolution.minimumEvaluatedCount;
    if (initialPool) {
      return `<section class="panel evolution-panel"><h2>진화할 조합 준비</h2><p>Random 신규 조합을 생성하고 선별하면 상위 30%를 부모로 다음 세대를 만들 수 있습니다.</p><p class="form-note">평가 ${evolution.evaluatedCount} / 최소 ${evolution.minimumEvaluatedCount}개</p><div class="generation-start-controls"><button class="primary" data-action="navigate" data-screen="generation">Random 조합 만들기</button>${evolution.candidateCount ? '<button data-action="navigate" data-screen="compare">선별하기</button>' : ''}</div></section>`;
    }
    const count = state.candidateGenerationCount ?? previewState.candidateGenerationRequests?.[previewState.currentProjectIdentifier]?.candidateCount ?? 6;
    const canGenerate = !evolution.pendingRequestCount && evolution.canPrepare;
    const generationNumber = evolution.currentGeneration + 1;
    const generationConfirmed = evolution.history.some(item => item.status === 'confirmed' && item.targetGeneration === evolution.currentGeneration);
    const title = generationConfirmed ? `${evolution.currentGeneration}세대 확정 완료` : `${generationNumber}세대 후보`;
    const nextGenerationDescription = generationConfirmed ? `<p class="form-note">다음 단계: ${generationNumber}세대 후보 이미지 생성</p>` : '';
    const blockers = evolution.blockers.map(message => `<li>${escapeMarkup(message)}</li>`).join('');
    return `<section class="panel evolution-panel"><div class="settings-section-heading"><h2>${title}</h2><span class="muted">평가 ${evolution.evaluatedCount} / ${evolution.candidateCount}</span></div>
      ${nextGenerationDescription}
      <div class="generation-start-controls"><label for="style-generation-candidate-count">자녀 수</label><input id="style-generation-candidate-count" type="number" min="1" max="32" step="1" value="${escapeMarkup(count)}" ${canGenerate ? '' : 'disabled'} /><button class="primary" data-generation-action="generate-candidates" ${canGenerate ? '' : 'disabled'}>다음 세대 후보 생성</button><button data-action="navigate" data-screen="generation">Random 조합 추가</button><button data-action="navigate" data-screen="compare">선별하기</button></div>
      ${!canGenerate && blockers ? `<details class="evolution-blockers"><summary>${evolution.pendingRequestCount ? '후보 생성 중' : '선별을 먼저 마쳐 주세요'}</summary><ul>${blockers}</ul></details>` : ''}</section>`;
  }
  const phaseLabels = { planned: '생성 대기', generating: '생성 중', selecting: '선별 중', failed: '생성 확인 필요', ready: '선별 완료' };
  const generationActions = batch.status === 'planned'
    ? '<button class="primary" data-style-evolution-action="resume">후보 생성 이어하기</button>'
    : '<button class="primary" data-action="navigate" data-screen="compare">선별하기</button>';
  const confirmation = batch.canConfirm ? `<button class="primary" data-style-evolution-action="confirm">${batch.targetGeneration}세대 확정</button>` : generationActions;
  return `<section class="panel evolution-panel"><div class="settings-section-heading"><h2>${batch.targetGeneration}세대 후보 · ${phaseLabels[batch.phase] || '진행 중'}</h2><span class="muted">이미지 ${batch.readyChildCount}/${batch.childCount} · 선별 ${batch.completedSelectionCount}/${batch.childCount}</span></div>
    ${batch.canConfirm ? '<p class="form-note">세대를 확정한 뒤 다음 세대 이미지를 생성할 수 있습니다.</p>' : ''}
    <div class="generation-start-controls">${confirmation}${previewState.screen !== 'evolution' ? '<button data-action="navigate" data-screen="evolution">진화 보기</button>' : ''}</div>
    <details class="evolution-secondary-actions"><summary>이번 후보 취소</summary><button data-style-evolution-action="cancel">이번 진화 취소</button></details></section>`;
}

/** 실제 후보·부모와 세대 이력을 확인하는 진화 화면입니다. */
function renderStyleEvolutionWorkspace() {
  const evolution = currentStyleGenerationState().evolution;
  return `<div class="page-heading"><h1>진화</h1><span class="generation-current-badge">현재 ${evolution?.currentGeneration || currentProject().generation || 1}세대</span></div>${styleEvolutionContainerMarkup()}<p id="style-generation-error" class="error" role="alert">${escapeMarkup(currentStyleGenerationState().error)}</p><div id="style-render-results">${initialStyleResultsMarkup(currentStyleGenerationState().results)}</div>`;
}

/** 같은 조합 카드·Viewer를 사용하면서 세대의 평가·생존 상태만 덧붙입니다. */
function styleEvolutionCandidateGroupMarkup(title, identifiers, results, outcomes = {}) {
  const cards = [];
  for (const identifier of identifiers) {
    const candidate = results.candidates.find(item => item.identifier === identifier);
    if (!candidate) continue;
    const plan = results.plans.find(item => item.planIdentifier === candidate.planIdentifier);
    cards.push(`<div class="evolution-candidate"><span class="evolution-candidate-status">${escapeMarkup(outcomes[identifier] || '')}</span>${styleCandidateCardMarkup(candidate, plan)}</div>`);
  }
  return cards.length ? `<section class="evolution-candidate-group"><h2>${title}</h2><div class="style-library-grid">${cards.join('')}</div></section>` : '';
}

/** 진행 후보·현재 부모와 확정 이력을 기존 서버 Snapshot에서 표시합니다. */
function styleEvolutionResultsMarkup(results) {
  const evolution = currentStyleGenerationState().evolution;
  if (!results || !evolution) return '';
  if (previewState.blind) return rankingBlindNoticeMarkup();
  const batch = evolution.batch;
  const latest = evolution.history?.[0];
  const outcomes = {};
  let childIdentifiers = [];
  let title = '';
  if (batch) {
    childIdentifiers = batch.candidateIdentifiers;
    title = `${batch.targetGeneration}세대 후보`;
    for (const identifier of childIdentifiers) {
      outcomes[identifier] = batch.completedCandidateIdentifiers.includes(identifier) ? '선별 완료' : '평가 중 · 부모와 비교';
      if (batch.canConfirm) outcomes[identifier] = batch.enteredCandidateIdentifiers.includes(identifier) ? '생존 예정' : '탈락 예정';
    }
  } else if (latest) {
    childIdentifiers = latest.candidateIdentifiers.filter(identifier => results.candidates.some(candidate => candidate.identifier === identifier && candidate.renders.length));
    title = `${latest.targetGeneration}세대 결과`;
    for (const identifier of childIdentifiers) outcomes[identifier] = latest.status === 'cancelled' ? '취소' : latest.enteredIdentifiers.includes(identifier) ? '생존' : '탈락';
  } else {
    childIdentifiers = results.candidates.filter(candidate => candidate.evaluationIdentifier === evolution.evaluationIdentifier && candidate.lifecycle === 'active' && candidate.renders.length).map(candidate => candidate.identifier);
    title = '초기 후보';
  }
  const children = styleEvolutionCandidateGroupMarkup(title, childIdentifiers, results, outcomes);
  const parents = styleEvolutionCandidateGroupMarkup(batch ? '조합을 만든 부모' : '현재 상위 30%', evolution.parentCandidateIdentifiers, results);
  const generationActions = batch ? styleLibraryBatchActionsMarkup(results.candidates.filter(candidate => childIdentifiers.includes(candidate.identifier)), batch.plan) : '';
  const history = evolution.history?.length ? `<details class="panel evolution-history"><summary>세대 이력 · ${evolution.history.length}회</summary><ol>${evolution.history.map(item => `<li><strong>${item.targetGeneration}세대</strong><span>${item.status === 'cancelled' ? '취소' : `생존 ${item.enteredCount} · 탈락 ${item.failedCount}`}</span></li>`).join('')}</ol></details>` : '';
  const emptyState = !children && !parents ? '<section class="panel empty-state"><p>아직 후보가 없습니다.</p><button data-action="navigate" data-screen="generation">후보 만들기</button></section>' : '';
  return children + (generationActions ? `<div class="form-actions">${generationActions}</div>` : '') + emptyState + parents + history;
}

/** 같은 요청의 응답 유실·확인 취소에서는 이미 준비한 후보를 다시 뽑지 않습니다. */
async function prepareStyleCandidateGeneration(projectIdentifier, candidateCount) {
  const state = currentStyleGenerationState(projectIdentifier);
  const evolution = state.evolution;
  const previous = previewState.candidateGenerationRequests?.[projectIdentifier];
  const previousGenerationFinished = previous && evolution.history.some(batch => batch.operationIdentifier === previous.operationIdentifier);
  if (!previous || previousGenerationFinished || previous.candidateCount !== candidateCount || previous.expectedProjectRevision !== evolution.projectRevision) {
    previewState.candidateGenerationRequests ??= {};
    previewState.candidateGenerationRequests[projectIdentifier] = { operationIdentifier: newStyleClientIdentifier(), expectedProjectRevision: evolution.projectRevision, expectedVotingRevision: evolution.votingRevision, candidateCount };
  }
  persistStyleWorkspaceSession();
  try {
    const request = previewState.candidateGenerationRequests[projectIdentifier];
    const evolutionRequest = { operationIdentifier: request.operationIdentifier, expectedProjectRevision: request.expectedProjectRevision, expectedVotingRevision: request.expectedVotingRevision, childCount: request.candidateCount };
    return await styleProjectApi(`/api/style-projects/${projectIdentifier}/evolution-plans`, { method: 'POST', body: JSON.stringify(evolutionRequest) });
  } catch (error) {
    if ([409, 422].includes(error.status)) delete previewState.candidateGenerationRequests[projectIdentifier];
    persistStyleWorkspaceSession();
    throw error;
  }
}

/** 현재 세대 화면에 같은 진행 Panel을 배치해 새 탭 없이 생성·선별을 이어갑니다. */
function styleEvolutionContainerMarkup() {
  return `<div id="style-evolution-controls">${styleEvolutionPanelMarkup()}</div>`;
}

/** 생성 장수 외의 확인도 같은 Dialog에서 처리하고 Escape는 항상 취소로 봅니다. */
function confirmStyleEvolutionAction(action, generationNumber) {
  const dialog = document.querySelector("#style-generation-confirmation-dialog");
  const title = action === "confirm" ? `${generationNumber}세대로 확정할까요?` : "이번 진화를 취소할까요?";
  const description = action === "confirm"
    ? "살아남은 자녀가 들어오고 진입 수만큼 하위 기존 조합을 가능한 범위에서 퇴역시킵니다. 이미지와 이력은 보존됩니다. 확정하면 이번 진화의 Undo는 종료됩니다. 다음 세대 이미지는 확정 후 별도로 생성합니다."
    : "자녀 조합을 선별에서 제외합니다. 기존 조합의 일반 리그 평가와 생성한 이미지·작업 이력은 보존하며, 진행 중인 자녀 생성에는 취소를 요청합니다.";
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
  if (!["resume", "confirm", "cancel"].includes(action)) return;
  if (blockStyleMutationDuringVoting(projectIdentifier)) return;
  styleGenerationViewState.busy = true;
  state.evolutionCommandBusy = true;
  state.evolutionRefreshSequence = (state.evolutionRefreshSequence || 0) + 1;
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.error = "";
  const contentContainer = document.querySelector("#preview-content");
  contentContainer.inert = true;
  try {
    await refreshStyleEvolution(projectIdentifier, true);
    const evolution = state.evolution;
    if (action === "resume") {
      const plan = evolution.batch.plan;
      const batchIdentifier = plan.selection.batchIdentifier;
      if (await confirmStyleGeneration(plan)) {
        await submitConfirmedStyleGeneration(projectIdentifier, plan);
        state.comparisonPlanIdentifier = plan.planIdentifier;
      } else {
        await submitStyleEvolutionAction(projectIdentifier, "cancel", batchIdentifier, evolution.votingRevision);
      }
    } else if (await confirmStyleEvolutionAction(action, evolution.batch.targetGeneration)) {
      const result = await submitStyleEvolutionAction(projectIdentifier, action, evolution.batch.identifier, evolution.votingRevision);
      delete previewState.candidateGenerationRequests[projectIdentifier];
      persistStyleWorkspaceSession();
      showToast(action === "confirm" ? `${result.generationNumber}세대로 확정했습니다.` : "진화를 취소하고 부모 세대로 돌아왔습니다.");
      previewState.screen = "evolution";
      window.history.replaceState(null, "", "#evolution");
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.evolutionCommandBusy = false;
    try {
      await refreshStyleGenerationResults(projectIdentifier);
    } catch (error) {
      state.error ||= error.message;
    }
    styleGenerationViewState.busy = false;
    contentContainer.inert = false;
    if (projectIdentifier === previewState.currentProjectIdentifier) renderPreview(false);
  }
}

document.addEventListener("click", handleStyleEvolutionAction);
