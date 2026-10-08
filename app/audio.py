"""Capture the microphone and the speaker output (WASAPI loopback) as 16 kHz mono audio."""
import queue
import threading
import time
import wave

import numpy as np
import pyaudiowpatch as pyaudio
import soxr

RATE = 16000
FRAME = 480                 # 30 ms
PRE_ROLL = 10               # frames of silence kept before speech starts
TRAIL = int(RATE * 0.5)     # silence that ends an utterance
MIN_LEN = RATE * 1
MAX_LEN = RATE * 15
PREVIEW_EVERY = int(RATE * 0.5)     # how often an unfinished utterance is previewed
PREVIEW_MIN = int(RATE * 0.4)


class Chunker:
    """Splits a continuous stream into utterances, cutting at pauses."""

    def __init__(self, on_chunk, base_threshold, on_partial=None):
        self.on_chunk = on_chunk
        self.on_partial = on_partial
        self.previewed = 0
        self.base = base_threshold
        self.noise = base_threshold / 3
        self.rest = np.zeros(0, np.float32)
        self.frames = []
        self.n = 0
        self.start = 0      # sample index of frames[0]
        self.voiced = False
        self.trail = 0

    def feed(self, samples):
        x = np.concatenate([self.rest, samples]) if len(self.rest) else samples
        count = len(x) // FRAME
        for i in range(count):
            self._frame(x[i * FRAME:(i + 1) * FRAME])
        self.rest = x[count * FRAME:].copy()

    def _frame(self, frame):
        rms = float(np.sqrt(np.mean(frame * frame)))
        loud = rms > max(self.base, self.noise * 3)
        if not loud:
            self.noise = 0.98 * self.noise + 0.02 * rms
        self.frames.append(frame)
        self.n += FRAME
        if not self.voiced and not loud:
            if len(self.frames) > PRE_ROLL:
                self.frames.pop(0)
                self.n -= FRAME
                self.start += FRAME
            return
        if loud:
            self.voiced = True
            self.trail = 0
        else:
            self.trail += FRAME
        if (self.trail >= TRAIL and self.n >= MIN_LEN) or self.n >= MAX_LEN:
            self.flush()
        elif (self.on_partial and loud and self.n >= PREVIEW_MIN
              and self.n - self.previewed >= PREVIEW_EVERY):
            self.previewed = self.n
            self.on_partial(self.start / RATE, np.concatenate(self.frames))

    def flush(self):
        if self.voiced and self.frames:
            self.on_chunk(self.start / RATE, np.concatenate(self.frames))
        self.start += self.n
        self.frames = []
        self.n = 0
        self.voiced = False
        self.trail = 0
        self.previewed = 0


class Source:
    """One capture stream -> optional WAV file + utterance chunks + level meter."""

    def __init__(self, pa, device, name, wav_path, t0, on_chunk, on_level, threshold, on_partial=None):
        self.name = name
        self.t0 = t0
        self.written = 0
        self._channels = int(device["maxInputChannels"])
        rate = int(device["defaultSampleRate"])
        self._resampler = soxr.ResampleStream(rate, RATE, 1, dtype="float32")
        self._chunker = Chunker(lambda start, audio: on_chunk(name, start, audio), threshold,
                                on_partial and (lambda start, audio: on_partial(name, start, audio)))
        self._on_level = on_level
        self._level_peak = 0.0
        self._level_at = 0.0
        self._wav = None
        if wav_path:
            self._wav = wave.open(str(wav_path), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(RATE)
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._stream = pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=int(rate * 0.05),
            stream_callback=self._callback,
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _callback(self, data, frame_count, time_info, status):
        self._queue.put((time.monotonic(), data))
        return (None, pyaudio.paContinue)

    def _pump(self):
        while True:
            try:
                stamp, data = self._queue.get(timeout=0.3)
            except queue.Empty:
                if self._stop.is_set():
                    break
                # Loopback delivers nothing while the speakers are silent.
                self._pad_to(time.monotonic() - 0.3)
                continue
            x = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
            if self._channels > 1:
                x = x.reshape(-1, self._channels).mean(axis=1)
            y = self._resampler.resample_chunk(x)
            self._pad_to(stamp - len(y) / RATE)
            self._emit(y)

    def _pad_to(self, moment, slack=RATE // 4):
        gap = int((moment - self.t0) * RATE) - self.written
        if gap <= slack:
            return
        while gap > 0:
            n = min(gap, RATE * 10)
            self._emit(np.zeros(n, np.float32))
            gap -= n

    def _emit(self, y):
        if not len(y):
            return
        if self._wav:
            self._wav.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
        self.written += len(y)
        self._chunker.feed(y)
        self._level_peak = max(self._level_peak, float(np.sqrt(np.mean(y * y))))
        now = time.monotonic()
        if now - self._level_at > 0.2:
            self._on_level(self.name, self._level_peak)
            self._level_peak = 0.0
            self._level_at = now

    def stop(self, end):
        try:
            self._stream.stop_stream()
            self._stream.close()
        except OSError:
            pass
        self._stop.set()
        self._thread.join()
        self._pad_to(end, slack=0)
        self._chunker.flush()
        if self._wav:
            self._wav.close()


def _noop(*args):
    pass


def _microphones(pa):
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    devices = (pa.get_device_info_by_index(i) for i in range(pa.get_device_count()))
    return [d for d in devices if d["hostApi"] == wasapi and d["maxInputChannels"] > 0
            and not d.get("isLoopbackDevice")]


def list_microphones():
    """Names of the microphones Windows currently has connected."""
    pa = pyaudio.PyAudio()
    try:
        return [d["name"] for d in _microphones(pa)]
    finally:
        pa.terminate()


def find_microphone(pa, name):
    """The chosen microphone, or the Windows default if it is unset or unplugged."""
    if name and name != "default":
        for device in _microphones(pa):
            if device["name"] == name:
                return device
    return pa.get_default_input_device_info()


class Recorder:
    """Records mic.wav (you) and system.wav (everyone else) into a meeting folder."""

    def __init__(self, folder, on_chunk, on_level=_noop, on_partial=None, microphone="default"):
        self.folder = folder
        self.on_chunk = on_chunk
        self.on_level = on_level
        self.on_partial = on_partial
        self.microphone = microphone
        self.sources = []

    def start(self):
        self._pa = pyaudio.PyAudio()
        self.t0 = time.monotonic()
        wanted = [
            ("mic", lambda: find_microphone(self._pa, self.microphone), 0.008),
            ("system", self._pa.get_default_wasapi_loopback, 0.003),
        ]
        for name, find, threshold in wanted:
            try:
                device = find()
                self.sources.append(Source(self._pa, device, name, self.folder / f"{name}.wav",
                                           self.t0, self.on_chunk, self.on_level, threshold,
                                           self.on_partial))
            except Exception:
                continue
        if not self.sources:
            self._pa.terminate()
            raise RuntimeError("No microphone or speakers were found to record from.")
        return [s.name for s in self.sources]

    def stop(self):
        end = time.monotonic()
        for source in self.sources:
            source.stop(end)
        self._pa.terminate()
        _mix([self.folder / f"{s.name}.wav" for s in self.sources], self.folder / "audio.wav")
        return end - self.t0


class Standby:
    """Microphone-only listener used to hear the voice command while idle."""

    def __init__(self, on_chunk, microphone="default"):
        self._pa = pyaudio.PyAudio()
        try:
            device = find_microphone(self._pa, microphone)
            self._source = Source(self._pa, device, "standby", None, time.monotonic(),
                                  on_chunk, _noop, 0.008)
        except Exception:
            self._pa.terminate()
            raise

    def stop(self):
        self._source.stop(time.monotonic())
        self._pa.terminate()


def _mix(paths, out_path):
    """Sum the per-source WAVs into one file for playback."""
    readers = [wave.open(str(p), "rb") for p in paths]
    out = wave.open(str(out_path), "wb")
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(RATE)
    try:
        while True:
            blocks = [np.frombuffer(r.readframes(RATE * 10), np.int16) for r in readers]
            size = max(len(b) for b in blocks)
            if size == 0:
                break
            total = np.zeros(size, np.int32)
            for block in blocks:
                total[:len(block)] += block
            out.writeframes(np.clip(total, -32768, 32767).astype(np.int16).tobytes())
    finally:
        out.close()
        for r in readers:
            r.close()
