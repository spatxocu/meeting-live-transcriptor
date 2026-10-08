"""Open each microphone for two seconds and print the loudest level heard."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyaudiowpatch as pyaudio

from app.audio import Source, find_microphone, list_microphones

for name in list_microphones():
    levels = []
    pa = pyaudio.PyAudio()
    try:
        source = Source(pa, find_microphone(pa, name), "mic", None, time.monotonic(),
                        lambda *a: None, lambda _, level: levels.append(level), 0.008)
        time.sleep(2)
        source.stop(time.monotonic())
        print(f"OK    {name}: peak level {max(levels, default=0):.4f}, {source.written / 16000:.1f}s captured")
    except Exception as error:
        print(f"FAIL  {name}: {error}")
    pa.terminate()
