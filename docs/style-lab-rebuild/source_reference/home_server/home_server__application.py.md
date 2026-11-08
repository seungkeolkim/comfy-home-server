# Source Snapshot: home_server/application.py

- Source: `C:\Users\azzib\Desktop\workspace_local\comfy-home-server\home_server\application.py`
- Original Byte SHA-256: `4e21ec74e3892ec133fd690466ddae593d42ff9b2a439fbaec38abd7786d08e7`
- Snapshot Text SHA-256: `7f4d8127a86dbab0ef3b216f6a2b5449b001804d29992d4645dec0615b8094cd`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 선택 Symbol 발췌. 원래 전체 파일의 대체본이 아닙니다.
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
class BatchInput(BaseModel):
    """ComfyUI에 제출할 Batch의 공통 옵션입니다."""

    workflow: str
    description: str = Field(default="", max_length=200)
    folder_id: str | None = Field(default=None, min_length=1, max_length=64)
    body: dict[str, Any]
    selected_tag_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1, le=100)
    settings: dict[str, Any] = Field(default_factory=dict)
    loras: list[dict[str, Any]] = Field(default_factory=list)
    prompt_preset_id: str | None = Field(default=None, max_length=64)
    lora_preset_id: str | None = Field(default=None, max_length=64)
    lora_preset_name: str | None = Field(default=None, max_length=120)
    upload_ids: list[str] = Field(default_factory=list)
    output_ids: list[int] = Field(default_factory=list, max_length=100)
    input_scope: Literal["single", "folder", "job"] | None = None
    input_directory: str | None = None
    input_job_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_job_input(self) -> BatchInput:
        """작업 입력 출처를 MiniMax 서버 이미지 선택과 함께 명시적으로 전달하게 합니다."""

        if self.input_scope == "job":
            if self.workflow != "minimax_h3" or not self.input_job_id or not self.output_ids or self.upload_ids:
                raise ValueError("작업 결과 입력에는 원본 작업과 서버 이미지 1~100장을 선택해 주세요.")
        elif self.input_job_id is not None:
            raise ValueError("작업 결과 선택에서만 원본 작업을 지정할 수 있습니다.")
        return self

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        """작업 설명의 공백을 정리하고 여러 줄 입력을 거부합니다."""

        return normalize_job_description(value)


def store_batch_requests(
    server: HomeServer, payload: BatchInput, selected_tags: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """이미지 존재 확인·요청 구성·DB 저장을 Worker에서 함께 완료합니다."""

    upload_ids = payload.upload_ids if payload.workflow == "minimax_h3" else [None] * payload.count
    if len(upload_ids) > 100:
        raise HTTPException(422, "한 Batch의 요청은 최대 100개입니다.")
    for upload_id in payload.upload_ids:
        if not any(server.upload_directory.glob(f"{upload_id}.*")):
            raise HTTPException(422, f"업로드 파일이 없습니다: {upload_id}")

    image_snapshots = []
    try:
        request_settings = dict(payload.settings)
        if payload.output_ids:
            image_snapshots = snapshot_input_images(
                server.config.managed_output_directory, server.output_catalog, server.upload_directory,
                payload.output_ids, payload.input_scope, payload.input_directory, payload.input_job_id,
            )
            upload_ids = [image_record["upload_id"] for image_record in image_snapshots]
            reference_image = image_snapshots[0]
            request_settings.update({
                "input_scope": payload.input_scope, "input_directory": payload.input_directory,
                "resolution_reference": {key: reference_image[key] for key in ("output_id", "path", "width", "height")},
                "resize_policy": "fit_pad",
            })
            if payload.input_scope == "job":
                request_settings["input_job_id"] = payload.input_job_id
                request_settings["input_output_ids"] = [image_record["output_id"] for image_record in image_snapshots]
            resolution_mode = request_settings.get("resolution_mode", "automatic")
            if resolution_mode not in {"automatic", "manual"}:
                raise ValueError("해상도 설정은 자동 또는 직접 입력이어야 합니다.")
            request_settings["resolution_mode"] = resolution_mode
            if resolution_mode == "automatic":
                request_settings.update({"width": reference_image["width"], "height": reference_image["height"]})
        if payload.workflow == "anima":
            request_settings.pop("batch_size", None)
        else:
            minimax_execution_settings(request_settings)
        job_id = uuid.uuid4().hex[:12]
        submitted_requests = []
        for image_index, upload_id in enumerate(upload_ids):
            request_id = uuid.uuid4().hex[:12]
            output_stem = f"{server.config.managed_output_directory.name}/{payload.workflow}/{WORKFLOW_OUTPUT_NAMES[payload.workflow]}"
            initial_result = {}
            if image_snapshots:
                initial_result["source_image"] = {
                    key: image_snapshots[image_index][key] for key in ("output_id", "path", "name", "width", "height")
                }
                if payload.input_scope == "job":
                    initial_result["source_image"]["job_id"] = payload.input_job_id
            request = {
                "request_id": request_id, "job_id": job_id, "workflow": payload.workflow,
                "status": "submitting", "output_stem": output_stem,
                "detail": {"upload_id": upload_id, "body": payload.body, "selected_tags": selected_tags,
                           "settings": request_settings, "loras": payload.loras, "resolved": initial_result,
                           "prompt_preset_id": payload.prompt_preset_id,
                           "lora_preset_id": payload.lora_preset_id if payload.loras else None,
                           "lora_preset_name": payload.lora_preset_name if payload.loras else None},
            }
            submitted_requests.append(request)
        server.database.add_job(job_id, payload.workflow, payload.description, submitted_requests, payload.folder_id)
        return job_id, submitted_requests
    except Exception:
        remove_input_snapshots(image_snapshots)
        raise


async def _submit_requests(server: HomeServer, requests: list[dict[str, Any]]) -> None:
    """ComfyUI에 요청을 순서대로 접수하고 업로드 임시 파일을 제거합니다."""

    workflow_templates: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for request in requests:
            request_id = request["request_id"]
            detail = request["detail"]
            submission_started = False
            try:
                if await _skip_cancelled_submission(server, request_id):
                    continue
                favorite_restore = detail.get("favorite_restore")
                if favorite_restore and favorite_restore["mode"] == "exact":
                    prompt_text = detail["body"]["prompt"]
                    negative_text = detail["body"].get("negative", "")
                    saved_resolved = favorite_restore["resolved"]
                    selected_path = saved_resolved.get("selected_path", [])
                    negative_selected_path = saved_resolved.get("negative_selected_path", [])
                    wildcard_seed = saved_resolved.get("wildcard_seed")
                    tag_seed = saved_resolved.get("tag_seed")
                elif request["workflow"] == "anima":
                    wildcard_seed = secrets.randbelow(2**31)
                    tag_seed = wildcard_seed
                    prompt_template, negative_template, selected_path, negative_selected_path = await asyncio.to_thread(
                        resolve_anima_prompts,
                        detail["body"], detail["selected_tags"], wildcard_seed,
                    )
                    prompt_text = await server.comfy.populate_wildcards(prompt_template, wildcard_seed)
                    negative_text = await server.comfy.populate_wildcards(
                        negative_template, wildcard_seed,
                    )
                else:
                    wildcard_seed = None
                    tag_seed = secrets.randbelow(2**31)
                    prompt_text, selected_path = await asyncio.to_thread(
                        resolve_tag_text, minimax_prompt_template(detail["body"]), detail["selected_tags"], random.Random(tag_seed),
                    )
                    negative_selected_path = []
                    negative_text = ""
                if request["workflow"] not in workflow_templates:
                    workflow_templates[request["workflow"]] = await asyncio.to_thread(
                        load_workflows, server.config.workflow_directory, request["workflow"],
                    )
                api_workflow, ui_workflow = workflow_templates[request["workflow"]]
                if request["workflow"] == "anima":
                    request_settings = dict(detail["settings"])
                    request_settings["seed"] = detail["favorite_seed"] if "favorite_seed" in detail else secrets.randbelow(2**31)
                    request_workflow, metadata_workflow = await asyncio.to_thread(
                        prepare_anima,
                        api_workflow, ui_workflow, prompt_text, negative_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                else:
                    request_settings = minimax_execution_settings(detail["settings"])
                    upload_id = detail["upload_id"]
                    upload_path = await asyncio.to_thread(find_uploaded_image, server.upload_directory, upload_id)
                    if detail.get("resolved", {}).get("source_image"):
                        upload_path = await asyncio.to_thread(
                            prepare_input_canvas, upload_path, request_settings["width"], request_settings["height"],
                        )
                    uploaded_name = f"{request_id}_{upload_path.name}"
                    uploaded_reference = await server.comfy.upload_image(upload_path, uploaded_name)
                    request_workflow, metadata_workflow = await asyncio.to_thread(
                        prepare_minimax,
                        api_workflow, ui_workflow, uploaded_reference, prompt_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                metadata = {
                    "workflow": metadata_workflow,
                    "home_server_request": {
                        "request_id": request_id, "job_id": request["job_id"],
                        "prompt": prompt_text, "negative": negative_text,
                        "selected_path": selected_path,
                        "negative_selected_path": negative_selected_path,
                        "wildcard_seed": wildcard_seed, "tag_seed": tag_seed, "settings": request_settings,
                        "loras": detail["loras"],
                        "source_image": detail.get("resolved", {}).get("source_image"),
                    },
                }
                if await _skip_cancelled_submission(server, request_id):
                    continue
                submission_started = True
                prompt_id = await server.comfy.submit(request_workflow, metadata)
                await asyncio.to_thread(
                    server.database.set_request_accepted,
                    request_id, prompt_id, {**detail.get("resolved", {}), "prompt": prompt_text, "negative": negative_text,
                                            "selected_path": selected_path,
                                            "negative_selected_path": negative_selected_path,
                                            "wildcard_seed": wildcard_seed, "tag_seed": tag_seed, "settings": request_settings},
                )
                server.cancellation_wakeup.set()
                LOGGER.info("요청 접수: request_id=%s prompt_id=%s", request_id, prompt_id)
            except Exception as exception:
                submission_state = await asyncio.to_thread(server.database.get_submission_state, request_id)
                if submission_state and submission_state["status"] == "cancelling" and not submission_state["prompt_id"]:
                    if submission_started:
                        await asyncio.to_thread(
                            server.database.update_request, request_id, "stopped",
                            "제출 응답을 받지 못해 ComfyUI 접수 여부를 확인할 수 없습니다.",
                        )
                    else:
                        await asyncio.to_thread(server.database.cancel_unsubmitted_request, request_id)
                else:
                    await asyncio.to_thread(server.database.update_request, request_id, "failed", str(exception))
                LOGGER.error("요청 제출 실패: request_id=%s error_type=%s", request_id, type(exception).__name__)
    finally:
        await asyncio.to_thread(clear_batch_uploads, server.upload_directory, requests)


async def _refresh_requests_before_restore(server: HomeServer) -> None:
    """복원 Gate 안에서 ComfyUI 상태를 조회하고 DB에 반영합니다."""

    async with server.request_refresh_lock:
        active_requests = await asyncio.to_thread(server.database.list_active_requests)
        accepted_requests = [request for request in active_requests if request["prompt_id"]]
        active_request_ids = {request["request_id"] for request in active_requests}
        server.missing_request_since = {
            request_id: missing_since for request_id, missing_since in server.missing_request_since.items()
            if request_id in active_request_ids
        }
        if not accepted_requests:
            return
        try:
            queue = await server.comfy.queue()
            server.record_comfy_connection(True)
        except Exception as exception:
            server.record_comfy_connection(False, type(exception).__name__)
            server.missing_request_since.clear()
            return
        running_ids = {str(item[1]) for item in queue.get("queue_running", [])}
        pending_ids = {str(item[1]) for item in queue.get("queue_pending", [])}
        updates = []
        history_requests = []
        for request in accepted_requests:
            if request["prompt_id"] in running_ids or request["prompt_id"] in pending_ids:
                server.missing_request_since.pop(request["request_id"], None)
                next_status = "running" if request["prompt_id"] in running_ids else "pending"
                started_at = current_timestamp() if next_status == "running" and not request["started_at"] else None
                if request["status"] not in {next_status, "cancelling"} or started_at:
                    updates.append({"request_id": request["request_id"], "status": next_status, "started_at": started_at})
            else:
                history_requests.append(request)
        history_semaphore = asyncio.Semaphore(4)

        async def read_history_state(request: dict[str, Any]) -> dict[str, Any] | None:
            """이력 읽기 동시 수를 제한하고 실패한 조회를 유실 판정에 사용하지 않습니다."""

            async with history_semaphore:
                try:
                    history = await server.comfy.history(request["prompt_id"])
                except Exception:
                    server.missing_request_since.pop(request["request_id"], None)
                    return None
            record = history.get(request["prompt_id"])
            if not record:
                missing_since = server.missing_request_since.setdefault(request["request_id"], time.monotonic())
                grace_seconds = CANCEL_CONFIRMATION_SECONDS if request["status"] == "cancelling" else MISSING_REQUEST_GRACE_SECONDS
                if time.monotonic() - missing_since < grace_seconds:
                    return None
                next_status = "cancelled" if request["status"] == "cancelling" else "stopped"
                error_message = None if next_status == "cancelled" else "ComfyUI 대기열과 완료 이력에서 요청을 확인할 수 없어 추적을 중단했습니다."
                return {"request_id": request["request_id"], "status": next_status, "error_message": error_message}
            server.missing_request_since.pop(request["request_id"], None)
            status_info = record.get("status", {})
            started_at = comfy_execution_started_at(status_info)
            status_name = str(status_info.get("status_str", ""))
            if status_name == "success":
                output_paths = await asyncio.to_thread(_history_output_paths, server, record, request["workflow"])
                return {"request_id": request["request_id"], "status": "completed", "output_paths": output_paths,
                        "started_at": started_at}
            interruption_recorded = any(
                isinstance(message, (list, tuple)) and message and message[0] == "execution_interrupted"
                for message in status_info.get("messages", [])
            )
            if status_name in {"error", "interrupted"}:
                next_status = "cancelled" if status_name == "interrupted" or interruption_recorded else "failed"
                return {"request_id": request["request_id"], "status": next_status,
                        "started_at": started_at,
                        "error_message": None if next_status == "cancelled" else status_name}
            return None

        history_updates = await asyncio.gather(*(read_history_state(request) for request in history_requests))
        updates.extend(update for update in history_updates if update is not None)
        applied_updates = await asyncio.to_thread(server.database.apply_request_states, updates)
        for update in applied_updates:
            LOGGER.info("요청 상태 갱신: request_id=%s status=%s", update["request_id"], update["status"])
            if update["status"] == "completed":
                try:
                    await asyncio.to_thread(server.video_previews.completed_request, update["request_id"])
                except Exception:
                    LOGGER.exception("영상 미리보기 접수 실패: request_id=%s", update["request_id"])
                    server.video_previews.request_scan()


async def _monitor_requests(server: HomeServer) -> None:
    """브라우저 접속 여부와 관계없이 활성 작업의 완료 상태를 확인합니다."""

    while True:
        try:
            await _refresh_requests(server)
        except Exception:
            LOGGER.exception("작업 상태 확인 중 오류가 발생했습니다.")
        await asyncio.sleep(1)


def _history_output_paths(server: HomeServer, record: dict[str, Any], workflow: str) -> list[str]:
    """Saver의 실제 출력 경로를 history에서 읽고 관리 폴더 내부인지 검증합니다."""

    saver_identifier = "13" if workflow == "anima" else "2568"
    saver_outputs = record.get("outputs", {}).get(saver_identifier, {})
    output_paths = []
    managed_folder_name = server.config.managed_output_directory.name
    for output_kind in ("images", "gifs"):
        for output_asset in saver_outputs.get(output_kind, []):
            if output_asset.get("type") != "output":
                continue
            subfolder = str(output_asset.get("subfolder", "")).replace("\\", "/")
            if not subfolder.startswith(f"{managed_folder_name}/"):
                continue
            relative_folder = subfolder[len(managed_folder_name) + 1:]
            filename = str(output_asset.get("filename", ""))
            if not filename or "/" in filename or "\\" in filename:
                continue
            relative_path = f"{relative_folder}/{filename}"
            try:
                output_path = server.managed_path(relative_path)
            except ValueError:
                continue
            if output_path.suffix.lower() in MEDIA_EXTENSIONS and relative_path not in output_paths:
                output_paths.append(relative_path)
    return output_paths
```
