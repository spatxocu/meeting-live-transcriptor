# Meeting Transcriptor

A Windows desktop app that records meetings and transcribes them live, entirely on your own computer.
No account, no subscription, nothing uploaded.

- Hears your microphone (**You**) and whatever plays through your speakers (**Others**), so nothing joins the call.
- Live transcript: rough words appear as people speak and are tidied when they pause.
- About 99 languages (Whisper), with auto-detect.
- Library of saved meetings with search, rename, delete and audio playback.
- Copy a single section, the latest section or the whole transcript; export TXT, MD or SRT.
- Import an audio or video file to transcribe, or an existing transcript.
- Start and stop with the button, `Ctrl+Alt+R`, or by saying "start recording" / "stop recording".

## Run from source

Needs Windows 10/11 (64-bit) and Python 3.11.

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

The first start downloads the speech models from Hugging Face; after that it works offline.

## Build the shareable copy

```
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -File packaging\build.ps1
```

This produces `dist\MeetingTranscriptor.zip`. The recipient unzips it and runs `MeetingTranscriptor.exe`.

## How it works

| Part | File |
|---|---|
| Audio capture (mic + WASAPI loopback), utterance splitting | `app/audio.py` |
| Whisper transcription (faster-whisper, CPU) | `app/transcriber.py` |
| Window, recording state, live previews, settings | `app/main.py` |
| Meeting library, export and import | `app/store.py` |
| Voice commands, global hotkey, echo filter | `app/commands.py` |
| Local audio server for playback | `app/server.py` |
| Interface | `ui/` |

Settings live in `%USERPROFILE%\MeetingTranscriptor`. Meetings are saved in the folder chosen on first run.

Tell people when you record them. In many places that is required by law.
