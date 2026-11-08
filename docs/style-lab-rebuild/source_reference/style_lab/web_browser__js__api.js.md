# Source Snapshot: web_browser/js/api.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\api.js`
- Original Byte SHA-256: `d96cde4783c13a0dc255dad38fc8fe67612670f1c97132242337c77dfb1508d5`
- Snapshot Text SHA-256: `1d20ff52d79967600dc3a560d274c8ad5a55b80393d1a91b69d7e0b37cc7bf84`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// Browser에서 실제 Engine을 호출하고 인증 및 비교 대상 일치를 유지합니다.
let csrfToken = '';
let sessionRequest = null;
let currentMatchSignature = null;
let selectedArchive = null;

/** 로그인된 Session의 CSRF Token을 한 번만 가져옵니다. */
async function ensureBrowserSession() {
  if (!sessionRequest) {
    sessionRequest = fetch('/api/session', { credentials: 'same-origin', cache: 'no-store' })
      .then(readJsonResponse).then((details) => { csrfToken = details.csrf_token; });
  }
  return sessionRequest;
}

/** 서버 오류를 기존 UI에서 표시할 수 있는 Error로 변환합니다. */
async function readJsonResponse(httpResponse) {
  if (httpResponse.status === 401 && location.pathname !== '/login') {
    location.assign('/login');
    throw new Error('로그인이 필요합니다.');
  }
  let payload;
  try { payload = await httpResponse.json(); }
  catch { throw new Error(`서버 요청에 실패했습니다 (HTTP ${httpResponse.status}).`); }
  if (!httpResponse.ok || !payload?.ok) throw new Error(payload?.error || '요청에 실패했습니다.');
  return payload.data;
}

/** 서버 파일 경로 대신 Browser에서 ZIP 파일을 선택합니다. */
function chooseArchiveFile() {
  return new Promise((resolve) => {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.zip,application/zip';
    fileInput.addEventListener('change', () => {
      selectedArchive = fileInput.files?.[0] || null;
      resolve(selectedArchive ? { name: selectedArchive.name } : null);
    }, { once: true });
    fileInput.addEventListener('cancel', () => resolve(null), { once: true });
    fileInput.click();
  });
}

/** 상태 조회와 변경 요청을 인증된 HTTP API로 보냅니다. */
async function call(method, path, body = null) {
  if (path === '/api/data/pick') return chooseArchiveFile();
  await ensureBrowserSession();
  let requestBody = body;
  const requestHeaders = {};
  if (method === 'POST') {
    requestHeaders['X-CSRF-Token'] = csrfToken;
    if (path === '/api/data/import') {
      if (!selectedArchive) throw new Error('ZIP 파일을 먼저 선택해 주세요.');
      const uploadForm = new FormData();
      uploadForm.append('archive', selectedArchive);
      requestBody = uploadForm;
      selectedArchive = null;
    } else {
      requestHeaders['Content-Type'] = 'application/json';
      const payload = { ...(body || {}) };
      if (path === '/api/vote' || path === '/api/skip') payload.expected_match = currentMatchSignature;
      requestBody = JSON.stringify(payload);
    }
  }
  const httpResponse = await fetch(path, {
    method, headers: requestHeaders, body: method === 'POST' ? requestBody : undefined,
    credentials: 'same-origin', cache: 'no-store',
  });
  const replyData = await readJsonResponse(httpResponse);
  if (['/api/match', '/api/vote', '/api/skip', '/api/undo'].includes(path)) {
    currentMatchSignature = replyData?.kind && replyData.a && replyData.b
      ? { kind: replyData.kind, a: replyData.a.id, b: replyData.b.id } : null;
  }
  return replyData;
}

/** 인증된 GET 요청을 보냅니다. */
export function get(path) { return call('GET', path); }

/** CSRF 보호를 적용한 POST 요청을 보냅니다. */
export function post(path, body = {}) { return call('POST', path, body); }

/** 미완성 입력은 기기별 UI에 두고 기존 change 이벤트에서 저장합니다. */
export function keepDraft(changes) {}

/** 실제 데이터 ZIP을 Browser 다운로드로 전달합니다. */
export async function downloadArchiveFile() {
  await ensureBrowserSession();
  const httpResponse = await fetch('/api/data/export', {
    method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, credentials: 'same-origin',
  });
  if (!httpResponse.ok) { await readJsonResponse(httpResponse); return; }
  const archiveBlob = await httpResponse.blob();
  const archiveUrl = URL.createObjectURL(archiveBlob);
  const downloadLink = document.createElement('a');
  downloadLink.href = archiveUrl;
  downloadLink.download = 'style-lab-data.zip';
  downloadLink.click();
  setTimeout(() => URL.revokeObjectURL(archiveUrl), 60_000);
}
```
