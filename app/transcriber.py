"""Local speech-to-text with Whisper (faster-whisper, CPU)."""
import threading

from faster_whisper import WhisperModel


ENGLISH_ONLY = {"tiny", "base", "small", "medium"}


def model_name(size, language):
    """English-only variants are more accurate for English at the same speed."""
    return f"{size}.en" if language == "en" and size in ENGLISH_ONLY else size


class Transcriber:
    def __init__(self, on_status=lambda *a: None):
        self._models = {}
        self._lock = threading.Lock()
        self._on_status = on_status

    def model(self, size):
        with self._lock:
            if size not in self._models:
                self._on_status("loading", size, "")
                try:
                    self._models[size] = WhisperModel(size, device="cpu", compute_type="int8",
                                                      cpu_threads=4)
                except Exception as error:
                    self._on_status("error", size, str(error))
                    raise
                self._on_status("ready", size, "")
            return self._models[size]

    def transcribe_array(self, audio, language, size):
        """Transcribe one utterance (16 kHz float32). Returns [(start, end, text)]."""
        segments, _ = self.model(size).transcribe(
            audio,
            language=None if language == "auto" else language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return _clean(segments)

    def preview(self, audio, language, size):
        """Quick rough text for an utterance that is still being spoken."""
        segments, _ = self.model(size).transcribe(
            audio,
            language=None if language == "auto" else language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(text for _, _, text in _clean(segments))

    def transcribe_file(self, path, language, size, on_progress=lambda fraction: None):
        """Transcribe a whole audio/video file. Returns ([(start, end, text)], duration)."""
        segments, info = self.model(size).transcribe(
            str(path),
            language=None if language == "auto" else language,
            beam_size=5,
            vad_filter=True,
        )
        result = []
        for segment in segments:
            if info.duration:
                on_progress(min(1.0, segment.end / info.duration))
            result.extend(_clean([segment]))
        return result, info.duration


def _clean(segments):
    return [(s.start, s.end, s.text.strip()) for s in segments
            if s.text.strip() and s.no_speech_prob < 0.8]
