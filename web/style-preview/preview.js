"use strict";

const previewContent = document.querySelector("#preview-content");
const componentDialog = document.querySelector("#component-dialog");
const illustrationDialog = document.querySelector("#illustration-dialog");
const PREVIEW_SESSION_STORAGE_KEY = "comfy-home-style-preview-session-v2";
const sampleComponents = [
  { identifier: "artist:soft_ink", name: "soft_ink", kind: "작가" },
  { identifier: "artist:daylight", name: "daylight", kind: "작가" },
  { identifier: "lora:watercolor", name: "Watercolor", kind: "LoRA" },
  { identifier: "lora:flat_color", name: "Flat Color", kind: "LoRA" },
];
const sampleCandidates = [
  { identifier: "soft", name: "맑은 수채", palette: ["#d6e5e5", "#496577", "#f1d7c7", "#809fa7", "#f0e7d6"], components: { "artist:soft_ink": [0.8], "artist:daylight": [1.0], "lora:watercolor": [0.6, 0] } },
  { identifier: "warm", name: "따뜻한 채색", palette: ["#f0dbca", "#694d65", "#f5c9b4", "#b47b89", "#efe3ce"], components: { "artist:soft_ink": [0.8], "artist:daylight": [0.7], "lora:watercolor": [0.9, 0], "lora:flat_color": [0.4, 0] } },
  { identifier: "pastel", name: "옅은 파스텔", palette: ["#e1dced", "#6e6689", "#f1d3ca", "#a496bb", "#eee6ed"], components: { "artist:soft_ink": [0.5], "artist:daylight": [1.0], "lora:flat_color": [0.6, 0] } },
  { identifier: "forest", name: "깊은 초록", palette: ["#cad9c9", "#405f5b", "#eccbbc", "#6f9688", "#e7dfbd"], components: { "artist:soft_ink": [1.1], "lora:watercolor": [0.5, 0], "lora:flat_color": [0.3, 0] } },
];
const defaultPromptCases = [
  { name: "창가의 인물", prompt: "1girl, portrait, by the window, soft daylight, {artist}", scene: "portrait" },
  { name: "꽃이 있는 정원", prompt: "1girl, garden, flowers, full body, {artist}", scene: "garden" },
];

/** 탭 안에서만 사용하는 프로젝트 예시를 독립적으로 만듭니다. */
function createSampleProject(identifier, name, promptCases, candidateCount = 4, templateOffset = 0, globalSettings = createGlobalSettingsPreview()) {
  const candidates = [];
  for (let candidateIndex = 0; candidateIndex < candidateCount; candidateIndex += 1) {
    const template = structuredClone(sampleCandidates[(candidateIndex + templateOffset) % sampleCandidates.length]);
    template.identifier = `${identifier}-${template.identifier}`;
    candidates.push(template);
  }
  return {
    identifier, name, promptCases: structuredClone(promptCases), candidateCount, candidates,
    excludedComponents: [], savedCandidates: [], decisions: [], pairIndex: 0,
    settings: createProjectSettingsPreview(name, promptCases, globalSettings),
    rankingBaseline: createRankingPreviewBaseline(identifier, candidates),
  };
}

const previewState = {
  projects: [
    createSampleProject("portrait-project", "봄빛이 드는 인물", defaultPromptCases),
    createSampleProject("garden-project", "초록빛 이야기", [...defaultPromptCases].reverse(), 4, 2),
  ],
  currentProjectIdentifier: "portrait-project",
  screen: "projects",
  libraryFilter: "current",
  blind: false,
  singleImage: false,
  visibleSide: "a",
  activeCaseIndex: 0,
  nextProjectSequence: 1,
  globalSettings: createGlobalSettingsPreview(),
  settingsDrafts: { global: null, projects: {} },
  draft: { name: "새 그림체 탐색", candidateCount: 4, promptCases: structuredClone(defaultPromptCases) },
  toastTimeout: null,
};

/** 동일 탭에서 작업 공간을 오가도 예시 프로젝트와 선택을 유지합니다. */
function persistPreviewSession() {
  const { toastTimeout, ...storedState } = previewState;
  try {
    sessionStorage.setItem(PREVIEW_SESSION_STORAGE_KEY, JSON.stringify({ version: 2, state: storedState }));
  } catch (error) {
    // 임시 보관을 지원하지 않아도 현재 화면 조작은 계속 허용합니다.
  }
}

/** 현재 형식으로 저장한 예시 상태만 복구하고 손상된 값은 사용하지 않습니다. */
function restorePreviewSession() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(PREVIEW_SESSION_STORAGE_KEY) || "null");
    if (stored?.version !== 2 || !Array.isArray(stored.state?.projects)) return;
    const projects = stored.state.projects;
    if (!projects.length || projects.some(project => !Array.isArray(project.candidates) || project.candidates.length < 2)) return;
    if (!projects.some(project => project.identifier === stored.state.currentProjectIdentifier)) return;
    Object.assign(previewState, stored.state, { toastTimeout: null });
  } catch (error) {
    // Session Storage가 제한된 환경에서도 초기 예시 화면은 제공합니다.
  }
}

/** 사용자 입력을 HTML 문자로만 표시하도록 변환합니다. */
function escapeMarkup(value) {
  return String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

/** 현재 예시 프로젝트를 조회합니다. */
function currentProject() {
  return previewState.projects.find(project => project.identifier === previewState.currentProjectIdentifier);
}

/** 현재 비교하는 A/B의 고정된 의미를 반환합니다. */
function currentPair() {
  const project = currentProject();
  const firstIndex = project.pairIndex % project.candidateCount;
  return { a: project.candidates[firstIndex], b: project.candidates[(firstIndex + 1) % project.candidateCount] };
}

/** 실제 생성물과 구분되는 공통 구도의 샘플 일러스트를 만듭니다. */
function illustrationSource(candidate, scene = "portrait") {
  const [backgroundColor, inkColor, skinColor, clothingColor, paperColor] = candidate.palette;
  const gardenBackground = `<path d="M0 390 Q120 320 240 395 T600 355 V600 H0Z" fill="${clothingColor}" opacity=".35"/>
    <g fill="${paperColor}" stroke="${inkColor}" stroke-width="1.4" opacity=".8">
      <path d="M70 600 Q68 470 95 405 M498 600 Q490 440 533 373 M130 600 Q144 510 126 476" fill="none"/>
      <ellipse cx="95" cy="405" rx="17" ry="10"/><ellipse cx="80" cy="414" rx="13" ry="10"/><ellipse cx="109" cy="416" rx="15" ry="10"/>
      <ellipse cx="533" cy="373" rx="20" ry="12"/><ellipse cx="513" cy="384" rx="16" ry="10"/><ellipse cx="546" cy="385" rx="16" ry="12"/>
      <ellipse cx="126" cy="476" rx="16" ry="13"/><path d="M67 514 Q20 480 30 455 Q79 466 67 514 M499 492 Q552 443 566 461 Q554 496 499 492" fill="${clothingColor}"/>
    </g>`;
  const windowBackground = `<rect x="355" y="40" width="215" height="340" rx="100" fill="${paperColor}" opacity=".6"/>
    <path d="M461 47 V369 M359 202 H566" stroke="${inkColor}" opacity=".2" stroke-width="5"/>
    <path d="M20 600 Q70 460 57 371 M59 453 Q1 420 16 395 Q56 400 59 453 M57 422 Q109 377 116 398 Q101 428 57 422" fill="${clothingColor}" stroke="${inkColor}" stroke-width="2" opacity=".5"/>`;
  const figureTransform = scene === "garden" ? "translate(100 65) scale(.7)" : "translate(0 0)";
  const svgMarkup = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600">
    <defs><radialGradient id="wash"><stop stop-color="${paperColor}"/><stop offset="1" stop-color="${backgroundColor}"/></radialGradient>
    <pattern id="paper" width="13" height="13" patternUnits="userSpaceOnUse"><circle cx="2" cy="4" r=".65" fill="${inkColor}" opacity=".09"/><circle cx="9" cy="11" r=".45" fill="${inkColor}" opacity=".1"/></pattern></defs>
    <rect width="600" height="600" fill="url(#wash)"/>
    <circle cx="130" cy="130" r="140" fill="${paperColor}" opacity=".3"/>
    ${scene === "garden" ? gardenBackground : windowBackground}
    <g transform="${figureTransform}" stroke="${inkColor}" stroke-linecap="round" stroke-linejoin="round">
      <path d="M169 354 Q103 173 195 100 Q286 18 379 113 Q433 157 411 313 L439 470 L153 478Z" fill="${inkColor}" stroke-width="2"/>
      <path d="M151 600 Q151 429 244 406 L255 354 H329 L339 407 Q431 424 463 600Z" fill="${clothingColor}" stroke-width="2"/>
      <path d="M245 407 L290 455 L339 407 L363 440 L303 506 L219 439Z" fill="${paperColor}" stroke-width="1.5"/>
      <path d="M255 351 L253 409 Q289 441 333 407 L327 351Z" fill="${skinColor}" stroke-width="1.3"/>
      <path d="M190 200 Q186 129 284 119 Q376 120 388 214 L367 319 Q341 365 292 380 Q246 370 211 326Z" fill="${skinColor}" stroke-width="1.5"/>
      <path d="M176 225 Q161 126 253 96 Q348 74 391 159 L395 247 Q347 214 319 135 Q302 215 256 229 L266 163 Q238 226 176 253Z" fill="${inkColor}" stroke-width="2"/>
      <path d="M205 251 Q228 236 251 248 M321 248 Q345 235 365 248" fill="none" stroke-width="3"/>
      <path d="M215 261 Q232 249 248 260 M323 258 Q340 247 356 258" fill="none" stroke-width="3"/>
      <ellipse cx="233" cy="265" rx="7" ry="11" fill="${inkColor}"/><ellipse cx="337" cy="263" rx="7" ry="11" fill="${inkColor}"/>
      <circle cx="235" cy="262" r="2.5" fill="white" stroke="none"/><circle cx="339" cy="260" r="2.5" fill="white" stroke="none"/>
      <path d="M286 276 L280 302 L289 304 M274 329 Q289 337 307 328" fill="none" stroke-width="1.5" opacity=".75"/>
      <ellipse cx="229" cy="299" rx="22" ry="9" fill="#dc8e95" opacity=".18" stroke="none"/><ellipse cx="344" cy="297" rx="20" ry="9" fill="#dc8e95" opacity=".18" stroke="none"/>
      <path d="M185 258 Q153 353 185 430 M386 244 Q413 354 383 418 M199 438 L215 600 M381 443 L401 600" fill="none" stroke-width="2" opacity=".6"/>
      <path d="M291 458 L277 518 L293 542 L307 516Z" fill="${inkColor}" stroke-width="1" opacity=".8"/>
    </g>
    <rect width="600" height="600" fill="url(#paper)"/>
    <text x="575" y="581" text-anchor="end" fill="${inkColor}" opacity=".45" font-family="sans-serif" font-size="12" letter-spacing="3">SAMPLE / ${scene === "garden" ? "02" : "01"}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup)}`;
}

/** 짧은 확인 메시지를 중복 축적 없이 표시합니다. */
function showToast(message) {
  const toastElement = document.querySelector("#preview-toast");
  clearTimeout(previewState.toastTimeout);
  toastElement.textContent = message;
  toastElement.hidden = false;
  previewState.toastTimeout = setTimeout(() => { toastElement.hidden = true; }, 3500);
}

/** 단순 화면 이동으로 예시 프로젝트·작성 중 입력을 초기화하지 않습니다. */
function navigatePreview(screen) {
  if (window.location.hash === `#${screen}`) {
    renderPreview();
  } else {
    window.location.hash = screen;
  }
}

/** 익숙한 선별·그림체 메뉴와 프로젝트 전환을 그립니다. */
function renderNavigation() {
  const project = currentProject();
  document.querySelector("#project-context").innerHTML = `
    <label for="active-project-picker">현재 프로젝트</label>
    <select id="active-project-picker" aria-label="현재 프로젝트">${previewState.projects.map(item => `<option value="${item.identifier}" ${item.identifier === project.identifier ? "selected" : ""}>${escapeMarkup(item.name)}</option>`).join("")}</select>
    <span>선별·보관의 작업 대상</span>`;
  document.querySelector("#preview-sidebar").innerHTML = `
    <button data-action="navigate" data-screen="projects" class="${previewState.screen === "projects" ? "active" : ""}">▦　모든 프로젝트</button>
    <p class="project-label">현재 프로젝트</p><p class="project-name">${escapeMarkup(project.name)}</p>
    <button data-action="navigate" data-screen="compare" class="${previewState.screen === "compare" ? "active" : ""}">↔　선별</button>
    <button data-action="navigate" data-screen="candidates" class="${["candidates", "candidate-detail"].includes(previewState.screen) ? "active" : ""}">◇　그림체 <small>　${project.candidateCount}</small></button>
    <button data-action="navigate" data-screen="project-settings" class="${previewState.screen === "project-settings" ? "active" : ""}">⚙　프로젝트 설정</button>
    <p class="project-label">시스템 공통</p>
    <button data-action="navigate" data-screen="global-settings" class="${previewState.screen === "global-settings" ? "active" : ""}">◎　글로벌 설정</button>
    <p class="sidebar-note">먼저 화면을 사용해 보고<br>함께 흐름을 정합니다.</p>`;
  document.querySelector("#preview-mobile-navigation").innerHTML = [
    ["projects", "▦", "프로젝트"], ["compare", "↔", "선별"], ["candidates", "◇", "그림체"],
    ["project-settings", "⚙", "설정"],
  ].map(([screen, symbol, label]) => `<button data-action="navigate" data-screen="${screen}" class="${previewState.screen === screen || (screen === "project-settings" && previewState.screen === "global-settings") || (screen === "candidates" && previewState.screen === "candidate-detail") ? "active" : ""}"><b>${symbol}</b>${label}</button>`).join("");
}

/** 현재 작업을 파악할 수 있는 작은 조건 요약을 만듭니다. */
function conditionSummary() {
  const project = currentProject();
  return `<div class="condition-strip"><span class="tag">Anima · 예시</span><span>1세대</span><span>·</span><span>${project.candidateCount}개 조합</span><span>·</span><span>${project.promptCases.length}개 Prompt</span><span>· Seed 42</span></div>`;
}

/** 첫 진입점에서 예시 프로젝트를 선택하거나 새 흐름을 시작합니다. */
function renderProjects() {
  return `<div class="page-heading"><div><p class="eyebrow">STYLE EXPLORATION</p><h1>나만의 그림체 찾기</h1><p class="muted">Prompt와 모델에 맞는 그림체를, 프로젝트별로.</p></div><button class="primary" data-action="navigate" data-screen="create">＋ 새 프로젝트</button></div>
    <p class="section-label">사용해 볼 예시 프로젝트</p><div class="project-grid">${previewState.projects.map(project => `
      <article class="panel project-card"><div class="project-cover"><img src="${illustrationSource(project.candidates[0], project.promptCases[0].scene)}" alt="${escapeMarkup(project.name)} 샘플 일러스트" /></div>
      <div class="project-card-body"><h2>${escapeMarkup(project.name)}</h2><p class="muted">${project.promptCases.map(promptCase => escapeMarkup(promptCase.name)).join(" · ")}</p>
      <div class="card-meta"><span>Anima</span><span>1세대 · ${project.candidateCount}개 조합</span><span>${project.promptCases.length}개 Prompt</span></div>
      <button data-action="open-project" data-project="${project.identifier}">이어서 선별하기 →</button></div></article>`).join("")}</div>`;
}

/** Prompt 편집 영역을 추가·제거할 때 작성 중 내용을 보존합니다. */
function promptEditorMarkup(promptCase, caseIndex) {
  return `<section class="prompt-editor"><div class="prompt-editor-heading"><label for="case-name-${caseIndex}" class="muted">${caseIndex + 1}</label><input id="case-name-${caseIndex}" data-draft-case="${caseIndex}" data-field="name" value="${escapeMarkup(promptCase.name)}" aria-label="Prompt ${caseIndex + 1} 이름" required maxlength="60" /><button type="button" class="quiet small" data-action="remove-prompt" data-case="${caseIndex}" ${previewState.draft.promptCases.length === 1 ? "disabled" : ""}>제거</button></div>
    <label for="case-prompt-${caseIndex}">Positive Prompt</label><textarea id="case-prompt-${caseIndex}" data-draft-case="${caseIndex}" data-field="prompt" required maxlength="3000">${escapeMarkup(promptCase.prompt)}</textarea></section>`;
}

/** 필수 입력과 펼쳐 보는 생성 조건으로 새 프로젝트 흐름을 보여줍니다. */
function renderProjectCreation() {
  const draft = previewState.draft;
  return `<div class="page-heading"><div><p class="eyebrow">NEW PROJECT</p><h1>어떤 그림체를 찾을까요?</h1><p class="muted">여러 Prompt를 넣어 같은 조합을 함께 확인합니다.</p></div></div>
    <form id="project-preview-form" class="form-layout">
      <section class="panel"><div class="form-row"><div><label for="project-name">프로젝트 이름</label><input id="project-name" data-draft-field="name" required maxlength="80" value="${escapeMarkup(draft.name)}" /></div><div><label for="project-workflow">등록 Workflow</label><select id="project-workflow"><option>Anima Turbo · 화면 예시</option></select></div></div></section>
      <section class="panel"><h2>함께 비교할 Prompt</h2><p class="muted form-note" style="margin-bottom:16px">인물, 전신, 다른 장면에서도 원하는 느낌이 유지되는지 봅니다.</p><div id="draft-prompt-list">${draft.promptCases.map(promptEditorMarkup).join("")}</div><button type="button" data-action="add-prompt">＋ Prompt 추가</button></section>
      <section class="panel"><details><summary>성분과 생성 조건</summary><p class="form-note">예시 성분: 작가 soft_ink · daylight / LoRA Watercolor · Flat Color</p><p class="form-note">Seed 42 · Steps 8 · CFG 1 · 1024 × 1024</p><p class="form-note">글로벌 기본값 ${previewState.globalSettings.revision}번을 새 프로젝트 설정에 복사합니다. 프로젝트를 만든 뒤 설정 화면에서 Prompt·성분 범위를 조정할 수 있습니다.</p></details><label for="candidate-count">처음 만들 조합 수</label><select id="candidate-count" data-draft-field="candidateCount">${[2, 4].map(count => `<option value="${count}" ${draft.candidateCount === count ? "selected" : ""}>${count}개</option>`).join("")}</select></section>
      <div class="form-actions"><span id="generation-estimate" class="generation-estimate">${generationEstimate()}</span><button type="button" class="quiet" data-action="navigate" data-screen="projects">목록으로</button><button type="submit" class="primary">예시 조합 만들기 →</button></div>
    </form>`;
}

/** 조합 수와 Prompt 수에 따른 예시 이미지 장수를 표시합니다. */
function generationEstimate() {
  return `${previewState.draft.candidateCount}개 조합 × ${previewState.draft.promptCases.length}개 Prompt = ${previewState.draft.candidateCount * previewState.draft.promptCases.length}장 · 실제 생성 없음`;
}

/** 순위·전적·보관 필터를 그림체 목록에서 함께 보여줍니다. */
function renderCandidates() {
  const project = currentProject();
  const visibleProjects = previewState.projects.filter(owner => {
    if (previewState.libraryFilter === "all") return true;
    if (previewState.libraryFilter === "current") return owner.identifier === project.identifier;
    return previewState.libraryFilter === `project:${owner.identifier}`;
  });
  const heading = `<div class="page-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>그림체</h1><p class="muted">순위와 결과를 살펴보고 마음에 드는 조합을 보관하세요.</p></div><button class="primary" data-action="navigate" data-screen="compare">현재 프로젝트 선별 →</button></div>`;
  if (previewState.blind) return heading + rankingBlindNoticeMarkup();
  return `${heading}<div class="candidate-library-controls"><div><label for="candidate-project-filter">그림체 보기</label><select id="candidate-project-filter">
      <option value="current" ${previewState.libraryFilter === "current" ? "selected" : ""}>현재 프로젝트만</option>
      <option value="all" ${previewState.libraryFilter === "all" ? "selected" : ""}>전체 프로젝트 · 프로젝트별 묶음</option>
      ${previewState.projects.map(owner => `<option value="project:${owner.identifier}" ${previewState.libraryFilter === `project:${owner.identifier}` ? "selected" : ""}>${escapeMarkup(owner.name)}</option>`).join("")}
    </select></div><div><label for="candidate-sort-order">정렬</label><select id="candidate-sort-order">
      ${[["elo", "Elo 높은 순"], ["matches", "평가 횟수 많은 순"], ["creation", "등록 순"]].map(([value, label]) => `<option value="${value}" ${previewState.candidateSortOrder === value ? "selected" : ""}>${label}</option>`).join("")}
    </select></div><label class="candidate-saved-filter"><input id="candidate-saved-only" type="checkbox" ${previewState.savedCandidatesOnly ? "checked" : ""} />보관한 그림체만</label></div>
    <p class="form-note candidate-library-note">프로젝트별 순위 · 미평가는 Elo 없음 · 예시 데이터${previewState.libraryFilter !== "current" ? ` · 선별 대상은 ${escapeMarkup(project.name)}` : ""}</p>
    ${project.decisions.length ? '<div class="toolbar"><button data-action="undo">↶ 현재 프로젝트 직전 선택 되돌리기</button></div>' : ""}
    ${previewState.libraryFilter === "current" ? lastRankingChangeMarkup(project) : ""}
    ${visibleProjects.map(renderProjectCandidateGroup).join("")}`;
}

/** 그림체의 소유 프로젝트와 현재 작업 프로젝트를 혼동하지 않게 묶습니다. */
function renderProjectCandidateGroup(owner) {
  const isCurrentProject = owner.identifier === currentProject().identifier;
  const entries = sortCandidateLibraryEntries(calculateRankingPreview(owner), previewState.candidateSortOrder);
  const visibleEntries = previewState.savedCandidatesOnly ? entries.filter(entry => owner.savedCandidates.includes(entry.candidate.identifier)) : entries;
  const candidateCards = visibleEntries.map(entry => {
    const candidate = entry.candidate;
    const saved = owner.savedCandidates.includes(candidate.identifier);
    const actionMarkup = isCurrentProject
      ? `<button data-action="save-candidate" data-candidate="${candidate.identifier}" aria-pressed="${saved}">${saved ? "★ 보관됨" : "☆ 이 그림체 보관"}</button>`
      : `<button data-action="preview-style-transfer" data-owner="${owner.identifier}" data-candidate="${candidate.identifier}">현재 프로젝트에서 시험 ↗</button>`;
    return `<article class="candidate-card" data-owner="${owner.identifier}" data-ranking-candidate="${candidate.identifier}"><div class="candidate-cover"><img src="${illustrationSource(candidate, owner.promptCases[0].scene)}" alt="${escapeMarkup(candidate.name)} 샘플 일러스트" /><span class="candidate-rank-label">${entry.rank ? `${entry.rank}위` : "미평가"}</span></div><div class="candidate-card-body"><h2>${escapeMarkup(candidate.name)}</h2><div class="candidate-rating"><strong>${rankingRatingLabel(entry)}</strong><span>Elo · 예시</span></div><span class="ranking-status ${entry.matches ? "" : "unrated"}">${rankingPreviewStatus(entry, owner)}</span><p class="candidate-record">${entry.matches}회 평가 · ${entry.wins}승 ${entry.losses}패 · Skip ${entry.skips}회</p><p>${owner.promptCases.length}개 Prompt · ${saved ? "★ 보관됨" : "보관 안 함"}</p>${isCurrentProject ? `<button class="quiet" data-ranking-action="open-detail" data-candidate="${candidate.identifier}">결과·전적 상세</button>` : ""}${actionMarkup}</div></article>`;
  }).join("");
  return `<section class="candidate-project-group" data-project-group="${owner.identifier}"><div class="group-heading"><h2>${escapeMarkup(owner.name)}</h2><span>${isCurrentProject ? "현재 프로젝트" : "둘러보는 프로젝트"} · ${visibleEntries.length} / ${owner.candidates.length}개 · 프로젝트 내 순위</span></div>${candidateCards ? `<div class="candidate-grid">${candidateCards}</div>` : '<div class="panel empty-state"><p>이 프로젝트에 보관한 그림체가 없습니다.</p><button data-action="show-all-candidates">모든 그림체 보기</button></div>'}</section>`;
}

/** 표시 순서만 바꾸고 계산된 프로젝트 전체 순위는 유지합니다. */
function sortCandidateLibraryEntries(entries, sortOrder) {
  const sortedEntries = [...entries];
  if (sortOrder === "creation") sortedEntries.sort((first, second) => first.creationIndex - second.creationIndex);
  if (sortOrder === "matches") sortedEntries.sort((first, second) => second.matches - first.matches || compareRankingPreviewEntries(first, second));
  return sortedEntries;
}

/** 다른 프로젝트의 성분을 현재 조건에서 시험할 후속 흐름을 보여줍니다. */
function renderStyleTransferPreview(ownerIdentifier, candidateIdentifier) {
  const owner = previewState.projects.find(project => project.identifier === ownerIdentifier);
  const candidate = owner.candidates.find(item => item.identifier === candidateIdentifier);
  const target = currentProject();
  componentDialog.innerHTML = `<div class="dialog-heading"><h2 id="component-dialog-title">현재 프로젝트에서 시험</h2><button data-action="close-differences" aria-label="조합 차이 닫기">✕</button></div>
    <p>원본: ${escapeMarkup(owner.name)} / ${escapeMarkup(candidate.name)}</p>
    <p>시험 대상: <strong>${escapeMarkup(target.name)}</strong></p>
    <p class="muted">성분과 STR을 그대로 가져와 아래 Prompt로 새 이미지를 만들 계획입니다. 원본 점수는 이전하지 않습니다.</p>
    <ul>${target.promptCases.map(promptCase => `<li>${escapeMarkup(promptCase.name)}</li>`).join("")}</ul>
    <p class="form-note">현재는 가져오기 흐름을 설명하는 목업입니다. 실제 시험 생성·호환성 검사는 후속 단계에서 연결합니다.</p>`;
  componentDialog.showModal();
}

/** 화면 검토와 아직 구현하지 않은 기능의 경계를 사용자에게 보여줍니다. */
function renderPreviewScope() {
  return `<div class="page-heading"><div><p class="eyebrow">PHASE 0</p><h1>지금 확인할 수 있는 범위</h1><p class="muted">화면 검토 단계입니다. 실제 생성·DB 저장은 아직 연결하지 않았습니다.</p></div></div>
    <section class="panel scope-panel"><h2>지금 조작할 수 있는 화면</h2><p>같은 창의 작업 공간 전환, 프로젝트 선택·만들기 예시, 여러 Prompt를 함께 보는 A/B 선택, 되돌리기·Blind, STR 차이·제외, 프로젝트별 그림체·보관 예시입니다.</p><p>그림체 화면에서는 예시 Elo·전적·미평가 상태를 보고, 그림체 상세의 모든 Prompt 결과와 성분을 확인한 뒤 선별로 돌아올 수 있습니다. 선택·Undo에 따른 점수와 순위 변화도 예시로 표시합니다.</p><p>설정 화면에서는 글로벌 성분 기본값과 프로젝트의 Prompt·성분 범위를 나누어 편집하고, 기본값 적용 전 변경 내용을 확인할 수 있습니다.</p><p class="form-note">예시 상태는 이 탭의 Session에 임시 보관됩니다. 실제 프로젝트 DB 저장과는 별개입니다. 설정 변경으로 기존 예시 결과를 재생성하지 않습니다.</p></section>
    <section class="panel scope-panel"><h2>앞으로 함께 만들 것</h2><ol class="implementation-roadmap">
      <li><strong>설정 화면 확인 후 실제 저장 연결</strong><p>설정 UI는 이번 검토 범위입니다. 실제 등록 Workflow·성분 Catalog와 프로젝트 DB 저장은 다음 단계에서 연결합니다.</p></li>
      <li><strong>프로젝트 저장과 실제 후보 생성</strong><p>등록 Workflow·공통 조건·여러 Prompt의 실제 이미지·작업 추적.</p></li>
      <li><strong>점수·선별·진화·보관</strong><p>여러 Prompt를 함께 보고 조합 단위로 한 번 평가. 점수 이전·잠금·계보도 연결.</p></li>
      <li><strong>세대 복원과 Fork</strong><p>확정 세대로 돌아가기, 현재 상태 또는 특정 확정 세대에서 새 프로젝트로 독립 분기.</p></li>
      <li><strong>Prompt 재시험·다른 프로젝트 그림체 가져오기</strong><p>성분을 유지한 채 현재 Prompt들로 생성하고 별도로 평가.</p></li>
      <li><strong>검증·이관·다중 원본 융합</strong><p>추가 Prompt/Seed 검증·Ablation·Import/Export. 다른 기능 이후 비율·3개 이상 융합.</p></li>
    </ol></section>`;
}

/** Mobile에서도 의미상 A/B가 유지되는 후보 제목을 그립니다. */
function candidateHeading(candidate, side) {
  return `<div class="candidate-name ${side === previewState.visibleSide ? "visible-side" : ""}"><span class="candidate-letter">${side.toUpperCase()}</span><span>${previewState.blind ? "그림체 숨김" : escapeMarkup(candidate.name)}${comparisonRankingSummaryMarkup(candidate)}</span></div>`;
}

/** Prompt별 같은 A/B를 대응시키는 이미지 행을 만듭니다. */
function comparisonCaseMarkup(promptCase, caseIndex) {
  const pair = currentPair();
  return `<section class="case-section ${caseIndex === previewState.activeCaseIndex ? "active-case" : ""}"><div class="case-heading"><span class="case-number">PROMPT ${String(caseIndex + 1).padStart(2, "0")}</span><strong>${escapeMarkup(promptCase.name)}</strong><span>같은 조건 · Seed 42</span></div>
    <div class="comparison-columns ${previewState.singleImage ? "single-image" : ""}">${["a", "b"].map(side => `<button class="image-button ${side === previewState.visibleSide ? "visible-side" : ""}" data-action="enlarge" data-side="${side}" data-case="${caseIndex}" aria-label="${escapeMarkup(promptCase.name)} ${side.toUpperCase()} 이미지 확대"><img src="${illustrationSource(pair[side], promptCase.scene)}" alt="${escapeMarkup(promptCase.name)} · ${side.toUpperCase()} 샘플 일러스트" /></button>`).join("")}</div>
    </section>`;
}

/** 여러 Prompt의 같은 두 조합을 보고 조합 단위로 한 번 선택합니다. */
function renderComparison() {
  const project = currentProject();
  const pair = currentPair();
  return `<div class="page-heading comparison-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>어느 쪽 그림체가 더 좋나요?</h1><p class="muted">같은 두 조합을 여러 Prompt에서 확인해 보세요.</p></div><button data-action="undo" ${project.decisions.length ? "" : "disabled"}>↶ 되돌리기</button></div>${conditionSummary()}
    <div class="toolbar"><div class="toolbar-group"><button data-action="toggle-blind" aria-pressed="${previewState.blind}">◉ Blind ${previewState.blind ? "켜짐" : "꺼짐"}</button><button data-action="open-differences" ${previewState.blind ? "disabled" : ""}>조합 차이 보기 ↗</button><button data-action="navigate" data-screen="candidates">그림체 보기 →</button></div></div>
    <div class="mobile-case-controls mobile-only"><div class="case-tabs" aria-label="비교할 Prompt">${project.promptCases.map((promptCase, caseIndex) => `<button data-action="switch-case" data-case="${caseIndex}" aria-pressed="${previewState.activeCaseIndex === caseIndex}">${escapeMarkup(promptCase.name)}</button>`).join("")}</div><button data-action="image-layout" data-layout="${previewState.singleImage ? "pair" : "single"}">${previewState.singleImage ? "나란히" : "한 장씩"}</button>${previewState.singleImage ? `<button data-action="switch-side">${previewState.visibleSide === "a" ? "B" : "A"} 보기</button>` : ""}</div>
    <div class="comparison-columns candidate-headings ${previewState.singleImage ? "single-image" : ""}">${candidateHeading(pair.a, "a")}${candidateHeading(pair.b, "b")}</div>
    ${project.promptCases.map(comparisonCaseMarkup).join("")}
    <footer class="comparison-footer"><div class="vote-buttons"><button class="vote-choice" data-action="bundle-vote" data-choice="a">A가 더 좋아요</button><button data-action="bundle-vote" data-choice="similar">비슷함</button><button class="vote-choice" data-action="bundle-vote" data-choice="b">B가 더 좋아요</button></div><p class="vote-caption">모든 Prompt를 함께 보고 조합 하나를 선택 · 예시 선택 ${project.decisions.length}회</p></footer>${lastRankingChangeMarkup(project)}`;
}

/** 같은 성분의 독립 Weight 축을 비교해 차이와 동일 항목을 나눕니다. */
function componentDifferences() {
  const pair = currentPair();
  return sampleComponents.map(component => {
    const firstWeights = pair.a.components[component.identifier];
    const secondWeights = pair.b.components[component.identifier];
    if (!firstWeights && !secondWeights) return null;
    const sameWeights = firstWeights?.[0] === secondWeights?.[0];
    const differenceKind = !firstWeights ? "B에만 있음" : !secondWeights ? "A에만 있음" : sameWeights ? "STR 동일" : "강도 변경";
    return { ...component, firstWeights, secondWeights, differenceKind };
  }).filter(Boolean);
}

/** 간단한 비교 화면에서는 작가·LoRA 모두 STR만 표시합니다. */
function weightLabel(component, weights) {
  if (!weights) return "포함되지 않음";
  return `STR ${weights[0].toFixed(1)}`;
}

/** 차이 표에서 프로젝트 단위의 향후 사용 제외 조작을 보여줍니다. */
function renderComponentDialog() {
  const project = currentProject();
  const differences = componentDifferences();
  const changedComponents = differences.filter(component => component.differenceKind !== "STR 동일");
  const sameComponents = differences.filter(component => component.differenceKind === "STR 동일");
  componentDialog.innerHTML = `<div class="dialog-heading"><div><p class="eyebrow">A ↔ B</p><h2 id="component-dialog-title">어떤 성분이 다른가요?</h2></div><button data-action="close-differences" aria-label="조합 차이 닫기">✕</button></div><p class="form-note" style="margin-bottom:20px">차이가 있다는 사실을 보여줍니다. 특정 성분이 결과의 원인이라고 확정하지는 않습니다.</p>
    ${changedComponents.map(componentDifferenceRow).join("")}<details><summary>STR이 같은 성분 ${sameComponents.length}개</summary>${sameComponents.map(componentDifferenceRow).join("")}</details>
    <p class="form-note">제외 범위: <strong>${escapeMarkup(project.name)}</strong>의 향후 새 조합. 기존 조합과 다른 프로젝트에는 영향을 주지 않는 설정 예시입니다.</p>`;
}

/** 한 성분의 A/B 값과 제외 버튼을 읽기 쉬운 행으로 그립니다. */
function componentDifferenceRow(component) {
  const excluded = currentProject().excludedComponents.includes(component.identifier);
  return `<section class="difference-row"><span class="difference-kind">${component.differenceKind} · ${component.kind}</span><strong>${component.name}</strong><div class="difference-values"><div><small>A</small>${weightLabel(component, component.firstWeights)}</div><div><small>B</small>${weightLabel(component, component.secondWeights)}</div></div><button data-action="exclude-component" data-component="${component.identifier}" aria-pressed="${excluded}">${excluded ? "제외 설정됨 · 다시 허용" : "앞으로 새 조합에서 제외"}</button></section>`;
}

/** 투표 결과 대신 사용 흐름만 기록하고 다음 예시 Pair를 보여줍니다. */
function recordPreviewDecision(choice) {
  const project = currentProject();
  const pair = currentPair();
  project.decisions.push({
    choice, pairIndex: project.pairIndex,
    candidateIdentifier: choice === "a" || choice === "b" ? pair[choice].identifier : null,
  });
  project.pairIndex += 1;
  previewState.activeCaseIndex = 0;
  renderPreview(false);
  showToast(choice === "similar" ? "비슷함을 기록했습니다 · 예시" : `${choice.toUpperCase()} 조합을 선택했습니다 · 예시`);
}

/** 위임한 버튼 동작을 현재 화면과 프로젝트의 범위에서 처리합니다. */
function handlePreviewAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  const project = currentProject();
  if (action === "navigate") navigatePreview(button.dataset.screen);
  if (action === "show-all-candidates") {
    previewState.savedCandidatesOnly = false;
    renderPreview(false);
  }
  if (action === "open-project") {
    previewState.currentProjectIdentifier = button.dataset.project;
    previewState.activeCaseIndex = 0;
    previewState.libraryFilter = "current";
    navigatePreview("compare");
  }
  if (action === "add-prompt") {
    previewState.draft.promptCases.push({ name: `Prompt ${previewState.draft.promptCases.length + 1}`, prompt: "", scene: "garden" });
    renderPreview(false);
  }
  if (action === "remove-prompt" && previewState.draft.promptCases.length > 1) {
    previewState.draft.promptCases.splice(Number(button.dataset.case), 1);
    renderPreview(false);
  }
  if (action === "toggle-blind") {
    previewState.blind = !previewState.blind;
    renderPreview(false);
  }
  if (action === "image-layout") {
    previewState.singleImage = button.dataset.layout === "single";
    renderPreview(false);
  }
  if (action === "switch-side") {
    previewState.visibleSide = previewState.visibleSide === "a" ? "b" : "a";
    renderPreview(false);
  }
  if (action === "switch-case") {
    previewState.activeCaseIndex = Number(button.dataset.case);
    renderPreview(false);
  }
  if (action === "open-differences") {
    renderComponentDialog();
    componentDialog.showModal();
  }
  if (action === "close-differences") componentDialog.close();
  if (action === "exclude-component") {
    const componentIdentifier = button.dataset.component;
    if (project.excludedComponents.includes(componentIdentifier)) {
      project.excludedComponents = project.excludedComponents.filter(identifier => identifier !== componentIdentifier);
    } else {
      project.excludedComponents.push(componentIdentifier);
    }
    synchronizeSettingsComponentExclusion(project, componentIdentifier);
    renderComponentDialog();
  }
  if (action === "save-candidate") {
    const candidateIdentifier = button.dataset.candidate;
    if (project.savedCandidates.includes(candidateIdentifier)) {
      project.savedCandidates = project.savedCandidates.filter(identifier => identifier !== candidateIdentifier);
    } else {
      project.savedCandidates.push(candidateIdentifier);
    }
    renderPreview(false);
  }
  if (action === "bundle-vote") recordPreviewDecision(button.dataset.choice);
  if (action === "preview-style-transfer") renderStyleTransferPreview(button.dataset.owner, button.dataset.candidate);
  if (action === "undo") {
    const previousDecision = project.decisions.pop();
    if (previousDecision) {
      project.pairIndex = previousDecision.pairIndex;
      renderPreview(false);
      showToast("직전 선택을 되돌렸습니다 · 예시");
    }
  }
  if (action === "enlarge") {
    const promptCase = project.promptCases[Number(button.dataset.case)];
    const candidate = currentPair()[button.dataset.side];
    illustrationDialog.innerHTML = `<div class="dialog-heading"><h2>${escapeMarkup(promptCase.name)} · ${button.dataset.side.toUpperCase()}</h2><button data-action="close-illustration" aria-label="이미지 확대 닫기">✕</button></div><img src="${illustrationSource(candidate, promptCase.scene)}" alt="샘플 일러스트 확대" />`;
    illustrationDialog.showModal();
  }
  if (action === "close-illustration") illustrationDialog.close();
  persistPreviewSession();
}

/** 필드 변경을 즉시 draft에 반영하되 입력 중 전체 화면을 교체하지 않습니다. */
function handleDraftInput(event) {
  const field = event.target;
  if (field.dataset.draftField) {
    previewState.draft[field.dataset.draftField] = field.dataset.draftField === "candidateCount" ? Number(field.value) : field.value;
  }
  if (field.dataset.draftCase !== undefined) {
    previewState.draft.promptCases[Number(field.dataset.draftCase)][field.dataset.field] = field.value;
  }
  const estimateElement = document.querySelector("#generation-estimate");
  if (estimateElement) estimateElement.textContent = generationEstimate();
  if (field.id === "active-project-picker") {
    previewState.currentProjectIdentifier = field.value;
    previewState.libraryFilter = "current";
    previewState.activeCaseIndex = 0;
    if (previewState.screen === "candidate-detail") {
      previewState.rankingDetail = null;
      navigatePreview("candidates");
    } else {
      renderPreview(false);
    }
  }
  if (field.id === "candidate-project-filter") {
    previewState.libraryFilter = field.value;
    renderPreview(false);
  }
  if (field.id === "candidate-sort-order") {
    previewState.candidateSortOrder = field.value;
    renderPreview(false);
  }
  if (field.id === "candidate-saved-only") {
    previewState.savedCandidatesOnly = field.checked;
    renderPreview(false);
  }
  persistPreviewSession();
}

/** 실제 생성 요청을 보내지 않고 draft에서 예시 프로젝트를 만듭니다. */
function submitProjectPreview(event) {
  if (event.target.id !== "project-preview-form") return;
  event.preventDefault();
  const identifier = `preview-project-${previewState.nextProjectSequence}`;
  previewState.nextProjectSequence += 1;
  previewState.projects.push(createSampleProject(identifier, previewState.draft.name, previewState.draft.promptCases, previewState.draft.candidateCount, 0, previewState.globalSettings));
  previewState.currentProjectIdentifier = identifier;
  previewState.libraryFilter = "current";
  previewState.activeCaseIndex = 0;
  navigatePreview("candidates");
  showToast("예시 조합을 준비했습니다 · 실제 생성은 실행하지 않습니다.");
}

/** 화면 전환 때만 위로 이동하고 비교 조작 때 Scroll은 유지합니다. */
function renderPreview(scrollToTop = true) {
  renderNavigation();
  const screenRenderers = { projects: renderProjects, create: renderProjectCreation, candidates: renderCandidates, compare: renderComparison, scope: renderPreviewScope, "global-settings": renderGlobalSettingsPreview, "project-settings": renderProjectSettingsPreview, "candidate-detail": renderCandidateDetailPreview };
  previewContent.innerHTML = screenRenderers[previewState.screen]();
  if (previewState.rankingReturnScrollY !== null) {
    window.scrollTo(0, previewState.rankingReturnScrollY);
    previewState.rankingReturnScrollY = null;
  } else if (scrollToTop) {
    window.scrollTo(0, 0);
  }
  persistPreviewSession();
}

/** 주소의 화면 이름을 제한하고 뒤로 가기를 지원합니다. */
function restorePreviewScreen() {
  let requestedScreen = window.location.hash.slice(1) || previewState.screen;
  if (requestedScreen === "ranking") {
    requestedScreen = "candidates";
    window.history.replaceState(window.history.state, "", "#candidates");
  }
  previewState.screen = ["projects", "create", "candidates", "compare", "scope", "global-settings", "project-settings", "candidate-detail"].includes(requestedScreen) ? requestedScreen : "projects";
  renderPreview();
}

/** Home의 기존 로그인 Session을 사용하고 예시 화면을 표시합니다. */
async function initializePreview() {
  restorePreviewSession();
  ensureSettingsPreviewState();
  ensureRankingPreviewState();
  try {
    const returnUrl = sessionStorage.getItem("comfy-home-general-return-url");
    if (returnUrl?.startsWith("/") && !returnUrl.startsWith("//")) document.querySelector("#general-workspace-link").href = returnUrl;
  } catch (error) {
    // 임시 저장소가 없으면 일반 생성의 기본 주소를 사용합니다.
  }
  try {
    const response = await fetch("/api/session", { cache: "no-store" });
    if (!response.ok) throw new Error("접속 상태를 확인하지 못했습니다.");
    const session = await response.json();
    document.querySelector("#preview-login").hidden = session.authenticated;
    document.querySelector("#preview-application").hidden = !session.authenticated;
    if (session.authenticated) restorePreviewScreen();
  } catch (error) {
    document.querySelector("#preview-login").hidden = false;
    document.querySelector("#preview-login-error").textContent = `${error.message} 잠시 후 새로고침해 주세요.`;
  }
}

/** 기존 인증 API로 로그인하며 비밀번호는 화면 상태에 보관하지 않습니다. */
async function signInPreview(event) {
  event.preventDefault();
  const passwordField = document.querySelector("#preview-password");
  const submitButton = event.target.querySelector("button[type=submit]");
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: passwordField.value }) });
    passwordField.value = "";
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.detail || "로그인하지 못했습니다.");
    }
    document.querySelector("#preview-login-error").textContent = "";
    await initializePreview();
  } catch (error) {
    document.querySelector("#preview-login-error").textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
}

document.addEventListener("click", handlePreviewAction);
document.addEventListener("input", handleDraftInput);
document.addEventListener("change", handleDraftInput);
document.addEventListener("submit", submitProjectPreview);
document.querySelector("#preview-login-form").addEventListener("submit", signInPreview);
window.addEventListener("hashchange", restorePreviewScreen);
initializePreview();
