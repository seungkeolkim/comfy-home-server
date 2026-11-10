"use strict";

/** 같은 평가 조건의 후보들을 서버가 고른 현재 A/B 위치에 표시합니다. */
function currentPersistentComparison() {
  const state = currentStyleGenerationState();
  const results = state.results;
  const submittedPlans = (results?.plans || []).filter(plan => results.candidates.some(candidate => candidate.planIdentifier === plan.planIdentifier && candidate.renders.length));
  const selectedPlan = submittedPlans.find(plan => plan.planIdentifier === state.comparisonPlanIdentifier) || submittedPlans[0];
  const plans = submittedPlans.filter((plan, index) => submittedPlans.findIndex(item => item.evaluationIdentifier === plan.evaluationIdentifier) === index);
  const plan = plans.find(plan => plan.evaluationIdentifier === selectedPlan?.evaluationIdentifier);
  const allCandidates = plan ? results.candidates.filter(candidate => candidate.evaluationIdentifier === plan.evaluationIdentifier && candidate.renders.length && ["active", "evolving"].includes(candidate.lifecycle)) : [];
  const voting = state.votingEvaluations?.[plan?.evaluationIdentifier];
  const selectedIdentifiers = voting?.match ? [voting.match.a, voting.match.b] : allCandidates.slice(0, 2).map(candidate => candidate.identifier);
  const candidates = selectedIdentifiers.map(identifier => allCandidates.find(candidate => candidate.identifier === identifier)).filter(Boolean);
  return { plan, plans, candidates, allCandidates, voting };
}

/** 파일 네이밍 규칙의 세대·조합 이름을 화면에서도 재사용합니다. */
function persistentCandidateLabel(candidate) {
  return candidate.displayName || `세대${String(candidate.generationNumber || 1).padStart(3, "0")}-조합${String(candidate.combinationNumber || 1).padStart(2, "0")}`;
}

/** 일반 비교는 같은 평가 상태의 준비된 후보 중 A/B를 직접 바꿀 수 있습니다. */
function persistentComparisonPairPickerMarkup(comparison) {
  if (comparison.allCandidates.length <= 2) return "";
  const voting = comparison.voting;
  const fresh = Boolean(voting?.match?.metadata.fresh);
  const eligibleCandidates = comparison.allCandidates.filter(candidate => voting?.readyCandidateIdentifiers.includes(candidate.identifier) && Boolean(candidate.statistics?.rated) !== fresh);
  const disabled = previewState.blind || voting?.match?.kind !== "league";
  return `<div class="comparison-pair-picker">${["A", "B"].map((side, index) => `<label>${side} 위치<select data-comparison-candidate="${index}" ${disabled ? "disabled" : ""}>${comparison.allCandidates.map(candidate => `<option value="${candidate.identifier}" ${candidate.identifier === comparison.candidates[index]?.identifier ? "selected" : ""} ${candidate.identifier === comparison.candidates[1 - index]?.identifier || !eligibleCandidates.includes(candidate) ? "disabled" : ""}>${previewState.blind ? "그림체 숨김" : escapeMarkup(persistentCandidateLabel(candidate))}</option>`).join("")}</select></label>`).join("")}</div>`;
}

/** 변경 가능한 Prompt 표시 이름은 Case ID로 조회하고 생성 당시 내용은 보존합니다. */
function persistentPromptCaseName(promptCase) {
  return currentProject().settings.promptCases.find(currentCase => currentCase.identifier === promptCase.identifier)?.name || promptCase.name;
}

/** 검토한 선별 화면의 진입점과 결과 Polling 영역을 유지합니다. */
function renderPersistentComparison() {
  const project = currentProject();
  return `${styleEvolutionContainerMarkup()}<div class="page-heading comparison-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>어느 쪽 그림체가 더 좋나요?</h1><p class="muted">같은 두 조합을 여러 Prompt에서 확인해 보세요.</p></div><button data-style-voting-action="undo" disabled>↶ 되돌리기</button></div><div id="style-render-results">${initialStyleResultsMarkup(currentStyleGenerationState().results)}</div>`;
}

/** 실제 이미지로 Toolbar와 모든 Prompt를 스크롤해 보는 비교 화면을 구성합니다. */
function styleComparisonResultsMarkup() {
  const comparison = currentPersistentComparison();
  const { plan, plans, candidates, allCandidates, voting } = comparison;
  if (!plan) return '<section class="panel empty-state"><p>아직 생성한 이미지가 없습니다.</p><button data-action="navigate" data-screen="generation">이미지 생성</button></section>';
  if (voting?.activeEvolutionIdentifier && !voting.match) return '<section class="panel empty-state"><h2>다음 자녀 선별 대기</h2><p id="style-voting-status" role="status">준비된 자녀의 선별을 마쳤습니다. 위에서 생성 상태와 세대 확정 가능 여부를 확인해 주세요.</p></section>';
  const planSelector = plans.length > 1 ? `<label for="style-comparison-plan">비교할 평가 조건</label><select id="style-comparison-plan">${plans.map((item, index) => `<option value="${item.planIdentifier}" ${item.planIdentifier === plan.planIdentifier ? "selected" : ""}>${item.evaluationIdentifier === currentProject().evaluationIdentifier ? "현재 조건" : "이전 조건"} · Seed ${item.sampling.seed}</option>`).join("")}</select>` : "";
  const headings = ["a", "b"].map((side, index) => `<div class="candidate-name ${side === previewState.visibleSide ? "visible-side" : ""}"><span class="candidate-letter">${side.toUpperCase()}</span><span>${previewState.blind ? "그림체 숨김" : candidates[index] ? escapeMarkup(persistentCandidateLabel(candidates[index])) : "아직 생성하지 않음"}</span></div>`).join("");
  return `<div class="persistent-comparison">${planSelector}${persistentComparisonPairPickerMarkup(comparison)}<div class="condition-strip"><span>${allCandidates.length}개 조합</span><span>· ${plan.cases.length}개 Prompt</span><span>· 공통 Seed ${plan.sampling.seed}</span></div><div class="toolbar"><div class="toolbar-group"><button data-action="toggle-blind" aria-pressed="${previewState.blind}">◉ Blind ${previewState.blind ? "켜짐" : "꺼짐"}</button><button data-action="open-differences" ${previewState.blind || candidates.length !== 2 ? "disabled" : ""}>조합 차이 보기 ↗</button><button data-action="navigate" data-screen="candidates">그림체 보기 →</button>${candidates.length === 2 ? `<button class="danger" data-style-candidate-action="delete" data-candidates="${candidates.map(candidate => candidate.identifier).join(",")}" ${currentStyleGenerationState().evolution?.batch ? "disabled" : ""}>둘 다 폐기</button>` : ""}</div></div><div class="mobile-case-controls mobile-only"><button data-action="image-layout" data-layout="${previewState.singleImage ? "pair" : "single"}">${previewState.singleImage ? "나란히" : "한 장씩"}</button>${previewState.singleImage ? `<button data-action="switch-side">${previewState.visibleSide === "a" ? "B" : "A"} 보기</button>` : ""}</div><div class="comparison-columns candidate-headings ${previewState.singleImage ? "single-image" : ""}">${headings}</div><div class="comparison-columns comparison-management">${candidates.map(candidate => `<div>${styleCandidateRankingMarkup(candidate)}<div class="form-actions">${styleCandidateManagementButtonsMarkup(candidate)}</div></div>`).join("")}</div>${plan.cases.map((promptCase, index) => persistentComparisonCaseMarkup(promptCase, index, candidates)).join("")}<footer class="comparison-footer"><div class="vote-buttons"><button class="vote-choice vote-choice-a" data-style-voting-choice="a" disabled>A가 더 좋아요</button><button data-style-voting-choice="similar" disabled>비슷함</button><button class="vote-choice vote-choice-b" data-style-voting-choice="b" disabled>B가 더 좋아요</button></div><p id="style-voting-status" class="vote-caption" role="status">${voting?.match?.kind === "place" ? "새 조합을 기존 순위에 배치합니다. 기존 조합의 점수는 유지합니다." : "모든 Prompt를 함께 보고 조합 하나를 선택해 주세요."}</p></footer></div>`;
}

/** 같은 Case의 최신 Render를 A/B 위치 그대로 표시하고 이름 편집을 제공합니다. */
function persistentComparisonCaseMarkup(promptCase, caseIndex, candidates) {
  const caseName = persistentPromptCaseName(promptCase);
  const imageColumns = ["a", "b"].map((side, index) => {
    const candidate = candidates[index];
    const render = candidate?.renders.filter(item => item.caseIdentifier === promptCase.identifier).at(-1);
    const file = render?.files.find(item => item.is_available && !item.is_deleted);
    const content = file ? `<button class="image-button" data-generation-action="enlarge" data-path="${escapeMarkup(file.path)}" aria-label="${escapeMarkup(caseName)} ${side.toUpperCase()} 이미지 확대"><img src="${styleImageUrl(file.path)}" alt="${escapeMarkup(caseName)} · ${side.toUpperCase()}" /></button>` : `<div class="empty-state">${escapeMarkup(render ? styleRenderStatusLabel(render.status) : "아직 생성하지 않음")}</div>`;
    return `<div class="comparison-result ${side === previewState.visibleSide ? "visible-side" : ""}">${content}${render?.error ? `<p class="error">${escapeMarkup(render.error)}</p>` : ""}</div>`;
  }).join("");
  return `<section class="case-section"><div class="case-heading"><span class="case-number">PROMPT ${String(caseIndex + 1).padStart(2, "0")}</span><strong>${escapeMarkup(caseName)}</strong><button class="quiet small" data-style-comparison-action="rename-prompt" data-case="${escapeMarkup(promptCase.identifier)}">이름 변경</button></div><div class="comparison-columns ${previewState.singleImage ? "single-image" : ""}">${imageColumns}</div></section>`;
}

/** 생성 중·실패·접수 미확인을 구분한 상태를 같은 문구로 표시합니다. */
function styleRenderStatusLabel(status) {
  return { submitting: "제출 준비 중", pending: "대기 중", running: "생성 중", completed: "이미지 없음", failed: "실패", stopped: "중단·접수 미확인", cancelled: "취소됨", cancelling: "취소 중" }[status] || status;
}

/** 실제 후보에 들어 있는 작가·LoRA를 STR만으로 비교합니다. */
function persistentComponentDifferences() {
  const { candidates } = currentPersistentComparison();
  const firstComponents = new Map((candidates[0]?.components || []).map(component => [component.identifier, component.strength]));
  const secondComponents = new Map((candidates[1]?.components || []).map(component => [component.identifier, component.strength]));
  return [...new Set([...firstComponents.keys(), ...secondComponents.keys()])].map(identifier => {
    const firstStrength = firstComponents.get(identifier);
    const secondStrength = secondComponents.get(identifier);
    const differenceKind = !firstComponents.has(identifier) ? "B에만 있음" : !secondComponents.has(identifier) ? "A에만 있음" : firstStrength === secondStrength ? "STR 동일" : "강도 변경";
    return { identifier, name: identifier.replace(/^(artist:|lora:)/, ""), kind: identifier.startsWith("artist:") ? "작가" : "LoRA", firstStrength, secondStrength, differenceKind };
  });
}

/** 검토한 차이 Dialog를 실제 성분과 프로젝트별 향후 제외 설정에 연결합니다. */
function renderPersistentComponentDialog() {
  const differences = persistentComponentDifferences();
  const changedComponents = differences.filter(component => component.differenceKind !== "STR 동일");
  const sameComponents = differences.filter(component => component.differenceKind === "STR 동일");
  componentDialog.innerHTML = `<div class="dialog-heading"><h2 id="component-dialog-title">어떤 성분이 다른가요?</h2><button data-action="close-differences" aria-label="조합 차이 닫기">✕</button></div><p class="form-note">A/B의 작가·LoRA와 STR 차이입니다. 특정 성분이 결과의 원인이라고 확정하지 않습니다.</p>${changedComponents.map(persistentComponentDifferenceRow).join("")}<details><summary>STR이 같은 성분 ${sameComponents.length}개</summary>${sameComponents.map(persistentComponentDifferenceRow).join("")}</details><p class="form-note">제외는 현재 프로젝트의 향후 새 조합에만 적용합니다. 기존 결과는 유지합니다.</p><p id="style-comparison-error" class="error" role="alert"></p>`;
}

/** 누락된 성분과 STR 0을 구분하고 안전하게 이름을 출력합니다. */
function persistentComponentDifferenceRow(component) {
  const enabled = currentProject().settings.componentPolicies[component.identifier]?.enabled;
  return `<section class="difference-row"><span class="difference-kind">${escapeMarkup(component.differenceKind)} · ${component.kind}</span><strong>${escapeMarkup(component.name)}</strong><div class="difference-values"><div><small>A</small>${persistentStrengthLabel(component.firstStrength)}</div><div><small>B</small>${persistentStrengthLabel(component.secondStrength)}</div></div><button data-style-comparison-action="toggle-component" data-component="${escapeMarkup(component.identifier)}" aria-pressed="${!enabled}">${enabled ? "앞으로 새 조합에서 제외" : "제외 설정됨 · 다시 허용"}</button></section>`;
}

/** 포함되지 않은 성분과 포함된 STR 0을 다른 값으로 표시합니다. */
function persistentStrengthLabel(strength) {
  return strength === undefined ? "포함되지 않음" : `STR ${strength}`;
}

/** 이름 편집은 별도 Dialog에서 수행해 결과 Polling이 작성 중 입력을 지우지 못하게 합니다. */
function openPersistentPromptNameEditor(caseIdentifier) {
  const promptCase = currentProject().settings.promptCases.find(item => item.identifier === caseIdentifier);
  componentDialog.innerHTML = `<div class="dialog-heading"><h2 id="component-dialog-title">Prompt 이름 변경</h2><button data-action="close-differences" aria-label="이름 변경 닫기">✕</button></div><form id="style-prompt-name-form" data-case="${escapeMarkup(caseIdentifier)}"><label for="style-prompt-display-name">Prompt 이름</label><input id="style-prompt-display-name" name="name" required maxlength="60" value="${escapeMarkup(promptCase.name)}" /><p class="form-note">표시 이름만 변경합니다. Prompt 내용과 기존 이미지는 그대로 유지합니다.</p><p id="style-comparison-error" class="error" role="alert"></p><button class="primary" type="submit">이름 저장</button></form>`;
  componentDialog.showModal();
  document.querySelector("#style-prompt-display-name").focus();
}

/** 서버의 표시 설정 변경을 반영하되 프로젝트 설정의 다른 미저장 초안은 보존합니다. */
function applyPersistentComparisonSetting(savedProject, previousProject, changedCase, changedComponent) {
  savedProject.candidateCount = previousProject.candidateCount;
  previewState.projects[previewState.projects.findIndex(project => project.identifier === savedProject.identifier)] = savedProject;
  const draft = previewState.settingsDrafts.projects[savedProject.identifier];
  if (draft) {
    if (changedCase) {
      const draftCase = draft.promptCases.find(promptCase => promptCase.identifier === changedCase);
      const previousCase = previousProject.settings.promptCases.find(promptCase => promptCase.identifier === changedCase);
      if (draftCase?.name === previousCase.name) draftCase.name = savedProject.settings.promptCases.find(promptCase => promptCase.identifier === changedCase).name;
    }
    if (changedComponent && draft.componentPolicies[changedComponent]?.enabled === previousProject.settings.componentPolicies[changedComponent]?.enabled) draft.componentPolicies[changedComponent].enabled = savedProject.settings.componentPolicies[changedComponent].enabled;
    if (previewState.projectDraftRevisions[savedProject.identifier] === previousProject.revision) previewState.projectDraftRevisions[savedProject.identifier] = savedProject.revision;
  }
  persistStyleWorkspaceSession();
}

/** 현재 프로젝트의 이름 또는 성분 허용 여부 한 항목만 명시적으로 저장합니다. */
async function savePersistentComparisonSetting({ caseIdentifier, name, componentIdentifier }) {
  if (persistentSettingsBusy) return;
  const project = currentProject();
  const settings = structuredClone(project.settings);
  if (caseIdentifier) settings.promptCases.find(promptCase => promptCase.identifier === caseIdentifier).name = name.trim();
  if (componentIdentifier) settings.componentPolicies[componentIdentifier].enabled = !settings.componentPolicies[componentIdentifier].enabled;
  setPersistentSettingsBusy(true, componentDialog);
  try {
    const savedProject = await styleProjectApi(`/api/style-projects/${project.identifier}`, { method: "PUT", body: JSON.stringify({ settings, expectedRevision: project.revision, operationIdentifier: newStyleClientIdentifier() }) });
    applyPersistentComparisonSetting(savedProject, project, caseIdentifier, componentIdentifier);
    if (componentIdentifier) renderPersistentComponentDialog();
    else componentDialog.close();
    renderPreview(false);
    showToast(componentIdentifier ? "이 프로젝트의 향후 사용 설정을 저장했습니다." : "Prompt 이름을 저장했습니다.");
  } catch (error) {
    document.querySelector("#style-comparison-error").textContent = error.message;
  } finally {
    setPersistentSettingsBusy(false, componentDialog);
  }
}

/** 실제 데이터의 차이·표시 이름 조작만 처리하고 투표를 임의로 구현하지 않습니다. */
function handlePersistentComparisonAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE || persistentSettingsBusy) return;
  const button = event.target.closest("[data-style-comparison-action]");
  if (!button || button.disabled) return;
  if (button.dataset.styleComparisonAction === "rename-prompt") openPersistentPromptNameEditor(button.dataset.case);
  if (button.dataset.styleComparisonAction === "toggle-component") savePersistentComparisonSetting({ componentIdentifier: button.dataset.component });
}

/** Case 이름 저장이 일반 Form 제출이나 이미지 생성으로 이어지지 않게 합니다. */
function handlePersistentPromptNameSubmit(event) {
  if (event.target.id !== "style-prompt-name-form") return;
  event.preventDefault();
  savePersistentComparisonSetting({ caseIdentifier: event.target.dataset.case, name: event.target.elements.name.value });
}

/** 생성 묶음 전환은 같은 계획 안의 A/B만 바꾸고 기존 결과를 수정하지 않습니다. */
function handlePersistentComparisonPlanChange(event) {
  if (event.target.dataset.comparisonCandidate !== undefined) {
    const { candidates } = currentPersistentComparison();
    const selectedIndex = Number(event.target.dataset.comparisonCandidate);
    if (previewState.blind || !candidates[1 - selectedIndex]) return;
    const identifiers = candidates.map(candidate => candidate.identifier);
    identifiers[selectedIndex] = event.target.value;
    executeStyleVotingAction("pair", { firstCandidateIdentifier: identifiers[0], secondCandidateIdentifier: identifiers[1] });
    return;
  }
  if (event.target.id !== "style-comparison-plan") return;
  currentStyleGenerationState().comparisonPlanIdentifier = event.target.value;
  previewState.activeCaseIndex = 0;
  renderPreview(false);
}

document.addEventListener("click", handlePersistentComparisonAction);
document.addEventListener("submit", handlePersistentPromptNameSubmit);
document.addEventListener("change", handlePersistentComparisonPlanChange);
