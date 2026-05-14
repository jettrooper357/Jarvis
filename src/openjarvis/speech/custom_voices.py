"""Server-side store for user-created voices.

Two kinds of custom voices are supported:

- **mix**: a comma-separated list of built-in Kokoro voice IDs. Kokoro's
  ``load_voice`` averages the embeddings, so no extra files are needed.
- **clone**: a reference audio clip used by F5-TTS to clone speech. The clip
  lives on disk under ``~/.openjarvis/voices/clones/<id>.wav``.

State lives in ``~/.openjarvis/voices/voices.json`` so it survives restarts
and is shared across browser sessions / CLI / overlay clients.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from openjarvis.core.config import DEFAULT_CONFIG_DIR

VoiceKind = Literal["mix", "clone"]

_VOICES_DIR = DEFAULT_CONFIG_DIR / "voices"
_CLONES_DIR = _VOICES_DIR / "clones"
_INDEX_PATH = _VOICES_DIR / "voices.json"
_lock = threading.Lock()


@dataclass(slots=True)
class CustomVoice:
    id: str
    name: str
    kind: VoiceKind
    created_at: float
    # mix-only
    kokoro_voice: str = ""
    # clone-only
    ref_audio: str = ""
    ref_text: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


def _ensure_dirs() -> None:
    _VOICES_DIR.mkdir(parents=True, exist_ok=True)
    _CLONES_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> List[CustomVoice]:
    _ensure_dirs()
    if not _INDEX_PATH.exists():
        return []
    try:
        raw = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: List[CustomVoice] = []
    for entry in raw.get("voices", []):
        try:
            out.append(CustomVoice(**entry))
        except TypeError:
            continue
    return out


def _save(voices: List[CustomVoice]) -> None:
    _ensure_dirs()
    payload = {"voices": [asdict(v) for v in voices]}
    tmp = _INDEX_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(_INDEX_PATH)


def _new_id(kind: VoiceKind) -> str:
    return f"{kind}_{secrets.token_hex(4)}"


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip()).strip("-").lower() or "voice"


def list_voices() -> List[CustomVoice]:
    with _lock:
        return _load()


def get_voice(voice_id: str) -> Optional[CustomVoice]:
    with _lock:
        for v in _load():
            if v.id == voice_id:
                return v
    return None


def add_mix(name: str, kokoro_voice: str) -> CustomVoice:
    """Save a Kokoro voice blend (e.g. 'af_bella,am_adam')."""
    name = name.strip() or "Untitled mix"
    parts = [p.strip() for p in kokoro_voice.split(",") if p.strip()]
    if not parts:
        raise ValueError("kokoro_voice must contain at least one voice ID")
    if len(parts) > 4:
        raise ValueError("Mixes are limited to 4 voices for clarity")
    voice = CustomVoice(
        id=_new_id("mix"),
        name=name,
        kind="mix",
        created_at=time.time(),
        kokoro_voice=",".join(parts),
    )
    with _lock:
        voices = _load()
        voices.append(voice)
        _save(voices)
    return voice


def add_clone(name: str, audio_bytes: bytes, *, ref_text: str = "", suffix: str = ".wav") -> CustomVoice:
    """Save a reference audio clip for voice cloning."""
    name = name.strip() or "Cloned voice"
    if not audio_bytes:
        raise ValueError("audio_bytes is empty")
    if not suffix.startswith("."):
        suffix = "." + suffix
    voice_id = _new_id("clone")
    audio_path = _CLONES_DIR / f"{voice_id}_{_slugify(name)}{suffix}"
    _ensure_dirs()
    audio_path.write_bytes(audio_bytes)
    voice = CustomVoice(
        id=voice_id,
        name=name,
        kind="clone",
        created_at=time.time(),
        ref_audio=str(audio_path),
        ref_text=ref_text.strip(),
    )
    with _lock:
        voices = _load()
        voices.append(voice)
        _save(voices)
    return voice


def delete_voice(voice_id: str) -> bool:
    with _lock:
        voices = _load()
        keep = [v for v in voices if v.id != voice_id]
        if len(keep) == len(voices):
            return False
        removed = next(v for v in voices if v.id == voice_id)
        if removed.kind == "clone" and removed.ref_audio:
            try:
                Path(removed.ref_audio).unlink(missing_ok=True)
            except OSError:
                pass
        _save(keep)
        return True


def to_public_dict(voice: CustomVoice) -> Dict[str, object]:
    """Serialize for the API. Hides the absolute audio path."""
    data: Dict[str, object] = {
        "id": voice.id,
        "name": voice.name,
        "kind": voice.kind,
        "created_at": voice.created_at,
    }
    if voice.kind == "mix":
        data["kokoro_voice"] = voice.kokoro_voice
    elif voice.kind == "clone":
        data["has_audio"] = bool(voice.ref_audio and Path(voice.ref_audio).exists())
        if voice.ref_text:
            data["ref_text"] = voice.ref_text
    return data


__all__ = [
    "CustomVoice",
    "add_clone",
    "add_mix",
    "delete_voice",
    "get_voice",
    "list_voices",
    "to_public_dict",
]
