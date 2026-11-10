"use strict";

/** 기본 예시에는 다양한 평가 상태를 넣고 새 프로젝트는 미평가로 시작합니다. */
function createRankingPreviewBaseline(projectIdentifier, candidates) {
  const hasExampleHistory = ["portrait-project", "garden-project"].includes(projectIdentifier);
  const examples = [
    { rating: 10080, wins: 6, losses: 4, skips: 1 },
    { rating: 10000, wins: 1, losses: 1, skips: 0 },
    { rating: 9900, wins: 0, losses: 1, skips: 0 },
    { rating: 10000, wins: 0, losses: 0, skips: 0 },
  ];
  const baseline = {};
  for (const [candidateIndex, candidate] of candidates.entries()) {
    baseline[candidate.identifier] = hasExampleHistory
      ? structuredClone(examples[candidateIndex % examples.length])
      : { rating: 10000, wins: 0, losses: 0, skips: 0 };
  }
  return baseline;
}

/** 기존 탭의 프로젝트·선택 이력을 유지한 채 순위 예시 필드만 보충합니다. */
function ensureRankingPreviewState() {
  previewState.rankingDetail ??= null;
  previewState.rankingReturnScrollY ??= null;
  for (const project of previewState.projects) {
    project.rankingBaseline ??= createRankingPreviewBaseline(project.identifier, project.candidates);
  }
}

/** 표시용 일반 Elo 예시에서도 정확한 .5는 짝수 쪽으로 반올림합니다. */
function roundRankingPreviewRating(value) {
  const lowerInteger = Math.floor(value);
  if (value - lowerInteger === 0.5) return lowerInteger % 2 === 0 ? lowerInteger : lowerInteger + 1;
  return Math.round(value);
}

/** 기본 전적과 탭의 선택 이력에서 일반 리그 점수 예시를 매번 재구성합니다. */
function calculateRankingPreview(project, decisions = project.decisions) {
  const statistics = structuredClone(project.rankingBaseline);
  for (const decision of decisions) {
    if (!Number.isInteger(decision.pairIndex)) continue;
    const firstIndex = decision.pairIndex % project.candidates.length;
    const firstCandidate = project.candidates[firstIndex];
    const secondCandidate = project.candidates[(firstIndex + 1) % project.candidates.length];
    const firstStatistics = statistics[firstCandidate.identifier];
    const secondStatistics = statistics[secondCandidate.identifier];
    if (decision.choice === "similar") {
      firstStatistics.skips += 1;
      secondStatistics.skips += 1;
      continue;
    }
    if (!["a", "b"].includes(decision.choice)) continue;
    const firstWon = decision.choice === "a";
    const firstExpected = 1 / (1 + 10 ** ((secondStatistics.rating - firstStatistics.rating) / 4000));
    firstStatistics.rating = roundRankingPreviewRating(firstStatistics.rating + 320 * (Number(firstWon) - firstExpected));
    secondStatistics.rating = roundRankingPreviewRating(secondStatistics.rating + 320 * (Number(!firstWon) - (1 - firstExpected)));
    if (firstWon) {
      firstStatistics.wins += 1;
      secondStatistics.losses += 1;
    } else {
      secondStatistics.wins += 1;
      firstStatistics.losses += 1;
    }
  }
  const entries = project.candidates.map((candidate, creationIndex) => {
    const candidateStatistics = statistics[candidate.identifier];
    const matches = candidateStatistics.wins + candidateStatistics.losses;
    return { candidate, ...candidateStatistics, matches, creationIndex };
  });
  entries.sort(compareRankingPreviewEntries);
  let evaluatedRank = 0;
  for (const entry of entries) {
    entry.rank = entry.matches ? ++evaluatedRank : null;
  }
  return entries;
}

/** 미평가를 뒤로 분리하고 Elo·승률·경기 수·생성 순·ID로 예시 목록을 정렬합니다. */
function compareRankingPreviewEntries(firstEntry, secondEntry) {
  if (Boolean(firstEntry.matches) !== Boolean(secondEntry.matches)) return firstEntry.matches ? -1 : 1;
  if (firstEntry.matches) {
    const ratingDifference = secondEntry.rating - firstEntry.rating;
    if (ratingDifference) return ratingDifference;
    const winRateDifference = secondEntry.wins / secondEntry.matches - firstEntry.wins / firstEntry.matches;
    if (winRateDifference) return winRateDifference;
    if (firstEntry.matches !== secondEntry.matches) return secondEntry.matches - firstEntry.matches;
  }
  return firstEntry.creationIndex - secondEntry.creationIndex || firstEntry.candidate.identifier.localeCompare(secondEntry.candidate.identifier);
}

/** 비교 횟수에 따른 관측 상태를 표시하며 신뢰도 수치로 해석하지 않습니다. */
function rankingPreviewStatus(entry, project) {
  if (!entry.matches) return "미평가";
  const comparisonThreshold = roundRankingPreviewRating(Math.log2(Math.max(project.candidates.length, 2))) + 3;
  return entry.matches < comparisonThreshold ? "비교 부족" : "평가 예시";
}

/** 같은 형식으로 예시 Elo를 표시하고 미평가 수치는 숨깁니다. */
function rankingRatingLabel(entry) {
  return entry.matches ? entry.rating.toLocaleString("ko-KR") : "—";
}

/** Blind에서 순위·상세의 이름·점수·성분을 함께 가립니다. */
function rankingBlindNoticeMarkup() {
  return `<section class="panel ranking-blind-notice"><h2>Blind가 켜져 있습니다</h2><p class="muted">선별에 영향을 주는 이름·순위·Elo·성분을 숨겼습니다.</p><div class="toolbar-group"><button data-ranking-action="reveal-ranking">Blind 끄고 순위 보기</button><button class="primary" data-action="navigate" data-screen="compare">선별로 돌아가기</button></div></section>`;
}

/** 현재 프로젝트의 평가된 후보와 미평가 후보를 나누어 보여줍니다. */
function renderRankingPreview() {
  const project = currentProject();
  const heading = `<div class="page-heading"><div><p class="eyebrow">${escapeMarkup(project.name)}</p><h1>그림체 순위</h1><p class="muted">이 프로젝트의 같은 평가 조건에서 비교한 조합입니다.</p></div><button class="primary" data-action="navigate" data-screen="compare">선별 이어가기 →</button></div>`;
  if (previewState.blind) return heading + rankingBlindNoticeMarkup();
  const entries = calculateRankingPreview(project);
  const evaluated = entries.filter(entry => entry.matches);
  const unrated = entries.filter(entry => !entry.matches);
  return `${heading}${conditionSummary()}<div class="ranking-summary"><div><strong>${evaluated.length} / ${entries.length}</strong><span>평가된 그림체</span></div><div><strong>${unrated.length}</strong><span>미평가</span></div><div><strong>${project.decisions.length}</strong><span>이 탭의 선택 · Skip 포함</span></div></div>
    <p class="form-note ranking-scope-note">예시 Elo·전적입니다. 기본 프로젝트에는 예시 전적이 있으며, 새 프로젝트는 미평가로 시작합니다. 여러 Prompt를 함께 보고 조합 단위로 한 번 평가합니다.</p>
    <div class="toolbar"><span class="muted">Elo 높은 순 · 미평가는 별도 표시</span><button data-action="undo" ${project.decisions.length ? "" : "disabled"}>↶ 직전 선택 되돌리기</button></div>
    ${lastRankingChangeMarkup(project)}<section class="ranking-section" aria-label="평가된 그림체"><h2>평가된 그림체 <small>${evaluated.length}</small></h2>${evaluated.length ? evaluated.map(entry => rankingEntryMarkup(project, entry)).join("") : '<p class="panel muted">아직 평가한 그림체가 없습니다. 선별에서 두 조합을 비교해 주세요.</p>'}</section>
    ${unrated.length ? `<section class="ranking-section" aria-label="미평가 그림체"><h2>미평가 <small>${unrated.length}</small></h2><p class="form-note">순위와 Elo를 표시하지 않습니다. 아직 비교하지 않았거나 Skip만 한 그림체입니다.</p>${unrated.map(entry => rankingEntryMarkup(project, entry)).join("")}</section>` : ""}`;
}

/** 여러 Prompt Thumbnail·전적·보관 여부와 상세 진입을 하나의 순위 행으로 만듭니다. */
function rankingEntryMarkup(project, entry) {
  const candidate = entry.candidate;
  const saved = project.savedCandidates.includes(candidate.identifier);
  return `<article class="ranking-entry" data-ranking-candidate="${candidate.identifier}"><div class="ranking-placement">${entry.rank || "—"}</div>
    <div class="ranking-images">${project.promptCases.slice(0, 2).map(promptCase => `<img src="${illustrationSource(candidate, promptCase.scene)}" alt="${escapeMarkup(promptCase.name)} · ${escapeMarkup(candidate.name)} 예시" />`).join("")}</div>
    <div class="ranking-description"><h3>${escapeMarkup(candidate.name)}</h3><span class="ranking-status ${entry.matches ? "" : "unrated"}">${rankingPreviewStatus(entry, project)}</span><p>${entry.matches}회 평가 · ${entry.wins}승 ${entry.losses}패 · Skip ${entry.skips}회</p><small>1세대 · ${project.promptCases.length}개 Prompt · ${saved ? "★ 보관됨" : "보관 안 함"}</small></div>
    <div class="ranking-score"><strong>${rankingRatingLabel(entry)}</strong><span>Elo · 예시</span></div>
    <div class="ranking-actions"><button data-ranking-action="open-detail" data-candidate="${candidate.identifier}">결과·전적 상세 →</button><button class="quiet" data-action="save-candidate" data-candidate="${candidate.identifier}" aria-pressed="${saved}">${saved ? "★ 보관됨" : "☆ 보관"}</button></div></article>`;
}

/** 선별의 A/B 제목 아래 최소한의 예시 점수를 표시하고 Blind에서는 생성하지 않습니다. */
function comparisonRankingSummaryMarkup(candidate) {
  if (previewState.blind) return "";
  const project = currentProject();
  const entry = calculateRankingPreview(project).find(item => item.candidate.identifier === candidate.identifier);
  return `<span class="comparison-ranking-summary">${entry.matches ? `Elo ${rankingRatingLabel(entry)} · ${entry.matches}회 평가` : "미평가 · Elo 없음"}</span><button class="candidate-detail-link" data-ranking-action="open-detail" data-candidate="${candidate.identifier}">상세 보기</button>`;
}

/** 그림체 보관함의 기존 프로젝트 필터를 유지하면서 소유 프로젝트의 점수만 요약합니다. */
function galleryRankingSummaryMarkup(project, candidate) {
  if (previewState.blind) return '<p class="gallery-ranking-summary">Blind · Elo 숨김</p>';
  const entry = calculateRankingPreview(project).find(item => item.candidate.identifier === candidate.identifier);
  return `<p class="gallery-ranking-summary">${entry.rank ? `프로젝트 내 ${entry.rank}위 · Elo ${rankingRatingLabel(entry)}` : "미평가 · 순위 없음"}</p>`;
}

/** 직전 대결의 두 조합에서 점수·순위가 어떻게 바뀌었는지 표시합니다. */
function lastRankingChangeMarkup(project) {
  if (previewState.blind || !project.decisions.length) return "";
  const decision = project.decisions.at(-1);
  const firstIndex = decision.pairIndex % project.candidates.length;
  const pair = [project.candidates[firstIndex], project.candidates[(firstIndex + 1) % project.candidates.length]];
  if (decision.choice === "similar") return '<section class="ranking-last-choice" role="status"><strong>직전 대결 · 비슷함 / Skip</strong><p>두 조합의 Elo와 평가 전적은 유지했습니다. Skip 기록만 남기고 다음 예시 대결로 이동했습니다.</p></section>';
  const beforeEntries = calculateRankingPreview(project, project.decisions.slice(0, -1));
  const afterEntries = calculateRankingPreview(project);
  const changes = pair.map(candidate => {
    const beforeEntry = beforeEntries.find(entry => entry.candidate.identifier === candidate.identifier);
    const afterEntry = afterEntries.find(entry => entry.candidate.identifier === candidate.identifier);
    return `<li><strong>${escapeMarkup(candidate.name)}</strong><span>Elo ${rankingRatingLabel(beforeEntry)} → ${rankingRatingLabel(afterEntry)} · ${beforeEntry.rank ? `${beforeEntry.rank}위` : "미평가"} → ${afterEntry.rank}위</span></li>`;
  });
  return `<section class="ranking-last-choice" role="status"><strong>직전 대결 · ${decision.choice.toUpperCase()} 선택 · 예시 변화</strong><ul>${changes.join("")}</ul></section>`;
}

/** 선택한 그림체의 모든 Prompt 결과·전적·성분을 별도 상세 화면에 표시합니다. */
function renderCandidateDetailPreview() {
  if (previewState.blind) return rankingBlindNoticeMarkup();
  const project = currentProject();
  const context = previewState.rankingDetail;
  const candidate = context?.projectIdentifier === project.identifier
    ? project.candidates.find(item => item.identifier === context.candidateIdentifier) : null;
  if (!candidate) return '<section class="panel"><h1>그림체를 선택해 주세요</h1><p class="muted">현재 프로젝트의 순위에서 상세를 열 수 있습니다.</p><button data-action="navigate" data-screen="ranking">순위 보기</button></section>';
  const entry = calculateRankingPreview(project).find(item => item.candidate.identifier === candidate.identifier);
  const saved = project.savedCandidates.includes(candidate.identifier);
  const components = settingsCatalogComponents().filter(component => candidate.components[component.identifier]);
  const returnLabel = context.returnScreen === "compare" ? "선별로 돌아가기" : context.returnScreen === "candidates" ? "그림체 목록으로" : "순위로 돌아가기";
  return `<div class="page-heading"><div><p class="eyebrow">${escapeMarkup(project.name)} · 1세대 · 예시 조합</p><h1>${escapeMarkup(candidate.name)}</h1><p class="muted">${entry.rank ? `${entry.rank}위 · ` : ""}${rankingPreviewStatus(entry, project)}</p></div><button data-ranking-action="return-from-detail">← ${returnLabel}</button></div>
    <div class="ranking-detail-statistics"><div><span>Elo · 예시</span><strong>${rankingRatingLabel(entry)}</strong></div><div><span>평가 전적</span><strong>${entry.wins}승 ${entry.losses}패</strong><small>${entry.matches}회 평가 · Skip ${entry.skips}회</small></div><button data-ranking-action="toggle-detail-save" aria-pressed="${saved}">${saved ? "★ 보관됨" : "☆ 이 그림체 보관"}</button></div>
    <p class="form-note ranking-scope-note">아래는 기존 예시 Prompt의 SVG 결과입니다. 프로젝트 설정의 Prompt나 생성 조건을 바꿔도 이 결과를 재생성하지 않습니다.</p>
    <div class="ranking-detail-layout"><section><h2>모든 Prompt 결과 <small>${project.promptCases.length}</small></h2><div class="ranking-detail-images">${project.promptCases.map((promptCase, caseIndex) => `<article class="panel"><h3>${escapeMarkup(promptCase.name)}</h3><button class="image-button" data-ranking-action="enlarge-detail" data-case="${caseIndex}" aria-label="${escapeMarkup(promptCase.name)} 결과 확대"><img src="${illustrationSource(candidate, promptCase.scene)}" alt="${escapeMarkup(promptCase.name)} 예시 결과" /></button><details><summary>Positive Prompt</summary><p>${escapeMarkup(promptCase.prompt)}</p></details></article>`).join("")}</div></section>
    <section class="panel ranking-detail-components"><h2>이 그림체의 조합</h2><p class="form-note">생성된 예시 조합의 STR입니다. 프로젝트의 향후 탐색 범위와 별개입니다.</p>${components.map(component => `<div><span>${component.kind}</span><strong>${escapeMarkup(component.name)}</strong><span>STR ${candidate.components[component.identifier][0].toFixed(1)}</span></div>`).join("")}<p class="form-note">독립 CLIP 값과 원래 조합은 유지됩니다.</p></section></div>
    <div class="form-actions ranking-detail-actions"><button data-ranking-action="return-from-detail">← ${returnLabel}</button><button class="primary" data-ranking-action="resume-comparison">선별 이어가기 →</button></div>`;
}

/** 상세를 열 때 현재 대결·Case·Scroll을 변경하지 않고 돌아올 화면을 기록합니다. */
function openRankingCandidateDetail(candidateIdentifier) {
  if (previewState.blind) return;
  previewState.rankingDetail = {
    projectIdentifier: currentProject().identifier, candidateIdentifier,
    returnScreen: previewState.screen, returnScrollY: window.scrollY,
  };
  navigatePreview("candidate-detail");
}

/** 상세 열람·보관·이미지 확대와 원래 화면 복귀만 처리합니다. */
function handleRankingPreviewAction(event) {
  const button = event.target.closest("button[data-ranking-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.rankingAction;
  if (action === "open-detail") openRankingCandidateDetail(button.dataset.candidate);
  if (action === "reveal-ranking") {
    previewState.blind = false;
    navigatePreview("ranking");
  }
  if (action === "return-from-detail") {
    const context = previewState.rankingDetail;
    previewState.rankingReturnScrollY = context?.returnScrollY || 0;
    navigatePreview(context?.returnScreen || "ranking");
  }
  if (action === "resume-comparison") {
    if (previewState.rankingDetail?.returnScreen === "compare") {
      previewState.rankingReturnScrollY = previewState.rankingDetail.returnScrollY;
    }
    navigatePreview("compare");
  }
  if (action === "toggle-detail-save") {
    const project = currentProject();
    const identifier = previewState.rankingDetail.candidateIdentifier;
    if (project.savedCandidates.includes(identifier)) project.savedCandidates = project.savedCandidates.filter(item => item !== identifier);
    else project.savedCandidates.push(identifier);
    renderPreview(false);
  }
  if (action === "enlarge-detail") {
    const project = currentProject();
    const candidate = project.candidates.find(item => item.identifier === previewState.rankingDetail.candidateIdentifier);
    const promptCase = project.promptCases[Number(button.dataset.case)];
    illustrationDialog.innerHTML = `<div class="dialog-heading"><h2>${escapeMarkup(promptCase.name)}</h2><button data-action="close-illustration" aria-label="이미지 확대 닫기">✕</button></div><img src="${illustrationSource(candidate, promptCase.scene)}" alt="${escapeMarkup(promptCase.name)} 예시 확대" />`;
    illustrationDialog.showModal();
  }
  if (action) persistPreviewSession();
}

document.addEventListener("click", handleRankingPreviewAction);
