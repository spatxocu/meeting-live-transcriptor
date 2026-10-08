"""Meeting library: one folder per meeting holding meeting.json and its audio."""
import json
import re
import shutil
from datetime import datetime

from . import config

ID_PATTERN = re.compile(r"\d{8}-\d{6}(-\d+)?")
LINE_PATTERN = re.compile(r"^\[(\d+):(\d\d)(?::(\d\d))?\]\s*([^:]{1,40}):\s*(.*)$")
SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def folder(meeting_id):
    if not ID_PATTERN.fullmatch(meeting_id or ""):
        raise ValueError("Unknown meeting")
    return config.MEETINGS / meeting_id


def new_meeting(title=None, source="recording"):
    now = datetime.now()
    meeting_id = now.strftime("%Y%m%d-%H%M%S")
    n = 1
    while (config.MEETINGS / meeting_id).exists():
        n += 1
        meeting_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{n}"
    (config.MEETINGS / meeting_id).mkdir(parents=True)
    meeting = {
        "id": meeting_id,
        "title": title or now.strftime("Meeting %b %d, %H:%M"),
        "created": now.isoformat(timespec="seconds"),
        "duration": 0,
        "source": source,
        "audio_file": None,
        "segments": [],
    }
    save(meeting)
    return meeting


def save(meeting):
    path = folder(meeting["id"]) / "meeting.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(meeting, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(path)


def load(meeting_id):
    return json.loads((folder(meeting_id) / "meeting.json").read_text(encoding="utf-8"))


def delete(meeting_id):
    shutil.rmtree(folder(meeting_id), ignore_errors=True)


def move_library(source, target):
    """Move every meeting folder from `source` into `target`. Returns how many moved."""
    moved = 0
    if not source.exists() or source.resolve() == target.resolve():
        return moved
    for path in sorted(source.iterdir()):
        if path.is_dir() and ID_PATTERN.fullmatch(path.name) and not (target / path.name).exists():
            shutil.move(str(path), str(target / path.name))
            moved += 1
    return moved


def list_meetings(query=""):
    """Newest first. With a query, only meetings whose title or text matches, with a snippet."""
    query = (query or "").strip().lower()
    result = []
    if not config.MEETINGS.exists():
        return result
    for path in sorted(config.MEETINGS.iterdir(), reverse=True):
        try:
            meeting = json.loads((path / "meeting.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        item = {k: meeting.get(k) for k in ("id", "title", "created", "duration", "source")}
        item["snippet"] = ""
        if query:
            hit = next((s["text"] for s in meeting["segments"] if query in s["text"].lower()), None)
            if hit is None and query not in meeting["title"].lower():
                continue
            item["snippet"] = hit or ""
        elif meeting["segments"]:
            item["snippet"] = meeting["segments"][0]["text"]
        result.append(item)
    return result


def clock(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _srt_clock(seconds):
    millis = int(round(seconds * 1000))
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def export_text(meeting, fmt):
    segments = meeting["segments"]
    if fmt == "srt":
        blocks = []
        for i, s in enumerate(segments, 1):
            blocks.append(f"{i}\n{_srt_clock(s['start'])} --> {_srt_clock(s['end'])}\n"
                          f"{s['speaker']}: {s['text']}\n")
        return "\n".join(blocks)
    if fmt == "md":
        lines = [f"# {meeting['title']}", "",
                 f"*{meeting['created'].replace('T', ' ')} · {clock(meeting['duration'])}*", ""]
        lines += [f"**{s['speaker']}** `{clock(s['start'])}` {s['text']}\n" for s in segments]
        return "\n".join(lines)
    lines = [meeting["title"], meeting["created"].replace("T", " "), ""]
    lines += [f"[{clock(s['start'])}] {s['speaker']}: {s['text']}" for s in segments]
    return "\n".join(lines) + "\n"


def parse_transcript(text, suffix):
    """Read a .json (our own export), .srt or plain-text transcript into segments."""
    if suffix == ".json":
        data = json.loads(text)
        raw = data["segments"] if isinstance(data, dict) else data
        return [{"start": float(s.get("start", 0)), "end": float(s.get("end", 0)),
                 "speaker": str(s.get("speaker", "Speaker")), "text": str(s["text"])} for s in raw]
    segments = []
    if suffix == ".srt":
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [line for line in block.splitlines() if line.strip()]
            times = next((SRT_TIME.search(line) for line in lines if SRT_TIME.search(line)), None)
            if not times:
                continue
            g = [int(x) for x in times.groups()]
            body = " ".join(line for line in lines if not SRT_TIME.search(line) and not line.strip().isdigit())
            speaker, _, rest = body.partition(": ")
            if not rest or len(speaker) > 40:
                speaker, rest = "Speaker", body
            segments.append({"start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                             "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                             "speaker": speaker, "text": rest})
        return segments
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = LINE_PATTERN.match(line)
        if match:
            a, b, c, speaker, body = match.groups()
            start = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
            segments.append({"start": start, "end": start, "speaker": speaker.strip(), "text": body})
        else:
            segments.append({"start": 0, "end": 0, "speaker": "Speaker", "text": line})
    return segments
