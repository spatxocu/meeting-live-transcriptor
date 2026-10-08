"""Paths, settings and the language list."""
import json
from pathlib import Path

APP_NAME = "Meeting Transcriptor"
ROOT = Path.home() / "MeetingTranscriptor"   # settings and log
_OLD_ROOT = Path.home() / "LeosTranscriptor"    # the app's earlier name
if _OLD_ROOT.exists() and not ROOT.exists():
    try:
        _OLD_ROOT.rename(ROOT)
    except OSError:
        ROOT = _OLD_ROOT
DEFAULT_MEETINGS = ROOT / "meetings"
MEETINGS = DEFAULT_MEETINGS                 # replaced by the folder the user chose
SETTINGS_FILE = ROOT / "settings.json"
LOG_FILE = ROOT / "app.log"

DEFAULTS = {
    "language": "en",
    "live_model": "base",
    "hq_model": "large-v3-turbo",
    "voice_command": True,
    "microphone": "default",
    "folder": "",                           # empty until the user has chosen where to save
}

LIVE_MODELS = [
    {"id": "tiny", "label": "Tiny - instant, least accurate (75 MB)"},
    {"id": "base", "label": "Base - fast, recommended (140 MB)"},
    {"id": "small", "label": "Small - more accurate, 2-3 s behind (460 MB)"},
]
HQ_MODELS = [
    {"id": "small", "label": "Small (460 MB)"},
    {"id": "medium", "label": "Medium - accurate, slow (1.5 GB)"},
    {"id": "large-v3-turbo", "label": "Large v3 Turbo - most accurate (1.6 GB)"},
]

LANGUAGES = {
    "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic", "hy": "Armenian",
    "as": "Assamese", "az": "Azerbaijani", "ba": "Bashkir", "eu": "Basque", "be": "Belarusian",
    "bn": "Bengali", "bs": "Bosnian", "br": "Breton", "bg": "Bulgarian", "my": "Burmese",
    "yue": "Cantonese", "ca": "Catalan", "zh": "Chinese", "hr": "Croatian", "cs": "Czech",
    "da": "Danish", "nl": "Dutch", "en": "English", "et": "Estonian", "fo": "Faroese",
    "fi": "Finnish", "fr": "French", "gl": "Galician", "ka": "Georgian", "de": "German",
    "el": "Greek", "gu": "Gujarati", "ht": "Haitian Creole", "ha": "Hausa", "haw": "Hawaiian",
    "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian", "is": "Icelandic", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "jw": "Javanese", "kn": "Kannada", "kk": "Kazakh",
    "km": "Khmer", "ko": "Korean", "lo": "Lao", "la": "Latin", "lv": "Latvian",
    "ln": "Lingala", "lt": "Lithuanian", "lb": "Luxembourgish", "mk": "Macedonian", "mg": "Malagasy",
    "ms": "Malay", "ml": "Malayalam", "mt": "Maltese", "mi": "Maori", "mr": "Marathi",
    "mn": "Mongolian", "ne": "Nepali", "no": "Norwegian", "nn": "Norwegian Nynorsk", "oc": "Occitan",
    "ps": "Pashto", "fa": "Persian", "pl": "Polish", "pt": "Portuguese", "pa": "Punjabi",
    "ro": "Romanian", "ru": "Russian", "sa": "Sanskrit", "sr": "Serbian", "sn": "Shona",
    "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "so": "Somali",
    "es": "Spanish", "su": "Sundanese", "sw": "Swahili", "sv": "Swedish", "tl": "Tagalog",
    "tg": "Tajik", "ta": "Tamil", "tt": "Tatar", "te": "Telugu", "th": "Thai",
    "bo": "Tibetan", "tr": "Turkish", "tk": "Turkmen", "uk": "Ukrainian", "ur": "Urdu",
    "uz": "Uzbek", "vi": "Vietnamese", "cy": "Welsh", "yi": "Yiddish", "yo": "Yoruba",
}


def use_folder(path):
    """Point the meeting library at `path` (or the default when empty)."""
    global MEETINGS
    MEETINGS = Path(path) if path else DEFAULT_MEETINGS


def load_settings():
    settings = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    ROOT.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
