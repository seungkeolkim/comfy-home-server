# Source Snapshot: app/bridge.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\app\bridge.py`
- Original Byte SHA-256: `e59f67bbd455ba6c0672dfa708d1135dc01d5f77347e6c2f49b72a43910361d8`
- Snapshot Text SHA-256: `e59f67bbd455ba6c0672dfa708d1135dc01d5f77347e6c2f49b72a43910361d8`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""The app window's link to :class:`engine.Engine`: no server, no network.

The page calls :meth:`App.call` through pywebview's own channel, and its files (the page itself, the
pictures) are handed to WebView2 straight from disk by main.py through :meth:`App.resource`. Nothing
listens on a port, so no browser and no other program can reach the app.
"""
import json
import mimetypes
import os
import queue
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from pathlib import Path

import core
from engine import SETTING_RANGES, Engine, UserError
from version import VERSION

WEB_DIR = Path(__file__).resolve().parent.parent / 'web'
THUMB_SIZE = (440, 760)
# Never cached: a picture whose thumbnail is still being made, or the page's own files.
NO_STORE, CACHED = 'no-store', 'max-age=31536000, immutable'


class NotFound(Exception):
    """Unknown route (kept apart from KeyError/IndexError raised inside handlers)."""


def open_external(target):
    """Open a file, folder or URL with its usual program. The app window belongs to this process, so what
    it starts may come to the front."""
    os.startfile(target)


mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('image/svg+xml', '.svg')


class App:
    def __init__(self, engine: Engine, log_file: Path | None = None):
        self.engine = engine
        # Set by main.py from the app window: Save As (zip name -> path or None), Open (-> path or None), close,
        # and a file drag out of the window (path).
        self.save_dialog = self.open_dialog = self.close_window = self.start_drag = None
        self.log_file = log_file
        self.thumb_lock = threading.Lock()  # held while one is made
        self.thumb_queue = queue.Queue()
        self.thumb_waiting = set()  # queued and not made yet; its own lock, so the window never waits on a making
        self.waiting_lock = threading.Lock()
        self.picked_import = None  # the zip chosen in Open, until it is imported
        # Settings typed but not saved yet, kept by the page as it goes ((seq, changes): the newest wins),
        # so closing the window mid-typing still saves them (see shutdown).
        self.draft = (-1, {})

    def log(self, text):
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as fh:
                fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")

    # ---------------------------------------------------------------- the page's calls
    def call(self, method, path, body=None):
        """One request from the page: ``{ok, data}`` or ``{ok: false, error}``, as JSON text (so anything the
        page cannot read is an error here, not a broken reply)."""
        try:
            url = urllib.parse.urlsplit(path)
            if method == 'GET':
                data = self.get(url.path, dict(urllib.parse.parse_qsl(url.query)))
            elif method == 'POST':
                data = self.post(url.path, body if isinstance(body, dict) else {})
            else:
                raise NotFound(path)
            return json.dumps({'ok': True, 'data': data}, ensure_ascii=False)
        except UserError as exc:
            return json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False)
        except NotFound:
            return json.dumps({'ok': False, 'error': f'알 수 없는 요청입니다: {path}'}, ensure_ascii=False)
        except Exception as exc:
            self.log(f'{method} {path}\n{traceback.format_exc()}')
            return json.dumps({'ok': False, 'error': f'내부 오류가 났습니다: {exc}'}, ensure_ascii=False)

    def get(self, path, query):
        e = self.engine
        routes = {
            '/api/status': lambda: e.status(int(query.get('since', 0))),
            '/api/match': e.match,
            '/api/combos': e.list_combos,
            '/api/artists': e.list_artists,
            '/api/loras': e.list_loras,
            '/api/loras/loading': e.lora_loading_notice,
            '/api/evolution': e.evolution_view,
            '/api/lora-lock': e.lora_lock_view,
            '/api/tune': e.tune_view,
            '/api/merge': e.merge_view,
            '/api/improve': e.improve_view,
            '/api/settings': e.settings_payload,
            '/api/meta': lambda: {'sizes': list(core.SIZE_PRESETS),
                                  'samplers': core.SAMPLERS, 'schedulers': core.SCHEDULERS, 'tiers': core.TIER_ORDER,
                                  'data_dir': str(e.data_dir), 'max_seed': core.MAX_SEED, 'version': VERSION,
                                  # the one table of input limits; every field on every page reads it
                                  'ranges': {key: [low, high] for key, (_, low, high) in SETTING_RANGES.items()}},
            '/api/free': lambda: {'results': [{**r, 'url': f"/img/{r['image']}", 'listed': bool(r.get('listed') and any(c['id'] == r['listed'] for c in e.combos))} for r in e.state['free_results']]},
        }
        if path not in routes:
            raise NotFound(path)
        return routes[path]()

    def post(self, path, body):
        e = self.engine
        ids = body.get('ids', [])
        routes = {
            '/api/vote': lambda: e.vote(body.get('side')),
            '/api/skip': e.skip,
            '/api/undo': e.undo,
            '/api/settings': lambda: e.update_settings(body.get('changes', {})),
            '/api/settings/draft': lambda: self.keep_draft(body.get('seq'), body.get('changes')),
            '/api/connection': e.check_connection,
            '/api/artists/add': lambda: {'added': e.add_artists(body.get('text', ''))},
            '/api/artists/scan': lambda: e.scan_artists(body.get('text', '')),
            '/api/artists/rename': lambda: e.rename_artist(body.get('old'), body.get('new')),
            '/api/artists/delete': lambda: e.delete_artists(body.get('tags', [])),
            '/api/loras/add': lambda: e.add_loras(body.get('names', [])),
            '/api/loras/update': lambda: e.update_lora(body.get('tag'), body.get('min_w'), body.get('max_w'), body.get('trigger')),
            '/api/loras/read': lambda: e.read_loras(body.get('tags', [])),
            '/api/loras/check': lambda: e.start_lora_check(body.get('tags', [])),
            '/api/usage/reset': lambda: e.reset_usage(),
            '/api/loras/delete': lambda: e.delete_loras(body.get('tags', []), bool(body.get('with_combos'))),
            '/api/generate/random': lambda: e.start_random(body.get('count')),
            '/api/combos/merge': lambda: e.merge_combos(ids),
            '/api/tune/start': lambda: e.start_tune(body.get('id'), body.get('count'), body.get('spread', 'normal'), body.get('scope', 'all')),
            '/api/tune/more': lambda: e.tune_more(body.get('count')),
            '/api/tune/render': lambda: e.tune_render(body.get('count')),
            '/api/tune/finish': e.finish_tune,
            '/api/merge/add': lambda: e.merge_add(body.get('keys'), bool(body.get('keep'))),
            '/api/merge/refine': lambda: e.merge_refine(body.get('key')),
            '/api/merge/delete': lambda: e.merge_delete(body.get('keys')),
            '/api/generate/custom': lambda: e.start_custom(body.get('text', '')),
            '/api/free/delete': lambda: e.free_delete(body.get('images')),
            '/api/free/adopt': lambda: e.free_adopt(body.get('image'), bool(body.get('keep')), bool(body.get('refine'))),
            '/api/generate/free': lambda: e.start_free(body.get('prompt', ''), body.get('base'), body.get('negative'), body.get('seed')),
            '/api/job/stop': e.stop_job,
            '/api/combos/revive': lambda: {'revived': e.revive(ids)},
            '/api/combos/elo': lambda: e.set_elo(ids, body.get('elo')),
            '/api/combos/memo': lambda: e.set_memo(body.get('id'), body.get('memo')),
            '/api/combos/keep': lambda: e.set_kept(ids, body.get('kept', True)),
            '/api/combos/delete': lambda: e.delete_combos(ids),
            '/api/combos/purge': lambda: e.purge(body.get('reason')),
            '/api/open': lambda: self.open_image(body.get('id'), body.get('file')),
            '/api/open-folder': lambda: open_external(str(e.data_dir)),
            '/api/drag': lambda: self.drag_image(body.get('file')),
            # ComfyUI's own page, at the address set in the settings (http(s) only), in the user's browser.
            '/api/open-comfy': lambda: open_external(core.comfy_base(e.settings()['comfy_url'])),
            '/api/data/export': lambda: {'path': self.export_data()},
            '/api/data/pick': self.pick_import,
            '/api/data/import': self.import_data,
            '/api/evolution/start': lambda: e.start_evolution(body.get('count')),
            '/api/evolution/finish': e.finish_generation,
            '/api/evolution/cancel': e.cancel_generation,
            '/api/improve/start': lambda: e.start_improve(body.get('id'), body.get('variants')),
            '/api/improve/next': e.improve_next_round,
            '/api/improve/final': e.improve_final_check,
            '/api/improve/finish': lambda: {'result': e.finish_improve(body.get('choice', 'champion'))},
            '/api/improve/resume': e.improve_resume,
            '/api/improve/undo-finish': e.undo_finish,
            '/api/reset': lambda: e.reset(body.get('scope')),
        }
        if path not in routes:
            raise NotFound(path)
        return routes[path]()

    def keep_draft(self, seq, changes):
        if isinstance(seq, int) and isinstance(changes, dict) and seq > self.draft[0]:
            self.draft = (seq, changes)

    def open_image(self, combo_id=None, file=None):
        path = self.engine.image_path(combo_id) if combo_id else self.safe_image(file)
        if not path or not path.exists():
            raise UserError('원본 이미지 파일을 찾을 수 없습니다.')
        open_external(str(path))

    def drag_image(self, file):
        """Hand an image to Windows as a file being dragged, while the mouse button is still down in the window."""
        path = self.safe_image(file)
        if not path or not path.exists():
            raise UserError('원본 이미지 파일을 찾을 수 없습니다.')
        if self.start_drag:
            self.start_drag(path)

    def export_data(self):
        """Save As, then write the zip there. None when the dialog was cancelled."""
        path = self.save_dialog(f'anima-style-lab-{datetime.now():%Y%m%d_%H%M%S}.zip')
        if not path:
            return None
        part = Path(path + '.part')  # a failed export never replaces a file that was already there
        try:
            with open(part, 'wb') as fh:
                self.engine.export_data(fh)
            os.replace(part, path)
        except OSError as exc:
            raise UserError(f'파일을 저장할 수 없습니다: {exc}')
        finally:
            part.unlink(missing_ok=True)
        return path

    def pick_import(self):
        """Open, for the zip to import: its name (for the page to confirm), or None when cancelled."""
        path = self.open_dialog()
        self.picked_import = Path(path) if path else None
        return {'name': self.picked_import.name} if self.picked_import else None

    def import_data(self):
        """Import the zip picked in Open (only that one: the page never names a file itself)."""
        path, self.picked_import = self.picked_import, None
        if not path:
            raise UserError('불러올 파일을 먼저 고르세요.')
        try:
            blob = path.read_bytes()
        except OSError as exc:
            raise UserError(f'파일을 읽을 수 없습니다: {exc}')
        return self.engine.import_data(blob)

    def retire(self):
        """A launch with newer code takes over: close now unless generating. Closing the window ends the
        app (main.py then saves); without a window, save directly."""
        job = self.engine.job
        if job and job['running']:
            return {'closing': False}
        threading.Timer(0.1, self.close_window or self.shutdown).start()  # after this reply is sent
        return {'closing': True}

    # ---------------------------------------------------------------- files
    def resource(self, path):
        """What the window shows at ``path`` (the page, its files, the pictures): ``(file, content type,
        cache)``, or None. Only files inside web/, images/ and thumbs/ are ever handed out. ``path`` is as in the
        URL (still %-encoded): decoded once, here or by safe_image."""
        if path in ('/', '/index.html'):
            return self._typed(WEB_DIR / 'index.html', NO_STORE)
        if path.startswith('/static/'):
            target = (WEB_DIR / urllib.parse.unquote(path[len('/static/'):])).resolve()
            return self._typed(target, NO_STORE) if WEB_DIR.resolve() in target.parents else None
        if path.startswith('/img/'):
            return self._typed(self.safe_image(path[len('/img/'):]), CACHED)
        if path.startswith('/thumb/'):
            name = path[len('/thumb/'):]
            source = self.safe_image(name)
            if not source or not source.is_file():
                return None
            thumb = self.engine.thumb_dir / (source.stem + '.webp')
            if thumb.is_file() and thumb.stat().st_mtime >= source.stat().st_mtime:
                return self._typed(thumb, CACHED)
            # A picture made after the window opened: the full image this once (never blocking the window),
            # its thumbnail being made in the background for next time.
            self.queue_thumbnail(name)
            return self._typed(source, NO_STORE)
        return None

    @staticmethod
    def _typed(path, cache):
        if not path or not path.is_file():
            return None
        ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return path, ctype + ('; charset=utf-8' if ctype.startswith('text/') else ''), cache

    def safe_image(self, name):
        if not name:
            return None
        path = (self.engine.img_dir / urllib.parse.unquote(name)).resolve()
        return path if path.parent == self.engine.img_dir.resolve() and path.suffix.lower() == '.png' else None

    def thumbnail(self, name):
        source = self.safe_image(name)
        if not source or not source.exists():
            return None
        thumb_dir = self.engine.thumb_dir
        target = thumb_dir / (source.stem + '.webp')
        with self.thumb_lock:
            if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                from PIL import Image
                thumb_dir.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix('.part')  # never a half-written thumbnail where the window reads it
                with Image.open(source) as img:
                    img.thumbnail(THUMB_SIZE, Image.LANCZOS)
                    img.convert('RGB').save(part, 'WEBP', quality=84, method=4)
                os.replace(part, target)
        return target

    def queue_thumbnail(self, name):
        with self.waiting_lock:
            if name in self.thumb_waiting:
                return
            self.thumb_waiting.add(name)
        self.thumb_queue.put(name)

    def thumbnail_worker(self):
        """Make thumbnails one at a time, in the background: every missing one first (so galleries open
        instantly), then each one the window asked for."""
        with self.engine.lock:
            names = [c.get('image_file') for c in self.engine.combos + self.engine.retired]
        for name in names:
            if name:
                self.queue_thumbnail(name)
        while True:
            name = self.thumb_queue.get()
            try:
                self.thumbnail(name)
            except Exception as exc:
                self.log(f'thumbnail {name}: {exc}')
            finally:
                with self.waiting_lock:
                    self.thumb_waiting.discard(name)

    # ---------------------------------------------------------------- lifecycle
    def shutdown(self):
        """Stop (a running generation is stopped, not waited for), keep what was still being typed, save."""
        self.engine.stop_job()
        changes = self.draft[1]
        if changes:
            try:
                self.engine.update_settings(changes)
            except UserError as exc:  # out of range: like any refused change, the saved value stays
                self.log(f'unsaved settings on close: {exc}')
            except Exception:
                self.log(f'unsaved settings on close\n{traceback.format_exc()}')
        self.engine.save()
```
