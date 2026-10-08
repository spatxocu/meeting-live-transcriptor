"""Voice commands, a global hotkey and echo detection."""
import ctypes
import re
import threading
from ctypes import wintypes
from difflib import SequenceMatcher

START_PHRASES = ("start recording", "start the recording", "begin recording", "start to record")
STOP_PHRASES = ("stop recording", "stop the recording", "end recording", "end the recording")


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def _short(text):
    return len(text.split()) <= 6


def is_start(text):
    text = normalize(text)
    return text == "record" or (_short(text) and any(p in text for p in START_PHRASES))


def is_stop(text):
    text = normalize(text)
    return _short(text) and any(p in text for p in STOP_PHRASES)


def is_echo(mic_segment, system_segment):
    """True when the mic simply re-heard what the speakers were playing."""
    if abs(mic_segment["start"] - system_segment["start"]) > 4:
        return False
    a, b = normalize(mic_segment["text"]), normalize(system_segment["text"])
    if len(a) < 8 or not b:     # short replies like "yes" are likely genuine
        return False
    return a in b or SequenceMatcher(None, a, b).ratio() > 0.75


def listen_hotkey(callback):
    """Call `callback` whenever Ctrl+Alt+R is pressed, from anywhere in Windows."""
    def loop():
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, ord("R")):
            return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312:
                callback()

    threading.Thread(target=loop, daemon=True).start()
