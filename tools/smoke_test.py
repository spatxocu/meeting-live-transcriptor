"""Record ~12 s while Windows speaks a sentence through the speakers, then print the transcript."""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audio import Recorder
from app.transcriber import Transcriber

SENTENCE = "Hello team. This is a test of the meeting recorder. The quarterly budget review is on Friday."

transcriber = Transcriber(lambda status, size, error: print(f"model {size}: {status} {error}"))
transcriber.model("small")

folder = Path(tempfile.mkdtemp(prefix="lt-smoke-"))
chunks = []
recorder = Recorder(folder, lambda source, start, audio: chunks.append((source, start, audio)))
print("sources:", recorder.start())
time.sleep(1.5)
subprocess.run(["powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Speech; "
                f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{SENTENCE}')"])
time.sleep(2.5)
duration = recorder.stop()
print(f"recorded {duration:.1f}s, {len(chunks)} utterance(s), files:",
      {p.name: p.stat().st_size for p in folder.iterdir()})

for source, start, audio in chunks:
    began = time.time()
    for s, e, text in transcriber.transcribe_array(audio, "en", "small"):
        print(f"[{source} {start + s:5.1f}-{start + e:5.1f}] {text}")
    print(f"   ({len(audio) / 16000:.1f}s of audio transcribed in {time.time() - began:.1f}s)")
