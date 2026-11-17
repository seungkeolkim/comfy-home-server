"use strict";

const styleProjectForkDialogState = { sourceProjectIdentifier: null, options: null, busy: false, loadingSequence: 0 };

/** Fork 출처는 소유 프로젝트 이름과 출발 세대만 짧게 표시합니다. */
function styleProjectForkSourceMarkup(project) {
  if (!project.forkSource) return "";
  const source = project.forkSource;
  return `<p class="project-fork-source">${escapeMarkup(source.projectName)} · ${source.generationNumber}세대에서 Fork</p>`;
}

/** 선택지의 긴 Prompt 본문 대신 이름과 사용 성분 수를 표시합니다. */
function updateStyleProjectForkSummary() {
  const options = styleProjectForkDialogState.options;
  if (!options) return;
  const selectedIdentifier = document.querySelector("#style-project-fork-source").value;
  const selected = options.snapshots.find(snapshot => snapshot.identifier === selectedIdentifier);
  const includeStatistics = document.querySelector("#style-project-fork-statistics").checked;
  const summary = document.querySelector("#style-project-fork-summary");
  summary.textContent = selected
    ? `${selected.promptNames.join(" · ")} / 작가 ${selected.enabledArtistCount}개 · LoRA ${selected.enabledLoraCount}개 / ${includeStatistics ? "선호도·승패 포함" : "설정만 복사"}`
    : "선택한 세대를 다시 확인해 주세요.";
}

/** 현재 선택·이름 초안을 보존하면서 서버의 Fork 기준 목록만 갱신합니다. */
async function loadStyleProjectForkOptions() {
  const dialog = document.querySelector("#style-project-fork-dialog");
  const sequence = ++styleProjectForkDialogState.loadingSequence;
  const selectedIdentifier = dialog.querySelector("#style-project-fork-source").value;
  const submitButton = dialog.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  const options = await styleProjectApi(`/api/style-projects/${styleProjectForkDialogState.sourceProjectIdentifier}/fork-options`);
  if (sequence !== styleProjectForkDialogState.loadingSequence || !dialog.open) return;
  styleProjectForkDialogState.options = options;
  const select = dialog.querySelector("#style-project-fork-source");
  select.innerHTML = options.snapshots.map(snapshot => {
    const savedAt = new Date(snapshot.updatedAt).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
    return `<option value="${snapshot.identifier}">${snapshot.generationNumber}세대 · ${escapeMarkup(savedAt)}</option>`;
  }).join("");
  select.value = options.snapshots.some(snapshot => snapshot.identifier === selectedIdentifier) ? selectedIdentifier : options.currentSnapshotIdentifier;
  select.disabled = false;
  submitButton.disabled = options.snapshots.length === 0;
  updateStyleProjectForkSummary();
}

/** 원본은 바꾸지 않고 새 프로젝트 이름·출발 세대를 고르는 전용 Dialog를 엽니다. */
async function openStyleProjectForkDialog(sourceProjectIdentifier) {
  if (styleProjectForkDialogState.busy) return;
  const source = previewState.projects.find(project => project.identifier === sourceProjectIdentifier);
  if (!source) return;
  const dialog = document.querySelector("#style-project-fork-dialog");
  styleProjectForkDialogState.sourceProjectIdentifier = sourceProjectIdentifier;
  styleProjectForkDialogState.options = null;
  const initialName = source.name.slice(0, 75) + " Fork";
  dialog.innerHTML = `<form id="style-project-fork-form" class="form-layout">
    <div class="dialog-heading"><h2 id="style-project-fork-title">프로젝트 Fork</h2></div>
    <p class="muted">${escapeMarkup(source.name)}</p>
    <label for="style-project-fork-source">출발 상태</label>
    <select id="style-project-fork-source" disabled><option value="">불러오는 중…</option></select>
    <p id="style-project-fork-summary" class="form-note" role="status"></p>
    <label class="checkbox-row"><input id="style-project-fork-statistics" type="checkbox" /> 선호도 Score·승패도 가져오기</label>
    <label for="style-project-fork-name">새 프로젝트 이름</label>
    <input id="style-project-fork-name" required maxlength="80" value="${escapeMarkup(initialName)}" />
    <p class="form-note">새 프로젝트는 0세대에서 시작합니다. 이미지와 조합 Elo는 새로 생성·평가합니다.</p>
    <p id="style-project-fork-error" class="error" role="alert"></p>
    <div class="form-actions"><button type="button" data-project-fork-cancel>취소</button><button type="submit" class="primary" disabled>Fork 만들기</button></div>
  </form>`;
  dialog.querySelector("[data-project-fork-cancel]").addEventListener("click", () => dialog.close());
  dialog.querySelector("#style-project-fork-source").addEventListener("change", updateStyleProjectForkSummary);
  dialog.querySelector("#style-project-fork-statistics").addEventListener("change", updateStyleProjectForkSummary);
  dialog.querySelector("form").addEventListener("submit", submitStyleProjectFork);
  dialog.showModal();
  try {
    await loadStyleProjectForkOptions();
  } catch (error) {
    dialog.querySelector("#style-project-fork-error").textContent = error.message;
  }
}

/** 원하는 값과 Operation ID를 유지해 응답 유실 뒤에도 중복 생성하지 않습니다. */
async function submitStyleProjectFork(event) {
  event.preventDefault();
  if (styleProjectForkDialogState.busy || !styleProjectForkDialogState.options) return;
  const dialog = document.querySelector("#style-project-fork-dialog");
  const sourceProjectIdentifier = styleProjectForkDialogState.sourceProjectIdentifier;
  const sourceSnapshotIdentifier = dialog.querySelector("#style-project-fork-source").value;
  const includeComponentStatistics = dialog.querySelector("#style-project-fork-statistics").checked;
  const name = dialog.querySelector("#style-project-fork-name").value.trim();
  const selectedSnapshot = styleProjectForkDialogState.options.snapshots.find(snapshot => snapshot.identifier === sourceSnapshotIdentifier);
  if (!selectedSnapshot) return;
  const snapshotRevision = selectedSnapshot.revision;
  previewState.pendingProjectForks ??= {};
  let payload = previewState.pendingProjectForks[sourceProjectIdentifier];
  if (!payload || payload.name !== name || payload.sourceSnapshotIdentifier !== sourceSnapshotIdentifier || payload.expectedSnapshotRevision !== snapshotRevision || payload.includeComponentStatistics !== includeComponentStatistics) {
    payload = { name, sourceSnapshotIdentifier, expectedSnapshotRevision: snapshotRevision, includeComponentStatistics, operationIdentifier: newStyleClientIdentifier() };
    previewState.pendingProjectForks[sourceProjectIdentifier] = payload;
    persistPreviewSession();
  }
  styleProjectForkDialogState.busy = true;
  const form = dialog.querySelector("form");
  form.inert = true;
  const errorDisplay = dialog.querySelector("#style-project-fork-error");
  errorDisplay.textContent = "";
  try {
    const project = await styleProjectApi(`/api/style-projects/${sourceProjectIdentifier}/forks`, { method: "POST", body: JSON.stringify(payload) });
    delete previewState.pendingProjectForks[sourceProjectIdentifier];
    previewState.projects = [project, ...previewState.projects.filter(existing => existing.identifier !== project.identifier)];
    previewState.currentProjectIdentifier = project.identifier;
    previewState.settingsDrafts.projects[project.identifier] = structuredClone(project.settings);
    previewState.projectDraftRevisions[project.identifier] = project.revision;
    document.querySelector("#workspace-active-count").textContent = `프로젝트 ${previewState.projects.length}`;
    dialog.close();
    persistPreviewSession();
    navigatePreview("project-settings");
    showToast("새 프로젝트를 만들었습니다.");
  } catch (error) {
    errorDisplay.textContent = error.message;
    if ([404, 409, 422].includes(error.status)) {
      delete previewState.pendingProjectForks[sourceProjectIdentifier];
      persistPreviewSession();
    }
    if (error.status === 409) {
      try {
        await loadStyleProjectForkOptions();
      } catch (reloadError) {
        errorDisplay.textContent = reloadError.message;
      }
    }
  } finally {
    styleProjectForkDialogState.busy = false;
    form.inert = false;
  }
}

/** Fork는 원본 투표를 변경하지 않으며 프로젝트 카드에서만 명시적으로 시작합니다. */
function handleStyleProjectForkAction(event) {
  if (!PERSISTENT_STYLE_WORKSPACE) return;
  const button = event.target.closest("[data-project-fork]");
  if (button && !button.disabled) openStyleProjectForkDialog(button.dataset.projectFork);
}

document.addEventListener("click", handleStyleProjectForkAction);
document.querySelector("#style-project-fork-dialog").addEventListener("cancel", event => {
  if (styleProjectForkDialogState.busy) event.preventDefault();
});
