"""Config for BlitztextLinux.

Pfad: ~/.config/blitztext-linux/config.json
Berechtigungen: 0o600. Der eigentliche OpenAI-Key wird nur noch zur Laufzeit
über eine Umgebungsvariable gelesen.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from app.writing_presets import DEFAULT_PRESET_KEY, WRITING_PRESET_KEYS

logger = logging.getLogger("blitztext.config")

DEFAULTS: dict[str, Any] = {
    "model": "base",
    "language": "de",
    "backend": "openai-whisper",
    "hotkey_mode": "hold",
    "transcription_hotkey": "KEY_LEFTALT",
    "openai_api_key_env": "OPENAI_API_KEY",
    "autopaste": True,
    "audio_device": "@DEFAULT_SOURCE@",
    "notes_folder": str(Path.home() / "Blitztext-Notizen"),
    "history_size": 50,
    "tts_voice": "",
    "tts_speed": 1.0,
    "workflows": {
        "text_improver_tone": "neutral",
        "emoji_density": "mittel",
        "dampf_system_prompt": "",
        "custom_terms": [],
        "writing_preset": DEFAULT_PRESET_KEY,
    },
}

VALID_MODELS = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "large-v3-turbo"}
VALID_BACKENDS = {"openai-whisper", "faster-whisper"}
VALID_HOTKEY_MODES = {"toggle", "hold"}
VALID_TONES = {"formal", "neutral", "locker"}
VALID_EMOJI_DENSITIES = {"wenig", "mittel", "viel"}
VALID_WRITING_PRESETS = set(WRITING_PRESET_KEYS)
VALID_HOTKEY_KEYS = {
    "KEY_LEFTALT", "KEY_RIGHTALT", "KEY_RIGHTCTRL", "KEY_LEFTCTRL",
    "KEY_F13", "KEY_F14", "KEY_F15", "KEY_F16",
    "KEY_SCROLLLOCK", "KEY_PAUSE", "KEY_INSERT", "KEY_CAPSLOCK",
}
ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class ConfigError(Exception):
    """Raised for config file errors."""


class BlitztextConfig:
    """Laedt, validiert und speichert die BlitztextLinux-Konfiguration."""

    def __init__(self, config_dir: Path | None = None) -> None:
        if config_dir is None:
            self.config_dir = Path.home() / ".config" / "blitztext-linux"
        else:
            self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.json"
        self._legacy_openai_api_key_present = False
        self._legacy_openai_api_key_value = ""

        self._data = self._load()
        self._validate_and_sanitize()

    @classmethod
    def load(cls, path: Path | None = None) -> "BlitztextConfig":
        if path is not None:
            config_dir = Path(path).parent
        else:
            config_dir = None
        return cls(config_dir=config_dir)

    def _load(self) -> dict[str, Any]:
        if not self.config_file.is_file():
            return _deep_merge(DEFAULTS, {})

        try:
            raw = self.config_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return _deep_merge(DEFAULTS, {})

            legacy_api_key = data.get("openai_api_key")
            self._legacy_openai_api_key_present = "openai_api_key" in data
            self._legacy_openai_api_key_value = legacy_api_key.strip() if isinstance(legacy_api_key, str) else ""
            sanitized = dict(data)
            sanitized.pop("openai_api_key", None)
            return _deep_merge(DEFAULTS, sanitized)
        except Exception:
            logger.warning("Config could not be loaded, using defaults")
            return _deep_merge(DEFAULTS, {})

    def save(self) -> None:
        """Speichert Config als JSON mit Berechtigungen 0o600 ab erstem Schreibvorgang."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.config_file.with_suffix(".json.tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(str(tmp), flags, 0o600)
            payload = _deep_copy_without_legacy_key(self._data)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            tmp.replace(self.config_file)
            self.config_file.chmod(0o600)
            self._data = payload
            self._legacy_openai_api_key_present = False
            self._legacy_openai_api_key_value = ""
        except OSError as exc:
            raise ConfigError(f"Config konnte nicht gespeichert werden: {exc}") from exc

    def has_api_key(self) -> bool:
        return bool(self.resolve_openai_api_key())

    @property
    def openai_api_key_env(self) -> str:
        value = self._data.get("openai_api_key_env", DEFAULTS["openai_api_key_env"])
        return _normalize_env_var_name(value)

    @openai_api_key_env.setter
    def openai_api_key_env(self, value: str) -> None:
        self._data["openai_api_key_env"] = _normalize_env_var_name(value)

    def resolve_openai_api_key(self) -> str:
        env_name = self.openai_api_key_env
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return env_value
        return self._legacy_openai_api_key_value

    @property
    def has_legacy_openai_api_key(self) -> bool:
        return self._legacy_openai_api_key_present

    @property
    def model(self) -> str:
        return self._data["model"]

    @model.setter
    def model(self, value: str) -> None:
        if value not in VALID_MODELS:
            raise ValueError(f"Ungueltiges Modell: {value!r}. Gueltig: {sorted(VALID_MODELS)}")
        self._data["model"] = value

    @property
    def language(self) -> str:
        return self._data["language"]

    @language.setter
    def language(self, value: str) -> None:
        self._data["language"] = value

    @property
    def backend(self) -> str:
        return self._data["backend"]

    @backend.setter
    def backend(self, value: str) -> None:
        if value not in VALID_BACKENDS:
            raise ValueError(f"Ungueltiger Backend: {value!r}. Gueltig: {sorted(VALID_BACKENDS)}")
        self._data["backend"] = value

    @property
    def hotkey_mode(self) -> str:
        return self._data["hotkey_mode"]

    @hotkey_mode.setter
    def hotkey_mode(self, value: str) -> None:
        if value not in VALID_HOTKEY_MODES:
            raise ValueError(f"Ungueltiger Hotkey-Modus: {value!r}")
        self._data["hotkey_mode"] = value

    @property
    def transcription_hotkey(self) -> str:
        return self._data.get("transcription_hotkey", "KEY_LEFTALT")

    @transcription_hotkey.setter
    def transcription_hotkey(self, value: str) -> None:
        if value not in VALID_HOTKEY_KEYS:
            raise ValueError(f"Ungueltige Hotkey-Taste: {value!r}. Gueltig: {sorted(VALID_HOTKEY_KEYS)}")
        self._data["transcription_hotkey"] = value

    @property
    def autopaste(self) -> bool:
        return bool(self._data["autopaste"])

    @autopaste.setter
    def autopaste(self, value: bool) -> None:
        self._data["autopaste"] = bool(value)

    @property
    def audio_device(self) -> str:
        return self._data.get("audio_device", "@DEFAULT_SOURCE@")

    @audio_device.setter
    def audio_device(self, value: str) -> None:
        self._data["audio_device"] = value

    @property
    def notes_folder(self) -> str:
        return self._data.get("notes_folder", "")

    @notes_folder.setter
    def notes_folder(self, value: str) -> None:
        self._data["notes_folder"] = value

    @property
    def history_size(self) -> int:
        return int(self._data.get("history_size", 50))

    @history_size.setter
    def history_size(self, value: int) -> None:
        self._data["history_size"] = max(10, min(100, int(value)))

    @property
    def tts_voice(self) -> str:
        return self._data.get("tts_voice", "")

    @tts_voice.setter
    def tts_voice(self, value: str) -> None:
        self._data["tts_voice"] = value

    @property
    def tts_speed(self) -> float:
        return float(self._data.get("tts_speed", 1.0))

    @tts_speed.setter
    def tts_speed(self, value: float) -> None:
        self._data["tts_speed"] = max(0.5, min(2.0, float(value)))

    @property
    def workflows(self) -> dict[str, Any]:
        return self._data["workflows"]

    @property
    def text_improver_tone(self) -> str:
        return self._data["workflows"]["text_improver_tone"]

    @text_improver_tone.setter
    def text_improver_tone(self, value: str) -> None:
        if value not in VALID_TONES:
            raise ValueError(f"Ungueltiger Ton: {value!r}. Gueltig: {sorted(VALID_TONES)}")
        self._data["workflows"]["text_improver_tone"] = value

    @property
    def emoji_density(self) -> str:
        return self._data["workflows"]["emoji_density"]

    @emoji_density.setter
    def emoji_density(self, value: str) -> None:
        if value not in VALID_EMOJI_DENSITIES:
            raise ValueError(f"Ungueltige Emoji-Dichte: {value!r}")
        self._data["workflows"]["emoji_density"] = value

    @property
    def dampf_system_prompt(self) -> str:
        return self._data["workflows"]["dampf_system_prompt"]

    @dampf_system_prompt.setter
    def dampf_system_prompt(self, value: str) -> None:
        self._data["workflows"]["dampf_system_prompt"] = value

    @property
    def writing_preset(self) -> str:
        return self._data["workflows"].get("writing_preset", DEFAULT_PRESET_KEY)

    @writing_preset.setter
    def writing_preset(self, value: str) -> None:
        if value not in VALID_WRITING_PRESETS:
            raise ValueError(f"Ungueltiges Schreib-Preset: {value!r}. Gueltig: {sorted(VALID_WRITING_PRESETS)}")
        self._data["workflows"]["writing_preset"] = value

    @property
    def custom_terms(self) -> list[str]:
        return list(self._data["workflows"].get("custom_terms", []))

    @custom_terms.setter
    def custom_terms(self, value: list[str]) -> None:
        self._data["workflows"]["custom_terms"] = _sanitize_terms(value)

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def _validate_and_sanitize(self) -> None:
        if self._data.get("model") not in VALID_MODELS:
            self._data["model"] = "base"
        if self._data.get("backend") not in VALID_BACKENDS:
            self._data["backend"] = "openai-whisper"
        if self._data.get("hotkey_mode") not in VALID_HOTKEY_MODES:
            self._data["hotkey_mode"] = "toggle"
        if self._data.get("transcription_hotkey") not in VALID_HOTKEY_KEYS:
            self._data["transcription_hotkey"] = "KEY_LEFTALT"

        try:
            self._data["history_size"] = max(10, min(100, int(self._data.get("history_size", 50))))
        except (TypeError, ValueError):
            self._data["history_size"] = 50
        try:
            self._data["tts_speed"] = max(0.5, min(2.0, float(self._data.get("tts_speed", 1.0))))
        except (TypeError, ValueError):
            self._data["tts_speed"] = 1.0
        if not isinstance(self._data.get("notes_folder", ""), str):
            self._data["notes_folder"] = ""
        if not isinstance(self._data.get("tts_voice", ""), str):
            self._data["tts_voice"] = ""

        self._data["openai_api_key_env"] = _normalize_env_var_name(
            self._data.get("openai_api_key_env", DEFAULTS["openai_api_key_env"])
        )
        self._data.pop("openai_api_key", None)

        if "workflows" not in self._data or not isinstance(self._data["workflows"], dict):
            self._data["workflows"] = {}

        wf = self._data["workflows"]
        for k, v in DEFAULTS["workflows"].items():
            if k not in wf:
                if isinstance(v, dict):
                    wf[k] = _deep_merge(v, {})
                elif isinstance(v, list):
                    wf[k] = list(v)
                else:
                    wf[k] = v

        if wf.get("text_improver_tone") not in VALID_TONES:
            wf["text_improver_tone"] = "neutral"
        if wf.get("emoji_density") not in VALID_EMOJI_DENSITIES:
            wf["emoji_density"] = "mittel"
        preset_value = wf.get("writing_preset")
        if not isinstance(preset_value, str) or preset_value not in VALID_WRITING_PRESETS:
            wf["writing_preset"] = DEFAULT_PRESET_KEY
        wf["custom_terms"] = _sanitize_terms(wf.get("custom_terms"))


def _normalize_env_var_name(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULTS["openai_api_key_env"]
    candidate = value.strip().upper()
    if not candidate or not ENV_VAR_NAME_RE.fullmatch(candidate):
        return DEFAULTS["openai_api_key_env"]
    return candidate


def _sanitize_terms(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        term = value.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _deep_copy_without_legacy_key(data: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(data)
    payload.pop("openai_api_key", None)
    return payload


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


Config = BlitztextConfig
