# Python Symbol 색인

줄 번호는 원본 파일 기준입니다. 해당 Markdown Snapshot을 열어 이름으로 찾으세요.

| Source | Symbol | 원본 줄 | 설명 |
| --- | --- | ---: | --- |
| [app/bridge.py](style_lab/app__bridge.py.md) | `open_external` | 32 | Open a file, folder or URL with its usual program. The app window belongs to this process, so what |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.__init__` | 45 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.log` | 60 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.call` | 66 | One request from the page: ``{ok, data}`` or ``{ok: false, error}``, as JSON text (so anything the |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.get` | 86 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.post` | 112 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.keep_draft` | 175 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.open_image` | 179 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.drag_image` | 185 | Hand an image to Windows as a file being dragged, while the mouse button is still down in the window. |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.export_data` | 193 | Save As, then write the zip there. None when the dialog was cancelled. |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.pick_import` | 209 | Open, for the zip to import: its name (for the page to confirm), or None when cancelled. |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.import_data` | 215 | Import the zip picked in Open (only that one: the page never names a file itself). |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.retire` | 226 | A launch with newer code takes over: close now unless generating. Closing the window ends the |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.resource` | 236 | What the window shows at ``path`` (the page, its files, the pictures): ``(file, content type, |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App._typed` | 262 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.safe_image` | 268 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.thumbnail` | 274 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.queue_thumbnail` | 291 |  |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.thumbnail_worker` | 298 | Make thumbnails one at a time, in the background: every missing one first (so galleries open |
| [app/bridge.py](style_lab/app__bridge.py.md) | `App.shutdown` | 317 | Stop (a running generation is stopped, not waited for), keep what was still being typed, save. |
| [app/core.py](style_lab/app__core.py.md) | `ComfyError.__init__` | 94 |  |
| [app/core.py](style_lab/app__core.py.md) | `comfy_base` | 108 |  |
| [app/core.py](style_lab/app__core.py.md) | `_error_text` | 113 | ComfyUI's 400 reply: {"error": {...}, "node_errors": {...}} -> one readable line. |
| [app/core.py](style_lab/app__core.py.md) | `comfy_call` | 132 |  |
| [app/core.py](style_lab/app__core.py.md) | `_combo_options` | 152 | A node input spec from /object_info -> its choices: [[a, b], {...}] (older) or ["COMBO", {"options": [...]}]. |
| [app/core.py](style_lab/app__core.py.md) | `comfy_check` | 162 | Ask ComfyUI which models it has. Raises ComfyError when it cannot be reached. |
| [app/core.py](style_lab/app__core.py.md) | `comfy_lora_metadata` | 179 | The metadata block of a LoRA file (its safetensors header), asked of ComfyUI. Always a dict: when ComfyUI |
| [app/core.py](style_lab/app__core.py.md) | `_find_words` | 190 | Trigger words anywhere in a LoRA Manager answer: a 'trigger_words' / 'trainedWords' list, however deep. |
| [app/core.py](style_lab/app__core.py.md) | `comfy_lora_manager_words` | 208 | Trigger words ComfyUI-LoRA-Manager (a custom node, when installed) knows for a LoRA: (words, note). It keeps the |
| [app/core.py](style_lab/app__core.py.md) | `lora_info` | 253 | What a LoRA file's metadata says: {'trigger': its trigger phrase if it names one, 'candidates': [[tag, count]] |
| [app/core.py](style_lab/app__core.py.md) | `pick_default` | 306 | The first of ``names`` whose lower-cased name contains one of the hints, in hint order. |
| [app/core.py](style_lab/app__core.py.md) | `anima_tag` | 316 | ``artist:foo_bar_(baz)`` (as stored) -> ``@foo bar \(baz\)``; anything else is left as typed. |
| [app/core.py](style_lab/app__core.py.md) | `anima_prompt` | 325 | Stored ``1.2::artist:rurudo ::, 0.9::artist:shigure_ui ::`` (and ``artist:x``) -> ``(@rurudo:1.2), (@shigure ui:0.9)``. |
| [app/core.py](style_lab/app__core.py.md) | `anima_copy` | 347 | A stored style as it is written in Anima for pasting elsewhere: ``(@artist:1.2), ..., <lora:file:0.7>``. |
| [app/core.py](style_lab/app__core.py.md) | `build_prompt` | 360 |  |
| [app/core.py](style_lab/app__core.py.md) | `default_workflow` | 374 | Plain Anima text-to-image in ComfyUI's standard nodes (UNETLoader + CLIPLoader "stable_diffusion" + VAELoader). |
| [app/core.py](style_lab/app__core.py.md) | `load_workflow_file` | 391 | data/workflow.json, saved from ComfyUI with "Save (API Format)"; None when the file is not there. |
| [app/core.py](style_lab/app__core.py.md) | `_node_behind` | 407 | Follow a link through the graph until a node that has the input ``key`` as a plain value. |
| [app/core.py](style_lab/app__core.py.md) | `add_loras` | 425 | Chain one LoRA loader per ``(file name, weight)`` in front of the sampler's model (and, with ``with_clip``, |
| [app/core.py](style_lab/app__core.py.md) | `fill_workflow` | 472 | Put this app's prompts, seed, size and sampler settings into a workflow (the built-in one or the user's). |
| [app/core.py](style_lab/app__core.py.md) | `comfy_logs` | 509 | ComfyUI's recent console lines [{'t', 'm'}], or None when it does not offer them. |
| [app/core.py](style_lab/app__core.py.md) | `lora_tensor_component` | 519 | 알려진 Text Encoder·모델 Key만 분류하고 나머지는 미확인으로 남깁니다. |
| [app/core.py](style_lab/app__core.py.md) | `summarize_lora_tensor_keys` | 528 | Tensor Key 수와 대표 이름을 집계하며 Layer 수로 해석하지 않습니다. |
| [app/core.py](style_lab/app__core.py.md) | `lora_load_report` | 540 | 새 Console 기록의 Key 누락과 Patch 오류를 구성요소별로 분리합니다. |
| [app/core.py](style_lab/app__core.py.md) | `generate_style_image` | 569 | Draw one image through ComfyUI and return its PNG bytes. ``s``: the engine's generation settings. |
| [app/core.py](style_lab/app__core.py.md) | `generate_for_settings` | 627 |  |
| [app/core.py](style_lab/app__core.py.md) | `default_artists` | 630 |  |
| [app/core.py](style_lab/app__core.py.md) | `sanitize_tag` | 633 | ``artist:`` + the name as stored: no backslash escapes, underscores for spaces (turned back into Anima's |
| [app/core.py](style_lab/app__core.py.md) | `_looks_like_number` | 645 |  |
| [app/core.py](style_lab/app__core.py.md) | `artist_weights_in_prompt` | 661 | (weight, tag) for the artists of a whole prompt and nothing else (no 1girl, no quality tags). Both |
| [app/core.py](style_lab/app__core.py.md) | `lora_weights_in_prompt` | 684 | (file name, weight) for every ``lora:name`` of a prompt, in order: inside a "w::...::" group it takes the |
| [app/core.py](style_lab/app__core.py.md) | `artists_in_prompt` | 703 |  |
| [app/core.py](style_lab/app__core.py.md) | `extract_artist_names` | 707 |  |
| [app/core.py](style_lab/app__core.py.md) | `artists_from_style` | 721 |  |
| [app/core.py](style_lab/app__core.py.md) | `calc_elo` | 724 |  |
| [app/core.py](style_lab/app__core.py.md) | `confirm_matches` | 731 | Matches a combo needs before its tier is settled (no longer shown with "?"). |
| [app/core.py](style_lab/app__core.py.md) | `tier_confirmed` | 740 |  |
| [app/core.py](style_lab/app__core.py.md) | `rank_among` | 743 | Place of ``elo`` among ``ascending_elos`` counted from the top (1 = best); equal Elo share the lower place. |
| [app/core.py](style_lab/app__core.py.md) | `tier_for_percentile` | 749 |  |
| [app/core.py](style_lab/app__core.py.md) | `tier_grade` | 753 | Tier with a +/- step for display: each tier's band split in thirds (S+ top third, S, S- bottom third). |
| [app/core.py](style_lab/app__core.py.md) | `is_rated` | 764 | Has a meaningful Elo: played a regular match or was placed on the ladder. |
| [app/core.py](style_lab/app__core.py.md) | `rank_order` | 769 | Best first: higher Elo; on equal Elo the better win rate, then more matches, then the older combo. |
| [app/core.py](style_lab/app__core.py.md) | `top_tier_cut` | 782 | How many rated combos fit in S/A (the top 30%), using the same percentile arithmetic as the tiers. |
| [app/core.py](style_lab/app__core.py.md) | `top_tier_ids` | 787 | The parents outside a batch: the rated combos currently in S/A, best first. |
| [app/core.py](style_lab/app__core.py.md) | `boundary_tie_pair` | 793 | Two combos whose equal Elo straddles the top-30% boundary, or None. |
| [app/core.py](style_lab/app__core.py.md) | `top_tie_pair` | 811 | Two combos inside the top 30% with the same Elo, or None (the boundary tie is boundary_tie_pair's). |
| [app/core.py](style_lab/app__core.py.md) | `parse_style_combo` | 823 |  |
| [app/core.py](style_lab/app__core.py.md) | `is_lora` | 843 |  |
| [app/core.py](style_lab/app__core.py.md) | `split_pairs` | 847 | (artist pairs, LoRA pairs) of a combo's (weight, tag) list. |
| [app/core.py](style_lab/app__core.py.md) | `lora_tags_from_style` | 852 |  |
| [app/core.py](style_lab/app__core.py.md) | `lora_name` | 856 | ``lora:foo.safetensors`` -> ``foo.safetensors``, the name ComfyUI knows it by. |
| [app/core.py](style_lab/app__core.py.md) | `lora_label` | 861 | ``lora:anima\style\foo.safetensors`` -> ``foo`` (display only). |
| [app/core.py](style_lab/app__core.py.md) | `weighted` | 868 |  |
| [app/core.py](style_lab/app__core.py.md) | `rename_artist_in_style` | 874 | Rename one weighted tag (``w::tag ::``) without touching others. |
| [app/core.py](style_lab/app__core.py.md) | `style_from_pairs` | 880 |  |
| [app/core.py](style_lab/app__core.py.md) | `clamp_weight` | 884 | Weights are written with one decimal, so clamp on that grid to never print outside the range. |
| [app/core.py](style_lab/app__core.py.md) | `artist_preference` | 897 | {tag: draw weight} from artist_scores' {tag: score}: FAVOURITE_BOOST ** (score / best /score/). |
| [app/core.py](style_lab/app__core.py.md) | `pick_parents` | 907 | Two different parents from ``ranked`` (best first); the best is TOP_PARENT_BOOST times as likely as the |
| [app/core.py](style_lab/app__core.py.md) | `breed_weighted_style` | 918 | Create a child that always stays inside the configured artist count and weight range. |
| [app/core.py](style_lab/app__core.py.md) | `_batch_votes` | 979 | This batch's entries only (newest first, like history), so ranking never walks every vote ever cast. |
| [app/core.py](style_lab/app__core.py.md) | `selection_scores` | 985 | Rebuild this batch's scores from votes; parent scores never change. |
| [app/core.py](style_lab/app__core.py.md) | `apply_selection_ratings` | 1011 | Mirror this batch into each child's list Elo/record: Elo becomes its placed ladder score. |
| [app/core.py](style_lab/app__core.py.md) | `selection_votes` | 1047 | Return the parent ladder (lowest score first) and each child's votes against it. |
| [app/core.py](style_lab/app__core.py.md) | `_bisect` | 1080 | Slot bounds from the bisection path; slot = number of parents the child ranks above. |
| [app/core.py](style_lab/app__core.py.md) | `_climb_rung` | 1101 | After a tie with parent k, the parent just above (k + 1) is asked next, if still open. |
| [app/core.py](style_lab/app__core.py.md) | `_best_slots` | 1110 | Slots that contradict the fewest of the child's votes (preferences need not be transitive). |
| [app/core.py](style_lab/app__core.py.md) | `_next_rung` | 1120 | Lowest parent first (most children stop there), then bisect the remaining range. |
| [app/core.py](style_lab/app__core.py.md) | `_check_rung` | 1129 | A parent to re-ask about: inside an ambiguous range first, then 2-3 rungs above and below. |
| [app/core.py](style_lab/app__core.py.md) | `selection_ranking` | 1141 | Rank parents and children together and decide which vote, if any, is still needed. |
| [app/core.py](style_lab/app__core.py.md) | `selection_next_pair` | 1224 | Next vote: bisect unsettled children, verify those near the cut, then order cut ties. |
| [app/core.py](style_lab/app__core.py.md) | `selection_remaining_matches` | 1242 | Estimate remaining votes: bisection left, up to two checks per child, plus cut ties. |
| [app/core.py](style_lab/app__core.py.md) | `placement_state` | 1262 | Where a newcomer stands after its votes against ladder rungs. |
| [app/core.py](style_lab/app__core.py.md) | `placement_elo` | 1281 | Elo for a newcomer placed at ``slot`` among ascending ``ladder_scores``. |
| [app/core.py](style_lab/app__core.py.md) | `artist_scores` | 1297 | Each artist's share of the combo ratings: {tag: (score, combos it is in)}. |
| [app/core.py](style_lab/app__core.py.md) | `random_lora_pairs` | 1330 | A fresh random pick: between min_n and max_n registered LoRAs (as many as exist, at most), each with a |
| [app/core.py](style_lab/app__core.py.md) | `breed_loras` | 1338 | The LoRA part of a child, ``mode`` being the one picked for its artists: mutate keeps parent A's LoRAs with |
| [app/core.py](style_lab/app__core.py.md) | `jitter_weights` | 1386 | Same artists, new weights: every weight moves by up to ±jitter (at least one changes). |
| [app/core.py](style_lab/app__core.py.md) | `upgrade_state` | 1417 | Bring a loaded state up to SCHEMA, in place; returns the format it had. Data without a format number is |
| [app/core.py](style_lab/app__core.py.md) | `empty_state` | 1431 |  |
| [app/core.py](style_lab/app__core.py.md) | `load_state` | 1438 | Read state.json; an unreadable file is set aside (never overwritten) and reported. |
| [app/core.py](style_lab/app__core.py.md) | `backup_file` | 1472 |  |
| [app/core.py](style_lab/app__core.py.md) | `write_state` | 1476 | Atomically replace the state file so a crash never leaves half-written JSON. |
| [app/data_access.py](style_lab/app__data_access.py.md) | `DataDirectoryLock.__init__` | 15 | 폴더 이름이 같아도 실제 경로가 다르면 별도의 Mutex를 준비합니다. |
| [app/data_access.py](style_lab/app__data_access.py.md) | `DataDirectoryLock.__enter__` | 29 | 대기하지 않고 잠금을 획득하며, 사용 중이면 시작을 거부합니다. |
| [app/data_access.py](style_lab/app__data_access.py.md) | `DataDirectoryLock.__exit__` | 41 | 실행이 정상 종료되거나 예외가 나도 Mutex Handle을 반납합니다. |
| [app/engine.py](style_lab/app__engine.py.md) | `_now` | 69 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `_new_id` | 73 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `_next_jitter` | 77 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `_jitter_schedule` | 81 | Every round's adjustment, first to last: [0.3, 0.2, 0.1]. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.__init__` | 88 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.save` | 127 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._event` | 131 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._event_locked` | 135 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.events_since` | 139 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.combos` | 143 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.selection` | 147 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.retired` | 151 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.settings` | 154 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.rules` | 165 | The settings combos are made with: a side that is switched off counts as 0 pieces. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.update_settings` | 176 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._apply_settings` | 193 | Write checked ``changes`` into ``ui``. Raises UserError. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._start_count` | 232 | The count a start request asks for (or the saved one), checked like the settings field and |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.workflow_state` | 244 | data/workflow.json: {'exists', 'error'}; a ComfyUI workflow saved in API format replaces the built-in one. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._gen_settings` | 251 | Settings for one generation run; an empty seed gets a random one that is kept. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.find` | 273 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.find_any` | 279 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.rated` | 291 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.newcomers` | 294 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.ranking_counts` | 298 | (ranked, waiting) as the user sees them. The first combo becomes the anchor without a vote, |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.top_ids` | 306 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.boundary_tie` | 309 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.top_tie` | 312 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tiers` | 316 | (tier, provisional, grade, #n, child of the running batch) for every active combo, computed once. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.combo_view` | 337 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.list_combos` | 357 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.job_view` | 365 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._require_idle` | 371 | Refuse a change while images are being made (or only while a job of one of ``kinds`` runs). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._start_job` | 377 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._drop_empty_batch` | 403 | A generation that started but has no child at all (the job was cancelled, ComfyUI went away): back to before |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.stop_job` | 412 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._render` | 415 | Generate one image outside the lock; returns the saved file name or None on failure (or a stop). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._draw_and_render` | 448 | The loop shared by random combos, evolution and refine variants: ``count`` images, each from |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._new_combo` | 474 | A combo just drawn: random ones, evolution children and refine variants start from the same fields. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._pause` | 480 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._after_job` | 484 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_random` | 489 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.merge_combos` | 526 | Two combos in one, several ways (one picture can't tell whether the mix works): every tag of both, a tag |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.merge_view` | 581 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.merge_add` | 600 | Put merged pictures into the list of combos (they find their place in 선별); they leave 합친 그림. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.merge_refine` | 619 | A merged picture the user likes: into the list; the page then opens 다듬기 with it. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.merge_delete` | 627 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._require_loras_without_artists` | 636 | Artists set to 0 (only LoRAs are mixed): there must be LoRAs to mix. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_custom` | 641 | One combo exactly as typed (its artist: tags and weights), drawn and added like a random one. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_lora_check` | 678 | Each chosen LoRA alone in one picture (not kept): when ComfyUI cannot attach its layers, _lora_report marks |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._expand_lora_syntax` | 719 | Anima's ``<lora:name:0.7>`` (the file name without folder and extension) into the app's own |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_free` | 732 | One picture from the text typed. ``base`` / ``negative`` replace the settings' prompts for this picture only |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.free_delete` | 761 | Remove 자유 생성 pictures. One that became a combo keeps its file (the combo owns it); only the record goes. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.free_adopt` | 775 | A 자유 생성 picture the user likes becomes a combo of the list as drawn (no new image); optionally into the |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.list_artists` | 812 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.add_artists` | 819 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.scan_artists` | 837 | The artists a prompt names with their weights, as the combos' pairs (tags as add_artists would |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._lora_range` | 864 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.lora_registry` | 870 | {lora tag: (lowest, highest weight)} of the registered LoRAs: their own range, else the settings'. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.resolve_lora` | 875 | The registered tag a typed LoRA name means: the exact file name, else the one whose name (without folder |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._count_use` | 886 | A new combo used these artist / LoRA tags. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.reset_usage` | 895 | Every artist's and LoRA's use count back to 0 (scores and combos stay). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.list_loras` | 902 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.lora_loading_notice` | 932 | 최근 조합의 적용 안내를 반환하며 특정 파일의 실패로 단정하지 않습니다. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._lora_report` | 937 | 의도적인 TE 미적용은 상세 기록으로, 실제 적용 문제는 중복 없는 경고로 남깁니다. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._unread` | 1013 | [[label, why]] for the files nothing useful could be read from: ComfyUI could not give the metadata, or it has |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._meta_report` | 1023 | data/lora_meta.log: for every file that gave no trigger, the metadata key names it does have, so it can be |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._read_infos` | 1039 | {file name: core.lora_info} asked of ComfyUI (outside the lock: it is a network call per file). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.add_loras` | 1053 | Register LoRAs by their file names in ComfyUI. Returns {'added', 'skipped' (names that cannot be used), |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.read_loras` | 1086 | Read the files' metadata again: the trigger suggestions and the base model. A trigger phrase the file names |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.update_lora` | 1107 | A LoRA's own weight range (None: follow the settings') and trigger words. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.delete_loras` | 1131 | Take LoRAs off the list. ``with_combos``: also delete every combo that has one of them (refused while a |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.rename_artist` | 1145 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._artists_checked` | 1162 | Editing the artist list is checking it (the setup step starts from the default list). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.delete_artists` | 1166 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.match` | 1174 | The current match (kept until voted/skipped), choosing a new one if needed. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._priority_pair` | 1193 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._fresh_pair` | 1219 | While the ladder is short, two newcomers fight each other (both become rated by that one vote). Placing |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._league_pair` | 1238 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._match_weights` | 1259 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._match_view` | 1271 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._roles` | 1288 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._context` | 1299 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._idle_message` | 1329 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.vote` | 1340 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.skip` | 1358 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._remember_match` | 1397 | The undo step this vote just added keeps the match itself, sides included, so undo shows it again. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._vote_regular` | 1402 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.undo` | 1433 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._placement_votes` | 1485 | (rung, result) for the placed newcomer, oldest first. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._ensure_placement` | 1502 | Start placing the next newcomer; the very first combo simply becomes the START_ELO anchor. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._placement_pair` | 1526 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._vote_place` | 1536 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._record_place` | 1539 | A placement vote (or skip = tie when ``winner_id`` is None); settles the slot when decided. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._settle_placement` | 1553 | If the current newcomer's slot is settled, give it its Elo and move on. Returns True if settled. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.evolution_view` | 1574 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.cancel_generation` | 1610 | Abandon the running generation: its children, their votes and the batch go; the parents stay untouched. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._evolution_blocker` | 1633 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_evolution` | 1650 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._selection_pool` | 1700 | The running batch's parents and children. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._selection_pair` | 1705 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._vote_select` | 1717 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._selection_done` | 1725 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._generation_plan` | 1731 | Failed children leave; as many existing combos as children got in drop from the bottom of |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.finish_generation` | 1750 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._record_lora_snapshot` | 1789 | The LoRAs of the top combos as this generation ends: per LoRA count / mean / min / max, and which pairs |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.lora_lock_view` | 1811 | Per LoRA across the recorded generations: steady ones become 확정 (and only when the combos that used that |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._converged` | 1858 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_tags` | 1868 | The tags a 다듬기 moves: all of them, only the artists, or only the LoRAs. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_variant` | 1872 | One variant of the base: each chosen tag's weight (artist or LoRA) moves by a small, middling or large step |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_tune` | 1888 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_generate` | 1917 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.tune_more` | 1944 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_remaining` | 1959 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_pair` | 1962 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_snap` | 1981 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._vote_tune` | 1985 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._undo_tune` | 1999 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_rate` | 2010 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._tune_recommend` | 2013 | From the best-judged variants: for each tag the window of 0.10 holding the most of their weights, and the |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.tune_view` | 2050 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.tune_render` | 2071 | Pictures with the recommended values: the first with the combo's seed, the others with new seeds, so the user |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.finish_tune` | 2109 | Close the session: the variants' pictures go (the reference's belongs to its combo); the pictures drawn with the |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.improve_view` | 2129 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.start_improve` | 2163 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._improve_generate` | 2185 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._final_of` | 2218 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._improve_pair` | 2225 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._vote_improve` | 2237 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._same_as_base` | 2244 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._final_vote` | 2248 | winner: 'champion', 'base', or 'tie' (비슷함: it counts for neither). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._maybe_finish_final` | 2253 | All seeds judged: the side that won more of them is the final style (a draw keeps the original). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._improve_step` | 2266 | The first waiting variant meets the champion, undoably. ``winner_id`` None = "similar": the first time |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._improve_round_check` | 2290 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.improve_next_round` | 2296 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.improve_final_check` | 2312 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.finish_improve` | 2364 | End the session: 'champion' keeps the winner, 'base' keeps the original, 'discard' keeps neither. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._finish_target` | 2410 | The refine that was finished last, rebuilt from what it left behind: the variants it marked 탈락 (they carry the |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.undo_finish` | 2428 | Take back the last 확정: the session is back at its last round, so it can be refined further or confirmed again. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.improve_resume` | 2466 | Back from the final check to keep refining. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._drop_final_images` | 2477 | Final-check previews are only ever shown in the app's own window: removed as far as possible. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._delete_images` | 2497 | Delete images and their thumbnails, before the records go. Windows refuses a file another program |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._protected` | 2509 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.delete_combos` | 2515 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.set_memo` | 2541 | A free note on a combo (what it is good for, which prompt it likes ...). Empty removes it. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.set_kept` | 2555 | 보관함: combos the user wants to keep. They are never dropped by evolution, never purged, and cannot be |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.purge` | 2571 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.revive` | 2576 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.set_elo` | 2592 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.image_path` | 2620 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.reset` | 2628 | Reset one part of the data. Nothing is backed up. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.export_data` | 2678 | Write one zip with state.json and every image into the binary file ``target``. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.import_data` | 2688 | Replace everything with an exported zip. Nothing is backed up. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.refresh_connection` | 2740 | Ask ComfyUI which models it has, in the background (at launch), so the settings and the sidebar know. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.check_connection` | 2744 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine._prune_loras` | 2765 | LoRAs whose file ComfyUI no longer lists drop out of the registry (a combo with one cannot be drawn at all). |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.settings_payload` | 2780 | Everything /api/settings returns; the pages keep one copy and refetch it when settings_rev changes. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.connection_view` | 2784 |  |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.stage` | 2796 | Where the user is in 준비 → 순위 결정 → 진화 → 다듬기 → 완성, and what to do now. |
| [app/engine.py](style_lab/app__engine.py.md) | `Engine.status` | 2875 |  |
| [main.py](style_lab/main.py.md) | `code_version` | 49 | Changes whenever the app's code changes, so a running app with old code can be replaced. |
| [main.py](style_lab/main.py.md) | `tell` | 55 |  |
| [main.py](style_lab/main.py.md) | `_is_app_process` | 59 | True while ``pid`` is a running Python (the app runs as pythonw.exe), so a reused pid is not mistaken for it. |
| [main.py](style_lab/main.py.md) | `legacy_running` | 79 | True while a version with a local server runs on this data folder: it cannot be asked to close, and two |
| [main.py](style_lab/main.py.md) | `Instance.__init__` | 99 |  |
| [main.py](style_lab/main.py.md) | `Instance._serve` | 106 |  |
| [main.py](style_lab/main.py.md) | `Instance.lock_info` | 123 |  |
| [main.py](style_lab/main.py.md) | `Instance.close` | 126 |  |
| [main.py](style_lab/main.py.md) | `_ask` | 134 | Send ``message`` to the running app; its reply, or None if it is not there (or does not answer). |
| [main.py](style_lab/main.py.md) | `hand_over` | 153 | True if the app is already running for this data folder: this launch then says so and opens nothing |
| [main.py](style_lab/main.py.md) | `name_taskbar_button` | 192 | Give the window's taskbar button the app's name, icon and launch command. |
| [main.py](style_lab/main.py.md) | `fit_page` | 222 | Resize the window so the page inside (its client area) is ``width`` x ``height`` CSS pixels, whatever the |
| [main.py](style_lab/main.py.md) | `serve_files` | 236 | Answer every request the window makes to ORIGIN from disk (app.resource), and keep the window there: |
| [main.py](style_lab/main.py.md) | `open_window` | 284 | Show the app window and block until it is closed. Gives ``app`` its Save As, Open, close and drag. |
| [main.py](style_lab/main.py.md) | `main` | 329 | 데이터 접근 잠금을 확보한 뒤 Desktop 앱을 실행합니다. |
| [main.py](style_lab/main.py.md) | `run_desktop_application` | 338 | 기존 Desktop 창과 Engine을 초기화하고 종료 시 저장합니다. |
| [main.py](style_lab/main.py.md) | `launch` | 361 | main(), but a launch that fails says why: pythonw.exe has no console, so it would just vanish. The message |
| [tests_web/fixtures.py](style_lab/tests_web__fixtures.py.md) | `fixture_image_bytes` | 18 | 노출해도 되는 단색 PNG를 만듭니다. |
| [tests_web/fixtures.py](style_lab/tests_web__fixtures.py.md) | `generate_fixture_image` | 25 | ComfyUI를 호출하지 않고 테스트 이미지만 반환합니다. |
| [tests_web/fixtures.py](style_lab/tests_web__fixtures.py.md) | `fixture_connection` | 30 | 웹 화면에 필요한 모델 목록만 반환합니다. |
| [tests_web/fixtures.py](style_lab/tests_web__fixtures.py.md) | `create_fixture_engine` | 39 | 원본 데이터와 독립적인 비교 조합·이미지·Workflow를 준비합니다. |
| [tests_web/serve_fixture.py](style_lab/tests_web__serve_fixture.py.md) | `main` | 12 | 실제 데이터와 ComfyUI를 사용하지 않는 임시 서버를 실행합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `report_for_messages` | 11 | Console 메시지를 고유한 시각의 ComfyUI Log Entry로 바꿉니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.setUp` | 22 | 실제 서버와 연결되지 않는 임시 Engine을 준비합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.tearDown` | 30 | 테스트 자료만 정리합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.apply_report` | 34 | 선택한 LoRA 조합의 생성 후 보고를 실행합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_components_are_classified_before_sample_truncation` | 38 | 앞의 TE 예시 8개 때문에 뒤의 실제 모델 문제가 숨겨지지 않아야 합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_expected_encoder_omission_is_logged_without_warning` | 56 | Model Only의 TE 미적용은 상태와 Log에 남고 실패 경고는 없어야 합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_enabled_encoder_omission_remains_a_warning` | 74 | TE도 적용하도록 설정한 경우에는 같은 Key 누락을 경고해야 합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_mixed_combinations_deduplicate_by_problem_kind` | 81 | 조합 변경은 같은 경고를 반복하지 않지만 새로운 종류의 문제는 알립니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_single_files_keep_separate_warning_identities` | 93 | 개별 파일의 실제 문제는 다른 파일의 이전 경고에 가려지지 않아야 합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_patch_errors_are_not_suppressed_by_model_only` | 100 | Shape 불일치와 Patch 실패는 누락 Key가 없어도 경고해야 합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_truncated_encoder_log_does_not_clear_previous_failure` | 112 | 잘린 Log에서는 TE 경고만 보여도 이전 모델 문제 해결을 단정하지 않습니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_complete_expected_omission_clears_obsolete_failure` | 123 | 전체 Log에서 실제 문제 없이 끝난 개별 검사는 이전 실패 표시를 갱신합니다. |
| [tests_web/test_lora_reporting.py](style_lab/tests_web__test_lora_reporting.py.md) | `LoraReportingTests.test_existing_log_entries_are_not_reported_again` | 129 | 생성 전에 있던 경고는 이번 LoRA 결과에 포함하지 않습니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.setUp` | 23 | 테스트 전용 Engine과 임의 Port의 HTTP Server를 시작합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.tearDown` | 38 | 테스트 서버를 닫고 테스트 전용 자료만 정리합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.send_request` | 46 | 테스트용 Cookie와 JSON으로 요청하고 오류 응답도 반환합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.sign_in` | 61 | 테스트 비밀번호로 로그인하고 CSRF Token을 확보합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_authentication_and_path_boundaries` | 70 | 상태·이미지·설정 파일은 인증 없이 공개되지 않아야 합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_expected_encoder_notice_is_available_without_toast_events` | 84 | TE 미적용 안내는 인증된 API로 조회되고 Warning Event는 발생하지 않습니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_csrf_and_origin_protection` | 97 | 인증 Cookie만 있거나 Origin이 다른 변경 요청은 거부합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_vote_persistence_and_stale_pair` | 109 | 한 번 투표를 저장하고 이전 화면의 중복 투표는 거부합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_zip_export_and_desktop_actions` | 126 | 다운로드에는 상태와 이미지만 포함하고 서버 PC 실행은 거부합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_generation_uses_custom_workflow_without_comfy` | 138 | 실제 생성 경로가 NegPip Workflow와 음수 가중치를 전달하는지 확인합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_zip_import_restores_browser_state` | 160 | Browser 업로드로 복원한 뒤 융합 조회까지 정상이어야 합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_login_rate_limit_and_expired_session` | 179 | 반복 로그인 실패와 만료된 Session을 거부합니다. |
| [tests_web/test_web_server.py](style_lab/tests_web__test_web_server.py.md) | `WebServerTests.test_data_mutex_rejects_another_process` | 193 | 다른 프로세스가 같은 폴더의 잠금을 획득하지 못해야 합니다. |
| [web_server.py](style_lab/web_server.py.md) | `WebAuthentication.__init__` | 40 | 인증 정보만 메모리에 올리고 Session은 프로세스별로 새로 만듭니다. |
| [web_server.py](style_lab/web_server.py.md) | `WebAuthentication.verify_password` | 47 | 저장된 PBKDF2 Hash와 입력값을 일정 시간 비교합니다. |
| [web_server.py](style_lab/web_server.py.md) | `WebAuthentication.sign_in` | 56 | 반복되는 실패를 제한하고 로그인 성공 시 Session을 발급합니다. |
| [web_server.py](style_lab/web_server.py.md) | `WebAuthentication._remove_expired_sessions` | 81 | 오래된 Session이 계속 메모리에 쌓이지 않도록 정리합니다. |
| [web_server.py](style_lab/web_server.py.md) | `WebAuthentication.current_session` | 87 | 요청 Cookie에 해당하는 유효한 Session만 반환합니다. |
| [web_server.py](style_lab/web_server.py.md) | `BrowserBridge.resource` | 97 | 웹 파일은 별도 폴더에서, 이미지는 기존 안전한 경로 검사로 제공합니다. |
| [web_server.py](style_lab/web_server.py.md) | `BrowserBridge.post` | 111 | 실제 Engine을 호출하며 Desktop 전용 파일 접근은 실행하지 않습니다. |
| [web_server.py](style_lab/web_server.py.md) | `password_configuration` | 127 | 비밀번호 원문 없이 저장할 PBKDF2 설정을 생성합니다. |
| [web_server.py](style_lab/web_server.py.md) | `load_authentication` | 134 | 첫 실행에서는 임의 비밀번호를 만들고, 요청 시에만 교체합니다. |
| [web_server.py](style_lab/web_server.py.md) | `check_same_origin` | 162 | 다른 사이트가 Browser의 인증 Cookie를 이용해 변경 요청을 보내지 못하게 합니다. |
| [web_server.py](style_lab/web_server.py.md) | `require_session` | 173 | 인증과 필요한 CSRF 검사를 수행하고 현재 Session을 반환합니다. |
| [web_server.py](style_lab/web_server.py.md) | `json_reply` | 186 | 기존 Frontend와 같은 JSON 응답 형식을 사용합니다. |
| [web_server.py](style_lab/web_server.py.md) | `archive_chunks` | 193 | 다운로드를 Stream으로 보내고 완료 또는 연결 종료 시 임시 파일을 지웁니다. |
| [web_server.py](style_lab/web_server.py.md) | `create_web_application` | 203 | 기존 Engine을 HTTP로 연결하는 인증된 Bottle 애플리케이션을 만듭니다. |
| [web_server.py](style_lab/web_server.py.md) | `ThreadedWebServer.get_request` | 354 | 연결이 응답 없이 Thread를 계속 점유하지 않도록 Timeout을 둡니다. |
| [web_server.py](style_lab/web_server.py.md) | `QuietRequestHandler.log_message` | 364 | 요청 URL과 인증 내용을 로그에 쓰지 않습니다. |
| [web_server.py](style_lab/web_server.py.md) | `configure_logging` | 369 | 수명주기와 서버 오류만 크기가 제한된 로그로 남깁니다. |
| [web_server.py](style_lab/web_server.py.md) | `main` | 379 | 설정과 데이터 잠금을 확보한 뒤 Port 8389에서 웹 서버를 실행합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `load_workflows` | 28 | 선택한 workflow의 API JSON과 UI JSON을 읽습니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `update_ui_widget` | 39 | Drag and drop metadata의 widget 값도 API 요청과 맞춥니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `connect_ui_seed` | 58 | MiniMax metadata에도 sampling seed와 Saver의 연결을 기록합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `validate_output_stem` | 85 | 출력 경로가 앱 관리 폴더 아래의 단순 상대 경로인지 확인합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `disable_anima_trigger_words` | 100 | 생성 요청의 trigger word는 비우고 UI의 LoRA 연동과 기본 비활성 상태를 유지합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `prepare_anima` | 116 | Anima의 Prompt, sampling, LoRA, 출력 파일 경로를 적용합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `build_minimax_timeline` | 193 | 요청 모드에 필요한 endpoint만 만들고 동일 이미지와 평문을 Timeline에 반영합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `minimax_execution_settings` | 227 | 지원 모드와 숫자 범위를 검증하고 기존 정책인 32 단위 해상도 정렬을 적용합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `apply_minimax_upscale` | 253 | 선택한 2배 upscale node를 video 저장 node 앞에 삽입합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `validate_minimax_loras` | 300 | LoRA 개수와 loader가 받는 STR·VIS·AUDIO의 숫자 범위를 확인합니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `apply_minimax_modality_loras` | 317 | LoRA마다 loader 하나를 사용해 개별 modality weight와 복원 metadata를 맞춥니다. |
| [home_server/workflows.py](home_server/home_server__workflows.py.md) | `prepare_minimax` | 348 | 공통 템플릿에 MiniMax 모드별 endpoint, LoRA, upscale과 저장 경로를 설정합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `encode_json_payload` | 13 | 큰 Workflow JSON의 직렬화와 UTF-8 변환을 Worker에서 완료합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `queue_from_response` | 19 | ComfyUI JSON 해석과 대기·실행 ID 목록 구성을 Worker에서 수행합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.__init__` | 35 | ComfyUI 주소를 보관하고 HTTP client를 생성합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.close` | 41 | HTTP 연결을 종료합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.request_json` | 46 | HTTP 통신은 비동기로 수행하고 요청·응답 JSON 변환은 Worker로 옮깁니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.list_loras` | 59 | ComfyUI가 인식하는 LoRA 이름을 조회합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.refresh_loras` | 65 | LoRA Manager의 파일 재검색이 끝날 때까지 기다립니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.populate_wildcards` | 77 | 설치된 Impact Pack으로 Prompt wildcard를 확장합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.upload_image` | 85 | MiniMax 입력 이미지를 ComfyUI input에 업로드합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.submit` | 101 | Workflow를 queue에 제출하고 접수된 prompt ID를 반환합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.queue` | 113 | Workflow 본문을 포함하지 않는 ComfyUI 상태 목록을 queue 형태로 반환합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.history` | 122 | 한 요청의 완료 기록을 조회합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.free_memory` | 127 | Model unload와 execution cache 해제를 요청하고 빈 성공 응답을 처리합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.system_resources` | 135 | 설치된 DaSiWa API에서 Docker가 아닌 ComfyUI host의 자원 상태를 읽습니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.cancel_prompt` | 140 | ComfyUI에서 지정한 대기·실행 요청만 취소합니다. |
| [home_server/comfy_client.py](home_server/home_server__comfy_client.py.md) | `ComfyClient.cancel_prompts` | 146 | 선택한 대기 ID만 한 번에 제거한 뒤 실행으로 넘어간 ID만 원자적으로 취소합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `referenced_tag_keys` | 19 | 본문에 등장하는 대문자 태그 참조를 순서대로 찾습니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `anima_prompt` | 25 | Anima Prompt 텍스트를 검증한 뒤 원문 그대로 반환합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `anima_negative_prompt` | 36 | 비어 있어도 되는 Negative Prompt의 타입과 길이를 검증합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `validate_tag_selection` | 47 | 그룹 참조를 복사한 항목 snapshot에서 모든 선택지의 누락과 cycle을 검사합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `resolve_tag_prompt` | 94 | 같은 그룹 참조의 항목 snapshot을 합쳐 각 참조를 weight로 독립 추첨합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `resolve_anima_prompts` | 102 | 두 Prompt의 각 참조를 공유 난수 흐름으로 독립 추첨하고 선택 경로를 구분합니다. |
| [home_server/tag_builder.py](home_server/home_server__tag_builder.py.md) | `resolve_tag_text` | 115 | 검증한 문자열의 중첩 태그를 확장하며 빈 Negative Prompt도 그대로 반환합니다. |
| [home_server/configuration.py](home_server/home_server__configuration.py.md) | `video_preview_settings` | 44 | 영상 설정의 타입·범위를 검증하고 누락된 항목에는 기본값을 적용합니다. |
| [home_server/configuration.py](home_server/home_server__configuration.py.md) | `load_config` | 63 | TOML 설정을 읽고 관리 폴더가 output 내부인지 확인합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_anima_adapter_sets_prompt_lora_and_output` | 23 | Anima의 실제 실행 입력과 drag and drop metadata를 함께 수정합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_anima_embedded_workflow_preserves_restorable_lora_widgets` | 53 | PNG의 UI Workflow에 활성 LoRA 배열과 독립적인 Model/CLIP 강도가 남는지 검증합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_anima_negpip_routes_model_and_clip_in_execution_and_embedded_workflow` | 102 | CFG 1의 음수 Prompt 가중치와 LoRA가 실행·복원 양쪽에서 NegPiP를 거치는지 확인합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_anima_templates_have_no_saved_lora_or_trigger_word_state` | 143 | 두 기본 Workflow는 빈 LoRA·trigger 목록과 살아 있는 UI 연결로 시작합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_anima_trigger_words_are_disabled_without_adding_entries` | 171 | 찌꺼기는 비우고 실행 시 자동 삽입을 막으면서 복원 후 UI의 목록 갱신 연결은 유지합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_minimax_adapter_sets_timeline_and_output` | 227 | MiniMax의 첫·마지막 이미지와 LoRA, 저장 위치를 검증합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_minimax_modality_weights_chain_and_metadata_round_trip` | 257 | LoRA별 서로 다른 weight와 0, 빈 slot 및 복원용 세 저장 위치가 일치하는지 확인합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_minimax_modality_template_links_preserve_clip_and_model_consumers` | 303 | Top-level·subgraph의 연결 양끝과 CLIP 직결을 검사해 복원 시 끊긴 배선을 잡습니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_minimax_modality_loader_rejects_invalid_weights` | 330 | Loader가 받을 수 없는 weight나 개수는 요청 전에 거부합니다. |
| [tests/test_workflows.py](home_server/tests__test_workflows.py.md) | `test_adapter_rejects_output_path_escape` | 337 | 요청 값으로 앱 output 밖의 저장 경로를 만들 수 없게 합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `tag_entry` | 8 | 그래프 테스트에 사용할 태그 항목을 만듭니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_multi_hop_tag_selection_keeps_each_reference_independent` | 17 | Prompt에서 두 단계 내려가며 동일한 CHR 참조를 독립적으로 선택합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_shared_tag_pool_allows_all_combinations` | 36 | 두 ACTION 항목이 같은 CHR 선택 집합을 공유합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_weight_applies_to_each_referenced_tag_choice` | 52 | 상위 참조와 하위 참조에 저장된 weight를 각각 적용합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_selection_rejects_missing_candidates_and_cycles` | 73 | 랜덤 추첨 전에 누락과 직접·간접 cycle을 거부합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_disconnected_cycle_does_not_block_prompt` | 80 | Prompt에서 닿지 않는 체크 항목의 cycle은 이번 요청에 영향을 주지 않습니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_possible_cycle_in_unselected_random_branch_is_rejected` | 91 | weight가 낮아도 선택 가능한 cycle 경로가 있으면 제출을 막습니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_longest_possible_path_is_checked_before_submission` | 103 | 같은 항목에 짧은 경로로 먼저 도달해도 긴 경로의 한도를 검사합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_plain_anima_prompt_needs_no_tag_selection` | 115 | 태그 참조가 없는 Anima Prompt는 원문 그대로 통과합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_negative_only_references_expand_nested_tags_and_keep_separate_paths` | 121 | Positive에 참조가 없어도 Negative의 하위 참조를 확장하고 선택 경로를 따로 남깁니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_same_reference_in_positive_and_negative_is_chosen_independently` | 137 | 같은 키가 두 Prompt에 쓰여도 하나의 선택을 재사용하지 않고 각각 추첨합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_negative_references_reject_missing_candidates_and_cycles` | 151 | Negative에만 존재하는 누락이나 cycle도 확정 전에 거부합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_negative_prompt_validates_type_and_length` | 159 | 잘못된 타입을 문자열로 강제 변환하지 않고 Negative 길이 제한도 검사합니다. |
| [tests/test_tag_builder.py](home_server/tests__test_tag_builder.py.md) | `test_empty_negative_keeps_positive_selection_unchanged` | 166 | Negative가 없으면 기존 Positive 선택 결과와 seed 재현성을 유지합니다. |
