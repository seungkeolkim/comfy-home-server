# 조사 시점과 자동 추출 근거

- UTC 기록 시각: `2026-11-08T11:29:40.591623+00:00`
- Style Lab Version 표기: `2.0.0` + 로컬 수정. 실제 식별은 Source Hash 기준.
- Home Git HEAD: `09b7bab352c380548d08f595316d8f56abedcbae`. Source 파일 Hash는 원문 목록 참고.
- 관측 State SHA-256: `3a241f224873963f08d7e97ffaa39db46d28937392231a89e8021fbd408e660e`. 사용자 State 원문은 복제하지 않았습니다.
- Runtime 상태나 Model Tensor의 Hash를 새로 검증한 문서는 아닙니다.

## 관측 데이터 구조
```json
{
  "schema": 2,
  "top_level": {
    "schema": "int",
    "artists": "list",
    "loras": "list",
    "combinations": "list",
    "history": "list",
    "ui_state": "dict",
    "selection": "dict",
    "placement": "NoneType",
    "improve": "NoneType",
    "free_results": "list",
    "merged": "list",
    "lora_history": "list",
    "lora_loading_notice": "dict"
  },
  "sample_record_fields": {
    "artists": {
      "tag": "str",
      "count": "int",
      "arena_matches": "int",
      "arena_wins": "int"
    },
    "loras": {
      "tag": "str",
      "min_w": "float",
      "max_w": "float",
      "trigger": "str",
      "count": "int",
      "arena_matches": "int",
      "arena_wins": "int",
      "candidates": "list",
      "base": "str",
      "incompatible": "bool",
      "checked": "str"
    },
    "combinations": {
      "id": "str",
      "style": "str",
      "elo": "int",
      "matches": "int",
      "wins": "int",
      "placed": "bool",
      "image_file": "str",
      "seed": "int",
      "created": "float",
      "generation": "int",
      "selection_applied": "dict"
    },
    "history": {
      "type": "str",
      "pair": "dict",
      "winner_id": "str",
      "batch_id": "str"
    },
    "lora_history": {
      "generation": "int",
      "n": "int",
      "time": "float",
      "pairs": "dict",
      "loras": "dict"
    },
    "free_results": {
      "image": "str",
      "prompt": "str",
      "time": "str",
      "seed": "int"
    },
    "merged": {
      "key": "str",
      "style": "str",
      "image": "str",
      "parents": "list",
      "source": "str",
      "seed": "int",
      "created": "float",
      "used": "list"
    },
    "selection.retired": {
      "id": "str",
      "style": "str",
      "elo": "int",
      "matches": "int",
      "wins": "int",
      "placed": "bool",
      "image_file": "str",
      "seed": "int",
      "created": "float",
      "generation": "int",
      "selection_applied": "dict",
      "excluded": "dict"
    },
    "selection": {
      "generation": "int",
      "candidate_ids": "list",
      "batch_id": "str",
      "retired": "list",
      "parent_ids": "list",
      "parent_scores": "dict",
      "log": "list"
    }
  }
}
```

## 읽은 Snapshot의 수량
```json
{
  "artists": 197,
  "loras": 10,
  "active_combinations": 27,
  "retired_combinations": 936,
  "history_entries": 1634,
  "history_types": {
    "selection_vote": 1367,
    "arena": 85,
    "selection_skip": 171,
    "place_skip": 3,
    "place_vote": 8
  },
  "generation": 79
}
```

서비스 사용 중 데이터가 달라질 수 있습니다. 위 숫자는 문서 생성 시 한 번 읽은 파일의 수량입니다.

## Workflow Node 원문 식별

| 구분 | Node ID | Class Type |
| --- | --- | --- |
| Style Lab | 1 | `UNETLoader` |
| Style Lab | 2 | `CLIPLoader` |
| Style Lab | 3 | `VAELoader` |
| Style Lab | 4 | `CLIPTextEncode` |
| Style Lab | 5 | `CLIPTextEncode` |
| Style Lab | 6 | `EmptyLatentImage` |
| Style Lab | 7 | `KSampler` |
| Style Lab | 8 | `VAEDecode` |
| Style Lab | 9 | `PreviewImage` |
| Style Lab | style_lab_negpip | `CLIPNegPip` |
| Home Anima | 1 | `UNETLoader` |
| Home Anima | 3 | `ImpactWildcardProcessor` |
| Home Anima | 4 | `ImpactWildcardProcessor` |
| Home Anima | 5 | `Lora Loader (LoraManager)` |
| Home Anima | 6 | `KSampler` |
| Home Anima | 7 | `UltralyticsDetectorProvider` |
| Home Anima | 8 | `SAMLoader` |
| Home Anima | 13 | `Image Saver Simple` |
| Home Anima | 18 | `CLIPLoader` |
| Home Anima | 19 | `ToDetailerPipe` |
| Home Anima | 23 | `VAELoader` |
| Home Anima | 24 | `Input Parameters (Image Saver)` |
| Home Anima | 26 | `easy showAnything` |
| Home Anima | 27 | `easy showAnything` |
| Home Anima | 28 | `DifferentialDiffusion` |
| Home Anima | 34 | `ImpactSwitch` |
| Home Anima | 35 | `VAEDecode` |
| Home Anima | 38 | `StringConcatenate` |
| Home Anima | 39 | `PrimitiveFloat` |
| Home Anima | 40 | `RegexReplace` |
| Home Anima | 42 | `StringConcatenate` |
| Home Anima | 43 | `TriggerWord Toggle (LoraManager)` |
| Home Anima | 44 | `PrimitiveFloat` |
| Home Anima | 45 | `easy int` |
| Home Anima | 47 | `PrimitiveFloat` |
| Home Anima | 48 | `easy int` |
| Home Anima | 50 | `PrimitiveBoolean` |
| Home Anima | 51 | `easy int` |
| Home Anima | 53 | `CLIPTextEncode` |
| Home Anima | 54 | `CLIPTextEncode` |
| Home Anima | 55 | `EmptyLatentImage` |
| Home Anima | 56 | `WidgetToString` |
| Home Anima | 57 | `Image Saver Metadata` |
| Home Anima | 462 | `CLIPNegPip` |

## 기존 Bridge API 라우트

| Method | Path | 원문 Handler 표현 |
| --- | --- | --- |
| GET | `/api/status` | `lambda: e.status(int(query.get('since', 0)))` |
| GET | `/api/match` | `e.match` |
| GET | `/api/combos` | `e.list_combos` |
| GET | `/api/artists` | `e.list_artists` |
| GET | `/api/loras` | `e.list_loras` |
| GET | `/api/loras/loading` | `e.lora_loading_notice` |
| GET | `/api/evolution` | `e.evolution_view` |
| GET | `/api/lora-lock` | `e.lora_lock_view` |
| GET | `/api/tune` | `e.tune_view` |
| GET | `/api/merge` | `e.merge_view` |
| GET | `/api/improve` | `e.improve_view` |
| GET | `/api/settings` | `e.settings_payload` |
| GET | `/api/meta` | `lambda: {'sizes': list(core.SIZE_PRESETS), 'samplers': core.SAMPLERS, 'schedulers': core.SCHEDULERS, 'tiers': core.TIER_ORDER, 'data_dir': str(e.data_dir), 'max_seed': core.MAX_SEED, 'version': VERSION, # the one table of input limits; every field on every page reads it 'ranges': {key: [low, high] for key, (_, low, high) in SETTING_RANGES.items()}}` |
| GET | `/api/free` | `lambda: {'results': [{**r, 'url': f"/img/{r['image']}", 'listed': bool(r.get('listed') and any(c['id'] == r['listed'] for c in e.combos))} for r in e.state['free_results']]}` |
| POST | `/api/vote` | `lambda: e.vote(body.get('side'))` |
| POST | `/api/skip` | `e.skip` |
| POST | `/api/undo` | `e.undo` |
| POST | `/api/settings` | `lambda: e.update_settings(body.get('changes', {}))` |
| POST | `/api/settings/draft` | `lambda: self.keep_draft(body.get('seq'), body.get('changes'))` |
| POST | `/api/connection` | `e.check_connection` |
| POST | `/api/artists/add` | `lambda: {'added': e.add_artists(body.get('text', ''))}` |
| POST | `/api/artists/scan` | `lambda: e.scan_artists(body.get('text', ''))` |
| POST | `/api/artists/rename` | `lambda: e.rename_artist(body.get('old'), body.get('new'))` |
| POST | `/api/artists/delete` | `lambda: e.delete_artists(body.get('tags', []))` |
| POST | `/api/loras/add` | `lambda: e.add_loras(body.get('names', []))` |
| POST | `/api/loras/update` | `lambda: e.update_lora(body.get('tag'), body.get('min_w'), body.get('max_w'), body.get('trigger'))` |
| POST | `/api/loras/read` | `lambda: e.read_loras(body.get('tags', []))` |
| POST | `/api/loras/check` | `lambda: e.start_lora_check(body.get('tags', []))` |
| POST | `/api/usage/reset` | `lambda: e.reset_usage()` |
| POST | `/api/loras/delete` | `lambda: e.delete_loras(body.get('tags', []), bool(body.get('with_combos')))` |
| POST | `/api/generate/random` | `lambda: e.start_random(body.get('count'))` |
| POST | `/api/combos/merge` | `lambda: e.merge_combos(ids)` |
| POST | `/api/tune/start` | `lambda: e.start_tune(body.get('id'), body.get('count'), body.get('spread', 'normal'), body.get('scope', 'all'))` |
| POST | `/api/tune/more` | `lambda: e.tune_more(body.get('count'))` |
| POST | `/api/tune/render` | `lambda: e.tune_render(body.get('count'))` |
| POST | `/api/tune/finish` | `e.finish_tune` |
| POST | `/api/merge/add` | `lambda: e.merge_add(body.get('keys'), bool(body.get('keep')))` |
| POST | `/api/merge/refine` | `lambda: e.merge_refine(body.get('key'))` |
| POST | `/api/merge/delete` | `lambda: e.merge_delete(body.get('keys'))` |
| POST | `/api/generate/custom` | `lambda: e.start_custom(body.get('text', ''))` |
| POST | `/api/free/delete` | `lambda: e.free_delete(body.get('images'))` |
| POST | `/api/free/adopt` | `lambda: e.free_adopt(body.get('image'), bool(body.get('keep')), bool(body.get('refine')))` |
| POST | `/api/generate/free` | `lambda: e.start_free(body.get('prompt', ''), body.get('base'), body.get('negative'), body.get('seed'))` |
| POST | `/api/job/stop` | `e.stop_job` |
| POST | `/api/combos/revive` | `lambda: {'revived': e.revive(ids)}` |
| POST | `/api/combos/elo` | `lambda: e.set_elo(ids, body.get('elo'))` |
| POST | `/api/combos/memo` | `lambda: e.set_memo(body.get('id'), body.get('memo'))` |
| POST | `/api/combos/keep` | `lambda: e.set_kept(ids, body.get('kept', True))` |
| POST | `/api/combos/delete` | `lambda: e.delete_combos(ids)` |
| POST | `/api/combos/purge` | `lambda: e.purge(body.get('reason'))` |
| POST | `/api/open` | `lambda: self.open_image(body.get('id'), body.get('file'))` |
| POST | `/api/open-folder` | `lambda: open_external(str(e.data_dir))` |
| POST | `/api/drag` | `lambda: self.drag_image(body.get('file'))` |
| POST | `/api/open-comfy` | `lambda: open_external(core.comfy_base(e.settings()['comfy_url']))` |
| POST | `/api/data/export` | `lambda: {'path': self.export_data()}` |
| POST | `/api/data/pick` | `self.pick_import` |
| POST | `/api/data/import` | `self.import_data` |
| POST | `/api/evolution/start` | `lambda: e.start_evolution(body.get('count'))` |
| POST | `/api/evolution/finish` | `e.finish_generation` |
| POST | `/api/evolution/cancel` | `e.cancel_generation` |
| POST | `/api/improve/start` | `lambda: e.start_improve(body.get('id'), body.get('variants'))` |
| POST | `/api/improve/next` | `e.improve_next_round` |
| POST | `/api/improve/final` | `e.improve_final_check` |
| POST | `/api/improve/finish` | `lambda: {'result': e.finish_improve(body.get('choice', 'champion'))}` |
| POST | `/api/improve/resume` | `e.improve_resume` |
| POST | `/api/improve/undo-finish` | `e.undo_finish` |
| POST | `/api/reset` | `lambda: e.reset(body.get('scope'))` |

Web 전용 Login/Session/CSRF/ZIP 처리는 `web_server.py` Snapshot을 참고합니다.
Bridge 내부의 Native Open/Drag를 Web에서도 실행할 수 있다고 해석하면 안 됩니다.

## 원본 구현과 새 설계의 대응

- 기존 데이터는 Project가 없는 Schema2이고 Home은 현재 DB Schema14입니다.
- Project API·ComponentPrior·Moss Adapter는 이 문서의 설계안입니다.
- 작가 점수는 Registry Field를 단순 복사한 값이 아니라 `artist_scores(active + retired)`의 결과입니다.
