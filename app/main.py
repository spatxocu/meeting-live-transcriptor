"""Meeting Transcriptor - desktop window and the API the interface calls."""
import ctypes
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

import webview

from . import commands, config, server, store
from .audio import Recorder, Standby, list_microphones
from .transcriber import Transcriber, model_name

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))   # packaged or source
UI = BASE / "ui" / "index.html"
ICON = BASE / "assets" / "icon.ico"
TRANSCRIPT_TYPES = {".txt", ".md", ".srt", ".json"}
SPEAKERS = {"mic": "You", "system": "Others"}

if hasattr(webview, "FileDialog"):
    OPEN_DIALOG, SAVE_DIALOG, FOLDER_DIALOG = (webview.FileDialog.OPEN, webview.FileDialog.SAVE,
                                               webview.FileDialog.FOLDER)
else:
    OPEN_DIALOG, SAVE_DIALOG, FOLDER_DIALOG = webview.OPEN_DIALOG, webview.SAVE_DIALOG, webview.FOLDER_DIALOG


def log(*parts):
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except OSError:
        pass


class Api:
    def __init__(self):
        self._window = None
        self._ready = False
        self._settings = config.load_settings()
        self._needs_folder = not self._settings["folder"]
        config.use_folder(self._settings["folder"])
        try:
            config.MEETINGS.mkdir(parents=True, exist_ok=True)
        except OSError:                 # e.g. the chosen drive is not connected
            log("meeting folder unavailable", config.MEETINGS)
            self._needs_folder = True
            config.use_folder("")
            config.MEETINGS.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = "idle"            # idle | recording | finishing
        self._started = 0
        self._meeting = None
        self._recorder = None
        self._standby = None
        self._session = 0
        self._busy = None               # meeting id being imported or re-transcribed
        self._jobs = queue.Queue()
        self._partials = {}             # source -> newest unfinished utterance
        self._closed = {}               # source -> start of the last finished utterance
        self._previews = {}             # speaker -> preview currently on screen
        self._wake = threading.Event()
        self._model = {"status": "loading", "name": self._settings["live_model"], "error": ""}
        self._transcriber = Transcriber(self._on_model)
        self._port = server.start()

    # ---- startup -------------------------------------------------------

    def _attach(self, window):
        self._window = window
        window.events.loaded += self._on_loaded
        window.events.closed += self._shutdown
        self._start_workers()
        threading.Thread(target=self._preload, daemon=True).start()
        commands.listen_hotkey(self.toggle_recording)

    def _on_loaded(self):
        self._ready = True
        set_window_icon()

    def _start_workers(self):
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._preview_worker, daemon=True).start()

    def _live_model(self):
        return model_name(self._settings["live_model"], self._settings["language"])

    def _preview_model(self, language=None):
        language = language or self._settings["language"]
        # The tiny model is only good enough for rough previews in English.
        size = "tiny" if language == "en" or self._settings["live_model"] == "tiny" else "base"
        return model_name(size, language)

    def _preload(self):
        try:
            self._transcriber.model(self._preview_model())
            self._transcriber.model(self._live_model())
        except Exception:
            log("model load failed", traceback.format_exc())
        self._start_standby()

    def _emit(self, kind, data=None):
        if not self._ready:
            return
        try:
            self._window.evaluate_js(f"window.LT && LT.onEvent({json.dumps(kind)}, {json.dumps(data)})")
        except Exception:
            pass

    def _on_model(self, status, name, error):
        self._model = {"status": status, "name": name, "error": error}
        self._emit("model", self._model)

    def _status(self):
        return {"state": self._state, "started": self._started, "busy": self._busy,
                "meeting_id": self._meeting["id"] if self._meeting else None}

    # ---- live transcription -------------------------------------------

    def _worker(self):
        while True:
            job = self._jobs.get()
            if job[0] == "end":
                job[1].set()
                continue
            _, session, source, start, audio = job
            if session != self._session:
                continue
            try:
                if source == "standby":
                    segments = self._transcriber.transcribe_array(audio, "en", self._preview_model("en"))
                else:
                    segments = self._transcriber.transcribe_array(audio, self._settings["language"],
                                                                  self._live_model())
            except Exception:
                log("live transcription failed", traceback.format_exc())
                continue
            for seg_start, seg_end, text in segments:
                self._on_segment(session, source, start + seg_start, start + seg_end, text)
            if source != "standby" and session == self._session and self._meeting:
                self._previews.pop(SPEAKERS[source], None)
                self._emit("partial", {"id": self._meeting["id"], "speaker": SPEAKERS[source],
                                       "start": start, "text": ""})

    def _queue_final(self, session, source, start, audio):
        self._closed[source] = start
        self._partials.pop(source, None)
        self._jobs.put(("chunk", session, source, start, audio))

    def _queue_partial(self, session, source, start, audio):
        self._partials[source] = (session, start, audio)
        self._wake.set()

    def _preview_worker(self):
        """Shows rough text for a sentence while it is still being spoken."""
        while True:
            self._wake.wait()
            self._wake.clear()
            for source in list(self._partials):
                item = self._partials.pop(source, None)
                if not item:
                    continue
                session, start, audio = item
                if session != self._session:
                    continue
                try:
                    text = self._transcriber.preview(audio, self._settings["language"], self._preview_model())
                except Exception:
                    log("preview failed", traceback.format_exc())
                    continue
                meeting = self._meeting
                if (not text or not meeting or session != self._session
                        or self._closed.get(source, -1) >= start):
                    continue
                speaker = SPEAKERS[source]
                preview = {"start": round(start, 2), "end": round(start, 2), "speaker": speaker, "text": text}
                if speaker == "You":
                    heard = [s for s in meeting["segments"][-6:] if s["speaker"] == "Others"]
                    if "Others" in self._previews:
                        heard.append(self._previews["Others"])
                    if any(commands.is_echo(preview, s) for s in heard):
                        continue
                self._previews[speaker] = preview
                self._emit("partial", {"id": meeting["id"], "speaker": speaker,
                                       "start": preview["start"], "text": text})

    def _on_segment(self, session, source, start, end, text):
        if session != self._session:
            return
        if source == "standby":
            if commands.is_start(text):
                threading.Thread(target=self.start_recording, daemon=True).start()
            return
        meeting = self._meeting
        if meeting is None:
            return
        if source == "mic" and self._settings["voice_command"] and commands.is_stop(text):
            self.stop_recording()
            return
        segment = {"start": round(start, 2), "end": round(end, 2), "speaker": SPEAKERS[source], "text": text}
        segments = meeting["segments"]
        if source == "mic":
            if any(s["speaker"] == "Others" and commands.is_echo(segment, s) for s in segments[-12:]):
                return
        else:
            echoes = [s for s in segments[-12:] if s["speaker"] == "You" and commands.is_echo(s, segment)]
            if echoes:
                meeting["segments"] = segments = [s for s in segments if s not in echoes]
        segments.append(segment)
        segments.sort(key=lambda s: s["start"])
        store.save(meeting)
        offset = max(0, len(segments) - 40)     # only the tail can have changed
        self._emit("segments", {"id": meeting["id"], "offset": offset, "tail": segments[offset:]})

    def _on_level(self, source, level):
        self._emit("level", {"source": source, "level": level})

    def _start_standby(self):
        with self._lock:
            if self._standby or self._state != "idle" or not self._settings["voice_command"]:
                return
            self._session += 1
            session = self._session
            try:
                self._standby = Standby(lambda src, start, audio:
                                        self._jobs.put(("chunk", session, src, start, audio)),
                                        self._settings["microphone"])
            except Exception:
                log("standby listener failed", traceback.format_exc())

    def _stop_standby(self):
        with self._lock:
            standby, self._standby = self._standby, None
        if standby:
            standby.stop()

    # ---- recording ----------------------------------------------------

    def start_recording(self):
        with self._lock:
            if self._state != "idle":
                return {"ok": False, "error": "Already recording."}
            if self._busy:
                return {"ok": False, "error": "Wait for the current transcription to finish."}
            self._stop_standby()
            self._session += 1
            session = self._session
            meeting = store.new_meeting()
            self._partials, self._closed, self._previews = {}, {}, {}
            recorder = Recorder(store.folder(meeting["id"]),
                                lambda src, start, audio: self._queue_final(session, src, start, audio),
                                self._on_level,
                                lambda src, start, audio: self._queue_partial(session, src, start, audio),
                                self._settings["microphone"])
            try:
                meeting["sources"] = recorder.start()
            except Exception as error:
                log("recording failed to start", traceback.format_exc())
                store.delete(meeting["id"])
                self._start_standby()
                return {"ok": False, "error": str(error)}
            self._meeting, self._recorder = meeting, recorder
            self._state, self._started = "recording", time.time()
        self._emit("meetings")
        self._emit("status", self._status())
        return {"ok": True, "id": meeting["id"]}

    def stop_recording(self):
        with self._lock:
            if self._state != "recording":
                return {"ok": False}
            self._state = "finishing"
        self._emit("status", self._status())
        threading.Thread(target=self._finish, daemon=True).start()
        return {"ok": True}

    def toggle_recording(self):
        return self.start_recording() if self._state == "idle" else self.stop_recording()

    def _finish(self):
        meeting, recorder = self._meeting, self._recorder
        try:
            meeting["duration"] = round(recorder.stop(), 1)
            meeting["audio_file"] = "audio.wav"
            store.save(meeting)
            done = threading.Event()
            self._jobs.put(("end", done))
            done.wait()
            store.save(meeting)
        except Exception:
            log("finishing failed", traceback.format_exc())
        with self._lock:
            self._meeting = self._recorder = None
            self._state = "idle"
        self._emit("status", self._status())
        self._emit("meetings")
        self._emit("meeting", meeting["id"])
        self._start_standby()

    def _shutdown(self):
        """Window closed: stop capture and keep whatever was transcribed so far."""
        self._stop_standby()
        with self._lock:
            meeting, recorder = self._meeting, self._recorder
            self._session += 1
        if recorder and meeting:
            try:
                meeting["duration"] = round(recorder.stop(), 1)
                meeting["audio_file"] = "audio.wav"
                store.save(meeting)
            except Exception:
                log("shutdown save failed", traceback.format_exc())

    # ---- library ------------------------------------------------------

    def boot(self):
        return {
            "app": config.APP_NAME,
            "settings": self._settings,
            "languages": sorted(config.LANGUAGES.items(), key=lambda item: item[1]),
            "live_models": config.LIVE_MODELS,
            "hq_models": config.HQ_MODELS,
            "microphones": self.list_microphones(),
            "model": self._model,
            "status": self._status(),
            "meetings": store.list_meetings(),
            "folder": str(config.MEETINGS),
            "needs_folder": self._needs_folder,
            "default_folder": str(config.DEFAULT_MEETINGS),
        }

    def list_microphones(self):
        try:
            return list_microphones()
        except Exception:
            log("listing microphones failed", traceback.format_exc())
            return []

    def list_meetings(self, query=""):
        return store.list_meetings(query)

    def get_meeting(self, meeting_id):
        try:
            meeting = self._meeting if self._meeting and self._meeting["id"] == meeting_id \
                else store.load(meeting_id)
        except (OSError, ValueError):
            return None
        result = dict(meeting)
        result["audio_url"] = None
        if meeting.get("audio_file") and not (self._meeting and self._meeting["id"] == meeting_id):
            result["audio_url"] = f"http://127.0.0.1:{self._port}/audio/{meeting_id}/{meeting['audio_file']}"
        result["can_improve"] = bool(meeting.get("audio_file"))
        return result

    def rename_meeting(self, meeting_id, title):
        title = (title or "").strip()[:120]
        if not title:
            return False
        meeting = self._meeting if self._meeting and self._meeting["id"] == meeting_id \
            else store.load(meeting_id)
        meeting["title"] = title
        store.save(meeting)
        return True

    def delete_meeting(self, meeting_id):
        if (self._meeting and self._meeting["id"] == meeting_id) or self._busy == meeting_id:
            return False
        store.delete(meeting_id)
        return True

    def export_meeting(self, meeting_id, fmt):
        if fmt not in ("txt", "md", "srt"):
            return {"ok": False}
        meeting = store.load(meeting_id)
        safe = "".join(c for c in meeting["title"] if c not in '\\/:*?"<>|').strip() or "transcript"
        chosen = self._window.create_file_dialog(SAVE_DIALOG, save_filename=f"{safe}.{fmt}")
        if not chosen:
            return {"ok": False}
        path = chosen if isinstance(chosen, str) else chosen[0]
        Path(path).write_text(store.export_text(meeting, fmt), encoding="utf-8")
        return {"ok": True, "path": path}

    def import_file(self):
        if self._state != "idle" or self._busy:
            return {"ok": False, "error": "Finish the current recording or transcription first."}
        chosen = self._window.create_file_dialog(OPEN_DIALOG, file_types=(
            "Audio, video or transcript (*.mp3;*.wav;*.m4a;*.mp4;*.mkv;*.mov;*.webm;*.ogg;*.flac;*.aac;*.wma;*.txt;*.md;*.srt;*.json)",
            "All files (*.*)"))
        if not chosen:
            return {"ok": False}
        source = Path(chosen if isinstance(chosen, str) else chosen[0])
        suffix = source.suffix.lower()
        if suffix in TRANSCRIPT_TYPES:
            try:
                segments = store.parse_transcript(source.read_text(encoding="utf-8-sig"), suffix)
            except (OSError, ValueError, KeyError, TypeError) as error:
                return {"ok": False, "error": f"Could not read that transcript: {error}"}
            meeting = store.new_meeting(source.stem, "imported transcript")
            meeting["segments"] = segments
            meeting["duration"] = max((s["end"] for s in segments), default=0)
            store.save(meeting)
            return {"ok": True, "id": meeting["id"]}
        meeting = store.new_meeting(source.stem, "imported file")
        meeting["audio_file"] = "audio" + suffix
        shutil.copyfile(source, store.folder(meeting["id"]) / meeting["audio_file"])
        store.save(meeting)
        self._busy = meeting["id"]
        threading.Thread(target=self._transcribe_files, daemon=True,
                         args=(meeting, [(meeting["audio_file"], "Speaker")], self._settings["live_model"])).start()
        return {"ok": True, "id": meeting["id"]}

    def improve_meeting(self, meeting_id):
        """Re-transcribe saved audio with the larger, more accurate model."""
        if self._state != "idle" or self._busy:
            return {"ok": False, "error": "Finish the current recording or transcription first."}
        meeting = store.load(meeting_id)
        base = store.folder(meeting_id)
        files = [(f"{name}.wav", SPEAKERS[name]) for name in ("mic", "system") if (base / f"{name}.wav").exists()]
        if not files and meeting.get("audio_file"):
            files = [(meeting["audio_file"], "Speaker")]
        if not files:
            return {"ok": False, "error": "This meeting has no audio to re-transcribe."}
        self._busy = meeting_id
        threading.Thread(target=self._transcribe_files, daemon=True,
                         args=(meeting, files, self._settings["hq_model"])).start()
        return {"ok": True}

    def _transcribe_files(self, meeting, files, model):
        meeting_id = meeting["id"]
        self._emit("status", self._status())
        try:
            segments = []
            for index, (name, speaker) in enumerate(files):
                def progress(fraction, index=index):
                    self._emit("progress", {"id": meeting_id, "value": (index + fraction) / len(files)})
                self._emit("progress", {"id": meeting_id, "value": index / len(files)})
                found, duration = self._transcriber.transcribe_file(
                    store.folder(meeting_id) / name, self._settings["language"], model, progress)
                meeting["duration"] = max(meeting.get("duration") or 0, round(duration, 1))
                segments += [{"start": round(s, 2), "end": round(e, 2), "speaker": speaker, "text": t}
                             for s, e, t in found]
            mine = [s for s in segments if s["speaker"] == "You"]
            others = [s for s in segments if s["speaker"] == "Others"]
            segments = [s for s in segments
                        if not (s in mine and any(commands.is_echo(s, o) for o in others))]
            segments.sort(key=lambda s: s["start"])
            meeting["segments"] = segments
            store.save(meeting)
        except Exception as error:
            log("file transcription failed", traceback.format_exc())
            self._emit("toast", f"Transcription failed: {error}")
        self._busy = None
        self._emit("progress", {"id": meeting_id, "value": None})
        self._emit("status", self._status())
        self._emit("meetings")
        self._emit("meeting", meeting_id)

    # ---- settings -----------------------------------------------------

    def set_settings(self, patch):
        patch = patch or {}
        for key, value in patch.items():
            if key in config.DEFAULTS and key != "folder":
                self._settings[key] = value
        config.save_settings(self._settings)
        if "microphone" in patch or not self._settings["voice_command"]:
            self._stop_standby()
        if "live_model" in patch or "language" in patch:
            threading.Thread(target=self._preload, daemon=True).start()     # restarts standby when ready
        else:
            self._start_standby()
        return self._settings

    def choose_folder(self):
        """Let the user pick where meetings are saved."""
        chosen = self._window.create_file_dialog(FOLDER_DIALOG, directory=str(config.MEETINGS))
        if not chosen:
            return {"ok": False}
        return self.set_folder(chosen if isinstance(chosen, str) else chosen[0])

    def set_folder(self, path):
        if self._state != "idle" or self._busy:
            return {"ok": False, "error": "Finish the current recording or transcription first."}
        target = Path(path)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as error:
            return {"ok": False, "error": f"That folder can't be written to: {error}"}
        try:
            moved = store.move_library(config.MEETINGS, target)
        except OSError as error:
            log("moving meetings failed", traceback.format_exc())
            return {"ok": False, "error": f"Could not move the existing meetings: {error}"}
        config.use_folder(target)
        self._settings["folder"] = str(target)
        self._needs_folder = False
        config.save_settings(self._settings)
        return {"ok": True, "folder": str(target), "moved": moved}

    def open_folder(self):
        os.startfile(config.MEETINGS)


def find_window():
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    return user32.FindWindowW(None, config.APP_NAME)


def set_window_icon():
    """Show the app logo in the title bar and taskbar instead of Python's."""
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    window = find_window()
    if not window or not ICON.exists():
        return
    for which, size in ((1, 48), (0, 16)):      # big and small icon
        handle = user32.LoadImageW(None, str(ICON), 1, size, size, 0x0010)
        if handle:
            user32.SendMessageW(window, 0x0080, which, handle)


def already_running():
    """True if another copy is open; that copy's window is brought to the front."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "MeetingTranscriptor.SingleInstance")
    if ctypes.get_last_error() != 183:          # ERROR_ALREADY_EXISTS
        return False
    window = find_window()
    if window:
        user32 = ctypes.windll.user32
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.ShowWindow(window, 9)
        user32.SetForegroundWindow(window)
    return True


def unblock_own_files():
    """Clear the "downloaded from the internet" mark from the packaged app's files.

    Windows puts that mark on everything unzipped from a downloaded archive, and .NET then
    refuses to load the DLLs the window needs, so the app would crash on start.
    """
    if not getattr(sys, "frozen", False):
        return
    for folder, _, names in os.walk(BASE):
        for name in names:
            if name.lower().endswith((".dll", ".exe", ".pyd")):
                try:
                    os.remove(os.path.join(folder, name) + ":Zone.Identifier")
                except OSError:
                    pass


def main():
    if already_running():
        return
    unblock_own_files()
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Meeting.Transcriptor")
    config.ROOT.mkdir(parents=True, exist_ok=True)
    if sys.stderr is None or sys.stdout is None:    # started without a console
        sys.stdout = sys.stderr = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)
    api = Api()
    window = webview.create_window(config.APP_NAME, str(UI), js_api=api,
                                   width=1180, height=780, min_size=(900, 600))
    api._attach(window)
    webview.start()


if __name__ == "__main__":
    main()
