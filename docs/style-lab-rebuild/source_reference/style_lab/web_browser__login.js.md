# Source Snapshot: web_browser/login.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\login.js`
- Original Byte SHA-256: `aafa6e51daff9a9256cf0e828b89ad95aeffa7abe831b65c00618bd3f9f5d72c`
- Snapshot Text SHA-256: `aafa6e51daff9a9256cf0e828b89ad95aeffa7abe831b65c00618bd3f9f5d72c`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
const loginForm = document.getElementById('browser-login-form');
const passwordInput = document.getElementById('browser-login-password');
const submitButton = document.getElementById('browser-login-submit');
const errorMessage = document.getElementById('browser-login-error');

/** 비밀번호를 전송하고 로그인한 Session에서 앱을 엽니다. */
async function submitLogin(event) {
  event.preventDefault();
  if (submitButton.disabled) return;
  submitButton.disabled = true;
  errorMessage.textContent = '';
  try {
    const loginResponse = await fetch('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ password: passwordInput.value }),
    });
    const loginResult = await loginResponse.json();
    if (!loginResponse.ok || !loginResult.ok) throw new Error(loginResult.error || '로그인에 실패했습니다.');
    passwordInput.value = '';
    location.replace('/#/arena');
  } catch (error) { errorMessage.textContent = error.message; }
  finally { submitButton.disabled = false; }
}

loginForm.addEventListener('submit', submitLogin);
```
