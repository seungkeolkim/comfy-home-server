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
  const continuation = previewState.evolutionContinuations?.[previewState.currentProjectIdentifier];
  if (continuation && previewState.screen !== "compare") {
    const title = continuation.confirmedGeneration ? `${continuation.confirmedGeneration}세대 확정 · 다음 후보 생성 대기` : "세대 확정·다음 후보 상태 확인";
    return `<section class="panel evolution-panel"><h2>${title}</h2><div class="form-actions"><button class="primary" data-style-evolution-action="resume-next">이어하기</button><button data-action="navigate" data-screen="compare">선별하기</button><button data-style-evolution-action="dismiss-next">이어 만들기 중단</button></div></section>`;
  }
  const batch = evolution.batch;
  if (!batch) {
    if (previewState.screen === "compare") return evolution.canPrepare ? '<div class="cycle-next-action"><button data-action="navigate" data-screen="evolution">다음 세대 후보 만들기 →</button></div>' : '';
    const initialPool = evolution.candidateCount < evolution.minimumEvaluatedCount;
    const count = state.candidateGenerationCount ?? previewState.candidateGenerationRequests?.[previewState.currentProjectIdentifier]?.candidateCount ?? (initialPool ? Math.max(evolution.minimumEvaluatedCount - evolution.candidateCount, 1) : 6);
    const canGenerate = !evolution.pendingRequestCount && (initialPool || evolution.canPrepare);
    const generationNumber = initialPool ? evolution.currentGeneration : evolution.currentGeneration + 1;
    const title = initialPool ? `${generationNumber}세대 초기 후보` : `${generationNumber}세대 후보`;
    const blockers = evolution.blockers.map(message => `<li>${escapeMarkup(message)}</li>`).join('');
    return `<section class="panel evolution-panel"><div class="settings-section-heading"><h2>${title}</h2><span class="muted">평가 ${evolution.evaluatedCount} / ${evolution.candidateCount}</span></div>
      <div class="generation-start-controls"><label for="style-generation-candidate-count">후보 수</label><input id="style-generation-candidate-count" type="number" min="1" max="32" step="1" value="${escapeMarkup(count)}" ${canGenerate ? '' : 'disabled'} /><button class="primary" data-generation-action="generate-candidates" ${canGenerate ? '' : 'disabled'}>${initialPool ? '초기 후보 생성' : '다음 세대 후보 생성'}</button>${evolution.candidateCount ? '<button data-action="navigate" data-screen="compare">선별하기</button>' : ''}</div>
      ${!canGenerate && blockers ? `<details class="evolution-blockers"><summary>${evolution.pendingRequestCount ? '후보 생성 중' : '선별을 먼저 마쳐 주세요'}</summary><ul>${blockers}</ul></details>` : ''}</section>`;
  }
  const phaseLabels = { planned: '생성 대기', generating: '생성 중', selecting: '선별 중', failed: '생성 확인 필요', ready: '선별 완료' };
  const nextCount = state.nextCandidateCount ?? batch.childCount;
  const generationActions = batch.status === 'planned'
    ? '<button class="primary" data-style-evolution-action="resume">후보 생성 이어하기</button>'
    : '<button class="primary" data-action="navigate" data-screen="compare">선별하기</button>';
  const confirmation = batch.canConfirm ? `<label for="style-next-candidate-count">다음 후보 수</label><input id="style-next-candidate-count" type="number" min="1" max="32" step="1" value="${escapeMarkup(nextCount)}" /><button class="primary" data-style-evolution-action="confirm-next">확정하고 다음 후보 생성</button><button data-style-evolution-action="confirm">${batch.targetGeneration}세대 확정</button>` : generationActions;
  return `<section class="panel evolution-panel"><div class="settings-section-heading"><h2>${batch.targetGeneration}세대 후보 · ${phaseLabels[batch.phase] || '진행 중'}</h2><span class="muted">이미지 ${batch.readyChildCount}/${batch.childCount} · 선별 ${batch.completedSelectionCount}/${batch.childCount}</span></div>
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
      outcomes[identifier] = batch.completedCandidateIdentifiers.includes(identifier) ? '배치 완료' : '평가 중';
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
  const parents = styleEvolutionCandidateGroupMarkup(batch ? '비교 기준 부모' : '현재 상위 30%', evolution.parentCandidateIdentifiers, results);
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
  if (!previous || previous.candidateCount !== candidateCount || previous.expectedProjectRevision !== evolution.projectRevision) {
    previewState.candidateGenerationRequests ??= {};
    previewState.candidateGenerationRequests[projectIdentifier] = { operationIdentifier: newStyleClientIdentifier(), expectedProjectRevision: evolution.projectRevision, expectedVotingRevision: evolution.votingRevision, candidateCount };
  }
  persistStyleWorkspaceSession();
  try {
    return await styleProjectApi(`/api/style-projects/${projectIdentifier}/candidate-generation-plans`, { method: 'POST', body: JSON.stringify(previewState.candidateGenerationRequests[projectIdentifier]) });
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

/** 자녀 수 초안은 Polling이 바꾸지 못하도록 프로젝트별 화면 상태에 저장합니다. */
function handleStyleEvolutionInput(event) {
  if (event.target.id === "style-next-candidate-count") currentStyleGenerationState().nextCandidateCount = event.target.value;
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

/** 확정과 다음 GPU 제출을 한 확인창으로 승인하고 실제 장수 상한을 표시합니다. */
function confirmStyleEvolutionContinuation(evolution, candidateCount) {
  const dialog = document.querySelector('#style-generation-confirmation-dialog');
  const promptCount = currentProject().settings.promptCases.length;
  dialog.innerHTML = `<form method="dialog"><h2>${evolution.batch.targetGeneration}세대를 확정하고 다음 후보를 만들까요?</h2><p>${evolution.batch.targetGeneration + 1}세대 후보 최대 ${candidateCount}개 × ${promptCount}개 Prompt = 최대 <strong>${candidateCount * promptCount}장</strong></p><p>현재 선별의 Undo는 종료됩니다.</p><div class="form-actions"><button value="cancel">취소</button><button class="primary" value="confirm">확정하고 생성</button></div></form>`;
  dialog.returnValue = 'cancel';
  return new Promise(resolve => {
    /** 확인 전에 닫은 창은 세대·이미지에 영향을 주지 않습니다. */
    function resolveContinuationConfirmation() {
      resolve(dialog.returnValue === 'confirm');
    }
    dialog.addEventListener('close', resolveContinuationConfirmation, { once: true });
    dialog.showModal();
  });
}

/** 저장한 명령 ID로만 이어가 응답 유실·Refresh 뒤에도 세대와 Job을 중복 만들지 않습니다. */
async function continueStyleEvolutionGeneration(projectIdentifier) {
  const continuation = previewState.evolutionContinuations[projectIdentifier];
  const state = currentStyleGenerationState(projectIdentifier);
  let confirmation;
  try {
    confirmation = await styleProjectApi(`/api/style-projects/${projectIdentifier}/evolution-batches/${continuation.batchIdentifier}/confirm`, { method: 'POST', body: JSON.stringify(continuation.confirmationPayload) });
  } catch (error) {
    if ([404, 409, 422].includes(error.status)) {
      delete previewState.evolutionContinuations[projectIdentifier];
      persistStyleWorkspaceSession();
    }
    throw error;
  }
  continuation.confirmedGeneration = confirmation.generationNumber;
  persistStyleWorkspaceSession();
  await refreshStyleEvolution(projectIdentifier, true);
  const evolution = state.evolution;
  if (evolution.projectRevision !== continuation.projectRevision) throw new Error('생성 설정이 바뀌었습니다. 이어 만들기를 중단하고 새 조건에서 후보를 만들어 주세요.');
  const completedNextPlan = evolution.history.find(batch => batch.operationIdentifier === continuation.nextPlanRequest?.operationIdentifier);
  if (completedNextPlan) {
    delete previewState.evolutionContinuations[projectIdentifier];
    persistStyleWorkspaceSession();
    throw new Error('다음 후보가 이미 확정 또는 취소되었습니다. 진화 화면에서 현재 세대를 확인해 주세요.');
  }
  if (!continuation.nextPlan) {
    const existing = evolution.batch?.plan;
    if (existing) {
      if (existing.operationIdentifier !== continuation.nextPlanRequest?.operationIdentifier) throw new Error('이미 다른 후보를 준비하고 있습니다. 진화 화면에서 확인해 주세요.');
      continuation.nextPlan = existing;
    } else {
      if (!evolution.canPrepare) throw new Error(`${confirmation.generationNumber}세대는 확정했습니다. ${evolution.blockers[0] || '추가 선별 뒤 이어해 주세요.'}`);
      if (!continuation.nextPlanRequest) continuation.nextPlanRequest = { operationIdentifier: newStyleClientIdentifier(), expectedProjectRevision: evolution.projectRevision, expectedVotingRevision: evolution.votingRevision, candidateCount: continuation.candidateCount };
      persistStyleWorkspaceSession();
      try {
        continuation.nextPlan = await styleProjectApi(`/api/style-projects/${projectIdentifier}/candidate-generation-plans`, { method: 'POST', body: JSON.stringify(continuation.nextPlanRequest) });
      } catch (error) {
        if ([409, 422].includes(error.status)) {
          await refreshStyleEvolution(projectIdentifier, true);
          const recoveredPlan = state.evolution.batch?.plan;
          if (recoveredPlan?.operationIdentifier === continuation.nextPlanRequest.operationIdentifier) continuation.nextPlan = recoveredPlan;
          else continuation.nextPlanRequest = null;
        }
        persistStyleWorkspaceSession();
        if (!continuation.nextPlan) throw error;
      }
    }
    persistStyleWorkspaceSession();
  }
  await submitConfirmedStyleGeneration(projectIdentifier, continuation.nextPlan);
  state.comparisonPlanIdentifier = continuation.nextPlan.planIdentifier;
  state.candidateGenerationCount = continuation.candidateCount;
  delete previewState.evolutionContinuations[projectIdentifier];
  persistStyleWorkspaceSession();
}

/** 명시적 사용자 확인으로만 자녀 생성·세대 확정·취소를 실행합니다. */
async function handleStyleEvolutionAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-evolution-action]");
  if (!button || button.disabled || styleGenerationViewState.busy) return;
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const action = button.dataset.styleEvolutionAction;
  if (action === 'dismiss-next') {
    delete previewState.evolutionContinuations[projectIdentifier];
    persistStyleWorkspaceSession();
    renderPreview(false);
    return;
  }
  const nextCountInput = document.querySelector('#style-next-candidate-count');
  if (action === 'confirm-next' && (!nextCountInput.reportValidity() || !nextCountInput.value)) return;
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
    if (action === 'confirm-next' || action === 'resume-next') {
      if (action === 'confirm-next') {
        const candidateCount = Number(state.nextCandidateCount ?? evolution.batch.childCount);
        if (!await confirmStyleEvolutionContinuation(evolution, candidateCount)) return;
        previewState.evolutionContinuations ??= {};
        previewState.evolutionContinuations[projectIdentifier] = { batchIdentifier: evolution.batch.identifier, projectRevision: evolution.projectRevision, candidateCount,
          confirmationPayload: { operationIdentifier: newStyleClientIdentifier(), expectedVotingRevision: evolution.votingRevision } };
        persistStyleWorkspaceSession();
      }
      await continueStyleEvolutionGeneration(projectIdentifier);
      previewState.screen = 'evolution';
      window.history.replaceState(null, '', '#evolution');
    } else if (action === "resume") {
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

document.addEventListener("input", handleStyleEvolutionInput);
document.addEventListener("click", handleStyleEvolutionAction);
