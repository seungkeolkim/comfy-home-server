"""영상 공유 Queue·영속 저장·재시도·원본 정합성과 실제 FFmpeg 출력을 검증합니다."""

import asyncio
import json
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.application import create_app, _refresh_requests
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from home_server.database import Database
from home_server.output_catalog import OutputCatalog
from home_server.video_encoding import VideoEncodingError, VideoEncodingStopped
from home_server.video_preview_cache import VideoPreviewCache
from test_application import FakeComfyClient


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg가 필요합니다.")


def cache_configuration(tmp_path: Path, **changes) -> AppConfig:
    """실제 생성물과 분리된 임시 원본·Runtime 설정을 준비합니다."""

    configuration = AppConfig(
        host="127.0.0.1", port=8388, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=tmp_path / "outputs", managed_output_directory=tmp_path / "outputs" / "managed",
        runtime_directory=tmp_path / "runtime", workflow_directory=PROJECT_DIRECTORY / "data/workflows",
        video_preview_warmup_enabled=False, video_preview_worker_count=2,
    )
    configuration.managed_output_directory.mkdir(parents=True)
    configuration.runtime_directory.mkdir()
    return replace(configuration, **changes)


def create_cache(configuration: AppConfig, number_of_sources: int = 1) -> tuple[VideoPreviewCache, list[int]]:
    """독립 DB Catalog에 테스트 영상 후보를 등록합니다."""

    database = Database(configuration.runtime_directory / "home_server.sqlite3")
    for source_index in range(number_of_sources):
        (configuration.managed_output_directory / f"video-{source_index:03}.mp4").write_bytes(b"test source")
    catalog = OutputCatalog(database.database_path)
    catalog.synchronize(configuration.managed_output_directory)
    return VideoPreviewCache(configuration, catalog), [row["output_id"] for row in catalog.iter_video_sources()]


def wait_for_state(cache: VideoPreviewCache, output_id: int, expected_state: str, timeout: float = 10) -> dict:
    """Worker 상태를 제한 시간 동안 확인하고 실패 원인을 Assertion에 남깁니다."""

    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = cache.describe(cache.source(output_id))
        if state["state"] == expected_state:
            return state
        time.sleep(0.01)
    raise AssertionError(f"Expected {expected_state}: {state}")


def fake_encoding(source_path, output_path, configuration, stop_event, process_started) -> dict:
    """Queue 검증에서는 외부 Codec 비용 없이 식별 가능한 출력만 생성합니다."""

    output_path.write_bytes(b"encoded-preview" * 200)
    return {"has_audio": False, "frame_rate": 12}


def test_startup_fills_all_sources_beyond_queue_limit_and_workers_stay_alive(tmp_path, monkeypatch):
    """Producer는 전체 접수 후 종료하고 Worker는 빈 Queue에서도 살아 있어야 합니다."""

    configuration = cache_configuration(tmp_path, video_preview_warmup_enabled=True, video_preview_queue_max_entries=1)
    cache, output_ids = create_cache(configuration, 6)
    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", fake_encoding)
    cache.start()
    try:
        for output_id in output_ids:
            wait_for_state(cache, output_id, "ready")
        cache._producer.join(timeout=2)
        assert not cache._producer.is_alive()
        assert all(worker.is_alive() for worker in cache._workers)
        assert cache._scheduler.is_alive()
        assert len(list((cache.root / "previews").glob("*/preview.mp4"))) == 6
        assert not cache._tasks
    finally:
        cache.stop()


def test_shared_conversion_pool_limit_and_queue_priority(tmp_path, monkeypatch):
    """동일 Key는 공유하고 다른 원본의 동시 FFmpeg 수는 설정한 Worker 수 이내입니다."""

    cache, output_ids = create_cache(cache_configuration(tmp_path), 4)
    release = threading.Event()
    concurrency_lock = threading.Lock()
    counters = {"active": 0, "maximum": 0, "calls": 0}

    def blocked_encoding(*arguments):
        """두 Worker가 실행되는 동안 대기하여 중복 실행 여부를 관찰합니다."""

        with concurrency_lock:
            counters["active"] += 1
            counters["maximum"] = max(counters["maximum"], counters["active"])
            counters["calls"] += 1
        release.wait(timeout=5)
        try:
            return fake_encoding(*arguments)
        finally:
            with concurrency_lock:
                counters["active"] -= 1

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", blocked_encoding)
    cache.start()
    try:
        for output_id in output_ids:
            for _ in range(4):
                cache.enqueue(output_id, priority=2)
        cache.enqueue(output_ids[-1], priority=0)
        assert cache._tasks[cache.source(output_ids[-1]).identifier].priority == 0
        deadline = time.monotonic() + 3
        while counters["active"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert counters["active"] == counters["maximum"] == 2
        release.set()
        for output_id in output_ids:
            wait_for_state(cache, output_id, "ready")
        assert counters["calls"] == 4
    finally:
        release.set()
        cache.stop()


def test_completed_preview_survives_settings_change_move_and_thumbnail_eviction(tmp_path, monkeypatch):
    """출력 설정 변경·이동·Thumbnail 퇴출로 완료된 저용량 영상을 다시 만들지 않습니다."""

    configuration = cache_configuration(tmp_path, thumbnail_cache_max_entries=1)
    cache, output_ids = create_cache(configuration, 2)
    encoding_calls = []

    def tracked_encoding(*arguments):
        """새 변환만 기록하고 완료본 재사용 여부를 확인합니다."""

        encoding_calls.append(arguments[0])
        return fake_encoding(*arguments)

    def thumbnail_encoding(source_path, output_path, stop_event):
        """실제 WebP bytes를 작은 독립 파일로 만듭니다."""

        with Image.new("RGB", (20, 10), "red") as image:
            image.save(output_path, format="WEBP")

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", tracked_encoding)
    monkeypatch.setattr("home_server.video_preview_cache.extract_video_thumbnail", thumbnail_encoding)
    cache.start()
    try:
        for output_id in output_ids:
            cache.enqueue(output_id)
            wait_for_state(cache, output_id, "ready")
            cache.thumbnail(output_id)
        assert len(list((cache.root / "thumbnails").glob("*/poster.webp"))) == 1
        assert len(list((cache.root / "previews").glob("*/preview.mp4"))) == 2
        source = cache.source(output_ids[0])
        preview_path = cache.complete_file(source)
        original_stat = preview_path.stat()
        destination = source.path.with_name("moved.mp4")
        cache.catalog.move_file(source.relative_path, destination.name, lambda: source.path.rename(destination))
        assert cache.source(source.output_id).identifier == source.identifier
        cache.configuration = replace(configuration, video_preview_frame_rate=6, video_preview_max_dimension=320)
        cache.enqueue(source.output_id, retry=True)
        assert preview_path.stat().st_mtime_ns == original_stat.st_mtime_ns
        assert len(encoding_calls) == 2
        cache.cleanup()
        assert preview_path.exists()
    finally:
        cache.stop()


def test_transient_failure_retries_without_occupying_worker_and_persists_limit(tmp_path, monkeypatch):
    """지연 중에는 다른 영상을 처리하고 총 시도 상한은 재기동 뒤에도 보존합니다."""

    configuration = cache_configuration(
        tmp_path, video_preview_worker_count=1, video_preview_retry_initial_delay_seconds=0.05,
        video_preview_retry_max_delay_seconds=0.1,
    )
    cache, output_ids = create_cache(configuration, 2)
    failing_path = cache.source(output_ids[0]).path
    encoding_calls = []

    def failing_encoding(*arguments):
        """특정 원본만 일시 오류를 반복하도록 합니다."""

        encoding_calls.append(arguments[0])
        if arguments[0] == failing_path:
            raise VideoEncodingError("일시 IO 오류", True)
        return fake_encoding(*arguments)

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", failing_encoding)
    cache.start()
    try:
        cache.enqueue(output_ids[0])
        wait_for_state(cache, output_ids[0], "retry_wait")
        cache.enqueue(output_ids[1])
        wait_for_state(cache, output_ids[1], "ready")
        failure = wait_for_state(cache, output_ids[0], "failed")
        assert failure["attempts"] == 3
        assert encoding_calls.count(failing_path) == 3
    finally:
        cache.stop()
    restarted = VideoPreviewCache(replace(configuration, video_preview_warmup_enabled=True), cache.catalog)
    restarted.start()
    try:
        restarted._producer.join(timeout=3)
        assert restarted.enqueue(output_ids[0])["state"] == "failed"
        assert encoding_calls.count(failing_path) == 3
        monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", fake_encoding)
        restarted.enqueue(output_ids[0], retry=True)
        wait_for_state(restarted, output_ids[0], "ready")
    finally:
        restarted.stop()


def test_disconnect_keeps_conversion_running_and_manual_deletion_cleans_both_areas(tmp_path, monkeypatch):
    """Reader를 닫아도 변환이 끝나고 원본 삭제 때 두 파생 영역을 정리합니다."""

    cache, output_ids = create_cache(cache_configuration(tmp_path))
    release = threading.Event()

    def streaming_encoding(*arguments):
        """첫 bytes 뒤에서 대기해 실제 Reader 종료와 변환 수명을 분리합니다."""

        arguments[1].write_bytes(b"first fragment" * 200)
        release.wait(timeout=5)
        return fake_encoding(*arguments)

    async def read_then_disconnect(source):
        """첫 Chunk만 받은 뒤 연결을 닫습니다."""

        reader = cache.stream(source)
        assert await anext(reader)
        await reader.aclose()

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", streaming_encoding)
    cache.start()
    try:
        cache.enqueue(output_ids[0])
        wait_for_state(cache, output_ids[0], "converting")
        source = cache.source(output_ids[0])
        asyncio.run(read_then_disconnect(source))
        assert cache.describe(source)["state"] == "converting"
        release.set()
        wait_for_state(cache, output_ids[0], "ready")
        thumbnail_directory = cache.directory("thumbnails", source.identifier, create=True)
        cache._write_metadata(thumbnail_directory, source.metadata())
        (thumbnail_directory / "poster.webp").write_bytes(b"poster")
        source.path.unlink()
        cache.cleanup()
        assert not cache.directory("previews", source.identifier).exists()
        assert not thumbnail_directory.exists()
    finally:
        release.set()
        cache.stop()


def test_shutdown_interrupts_encoding_and_joins_all_workers(tmp_path, monkeypatch):
    """Queue가 남아도 종료를 무한 대기하지 않고 자식 변환과 Worker를 회수합니다."""

    cache, output_ids = create_cache(cache_configuration(tmp_path, video_preview_shutdown_timeout_seconds=0.05))

    def encoding_until_stopped(*arguments):
        """Stop Event까지 기다리는 긴 변환을 재현합니다."""

        arguments[3].wait(timeout=5)
        raise VideoEncodingStopped()

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", encoding_until_stopped)
    cache.start()
    cache.enqueue(output_ids[0])
    wait_for_state(cache, output_ids[0], "converting")
    workers = list(cache._workers)
    cache.stop()
    assert not any(worker.is_alive() for worker in workers)
    assert not cache._scheduler.is_alive()
    assert not cache._producer.is_alive()
    assert not cache.describe(cache.source(output_ids[0])).get("error")


def test_request_completion_commits_catalog_before_automatic_enqueue(tmp_path, monkeypatch):
    """상위 작업이 실행 중이어도 완료된 하위 요청의 영상만 자동으로 변환합니다."""

    configuration = cache_configuration(tmp_path)
    app = create_app(configuration)
    server = app.state.home_server
    fake_comfy = FakeComfyClient()
    server.comfy = fake_comfy
    source_directory = configuration.managed_output_directory / "minimax_h3"
    source_directory.mkdir()
    (source_directory / "first.mp4").write_bytes(b"first video")
    requests = []
    for request_index in range(2):
        requests.append({"request_id": f"request-{request_index}", "status": "pending",
                         "output_stem": f"minimax_h3/output-{request_index}", "detail": {"body": {"prompt": "test"}}})
    server.database.add_job("job", "minimax_h3", "completion", requests)
    server.database.set_request_accepted("request-0", "prompt-1", {})
    server.database.set_request_accepted("request-1", "prompt-2", {})
    fake_comfy.submissions = [({}, {}), ({}, {})]
    fake_comfy.history_records["prompt-1"] = {
        "status": {"status_str": "success"},
        "outputs": {"2568": {"gifs": [{"filename": "first.mp4", "subfolder": "managed/minimax_h3", "type": "output"}]}},
    }
    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", fake_encoding)
    server.video_previews.start()
    try:
        asyncio.run(_refresh_requests(server))
        video_id = server.output_catalog.video_output_id("minimax_h3/first.mp4")
        wait_for_state(server.video_previews, video_id, "ready")
        job = server.database.get_job("job")
        assert job["status_counts"]["completed"] == 1
        assert job["status_counts"]["pending"] == 1
        assert len(list((server.video_previews.root / "previews").glob("*/preview.mp4"))) == 1
    finally:
        server.video_previews.stop()


def test_startup_preserves_completed_outputs_and_defers_cleanup_for_missing_root(tmp_path, monkeypatch):
    """재기동·설정 변경은 완료본을 유지하고 원본 Root 부재를 일괄 삭제로 오판하지 않습니다."""

    configuration = cache_configuration(tmp_path)
    cache, output_ids = create_cache(configuration)
    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", fake_encoding)
    cache.start()
    try:
        cache.enqueue(output_ids[0])
        wait_for_state(cache, output_ids[0], "ready")
        original_preview = cache.complete_file(cache.source(output_ids[0]))
        preview_modified_at = original_preview.stat().st_mtime_ns
    finally:
        cache.stop()
    restarted = VideoPreviewCache(replace(configuration, video_preview_frame_rate=6, video_preview_warmup_enabled=True), cache.catalog)

    def reject_reencoding(*arguments):
        """완료본이 있는데 설정 변경 때문에 변환을 다시 실행하면 실패합니다."""

        raise AssertionError("Completed preview must not be encoded again")

    monkeypatch.setattr("home_server.video_preview_cache.encode_video_preview", reject_reencoding)
    restarted.start()
    try:
        restarted._producer.join(timeout=3)
        assert restarted.describe(restarted.source(output_ids[0]))["state"] == "ready"
        assert original_preview.stat().st_mtime_ns == preview_modified_at
        moved_root = configuration.managed_output_directory.with_name("temporarily-unmounted")
        configuration.managed_output_directory.rename(moved_root)
        try:
            restarted.cleanup()
            assert original_preview.exists()
        finally:
            moved_root.rename(configuration.managed_output_directory)
    finally:
        restarted.stop()


def create_real_video(output_path: Path, with_audio: bool = False) -> None:
    """짧은 회귀 검증용 실제 동영상만 생성하고 운영 원본은 사용하지 않습니다."""

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24"]
    if with_audio:
        command.extend(["-f", "lavfi", "-i", "sine=frequency=500:sample_rate=44100", "-c:a", "aac"])
    command.extend(["-t", "2", "-c:v", "libx264", "-threads", "1", "-y", str(output_path)])
    subprocess.run(command, check=True, capture_output=True, timeout=20)


@pytest.mark.parametrize("with_audio", [False, True])
def test_actual_encoding_authentication_range_and_thumbnail(tmp_path, with_audio):
    """실제 FFmpeg로 12fps·음성·WebP와 인증·Range·삭제 접근 차단을 검증합니다."""

    configuration = cache_configuration(tmp_path)
    video_path = configuration.managed_output_directory / "real.mp4"
    create_real_video(video_path, with_audio)
    app = create_app(configuration)
    app.state.home_server.comfy = FakeComfyClient()
    cache = app.state.home_server.video_previews
    output_id = next(cache.catalog.iter_video_sources())["output_id"]
    api_path = f"/api/outputs/{output_id}/video-preview"
    with TestClient(app) as client:
        assert client.post(api_path, json={}).status_code == 401
        client.post("/api/login", json={"password": "test"})
        thumbnail = client.get("/api/outputs/preview/real.mp4")
        assert thumbnail.status_code == 200
        with Image.open(BytesIO(thumbnail.content)) as image:
            assert image.format == "WEBP" and max(image.size) <= 384
        assert not cache._tasks
        assert client.post(api_path, json={}).status_code == 200
        ready = wait_for_state(cache, output_id, "ready")
        preview_path = cache.complete_file(cache.source(output_id))
        information = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(preview_path),
        ]))
        video_stream = next(stream for stream in information["streams"] if stream["codec_type"] == "video")
        assert video_stream["r_frame_rate"] == "12/1"
        assert abs(float(video_stream["duration"]) - 2) < 0.1
        assert video_stream["codec_name"] == "h264"
        assert any(stream["codec_type"] == "audio" for stream in information["streams"]) == with_audio
        stream_path = f'{api_path}/stream?version={ready["identifier"]}'
        complete = client.get(stream_path)
        assert complete.status_code == 200
        assert client.get(stream_path, headers={"Range": "bytes=0-31"}).content == complete.content[:32]
        assert client.get(stream_path, headers={"Range": "bytes=0-31"}).status_code == 206
        assert client.get(stream_path, headers={"If-None-Match": complete.headers["etag"]}).status_code == 304
        video_path.unlink()
        assert client.get(stream_path).status_code == 404
        assert client.get("/api/outputs/preview/real.mp4").status_code == 404
