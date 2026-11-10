"use strict";

const styleVotingViewState = { clientIdentifier: null };

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
  if (existing && existing.revision > selection.revision) return;
  state.votingEvaluations[selection.evaluationIdentifier] = selection;
  for (const statistics of selection.rankings) {
    const candidate = state.results?.candidates.find(candidate => candidate.identifier === statistics.identifier);
    if (candidate) candidate.statistics = statistics;
  }
}

/** 현재 선택한 평가 조건의 Match를 조회하고 화면을 떠난 프로젝트에는 반영만 합니다. */
async function refreshStyleVoting(projectIdentifier) {
  const state = currentStyleGenerationState(projectIdentifier);
  const submittedPlans = (state.results?.plans || []).filter(plan => plan.jobIdentifiers.length);
  const selectedPlan = submittedPlans.find(plan => plan.planIdentifier === state.comparisonPlanIdentifier) || submittedPlans[0];
  if (!selectedPlan) return;
  const parameters = new URLSearchParams({ evaluationIdentifier: selectedPlan.evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier() });
  const selection = await styleProjectApi(`/api/style-projects/${projectIdentifier}/selection?${parameters}`);
  applyStyleVotingResponse(projectIdentifier, selection);
}

/** 서버와 화면 모두 모든 Prompt 이미지가 준비됐을 때만 투표를 활성화합니다. */
function updateStyleVotingControls() {
  if (!PERSISTENT_STYLE_WORKSPACE || previewState.screen !== "compare") return;
  updateStyleVotingDockLayout();
  const { voting, plan } = currentPersistentComparison();
  const state = currentStyleGenerationState();
  const images = [...document.querySelectorAll(".persistent-comparison .comparison-result img")];
  const imagesReady = Boolean(plan && images.length === plan.cases.length * 2 && images.every(image => image.complete && image.naturalWidth > 0));
  const canVote = Boolean(voting?.match && imagesReady && !state.votingCommandBusy && !state.candidateCommandBusy);
  for (const button of document.querySelectorAll("[data-style-voting-choice]")) button.disabled = !canVote;
  if (state.votingCommandBusy) {
    for (const picker of document.querySelectorAll("[data-comparison-candidate], #style-comparison-plan")) picker.disabled = true;
  }
  const undoButton = document.querySelector("[data-style-voting-action=undo]");
  if (undoButton) {
    undoButton.disabled = !voting?.canUndo || Boolean(state.votingCommandBusy);
    undoButton.title = voting?.undoUnavailableReason || "최근 30개 선택 중 마지막 선택을 되돌립니다.";
  }
  const status = document.querySelector("#style-voting-status");
  if (status) {
    let message = "모든 이미지가 준비된 조합이 두 개 이상이면 선별을 시작합니다.";
    if (voting?.match && !imagesReady) message = images.some(image => image.complete && !image.naturalWidth) ? "이미지를 불러오지 못했습니다. 새로고침한 뒤 다시 확인해 주세요." : "모든 Prompt의 이미지를 불러오는 중입니다.";
    else if (voting?.match?.kind === "select") message = "자녀를 부모와 비교해 배치합니다. 부모의 Elo·전적은 유지합니다. 비슷함도 자녀 배치에 반영합니다.";
    else if (voting?.activeEvolutionIdentifier && !voting.match) message = "준비된 자녀의 선별을 마쳤습니다. 위에서 생성 상태와 세대 확정 가능 여부를 확인해 주세요.";
    else if (voting?.match?.kind === "place") message = "새 조합을 기존 순위에 배치합니다. 기존 조합의 점수는 유지합니다.";
    else if (voting?.match) message = "모든 Prompt를 함께 보고 조합 하나를 선택해 주세요. 비슷함은 Elo를 바꾸지 않습니다.";
    status.textContent = state.error || message;
  }
}

/** 연타를 막고 표시한 Revision·Token으로만 Vote·Undo·Pair 변경을 실행합니다. */
async function executeStyleVotingAction(action, additionalFields = {}) {
  const projectIdentifier = previewState.currentProjectIdentifier;
  const state = currentStyleGenerationState(projectIdentifier);
  const { voting } = currentPersistentComparison();
  if (!voting || state.votingCommandBusy) return;
  state.votingCommandBusy = true;
  state.resultRefreshSequence = (state.resultRefreshSequence || 0) + 1;
  state.error = "";
  const contentContainer = document.querySelector("#preview-content");
  contentContainer.inert = true;
  updateStyleVotingControls();
  try {
    const payload = {
      evaluationIdentifier: voting.evaluationIdentifier, clientIdentifier: styleVotingClientIdentifier(),
      operationIdentifier: newStyleClientIdentifier(), expectedRevision: voting.revision, ...additionalFields,
    };
    if (action === "vote") payload.matchToken = voting.match.token;
    if (action === "undo") payload.eventIdentifier = voting.undoEventIdentifier;
    const route = { vote: "votes", undo: "undo", pair: "selection-pair" }[action];
    const response = await styleProjectApi(`/api/style-projects/${projectIdentifier}/${route}`, { method: "POST", body: JSON.stringify(payload) });
    applyStyleVotingResponse(projectIdentifier, response);
    if (action !== "pair") {
      showToast(action === "undo" ? "마지막 선택과 점수·A/B 위치를 되돌렸습니다." : additionalFields.choice === "similar" ? (voting.match?.kind === "select" ? "비슷함을 자녀 배치에 반영했습니다." : "비슷함을 기록했습니다.") : "선택과 Elo를 저장했습니다.");
      if (action === "vote") previewState.visibleSide = "a";
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.votingCommandBusy = false;
    contentContainer.inert = false;
    try {
      await refreshStyleGenerationResults(projectIdentifier);
    } catch (error) {
      state.error ||= error.message;
    }
    if (projectIdentifier === previewState.currentProjectIdentifier) {
      renderPreview(false);
      updateStyleVotingControls();
      if (action !== "pair" && !state.error) document.querySelector(".candidate-headings")?.scrollIntoView({ block: "start" });
    }
  }
}

/** 리뷰한 A/B·비슷함·Undo 버튼을 실제 서버 명령에 연결합니다. */
function handleStyleVotingAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-style-voting-choice], [data-style-voting-action]");
  if (!button || button.disabled) return;
  if (button.dataset.styleVotingChoice) executeStyleVotingAction("vote", { choice: button.dataset.styleVotingChoice });
  else if (button.dataset.styleVotingAction === "undo") executeStyleVotingAction("undo");
}

/** 새 Match의 실제 이미지 로드가 끝날 때 투표 가능 상태를 다시 확인합니다. */
function handleStyleComparisonImageLoad(event) {
  if (event.target.matches?.(".persistent-comparison .comparison-result img")) updateStyleVotingControls();
}

document.addEventListener("click", handleStyleVotingAction);
document.addEventListener("load", handleStyleComparisonImageLoad, true);
document.addEventListener("error", handleStyleComparisonImageLoad, true);
