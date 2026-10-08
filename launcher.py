"""Entry point used when the app is packaged into an .exe."""
import ctypes
import traceback
from pathlib import Path

try:
    from app.main import main
    main()
except Exception:
    report = Path.home() / "MeetingTranscriptor-crash.txt"
    try:
        report.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(
        None,
        "Meeting Transcriptor could not start.\n\n"
        "Make sure you unzipped the whole folder before running it, then try again.\n\n"
        f"Details were saved to:\n{report}",
        "Meeting Transcriptor", 0x10)
