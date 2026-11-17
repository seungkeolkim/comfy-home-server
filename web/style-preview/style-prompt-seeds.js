"use strict";

/** 확정하지 않은 Seed는 프로젝트 설정 초안과 분리해 보관합니다. */
function stylePromptSeedDrafts(projectIdentifier) {
  previewState.promptSeedDrafts ??= {};
  previewState.promptSeedDrafts[projectIdentifier] ??= {};
  return previewState.promptSeedDrafts[projectIdentifier];
}

/** 64bit 정수 전체를 Number로 바꾸지 않고 입력 형식과 범위를 검사합니다. */
function isValidStylePromptSeed(value) {
  const seedText = String(value).trim();
  return /^\d+$/.test(seedText) && BigInt(seedText) <= 18446744073709551615n;
}

/** 여러 Prompt가 다른 Seed를 쓰면 조건 목록에 잘못된 공통값을 표시하지 않습니다. */
function stylePlanSeedSummary(plan) {
  const seeds = new Set(plan.cases.map(promptCase => String(promptCase.seed ?? plan.sampling.seed)));
  return seeds.size > 1 ? "Prompt별 Seed" : `Seed ${seeds.values().next().value ?? plan.sampling.seed}`;
}

/** Prompt별 Seed 입력과 오른쪽의 랜덤·변경 확정 버튼을 같은 행에 표시합니다. */
function stylePromptSeedEditorMarkup(promptCase, caseIndex) {
  promptCase.identifier ??= newStyleClientIdentifier();
  const projectIdentifier = previewState.screen === "create" ? "new-project" : previewState.currentProjectIdentifier;
  const draft = settingsPreviewDraft("project", projectIdentifier);
  const confirmedSeed = String(promptCase.seed ?? draft.seed);
  const inputSeed = stylePromptSeedDrafts(projectIdentifier)[promptCase.identifier] ?? confirmedSeed;
  return `<div class="prompt-seed-editor" data-prompt-seed-row="${escapeMarkup(promptCase.identifier)}">
    <label for="settings-case-seed-${caseIndex}">Seed</label><div class="prompt-seed-controls">
      <input id="settings-case-seed-${caseIndex}" type="text" inputmode="numeric" autocomplete="off" aria-describedby="settings-case-seed-error-${caseIndex}" data-prompt-seed-case="${escapeMarkup(promptCase.identifier)}" value="${escapeMarkup(inputSeed)}" />
      <button type="button" data-prompt-seed-action="random">랜덤</button>
      <button type="button" class="primary" data-prompt-seed-action="confirm" ${inputSeed === confirmedSeed ? "disabled" : ""}>변경 확정</button>
    </div><p id="settings-case-seed-error-${caseIndex}" class="error" data-prompt-seed-error role="alert"></p></div>`;
}

/** 지연된 입력도 해당 Form과 안정적인 Prompt ID에 귀속합니다. */
function stylePromptSeedContext(element) {
  const form = element.closest(".settings-form");
  if (!form || !form.isConnected) return null;
  const projectIdentifier = form.dataset.settingsProject || previewState.currentProjectIdentifier;
  const row = element.closest("[data-prompt-seed-row]");
  const input = row?.querySelector("[data-prompt-seed-case]");
  if (!input) return null;
  const draft = settingsPreviewDraft("project", projectIdentifier);
  const promptCase = draft.promptCases.find(promptCase => promptCase.identifier === input.dataset.promptSeedCase);
  return promptCase ? { form, row, input, projectIdentifier, draft, promptCase } : null;
}

/** 입력·랜덤 값은 Seed 초안에만 반영하고 확정 전 서버나 설정 본문을 바꾸지 않습니다. */
function updateStylePromptSeedInput(context) {
  const { row, input, projectIdentifier, draft, promptCase } = context;
  stylePromptSeedDrafts(projectIdentifier)[promptCase.identifier] = input.value;
  row.querySelector('[data-prompt-seed-action="confirm"]').disabled = input.value === String(promptCase.seed ?? draft.seed);
  row.querySelector("[data-prompt-seed-error]").textContent = "";
  input.removeAttribute("aria-invalid");
  persistPreviewSession();
}

/** 기본 Seed를 편집하면 개별 값이 없는 Prompt의 표시만 함께 갱신합니다. */
function updateInheritedStylePromptSeedInputs(form) {
  for (const input of form.querySelectorAll("[data-prompt-seed-case]")) {
    const context = stylePromptSeedContext(input);
    if (!context) continue;
    const { row, projectIdentifier, draft, promptCase } = context;
    const hasPendingSeed = Object.hasOwn(stylePromptSeedDrafts(projectIdentifier), promptCase.identifier);
    if (promptCase.seed == null && !hasPendingSeed) input.value = String(draft.seed);
    row.querySelector('[data-prompt-seed-action="confirm"]').disabled = input.value === String(promptCase.seed ?? draft.seed);
  }
}

/** 외부 HTTP 접속에서도 사용할 수 있는 Web Crypto로 새 64bit Seed를 뽑습니다. */
function randomStylePromptSeed(previousSeed) {
  let nextSeed;
  do {
    const randomWords = window.crypto.getRandomValues(new Uint32Array(2));
    nextSeed = ((BigInt(randomWords[0]) << 32n) | BigInt(randomWords[1])).toString();
  } while (nextSeed === previousSeed);
  return nextSeed;
}

/** 미저장 Prompt는 초안에 확정하고, 저장된 Prompt는 그 Seed만 서버에 저장합니다. */
async function confirmStylePromptSeed(context) {
  const { form, row, input, projectIdentifier, draft, promptCase } = context;
  const seedText = input.value.trim();
  if (!isValidStylePromptSeed(seedText)) {
    row.querySelector("[data-prompt-seed-error]").textContent = "Seed는 0~18446744073709551615의 정수로 입력해 주세요.";
    input.setAttribute("aria-invalid", "true");
    return;
  }
  if (PERSISTENT_STYLE_WORKSPACE && blockStyleMutationDuringVoting(projectIdentifier)) return;
  const seed = BigInt(seedText).toString();
  const project = previewState.projects.find(project => project.identifier === projectIdentifier);
  const savedPrompt = project?.settings.promptCases.find(savedPrompt => savedPrompt.identifier === promptCase.identifier);
  if (!PERSISTENT_STYLE_WORKSPACE || !savedPrompt) {
    promptCase.seed = seed;
    delete stylePromptSeedDrafts(projectIdentifier)[promptCase.identifier];
    renderPreview(false);
    updatePersistentSettingsStatus("미저장 변경");
    showToast("Seed를 프로젝트 초안에 적용했습니다.");
    return;
  }
  previewState.pendingPromptSeedSaves ??= {};
  const requestKey = `${projectIdentifier}:${promptCase.identifier}`;
  const expectedRevision = previewState.projectDraftRevisions[projectIdentifier] ?? project.revision;
  let pending = previewState.pendingPromptSeedSaves[requestKey];
  if (!pending || pending.seed !== seed || pending.expectedRevision !== expectedRevision) {
    pending = { seed, expectedRevision, operationIdentifier: newStyleClientIdentifier() };
    previewState.pendingPromptSeedSaves[requestKey] = pending;
  }
  setPersistentSettingsBusy(true, form);
  persistPreviewSession();
  try {
    const savedProject = await styleProjectApi(`/api/style-projects/${projectIdentifier}/prompt-cases/${encodeURIComponent(promptCase.identifier)}/seed`, {
      method: "PUT", body: JSON.stringify(pending),
    });
    const projectIndex = previewState.projects.findIndex(project => project.identifier === projectIdentifier);
    previewState.projects[projectIndex] = savedProject;
    promptCase.seed = savedProject.settings.promptCases.find(savedPrompt => savedPrompt.identifier === promptCase.identifier).seed;
    previewState.projectDraftRevisions[projectIdentifier] = savedProject.revision;
    delete stylePromptSeedDrafts(projectIdentifier)[promptCase.identifier];
    delete previewState.pendingPromptSeedSaves[requestKey];
    delete previewState.pendingProjectSaves[projectIdentifier];
    const generationState = currentStyleGenerationState(projectIdentifier);
    generationState.options = null;
    generationState.pendingPromptRegeneration = null;
    generationState.comparisonPlanIdentifier = null;
    renderPreview(false);
    showToast("Seed를 저장했습니다.");
  } catch (error) {
    if (row.isConnected) row.querySelector("[data-prompt-seed-error]").textContent = error.message;
    if ([404, 409, 422].includes(error.status)) delete previewState.pendingPromptSeedSaves[requestKey];
  } finally {
    setPersistentSettingsBusy(false, form);
    persistPreviewSession();
  }
}

/** Form의 일반 저장 처리와 독립적으로 Seed 입력을 보관합니다. */
function handleStylePromptSeedInput(event) {
  if (!event.target.matches("[data-prompt-seed-case]") || persistentSettingsBusy) return;
  const context = stylePromptSeedContext(event.target);
  if (context) updateStylePromptSeedInput(context);
}

/** 랜덤 버튼은 입력만 바꾸고 확정 버튼에서만 설정 변경을 수행합니다. */
function handleStylePromptSeedAction(event) {
  const button = event.target.closest("[data-prompt-seed-action]");
  if (!button || button.disabled || persistentSettingsBusy) return;
  const context = stylePromptSeedContext(button);
  if (!context) return;
  if (button.dataset.promptSeedAction === "random") {
    context.input.value = randomStylePromptSeed(context.input.value);
    updateStylePromptSeedInput(context);
  } else {
    confirmStylePromptSeed(context);
  }
}

/** Seed 입력 중 Enter는 다른 설정을 제출하지 않고 해당 값의 확정만 수행합니다. */
function handleStylePromptSeedKeydown(event) {
  if (event.key !== "Enter" || event.isComposing || !event.target.matches("[data-prompt-seed-case]")) return;
  event.preventDefault();
  const context = stylePromptSeedContext(event.target);
  if (context) context.row.querySelector('[data-prompt-seed-action="confirm"]').click();
}

document.addEventListener("input", handleStylePromptSeedInput);
document.addEventListener("click", handleStylePromptSeedAction);
document.addEventListener("keydown", handleStylePromptSeedKeydown);
