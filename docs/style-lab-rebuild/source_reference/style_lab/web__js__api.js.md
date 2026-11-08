# Source Snapshot: web/js/api.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\js\api.js`
- Original Byte SHA-256: `2586a80c951b3a27299c66e0605a9fd23fffaef8ae75215964577584d0dddb90`
- Snapshot Text SHA-256: `50ec66e2cdb98f396628b80440f9d81f1b1914fe7d11fb773255d93e3e50679f`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// The page's one way into Python: the app window's own channel (pywebview), no server and no network.
// Python answers {ok, data} or {ok: false, error} as JSON text (app/bridge.py, App.call).
const ready = window.pywebview?.api?.call ? Promise.resolve()
  : new Promise((resolve) => window.addEventListener('pywebviewready', resolve, { once: true }));

async function call(method, path, body = null) {
  await ready;
  let payload = null;
  try {
    payload = JSON.parse(await window.pywebview.api.call(method, path, body));
  } catch (error) {
    throw new Error(`앱 내부 오류가 났습니다: ${error?.message || error}`);
  }
  if (!payload?.ok) throw new Error(payload?.error || '요청에 실패했습니다.');
  return payload.data;
}

export const get = (path) => call('GET', path);
export const post = (path, body = {}) => call('POST', path, body);

// Settings typed but not saved yet: Python keeps the newest set and saves it if the window closes first.
let draftSeq = 0;
export function keepDraft(changes) {
  post('/api/settings/draft', { seq: ++draftSeq, changes }).catch(() => {});
}
```
