"""FFmpeg의 제한된 CPU 변환과 파일에 누적하는 fragmented MP4 출력을 제공합니다."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .configuration import AppConfig


LOGGER = logging.getLogger(__name__)


class VideoEncodingError(RuntimeError):
    """자동 재시도 가능한 실패와 영구적인 입력·환경 오류를 구분합니다."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        """사용자 안내와 재시도 가능 여부를 보관합니다."""

        super().__init__(message)
        self.retryable = retryable


class VideoEncodingStopped(Exception):
    """서버 종료 또는 원본 무효화로 실패 횟수 없이 변환을 중단합니다."""


def video_stream_information(source_path: Path) -> dict:
    """새 변환 원본만 Probe하여 fps·음성 유무를 확인합니다."""

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(source_path)],
            capture_output=True, timeout=15, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exception:
        raise VideoEncodingError("영상 정보를 읽는 시간이 초과되었습니다.", True) from exception
    except OSError as exception:
        raise VideoEncodingError("ffprobe 실행 환경을 확인해 주세요.") from exception
    if result.returncode != 0:
        LOGGER.warning("VIDEO_ENCODER event=probe_failed returncode=%s detail=%s", result.returncode,
                       result.stderr.decode("utf-8", errors="replace")[-2048:])
        raise VideoEncodingError("영상 정보를 읽을 수 없습니다. 파일 손상이나 Codec을 확인해 주세요.")
    try:
        streams = json.loads(result.stdout)["streams"]
        video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
        frame_rate_parts = video_stream.get("avg_frame_rate", "0/1").split("/")
        frame_rate = float(frame_rate_parts[0]) / float(frame_rate_parts[1])
    except (ValueError, KeyError, StopIteration, ZeroDivisionError, IndexError) as exception:
        raise VideoEncodingError("영상 Track 정보를 확인할 수 없습니다.") from exception
    return {"frame_rate": frame_rate, "has_audio": any(stream["codec_type"] == "audio" for stream in streams)}


def run_video_process(
    command: list[str], output_path: Path, stop_event: threading.Event,
    timeout_seconds: int, process_started: Callable[[subprocess.Popen], None],
) -> None:
    """출력을 파일로 바로 쓰고 종료 신호·Timeout을 확인하며 자식 프로세스를 회수합니다."""

    try:
        with output_path.open("wb") as output_file:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=output_file, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            process_started(process)
            deadline = time.monotonic() + timeout_seconds
            try:
                while True:
                    if stop_event.is_set():
                        raise VideoEncodingStopped()
                    if time.monotonic() >= deadline:
                        raise VideoEncodingError("영상 변환 시간이 초과되었습니다.", True)
                    try:
                        _, error_output = process.communicate(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode != 0:
                    error_text = error_output.decode("utf-8", errors="replace").lower()
                    LOGGER.warning("VIDEO_ENCODER event=conversion_failed returncode=%s detail=%s", process.returncode, error_text[-2048:])
                    permanent_errors = ("invalid data", "unknown encoder", "decoder not found", "permission denied",
                                        "no space left", "invalid argument", "error opening output")
                    retryable = not any(error_name in error_text for error_name in permanent_errors)
                    raise VideoEncodingError("미리보기 변환에 실패했습니다. 원본이나 변환 환경을 확인해 주세요.", retryable)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
    except (FileNotFoundError, PermissionError) as exception:
        raise VideoEncodingError("FFmpeg 또는 저장 폴더 접근 권한을 확인해 주세요.") from exception
    except OSError as exception:
        raise VideoEncodingError("미리보기 저장 중 IO 오류가 발생했습니다.", exception.errno not in {13, 28}) from exception


def encode_video_preview(
    source_path: Path, output_path: Path, configuration: AppConfig,
    stop_event: threading.Event, process_started: Callable[[subprocess.Popen], None],
) -> dict:
    """원본보다 확대하지 않는 H.264/AAC 미리보기를 fragmented MP4로 누적합니다."""

    information = video_stream_information(source_path)
    frame_rate = min(configuration.video_preview_frame_rate, information["frame_rate"] or configuration.video_preview_frame_rate)
    dimension = configuration.video_preview_max_dimension
    filters = (
        f"scale=w='min(iw,{dimension})':h='min(ih,{dimension})':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,"
        f"fps={frame_rate}"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads",
        str(configuration.video_preview_encoder_threads), "-i", str(source_path),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-filter_threads", "1", "-vf", filters,
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "baseline", "-level:v", "3.1",
        "-pix_fmt", "yuv420p", "-threads", str(configuration.video_preview_encoder_threads),
        "-b:v", f"{configuration.video_preview_video_bitrate_kbps}k",
        "-maxrate", f"{configuration.video_preview_video_bitrate_kbps * 2}k",
        "-bufsize", f"{configuration.video_preview_video_bitrate_kbps * 2}k",
        "-g", str(max(1, round(frame_rate))), "-bf", "0", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", f"{configuration.video_preview_audio_bitrate_kbps}k", "-ac", "2",
        "-movflags", "+empty_moov+default_base_moof+frag_keyframe", "-frag_duration", "500000",
        "-flush_packets", "1", "-f", "mp4", "pipe:1",
    ]
    run_video_process(command, output_path, stop_event, configuration.video_preview_timeout_seconds, process_started)
    return {"frame_rate": frame_rate, "has_audio": information["has_audio"]}


def extract_video_thumbnail(source_path: Path, output_path: Path, stop_event: threading.Event) -> None:
    """영상 첫 Frame을 384px 이하 WebP로 추출하고 전체 영상을 인코딩하지 않습니다."""

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1", "-i", str(source_path),
        "-map", "0:v:0", "-frames:v", "1", "-an", "-filter_threads", "1", "-vf",
        "scale=w='min(iw,384)':h='min(ih,384)':force_original_aspect_ratio=decrease,setsar=1",
        "-c:v", "libwebp", "-quality", "75", "-threads", "1", "-f", "image2pipe", "pipe:1",
    ]
    run_video_process(command, output_path, stop_event, 30, ignore_started_process)


def ignore_started_process(process: subprocess.Popen) -> None:
    """짧은 Thumbnail 변환은 공통 종료 Event로 회수하므로 별도 등록하지 않습니다."""
