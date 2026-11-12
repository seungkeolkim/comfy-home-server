"use strict";

/** 두 작업 공간이 같은 로그인과 안전한 복귀 주소를 사용하도록 연결합니다. */
window.ComfyWorkspaceShell = (() => {
  const loginReturnStorageKey = "comfy-home-workspace-login-return";
  const styleReturnStorageKey = "comfy-home-style-return-url";
  const requestedStyleWorkspace = new URLSearchParams(window.location.search).get("workspace") === "style" ||
    Boolean(validatedStyleReturnUrl(readStoredReturnUrl(loginReturnStorageKey)));

  /** 같은 사이트의 스타일 화면만 로그인 후 복귀 대상으로 허용합니다. */
  function validatedStyleReturnUrl(candidateUrl) {
    try {
      const destination = new URL(candidateUrl, window.location.origin);
      if (destination.origin !== window.location.origin || !["/style", "/style-preview"].includes(destination.pathname)) return null;
      return destination.pathname + destination.search + destination.hash;
    } catch (error) {
      return null;
    }
  }

  /** 일반 생성의 기존 화면 주소만 복귀 링크로 사용하고 로그인 복귀 순환을 막습니다. */
  function validatedGeneralReturnUrl(candidateUrl) {
    try {
      const destination = new URL(candidateUrl, window.location.origin);
      if (destination.origin !== window.location.origin || destination.pathname !== "/" || destination.searchParams.has("workspace")) return null;
      return destination.pathname + destination.search + destination.hash;
    } catch (error) {
      return null;
    }
  }

  /** 저장소가 제한된 Browser에서도 기본 주소로 작업 공간을 전환합니다. */
  function readStoredReturnUrl(storageKey) {
    try {
      return sessionStorage.getItem(storageKey);
    } catch (error) {
      return null;
    }
  }

  /** 현재 스타일 화면과 초안을 보관하고 공통 로그인 화면으로 이동합니다. */
  function redirectToLogin() {
    const returnUrl = validatedStyleReturnUrl(window.location.href) || "/style";
    try {
      sessionStorage.setItem(loginReturnStorageKey, returnUrl);
      sessionStorage.setItem(styleReturnStorageKey, returnUrl);
    } catch (error) {
      // 복귀 정보 저장이 불가능해도 공통 로그인은 사용할 수 있습니다.
    }
    window.location.replace("/?workspace=style");
  }

  /** 공통 로그인으로 들어온 스타일 요청만 인증 후 원래 화면으로 돌려보냅니다. */
  function resumeWorkspaceAfterLogin() {
    if (!requestedStyleWorkspace) return false;
    const returnUrl = validatedStyleReturnUrl(readStoredReturnUrl(loginReturnStorageKey)) || "/style";
    try {
      sessionStorage.removeItem(loginReturnStorageKey);
    } catch (error) {
      // 로그인 성공 여부는 Browser 저장소 접근과 무관합니다.
    }
    window.location.replace(returnUrl);
    return true;
  }

  /** 같은 탭의 마지막 스타일 화면을 두 화면의 동일한 전환 토글에 연결합니다. */
  function configureWorkspaceLinks() {
    const styleDestination = validatedStyleReturnUrl(readStoredReturnUrl(styleReturnStorageKey)) || "/style";
    for (const styleLink of document.querySelectorAll("[data-workspace-style]")) {
      if (!styleLink.hasAttribute("aria-current")) styleLink.href = styleDestination;
    }
    const generalLink = document.querySelector("#general-workspace-link");
    const generalDestination = validatedGeneralReturnUrl(readStoredReturnUrl("comfy-home-general-return-url"));
    if (generalLink && generalDestination) generalLink.href = generalDestination;
  }

  /** 스타일 화면의 현재 위치를 토글 왕복과 로그인 복구에 사용할 수 있게 남깁니다. */
  function rememberStyleLocation() {
    const returnUrl = validatedStyleReturnUrl(window.location.href);
    if (!returnUrl) return;
    try {
      sessionStorage.setItem(styleReturnStorageKey, returnUrl);
    } catch (error) {
      // 현재 프로젝트의 저장과 화면 이동은 그대로 허용합니다.
    }
  }

  configureWorkspaceLinks();
  document.querySelector('.workspace-switch [aria-current="page"]')?.addEventListener("click", event => event.preventDefault());
  window.addEventListener("hashchange", rememberStyleLocation);
  window.addEventListener("pagehide", rememberStyleLocation);
  return { redirectToLogin, resumeWorkspaceAfterLogin, configureWorkspaceLinks, rememberStyleLocation };
})();
