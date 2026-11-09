"""Language packs: everything a language needs, with no code.

A pack is languages/<code>/pack.json plus an optional audio/ folder. Each prompt
key can have text (read by text-to-speech, fine for development), a recorded
audio file (needed for languages with no TTS voice, such as Kalenjin), or both.
A pack is only offered to callers once every required key is covered.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent.parent / "languages"
CODE_RE = re.compile(r"^[a-z0-9_-]{2,12}$")

SYSTEM_PROMPTS = (
    "menu",            # "For <language>, press"  (a digit clip is played right after)
    "consent",
    "invalid",
    "yes_no_hint",
    "region_menu",
    "facility_intro",
    "alert_sent",
    "no_alert",
    "goodbye",
    "disclaimer",
)
DIGIT_PROMPTS = tuple(f"digit_{i}" for i in range(1, 10))


def required_keys(tree, directory) -> list:
    keys = set(SYSTEM_PROMPTS) | set(DIGIT_PROMPTS) | tree.prompt_keys()
    keys |= {f"region_{k}" for k in directory.region_keys()}
    return sorted(keys)


def note_for(key: str) -> str:
    if key == "menu" or key.startswith("region_") and key != "region_menu":
        return "Phrase ends with the word 'press'; the number clip is played straight after."
    if key.startswith("digit_"):
        return "Only the number word, e.g. 'one'."
    if key == "who":
        return "Digits 1, 2, 3 are fixed in this prompt."
    if key == "yes_no_hint":
        return "1 means yes, 2 means no."
    return ""


@dataclass
class Pack:
    code: str
    name: str
    order: int
    reviewed: bool
    prompts: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)
    path: Path = None

    @classmethod
    def from_dir(cls, folder: Path) -> "Pack":
        with open(folder / "pack.json", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(
            code=folder.name,
            name=data.get("name", folder.name),
            order=int(data.get("order", 99)),
            reviewed=bool(data.get("reviewed", False)),
            prompts=data.get("prompts", {}),
            audio=data.get("audio", {}),
            path=folder,
        )

    def text(self, key: str) -> str:
        return (self.prompts.get(key) or "").strip()

    def has(self, key: str) -> bool:
        return bool(self.text(key)) or bool(self.audio.get(key))

    def missing(self, required) -> list:
        return [k for k in required if not self.has(k)]

    def audio_problems(self) -> list:
        bad = []
        for key, filename in self.audio.items():
            if filename and (Path(filename).name != filename or not (self.path / "audio" / filename).is_file()):
                bad.append(key)
        return bad

    def is_ready(self, required) -> bool:
        return not self.missing(required) and not self.audio_problems()


def load_packs(lang_dir=LANG_DIR) -> dict:
    packs = {}
    for child in sorted(Path(lang_dir).iterdir()):
        if child.is_dir() and CODE_RE.match(child.name) and (child / "pack.json").is_file():
            packs[child.name] = Pack.from_dir(child)
    return packs


def available(packs: dict, required, require_reviewed: bool = False) -> list:
    """Packs offered on the language menu, in menu order (max 9: one digit each)."""
    ready = [p for p in packs.values() if p.is_ready(required) and (p.reviewed or not require_reviewed)]
    return sorted(ready, key=lambda p: (p.order, p.code))[:9]


def scaffold_pack(code: str, name: str, lang_dir, required) -> Path:
    """Create an empty pack with every required key, ready for translation and recording."""
    if not CODE_RE.match(code):
        raise ValueError("language code must be 2-12 characters of a-z, 0-9, _ or -")
    folder = Path(lang_dir) / code
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    existing = load_packs(lang_dir) if Path(lang_dir).exists() else {}
    order = max((p.order for p in existing.values()), default=0) + 1
    (folder / "audio").mkdir(parents=True)
    (folder / "audio" / ".gitkeep").write_text("", encoding="utf-8")
    data = {
        "name": name,
        "order": order,
        "reviewed": False,
        "prompts": {key: "" for key in required},
        "audio": {},
    }
    (folder / "pack.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return folder


def recording_sheet(pack: Pack, reference: Pack, required) -> str:
    """CSV for translators and voice talent: what to say, and the file name to deliver."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["key", "english_reference", "translation", "audio_file", "note"])
    for key in required:
        writer.writerow([
            key,
            reference.text(key) if reference else "",
            pack.text(key),
            pack.audio.get(key) or f"{key}.mp3",
            note_for(key),
        ])
    return out.getvalue()
