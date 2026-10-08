"""Drive the app's API without a window: record a spoken sentence, then check the saved meeting."""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store
from app.main import Api


class FakeWindow:
    def evaluate_js(self, script):
        if "level" not in script:
            print(f"  {time.time() % 100:5.1f} event:", script[28:150])


def say(text):
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"])


import tempfile
from app import config
config.save_settings = lambda settings: None    # never touch the real settings from a test
api = Api()
print("folder on start:", config.MEETINGS, "| needs_folder:", api._needs_folder)
first = Path(tempfile.mkdtemp(prefix="lt-lib-"))
print("set_folder:", api.set_folder(str(first)))
api._settings["voice_command"] = False
api._window = FakeWindow()
api._ready = True
api._start_workers()
api._transcriber.model(api._preview_model())
api._transcriber.model(api._live_model())
print("microphones:", api.list_microphones())

print("start:", api.start_recording())
time.sleep(1)
say("Good morning everyone. Let us review the launch plan. Marketing needs the final copy by Tuesday.")
time.sleep(2)
print("stop:", api.stop_recording())
while api._state != "idle":
    time.sleep(0.2)

meeting_id = store.list_meetings()[0]["id"]
meeting = api.get_meeting(meeting_id)
print("duration:", meeting["duration"], "audio:", meeting["audio_url"])
for s in meeting["segments"]:
    print(f"  [{s['start']:5.1f}] {s['speaker']}: {s['text']}")
print("search 'launch':", [m["title"] for m in api.list_meetings("launch")])
print("--- txt export ---")
print(store.export_text(store.load(meeting_id), "txt"))
print("--- srt export ---")
print(store.export_text(store.load(meeting_id), "srt")[:200])

request = urllib.request.Request(meeting["audio_url"], headers={"Range": "bytes=100-199"})
with urllib.request.urlopen(request) as response:
    print("audio range request:", response.status, response.headers["Content-Range"], len(response.read()))

round_trip = store.parse_transcript(store.export_text(store.load(meeting_id), "srt"), ".srt")
print("srt re-import segments:", len(round_trip), round_trip[0] if round_trip else None)
second = Path(tempfile.mkdtemp(prefix="lt-lib2-"))
moved = api.set_folder(str(second))
print("move to second folder:", moved, "| listed there:", len(store.list_meetings()),
      "| left in first:", len(list(first.iterdir())))
print("delete:", api.delete_meeting(meeting_id), "left:", len(store.list_meetings()))
