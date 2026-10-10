"""썸네일의 LRU·변경 감지·중복 생성 방지와 백그라운드 생명주기를 검증합니다."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.application import create_app
from home_server.thumbnail_cache import ThumbnailCache, ThumbnailTooLargeError, create_thumbnail_bytes
from test_application import FakeComfyClient, create_processing_test_app
from test_event_loop_responsiveness import prepare_responsiveness_jobs, verify_session_and_cancellation


def cache_current_image(cache: ThumbnailCache, image_path: Path) -> bytes:
    """현재 파일 속성으로 Cache를 조회하여 변경 감지 조건을 API와 같게 유지합니다."""

    file_stat = image_path.stat()
    return cache.get_or_create(image_path, file_stat.st_mtime_ns, file_stat.st_size)


def test_thumbnail_cache_stores_compressed_bytes_and_evicts_least_recently_used(tmp_path: Path, monkeypatch) -> None:
    """Bitmap 없이 bytes만 보관하고 조회한 항목을 살리면서 가장 오래 안 쓴 항목을 비웁니다."""

    generated_paths = []

    def tracked_thumbnail(image_path: Path) -> bytes:
        """실제 WebP 생성 횟수를 기록합니다."""

        generated_paths.append(image_path)
        return create_thumbnail_bytes(image_path)

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", tracked_thumbnail)
    cache = ThumbnailCache(maximum_entries=2)
    image_paths = []
    for image_number in range(3):
        image_path = tmp_path / f"image-{image_number}.png"
        with Image.new("RGB", (1600, 1200), (image_number * 40, 50, 60)) as image:
            image.save(image_path)
        image_paths.append(image_path)

    first_thumbnail = cache_current_image(cache, image_paths[0])
    cache_current_image(cache, image_paths[1])
    assert cache_current_image(cache, image_paths[0]) is first_thumbnail
    cache_current_image(cache, image_paths[2])
    assert len(cache._cached_thumbnails) == 2
    assert all(isinstance(thumbnail, bytes) for thumbnail in cache._cached_thumbnails.values())
    assert cache_current_image(cache, image_paths[0]) is first_thumbnail
    cache_current_image(cache, image_paths[1])
    assert generated_paths == [image_paths[0], image_paths[1], image_paths[2], image_paths[1]]
    with Image.open(BytesIO(first_thumbnail)) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert thumbnail.size == (384, 288)


def test_file_changes_and_failed_generations_do_not_return_stale_thumbnails(tmp_path: Path) -> None:
    """수정 시간·크기 변경과 손상된 이미지의 후속 수정을 새 Cache 항목으로 처리합니다."""

    cache = ThumbnailCache(3)
    image_path = tmp_path / "result.png"
    image_path.write_bytes(b"broken image")
    with pytest.raises(OSError):
        cache_current_image(cache, image_path)
    assert not cache._in_progress
    assert not cache._cached_thumbnails

    with Image.new("RGB", (100, 100), "red") as image:
        image.save(image_path)
    first_thumbnail = cache_current_image(cache, image_path)
    first_stat = image_path.stat()
    with Image.new("RGB", (100, 100), "blue") as image:
        image.save(image_path)
    os.utime(image_path, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000))
    assert cache_current_image(cache, image_path) != first_thumbnail
    image_path.unlink()
    with pytest.raises(FileNotFoundError):
        cache_current_image(cache, image_path)


def test_concurrent_requests_generate_same_thumbnail_once(tmp_path: Path, monkeypatch) -> None:
    """같은 파일의 동시 Cache miss가 변환 결과 하나를 공유합니다."""

    cache = ThumbnailCache(3)
    generation_started = threading.Event()
    release_generation = threading.Event()
    generated_paths = []

    def blocked_generation(image_path: Path) -> bytes:
        """여러 조회가 겹치도록 첫 변환을 잠시 중단합니다."""

        generated_paths.append(image_path)
        generation_started.set()
        assert release_generation.wait(3)
        return b"compressed thumbnail"

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", blocked_generation)
    with ThreadPoolExecutor(max_workers=6) as executor:
        try:
            pending_thumbnails = []
            for request_number in range(6):
                pending_thumbnails.append(executor.submit(cache.get_or_create, tmp_path / "same.png", 1, 2))
            assert generation_started.wait(1)
        finally:
            release_generation.set()
        for pending_thumbnail in pending_thumbnails:
            assert pending_thumbnail.result(timeout=2) == b"compressed thumbnail"
    assert generated_paths == [tmp_path / "same.png"]


def test_concurrent_image_decoding_is_limited(tmp_path: Path, monkeypatch) -> None:
    """서로 다른 파일의 동시 요청도 최대 두 개의 Bitmap 변환만 실행합니다."""

    cache = ThumbnailCache(10)
    release_generation = threading.Event()
    two_generations_started = threading.Event()
    count_lock = threading.Lock()
    active_count = 0
    maximum_active_count = 0

    def blocked_generation(image_path: Path) -> bytes:
        """동시 실행 수를 기록하고 테스트가 두 Slot을 확인할 때까지 기다립니다."""

        nonlocal active_count, maximum_active_count
        with count_lock:
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
            if active_count == 2:
                two_generations_started.set()
        try:
            assert release_generation.wait(3)
            return image_path.name.encode()
        finally:
            with count_lock:
                active_count -= 1

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", blocked_generation)
    with ThreadPoolExecutor(max_workers=6) as executor:
        try:
            pending_thumbnails = []
            for image_number in range(6):
                pending_thumbnails.append(executor.submit(cache.get_or_create, tmp_path / f"{image_number}.png", 1, 2))
            assert two_generations_started.wait(1)
        finally:
            release_generation.set()
        for pending_thumbnail in pending_thumbnails:
            pending_thumbnail.result(timeout=2)
    assert maximum_active_count == 2


def test_warmup_selects_latest_images_and_preserves_foreground_cache(tmp_path: Path, monkeypatch) -> None:
    """최신 파일만 채우고 먼저 요청된 썸네일을 백그라운드 작업으로 퇴출하지 않습니다."""

    generated_paths = []

    def tracked_generation(image_path: Path) -> bytes:
        """선택된 이미지 순서를 확인하고 디스크 쓰기 없이 압축 bytes를 흉내 냅니다."""

        generated_paths.append(image_path)
        return image_path.name.encode()

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", tracked_generation)
    for image_number in range(4):
        image_path = tmp_path / f"image-{image_number}.png"
        image_path.write_bytes(b"image")
        os.utime(image_path, ns=(1_000_000_000 + image_number, 1_000_000_000 + image_number))
    (tmp_path / "movie.webm").write_bytes(b"video")
    cache = ThumbnailCache(2)
    cache.start_warmup(tmp_path)
    cache._warmup_thread.join(timeout=2)
    assert not cache._warmup_thread.is_alive()
    assert generated_paths == [tmp_path / "image-3.png", tmp_path / "image-2.png"]
    assert len(cache._cached_thumbnails) == 2
    assert list(cache._cached_thumbnails)[-1][0] == tmp_path / "image-3.png"
    cache.stop_warmup()

    generated_paths.clear()
    foreground_cache = ThumbnailCache(2)
    foreground_thumbnail = foreground_cache.get_or_create(tmp_path / "foreground.png", 1, 2)
    foreground_cache.start_warmup(tmp_path)
    foreground_cache._warmup_thread.join(timeout=2)
    assert generated_paths == [tmp_path / "foreground.png", tmp_path / "image-3.png"]
    assert foreground_cache.get_or_create(tmp_path / "foreground.png", 1, 2) is foreground_thumbnail
    foreground_cache.stop_warmup()


def test_warmup_skips_corrupt_files_and_shutdown_stops_remaining_images(tmp_path: Path, monkeypatch) -> None:
    """깨진 파일을 건너뛰며 종료 요청 뒤에는 새 이미지 변환을 시작하지 않습니다."""

    cache = ThumbnailCache(10)
    generated_paths = []

    def stopping_generation(image_path: Path) -> bytes:
        """첫 파일은 실패하고 두 번째에서 종료를 요청합니다."""

        generated_paths.append(image_path)
        if len(generated_paths) == 1:
            raise OSError("broken image")
        cache._warmup_stop.set()
        return b"thumbnail"

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", stopping_generation)
    for image_number in range(4):
        (tmp_path / f"{image_number}.png").write_bytes(b"image")
    cache.start_warmup(tmp_path)
    cache._warmup_thread.join(timeout=2)
    cache.stop_warmup()
    assert len(generated_paths) == 2
    assert len(cache._cached_thumbnails) == 1
    assert not cache._in_progress


@pytest.mark.parametrize("modify_after_listing", [False, True])
def test_warmup_skips_thumbnail_created_by_user_after_listing(
    tmp_path: Path, monkeypatch, caplog, modify_after_listing: bool,
) -> None:
    """목록 확인 뒤 사용자가 채운 현재 파일 버전을 원본 재읽기 없이 건너뜁니다."""

    cache = ThumbnailCache(2)
    image_path = tmp_path / "result.png"
    with Image.new("RGB", (100, 100), "red") as image:
        image.save(image_path)
    original_file_stat = image_path.stat()
    listing_finished = threading.Event()
    resume_warmup = threading.Event()
    generated_paths = []

    def paused_image_listing(managed_directory: Path):
        """기동 시 파일 목록의 버전을 전달한 뒤 사용자 조회까지 기다립니다."""

        yield (original_file_stat.st_mtime_ns, image_path.name, image_path, original_file_stat.st_size)
        listing_finished.set()
        assert resume_warmup.wait(3)

    def tracked_generation(selected_path: Path) -> bytes:
        """사용자 조회와 Prefill에서 원본을 연 횟수를 합쳐 확인합니다."""

        generated_paths.append(selected_path)
        return create_thumbnail_bytes(selected_path)

    monkeypatch.setattr(cache, "_existing_images", paused_image_listing)
    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", tracked_generation)
    caplog.set_level("INFO", logger="home_server.thumbnail_cache")
    cache.start_warmup(tmp_path)
    try:
        assert listing_finished.wait(1)
        if modify_after_listing:
            with Image.new("RGB", (100, 100), "blue") as image:
                image.save(image_path)
            os.utime(image_path, ns=(original_file_stat.st_atime_ns, original_file_stat.st_mtime_ns + 1_000_000))
        user_thumbnail = cache_current_image(cache, image_path)
    finally:
        resume_warmup.set()
        cache._warmup_thread.join(timeout=2)
        cache.stop_warmup()
    assert generated_paths == [image_path]
    assert cache_current_image(cache, image_path) is user_thumbnail
    assert "completed=0 reused=1 skipped=0" in caplog.text


@pytest.mark.parametrize("warmup_enabled", [False, True])
def test_warmup_is_optional_and_does_not_block_session_or_cancellation(tmp_path: Path, monkeypatch, warmup_enabled: bool) -> None:
    """기동 시 채우기 옵션을 적용하고 느린 변환 중에도 Session·100건 취소에 응답합니다."""

    initial_app = create_processing_test_app(tmp_path, FakeComfyClient())
    config = replace(initial_app.state.home_server.config, thumbnail_cache_warmup_enabled=warmup_enabled)
    app = create_app(config)
    app.state.home_server.comfy = FakeComfyClient()
    prepare_responsiveness_jobs(app.state.home_server.database)
    image_path = config.managed_output_directory / "result.png"
    image_path.write_bytes(b"image")
    generation_started = threading.Event()
    release_generation = threading.Event()

    def blocked_generation(selected_path: Path) -> bytes:
        """기동 시 변환을 멈춰도 API를 사용할 수 있는지 확인합니다."""

        assert selected_path == image_path
        generation_started.set()
        assert release_generation.wait(3)
        return b"thumbnail"

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", blocked_generation)
    with TestClient(app) as client:
        try:
            if warmup_enabled:
                assert generation_started.wait(1)
            else:
                assert app.state.home_server.thumbnail_cache._warmup_thread is None
            assert client.post("/api/login", json={"password": "test"}).status_code == 200
            verify_session_and_cancellation(client)
        finally:
            release_generation.set()
    assert app.state.home_server.thumbnail_cache._warmup_thread is None


def test_preview_endpoint_reuses_cache_but_checks_authentication_and_current_file(tmp_path: Path, monkeypatch) -> None:
    """조건 없는 재요청도 변환 없이 응답하고 인증·파일 변경·삭제·이동을 매번 검사합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    image_path = app.state.home_server.config.managed_output_directory / "result.png"
    with Image.new("RGB", (100, 100), "red") as image:
        image.save(image_path)
    generated_paths = []

    def tracked_generation(selected_path: Path) -> bytes:
        """HTTP 재요청 중 실제 WebP 생성 횟수를 기록합니다."""

        generated_paths.append(selected_path)
        return create_thumbnail_bytes(selected_path)

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", tracked_generation)
    with TestClient(app) as client:
        preview_url = "/api/outputs/preview/result.png"
        assert client.get(preview_url).status_code == 401
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        first_preview = client.get(preview_url)
        repeated_preview = client.get(preview_url)
        assert first_preview.status_code == repeated_preview.status_code == 200
        assert first_preview.content == repeated_preview.content
        assert generated_paths == [image_path]
        assert client.get(preview_url, headers={"If-None-Match": first_preview.headers["etag"]}).status_code == 304
        file_stat = image_path.stat()
        with Image.new("RGB", (100, 100), "blue") as image:
            image.save(image_path)
        os.utime(image_path, ns=(file_stat.st_atime_ns, file_stat.st_mtime_ns + 1_000_000))
        changed_preview = client.get(preview_url, headers={"If-None-Match": first_preview.headers["etag"]})
        assert changed_preview.status_code == 200
        assert changed_preview.content != first_preview.content
        assert generated_paths == [image_path, image_path]
        image_path.rename(image_path.with_name("moved.png"))
        assert client.get(preview_url).status_code == 404
        assert client.get("/api/outputs/preview/moved.png").status_code == 200
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/outputs/preview/moved.png").status_code == 401


def test_oversized_image_is_rejected_without_caching(tmp_path: Path, monkeypatch) -> None:
    """파일 내용 전부를 decode하기 전에 픽셀 제한을 검사하고 기존 413 응답을 유지합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    image_path = app.state.home_server.config.managed_output_directory / "result.png"
    image_path.write_bytes(b"image")

    def oversized_generation(selected_path: Path) -> bytes:
        """픽셀 제한 오류가 HTTP 응답과 Cache 정리로 전달되는지 확인합니다."""

        raise ThumbnailTooLargeError("미리보기 크기 제한을 초과했습니다.")

    monkeypatch.setattr("home_server.thumbnail_cache.create_thumbnail_bytes", oversized_generation)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        assert client.get("/api/outputs/preview/result.png").status_code == 413
    assert not app.state.home_server.thumbnail_cache._cached_thumbnails
    assert not app.state.home_server.thumbnail_cache._in_progress


def test_thumbnail_pixel_limit_prevents_decoding(tmp_path: Path, monkeypatch) -> None:
    """작은 테스트 제한으로 실제 생성 함수가 decode 전에 크기를 거부하는지 확인합니다."""

    image_path = tmp_path / "result.png"
    with Image.new("RGB", (100, 100), "red") as image:
        image.save(image_path)
    monkeypatch.setattr("home_server.thumbnail_cache.MAX_PREVIEW_PIXELS", 9_999)

    def unexpected_transpose(source_image) -> Image.Image:
        """픽셀 제한에서 중단했다면 방향 보정·decode가 호출되면 안 됩니다."""

        pytest.fail("이미지 크기 제한 검사 뒤에 decode가 실행됐습니다.")

    monkeypatch.setattr("home_server.thumbnail_cache.ImageOps.exif_transpose", unexpected_transpose)
    with pytest.raises(ThumbnailTooLargeError):
        create_thumbnail_bytes(image_path)
