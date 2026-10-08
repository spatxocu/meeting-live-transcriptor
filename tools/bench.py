"""Time each model on a short spoken clip to choose live-transcription settings."""
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

wav = Path(tempfile.mkdtemp()) / "clip.wav"
subprocess.run(["powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono'); "
                f"$s.SetOutputToWaveFile('{wav}', $f); "
                "$s.Speak('My name is Sam and I would like to move the budget meeting to Friday.'); $s.Dispose()"])
with wave.open(str(wav)) as handle:
    audio = np.frombuffer(handle.readframes(handle.getnframes()), np.int16).astype(np.float32) / 32768
print(f"clip: {len(audio) / 16000:.1f}s")

for name in sys.argv[1:]:
    for threads in (4, 8):
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
        times = []
        for _ in range(3):
            began = time.time()
            segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                           condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments)
            times.append(time.time() - began)
        print(f"{name:10s} threads={threads}  {min(times):.2f}s  {text}")
