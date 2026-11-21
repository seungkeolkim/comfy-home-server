"use strict";

const styleVotingViewState = { clientIdentifier: null };
const STYLE_VOTING_SELECTION_FEEDBACK_MILLISECONDS = 170;
const STYLE_VOTING_RESULT_REVEAL_MILLISECONDS = 1000;

/** 하단 메뉴·Vote Bar의 실제 높이를 예약해 마지막 이미지와 조작부가 가려지지 않게 합니다. */
function updateStyleVotingDockLayout() {
  const footer = document.querySelector(".persistent-comparison .comparison-footer");
  const navigation = document.querySelector("#preview-mobile-navigation");
  if (!styleVotingViewState.dockObserver) {
    styleVotingViewState.dockObserver = new ResizeObserver(updateStyleVotingDockLayout);
    styleVotingViewState.dockObserver.observe(navigation);
  }
  if (footer !== styleVotingViewState.observedFooter) {
    if (styleVotingViewState.observedFooter) styleVotingViewState.dockObserver.unobserve(styleVotingViewState.observedFooter);
    if (footer) styleVotingViewState.dockObserver.observe(footer);
    styleVotingViewState.observedFooter = footer;
  }
  document.documentElement.style.setProperty("--style-mobile-navigation-height", `${Math.ceil(navigation.getBoundingClientRect().height)}px`);
  document.documentElement.style.setProperty("--style-voting-dock-height", `${Math.ceil(footer?.getBoundingClientRect().height || 0)}px`);
}

/** Browser 식별자는 로그인 정보와 별도로 보존하여 다른 기기의 Undo를 구별합니다. */
function styleVotingClientIdentifier() {
  if (styleVotingViewState.clientIdentifier) return styleVotingViewState.clientIdentifier;
  let identifier;
  try {
    identifier = localStorage.getItem("comfy-home-style-voting-client");
  } catch {}
  if (!identifier || identifier.length < 16 || identifier.length > 100) identifier = newStyleClientIdentifier();
  styleVotingViewState.clientIdentifier = identifier;
  try {
    localStorage.setItem("comfy-home-style-voting-client", identifier);
  } catch {}
  return identifier;
}

/** 이미 접수한 명령보다 오래된 Polling 응답은 화면에 덮어쓰지 않습니다. */
function applyStyleVotingResponse(projectIdentifier, selection) {
  const state = currentStyleGenerationState(projectIdentifier);
  state.votingEvaluations ??= {};
  const existing = state.votingEvaluations[selection.evaluationIdentifier];
  if (existing && existing.revision > selection.revision) return false;
  state.votingEvaluations[selection.evaluationIdentifier] = selection;
  const candidatesByIdentifier = new Map((state.results?.candidates || []).map(candidate => [candidate.identifier, candidate]));
  for (const statistics of selection.rankings) {
    const candidate = candidatesByIdentifier.get(statistics.identifier);
    if (candidate) candidate.statistics = statistics;
  }
  return true;
}

/** 여러 Prompt에 표시된 같은 A/B 조합을 모두 동일한 선택 결과로 강조합니다. */
function updateStyleVotingFeedback() {
  const feedback = currentStyleGenerationState().votingFeedback;
  const comparison = currentPersistentComparison();
  const activeFeedback = feedback?.comparison === comparison ? feedback : null;
  const container = document.querySelector(".persistent-comparison");
  if (container) container.dataset.votingFeedback = activeFeedback?.phase || "";
  for (const element of document.querySelectorAll("[data-comparison-side]")) {
    const side = element.dataset.comparisonSide;
    element.classList.toggle("comparison-picked", Boolean(activeFeedback && activeFeedback.choice === side));
    element.classList.toggle("comparison-dimmed", Boolean(activeFeedback && activeFeedback.choice !== "similar" && activeFeedback.choice !== side));
    element.classList.toggle("comparison-even", activeFeedback?.choice === "similar");
  }
  for (const button of document.querySelectorAll("[data-style-voting-choice]")) {
    button.classList.toggle("comparison-choice-selected", activeFeedback?.choice === button.dataset.styleVotingChoice);
  }
}

/** 새 화면이나 다른 평가 조건으로 이동한 경우 과거 명령의 결과 공개를 덮어 그리지 않습니다. */
function styleVotingCommandStillVisible(projectIdentifier, evaluationIdentifier) {
  return previewState.screen === "compare" && previewState.currentProjectIdentifier === projectIdentifier && currentPersistentComparison().plan?.evaluationIdentifier === evaluationIdentifier;
}

/** Pair와 이미지 URL을 고정한 채 승인된 결과만 표시해 다음 Match로 너무 빨리 넘어가지 않게 합니다. */
function renderStyleVotingFeedback(projectIdentifier, evaluationIdentifier) {
  if (!styleVotingCommandStillVisible(projectIdentifier, evaluationIdentifier)) return;
  const container = document.querySelector("#style-render-results");
  if (!container) return;
  const markup = styleComparisonResultsMarkup();
  replaceStyleResultMarkup(container, markup);
  currentStyleGenerationState(projectIdentifier).lastResultMarkup = markup;
  updateStyleVotingControls();
}

/** 투표 전 강조와 승인 후 공개를 각각 지정한 시간 동안 유지합니다. */
function waitForStyleVotingFeedback(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

/** 화면 이동은 허용하되 같은 프로젝트의 선택 처리와 생성·관리 명령은 겹치지 않게 합니다. */
function blockStyleMutationDuringVoting(projectIdentifier) {
  if (!currentStyleGenerationState(projectIdentifier).votingCommandBusy) return false;
  showToast("선택 결과를 처리하고 있습니다. 잠시 후 다시 시도해 주세요.");
  return true;
}

/** 현재 선택한 평가 조건의 Match를 조회하고 화면을 떠난 프로젝트에는 반영만 합니다. */
async function refreshStyleVoting(projectIdentifier) {
  const state = currentStyleGenerationState(projectIdentifier);
  const refreshSequence = state.resultRefreshSequence;
  const submittedPlans = (state.results?.plans || []).filter(plan => plan.jobIdentifiers.length);
  const selectedPlan = submittedPlans.find(plan => plan.planIdentifier === state.comparisonPlanIdentifier) || submittedPlans[0];
  if (!selectedPlan) {
    state.votingEvaluations = {};
    return;
  }
  const parameters = new URLSearchParams({ evaluationIdentifier: selectedPlan.evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier() });
  const selection = await styleProjectApi(`/api/style-projects/${projectIdentifier}/selection?${parameters}`);
  if (refreshSequence === state.resultRefreshSequence && !state.votingCommandBusy && !state.candidateCommandBusy) applyStyleVotingResponse(projectIdentifier, selection);
}

/** 결과 공개 중 다음 Pair의 원본을 미리 Decode해 선별 화면에서 바로 사용합니다. */
function preloadStyleVotingMatch(projectIdentifier, selection) {
  const state = currentStyleGenerationState(projectIdentifier);
  const match = selection.match;
  if (!match) return;
  const candidates = (state.results?.candidates || []).filter(candidate => [match.a, match.b].includes(candidate.identifier));
  const sources = new Set();
  for (const candidate of candidates) {
    const plan = state.results.plans.find(plan => plan.planIdentifier === candidate.planIdentifier);
    for (const promptCase of plan?.cases || []) {
      const render = candidate.renders.filter(render => render.caseIdentifier === promptCase.identifier).at(-1);
      const file = render?.files.find(file => file.is_available && !file.is_deleted);
      if (file) sources.add(styleImageUrl(file.path, true));
    }
  }
  state.preloadedVotingImages = [];
  for (const source of sources) {
    const image = new Image();
    image.src = source;
    image.decode().catch(() => {});
    state.preloadedVotingImages.push(image);
  }
}

/** 서버와 화면 모두 모든 Prompt 이미지가 준비됐을 때만 투표를 활성화합니다. */
function updateStyleVotingControls() {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "compare") return;
  updateStyleVotingDockLayout();
  const { voting, plan } = currentPersistentComparison();
  const state = currentStyleGenerationState();
  const images = [...document.querySelectorAll(".persistent-comparison .comparison-result img")];
  const imagesReady = Boolean(plan && images.length === plan.cases.length * 2 && images.every(image => image.complete && image.naturalWidth > 0));
  const busy = Boolean(state.votingCommandBusy || state.candidateCommandBusy || state.evolutionCommandBusy);
  const canVote = Boolean(voting?.match && imagesReady && !busy);
  for (const button of document.querySelectorAll("[data-style-voting-choice]")) button.disabled = !canVote;
  for (const button of document.querySelectorAll("[data-style-selection-mode]")) button.disabled = !voting || busy;
  if (busy) {
    for (const control of document.querySelectorAll(".persistent-comparison button, .persistent-comparison select, #style-comparison-plan, [data-style-evolution-action], [data-generation-action=generate-candidates]")) control.disabled = true;
  }
  const undoButton = document.querySelector("[data-style-voting-action=undo]");
  if (undoButton) {
    undoButton.disabled = !voting?.canUndo || busy;
    undoButton.title = voting?.undoUnavailableReason || "최근 30개 선택 중 마지막 선택을 되돌립니다.";
  }
  const status = document.querySelector("#style-voting-status");
  if (status) {
    let message = "모든 이미지가 준비된 조합이 두 개 이상이면 선별을 시작합니다.";
    if (voting?.match && !imagesReady) message = images.some(image => image.complete && !image.naturalWidth) ? "이미지를 불러오지 못했습니다. 새로고침한 뒤 다시 확인해 주세요." : "모든 Prompt의 이미지를 불러오는 중입니다.";
    else if (voting?.match?.kind === "select") {
      const placement = voting.automaticPlacement;
      message = placement ? `자녀 선별 · ${placement.comparingNewcomers ? '승격 경계의 자녀끼리 비교' : '상위 30% 부모와 비교'} · 선별 완료 ${placement.completedCount}/${placement.candidateCount}` : "자녀 평가 중";
    }
    else if (voting?.activeEvolutionIdentifier && !voting.match) message = voting.automaticPlacement?.completedCount === voting.automaticPlacement?.candidateCount ? "자동 선별 완료 · 세대를 확정할 수 있습니다." : "비교할 이미지가 준비되면 자동 선별을 이어갑니다.";
    else if (voting?.match?.kind === "place") message = "새 조합 평가 중";
    else if (voting?.match?.kind === "tie") message = "상위 30% 경계의 동점 조합 비교";
    else if (voting?.match?.kind === "top") message = "상위 30% 조합끼리 비교";
    else if (voting?.match) message = voting.mode === "league" ? "전체 리그 · 기존 조합끼리 비교" : "전체 리그";
    if (!voting?.match && voting?.mode !== "auto" && voting?.mode) message = "이 모드에서 비교할 기존 조합이 두 개 이상 필요합니다. 자동 모드에서 신규 조합 선별을 진행할 수 있습니다.";
    if (state.votingFeedback?.phase === "selecting") message = "선택한 결과를 저장하고 있습니다.";
    if (state.votingFeedback?.phase === "reveal") message = state.votingFeedback.choice === "similar" ? "비슷함으로 기록했습니다. 잠시 후 다음 비교로 이동합니다." : `${state.votingFeedback.choice.toUpperCase()}를 선택했습니다. 잠시 후 다음 비교로 이동합니다.`;
    status.textContent = state.error || message;
  }
  updateStyleVotingFeedback();
}

/** 연타를 막고 표시한 Revision·Token으로만 Vote·Undo·Pair 변경을 실행합니다. */
async function executeStyleVotingAction(action, additionalFields = {}) {
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const comparison = currentPersistentComparison();
  const { voting } = comparison;
  if (!voting || state.votingCommandBusy || state.candidateCommandBusy || state.evolutionCommandBusy) return;
  if (action === "vote" && (!voting.match || !["a", "b", "similar"].includes(additionalFields.choice))) return;
  if (action === "undo" && !voting.canUndo) return;
  if (action === "mode" && (voting.mode || "auto") === additionalFields.mode) return;
  state.votingCommandBusy = true;
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.evolutionRefreshSequence = (state.evolutionRefreshSequence || 0) + 1;
  state.error = "";
  let responseApplied = false;
  if (action === "vote") state.votingFeedback = { comparison: structuredClone(comparison), phase: "selecting", choice: additionalFields.choice, rankings: [] };
  updateStyleVotingControls();
  try {
    const payload = {
      evaluationIdentifier: voting.evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier(),
      operationIdentifier: newStyleClientIdentifier(), expectedRevision: voting.revision, ...additionalFields,
    };
    if (action === "vote") payload.matchToken = voting.match.token;
    if (action === "undo") payload.eventIdentifier = voting.undoEventIdentifier;
    const route = { vote: "votes", undo: "undo", pair: "selection-pair", mode: "selection-mode" }[action];
    if (action === "vote") await waitForStyleVotingFeedback(STYLE_VOTING_SELECTION_FEEDBACK_MILLISECONDS);
    const response = await styleProjectApi(`/api/style-projects/${projectIdentifier}/${route}`, { method: "POST", body: JSON.stringify(payload) });
    const applied = applyStyleVotingResponse(projectIdentifier, response);
    responseApplied = applied;
    if (applied) preloadStyleVotingMatch(projectIdentifier, response);
    if (action === "vote" && applied) {
      state.votingFeedback.phase = "reveal";
      state.votingFeedback.rankings = structuredClone(response.rankings);
      renderStyleVotingFeedback(projectIdentifier, voting.evaluationIdentifier);
      await waitForStyleVotingFeedback(STYLE_VOTING_RESULT_REVEAL_MILLISECONDS);
    }
    if (action !== "pair") {
      if (action === "undo") showToast("되돌렸습니다.");
      if (action === "vote" && styleVotingCommandStillVisible(projectIdentifier, voting.evaluationIdentifier)) previewState.visibleSide = "a";
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.votingFeedback = null;
    state.votingCommandBusy = false;
    state.resultRefreshNotBefore = Date.now() + 2000;
    // 실패 응답은 같은 비교 상태여도 잠근 버튼을 복구하도록 다시 그립니다.
    if (!responseApplied) state.lastResultMarkup = "";
    if (styleVotingCommandStillVisible(projectIdentifier, voting.evaluationIdentifier)) {
      renderCurrentStyleGenerationResults(projectIdentifier);
      updateStyleVotingControls();
      if (["vote", "undo"].includes(action) && !state.error) document.querySelector(".candidate-headings")?.scrollIntoView({ block: "start" });
    }
    if (!responseApplied) {
      try {
        await refreshStyleGenerationResults(projectIdentifier);
      } catch (error) {
        state.error ||= error.message;
      }
    } else {
      refreshStyleEvolution(projectIdentifier).catch(error => { state.error ||= error.message; });
    }
    scheduleStyleGenerationRefresh();
    state.preloadedVotingImages = [];
  }
}

/** 리뷰한 A/B·비슷함·Undo 버튼을 실제 서버 명령에 연결합니다. */
function handleStyleVotingAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-voting-choice], [data-style-voting-action], [data-style-selection-mode]");
  if (!button || button.disabled) return;
  if (button.dataset.styleVotingChoice) executeStyleVotingAction("vote", { choice: button.dataset.styleVotingChoice });
  else if (button.dataset.styleVotingAction === "undo") executeStyleVotingAction("undo");
  else if (button.dataset.styleSelectionMode) executeStyleVotingAction("mode", { mode: button.dataset.styleSelectionMode });
}

/** 입력·IME·열린 Viewer의 단축키를 보존하고 활성화된 선별 버튼에만 Keyboard 명령을 전달합니다. */
function handleStyleVotingKeyboard(event) {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "compare" || event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  if (document.querySelector("dialog[open]")) return;
  const target = event.target;
  if (target.closest?.("input, textarea, select, [contenteditable]:not([contenteditable=false]), [role=textbox], [role=combobox]")) return;
  const choices = { ArrowLeft: "a", ArrowRight: "b", Numpad4: "a", Numpad6: "b", Enter: "similar" };
  const choice = choices[event.code] || choices[event.key];
  const undo = event.key === "Backspace";
  if (!choice && !undo) return;
  const focusedControl = target.closest?.("button, a, summary, [role=button]");
  if ((event.key === "Enter" || event.code === "Enter") && focusedControl) return;
  const button = document.querySelector(undo ? "[data-style-voting-action=undo]" : `[data-style-voting-choice=${choice}]`);
  event.preventDefault();
  if (!button || button.disabled) return;
  if (undo) executeStyleVotingAction("undo");
  else executeStyleVotingAction("vote", { choice });
}

/** 새 Match의 실제 이미지 로드가 끝날 때 투표 가능 상태를 다시 확인합니다. */
function handleStyleComparisonImageLoad(event) {
  if (event.target.matches?.(".persistent-comparison .comparison-result img")) updateStyleVotingControls();
}

document.addEventListener("click", handleStyleVotingAction);
document.addEventListener("keydown", handleStyleVotingKeyboard);
document.addEventListener("load", handleStyleComparisonImageLoad, true);
document.addEventListener("error", handleStyleComparisonImageLoad, true);
