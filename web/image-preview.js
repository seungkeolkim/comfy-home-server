"use strict";

/** 일반 결과물과 스타일 구성이 같은 이미지 Viewer·Cache 경로를 사용합니다. */
window.ComfyHomeImagePreview = (() => {
  /** 관리 상대 경로의 폴더 구분을 유지하며 URL을 안전하게 만듭니다. */
  function encodedOutputPath(relativePath) {
    return relativePath.split("/").map(encodeURIComponent).join("/");
  }

  /** Thumbnail Cache와 원본 파일의 기존 CHS API를 선택합니다. */
  function imageSource(relativePath, showOriginalFiles = false) {
    return `${showOriginalFiles ? "/media/" : "/api/outputs/preview/"}${encodedOutputPath(relativePath)}`;
  }

  /** CHS의 기존 기준대로 Desktop은 원본, Mobile은 압축 Preview부터 엽니다. */
  function defaultOriginalMode() {
    return window.matchMedia("(min-width: 801px)").matches;
  }

  /** 내부에서 시작한 Drag를 바깥 클릭으로 오인하지 않도록 좌표를 확인합니다. */
  function isPreviewBackdropEvent(event) {
    if (event.target !== event.currentTarget) return false;
    const bounds = event.currentTarget.getBoundingClientRect();
    return event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom;
  }

  /** CHS 이미지·영상 Viewer의 닫기·Escape·외부 클릭·방향키 처리를 공유합니다. */
  function bindDialogEvents({ dialog, closeButton, state, onClose, onNavigate, onOriginalChange }) {
    /** 끝에 도달해 이동 버튼이 비활성화돼도 Focus를 Viewer 안에 유지합니다. */
    function navigateWithinDialog(direction) {
      onNavigate(direction);
      const focused = document.activeElement;
      if (dialog.open && (!dialog.contains(focused) || focused.disabled)) {
        const availableButton = dialog.querySelector("[data-preview-previous]:not(:disabled), [data-preview-next]:not(:disabled)");
        (availableButton || closeButton || dialog).focus({ preventScroll: true });
      }
    }
    dialog.addEventListener("change", event => {
      if (event.target.matches("[data-preview-original-toggle]")) onOriginalChange(event.target.checked);
    });
    dialog.addEventListener("click", event => {
      const button = event.target.closest("[data-preview-previous], [data-preview-next]");
      if (button && !button.disabled) navigateWithinDialog(button.hasAttribute("data-preview-previous") ? "previous" : "next");
    });
    dialog.addEventListener("keydown", event => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest("video, input, textarea, select, [contenteditable=true]")) return;
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      navigateWithinDialog(event.key === "ArrowLeft" ? "previous" : "next");
    });
    closeButton?.addEventListener("click", () => onClose());
    dialog.addEventListener("pointerdown", event => {
      state.pointerStartedOutside = isPreviewBackdropEvent(event);
    });
    dialog.addEventListener("pointercancel", () => {
      state.pointerStartedOutside = false;
    });
    dialog.addEventListener("click", event => {
      const clickedBackdrop = state.pointerStartedOutside && isPreviewBackdropEvent(event);
      state.pointerStartedOutside = false;
      if (clickedBackdrop) onClose();
    });
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      onClose();
    });
    dialog.addEventListener("close", () => {
      if (!dialog.open && state.outputId !== null) onClose();
    });
  }

  /** 기존 CHS 이미지 창에서 화면별 탐색 범위만 분리한 공통 Controller입니다. */
  function createImagePreviewController({ dialog, image, title, originalLink, status, notice, originalToggle, state }) {
    let showOriginalFiles = false;

    /** 늦은 Load·Error가 닫은 Viewer의 상태를 바꾸지 않게 합니다. */
    function clearImageStatus() {
      if (state.outputId !== null) status.textContent = "";
    }

    /** Mobile Preview 오류와 원본 오류를 CHS의 기존 안내로 구분합니다. */
    function reportImageError() {
      if (state.outputId === null) return;
      status.textContent = showOriginalFiles
        ? "원본 이미지를 불러올 수 없습니다."
        : "이미지 미리보기를 불러올 수 없습니다. 원본 보기로 확인해 주세요.";
    }

    /** 선택한 보기 모드만 바꾸고 현재 조합·Prompt·탐색 범위는 유지합니다. */
    function loadImageSource(outputFile, originalMode) {
      showOriginalFiles = originalMode;
      status.textContent = originalMode ? "원본 이미지를 불러오는 중…" : "미리보기를 불러오는 중…";
      image.alt = outputFile.name || outputFile.path.split("/").at(-1);
      image.src = imageSource(outputFile.path, originalMode);
      if (originalToggle) originalToggle.checked = originalMode;
    }

    /** 원본 링크·제목·이미지 상태를 구성하고 같은 Dialog를 열거나 갱신합니다. */
    function openImage(outputFile, opener, originalMode) {
      state.outputId = outputFile.output_id ?? outputFile.path;
      state.opener = opener;
      title.textContent = outputFile.name || outputFile.path.split("/").at(-1);
      originalLink.href = imageSource(outputFile.path, true);
      notice?.classList.add("hidden");
      loadImageSource(outputFile, originalMode);
      if (!dialog.open) dialog.showModal();
    }

    /** 소스 연결을 해제하고 재사용할 Viewer에 이전 파일을 남기지 않습니다. */
    function clearImage() {
      state.pointerStartedOutside = false;
      state.outputId = null;
      image.removeAttribute("src");
      image.alt = "";
      originalLink.removeAttribute("href");
      status.textContent = "";
      notice?.classList.add("hidden");
    }

    image.addEventListener("load", clearImageStatus);
    image.addEventListener("error", reportImageError);
    return { openImage, loadImageSource, clearImage };
  }

  return { encodedOutputPath, imageSource, defaultOriginalMode, bindDialogEvents, createImagePreviewController };
})();
