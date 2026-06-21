"""Tests für portierte Features: Config-Felder, Diktat-Notizen, Merge,
Notifications und TTS-Verfuegbarkeit (alle GUI-frei)."""
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app import transcribe as transcribe_module
from app.history_panel import (
    save_dictation_note,
    merge_dictation_text,
    save_merged_dictation,
    _within_home,
)
from app import notify as notify_service
from app import tts_window


# ---------------------------------------------------------------------------
# Config: neue Felder
# ---------------------------------------------------------------------------

class TestConfigFeatureFields:
    def test_defaults(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        assert cfg.history_size == 50
        assert cfg.tts_speed == 1.0
        assert cfg.tts_voice == ""
        assert cfg.tts_provider == "piper"
        assert cfg.tts_openai_model == "gpt-4o-mini-tts"
        assert cfg.tts_openai_voice == "marin"
        assert cfg.notes_folder.endswith("Blitztext-Notizen")
        assert cfg.paste_key_delay_ms == 80

    def test_history_size_clamped(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.history_size = 5
        assert cfg.history_size == 10
        cfg.history_size = 500
        assert cfg.history_size == 100

    def test_tts_speed_clamped(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_speed = 0.1
        assert cfg.tts_speed == 0.5
        cfg.tts_speed = 9.0
        assert cfg.tts_speed == 2.0

    def test_roundtrip_save_load(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config.load(path)
        cfg.tts_voice = "de_DE-thorsten-medium.onnx"
        cfg.tts_provider = "openai"
        cfg.tts_openai_model = "gpt-4o-mini-tts"
        cfg.tts_openai_voice = "nova"
        cfg.notes_folder = str(Path.home() / "Notizen")
        cfg.history_size = 25
        cfg.paste_key_delay_ms = 135
        cfg.save()
        cfg2 = Config.load(path)
        assert cfg2.tts_voice == "de_DE-thorsten-medium.onnx"
        assert cfg2.tts_provider == "openai"
        assert cfg2.tts_openai_model == "gpt-4o-mini-tts"
        assert cfg2.tts_openai_voice == "nova"
        assert cfg2.history_size == 25
        assert cfg2.notes_folder.endswith("Notizen")
        assert cfg2.paste_key_delay_ms == 135

    def test_sanitize_bad_values(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"history_size": "abc", "tts_speed": "x", "notes_folder": 5}')
        cfg = Config.load(path)
        assert cfg.history_size == 50
        assert cfg.tts_speed == 1.0
        assert cfg.notes_folder == ""


class TestTranscriptionHints:
    def test_build_transcription_hint_none_for_empty_input(self):
        assert transcribe_module._build_transcription_hint(None) is None
        assert transcribe_module._build_transcription_hint([]) is None

    def test_build_transcription_hint_sanitizes_terms(self):
        hint = transcribe_module._build_transcription_hint([" Blitztext ", "", "OpenRouter", None, "   "])
        assert hint == "Eigennamen und Begriffe: Blitztext, OpenRouter"

    def test_openai_backend_receives_initial_prompt(self, tmp_path):
        wav_file = tmp_path / "sample.wav"
        wav_file.write_bytes(b"not-empty")

        class FakeModel:
            def __init__(self):
                self.kwargs = None

            def transcribe(self, *_args, **kwargs):
                self.kwargs = kwargs
                return {"text": " Hallo "}

        fake_model = FakeModel()

        class FakeWhisperModule:
            @staticmethod
            def load_model(_model_name):
                return fake_model

        fake_whisper_module = FakeWhisperModule()

        with patch("app.transcribe._load_openai_whisper_module", return_value=fake_whisper_module):
            result = transcribe_module.transcribe(
                wav_file=wav_file,
                model="base",
                language="de",
                backend="openai-whisper",
                custom_terms=["Blitztext", "OpenRouter"],
            )

        assert result == "Hallo"
        assert fake_model.kwargs["initial_prompt"] == "Eigennamen und Begriffe: Blitztext, OpenRouter"

    def test_faster_backend_receives_initial_prompt_and_hotwords(self, tmp_path):
        wav_file = tmp_path / "sample.wav"
        wav_file.write_bytes(b"not-empty")

        class FakeSegment:
            def __init__(self, text):
                self.text = text

        class FakeWhisperModel:
            last_kwargs = None

            def __init__(self, *_args, **_kwargs):
                pass

            def transcribe(self, *_args, **kwargs):
                type(self).last_kwargs = kwargs
                return iter([FakeSegment("Hallo"), FakeSegment("Welt")]), {"language": "de"}

        with patch("app.transcribe._load_faster_whisper_model_class", return_value=FakeWhisperModel):
            result = transcribe_module.transcribe(
                wav_file=wav_file,
                model="base",
                language="de",
                backend="faster-whisper",
                custom_terms=["Blitztext", "OpenRouter"],
            )

        assert result == "Hallo Welt"
        assert FakeWhisperModel.last_kwargs["initial_prompt"] == "Eigennamen und Begriffe: Blitztext, OpenRouter"
        assert FakeWhisperModel.last_kwargs["hotwords"] == "Blitztext, OpenRouter"


# ---------------------------------------------------------------------------
# Diktat-Notizen + Merge
# ---------------------------------------------------------------------------

@pytest.fixture
def home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tempfile.mkdtemp(dir=str(Path.home()), prefix=".blitztext-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestDictationNotes:
    def test_within_home_accepts_subdir(self, home_folder):
        assert _within_home(home_folder) is not None

    def test_within_home_rejects_outside(self):
        assert _within_home("/tmp/blitztext-evil") is None

    def test_within_home_empty(self):
        assert _within_home("") is None

    def test_save_dictation_note_creates_file(self, home_folder):
        path = save_dictation_note(home_folder, "Hallo Welt")
        assert path is not None
        assert os.path.isfile(path)
        assert "Hallo Welt" in Path(path).read_text(encoding="utf-8")
        assert (os.stat(path).st_mode & 0o777) == 0o600

    def test_save_dictation_note_empty_text(self, home_folder):
        assert save_dictation_note(home_folder, "   ") is None

    def test_save_dictation_note_outside_home_rejected(self):
        assert save_dictation_note("/tmp/evil-notes", "x") is None

    def test_merge_dictation_text(self):
        assert merge_dictation_text(["a", "b", "c"]) == "a\n\nb\n\nc"

    def test_merge_skips_empty(self):
        assert merge_dictation_text(["a", "  ", "", "b"]) == "a\n\nb"

    def test_save_merged_dictation(self, home_folder):
        path = save_merged_dictation(home_folder, "Satz 1\n\nSatz 2")
        assert path is not None and os.path.isfile(path)
        content = Path(path).read_text(encoding="utf-8")
        assert "Satz 1" in content and "Satz 2" in content


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotify:
    def test_notify_no_raise_when_missing(self):
        with patch("app.notify.shutil.which", return_value=None):
            notify_service.notify("Titel", "Text")  # darf nicht werfen

    def test_is_available(self):
        with patch("app.notify.shutil.which", return_value="/usr/bin/notify-send"):
            assert notify_service.is_available() is True
        with patch("app.notify.shutil.which", return_value=None):
            assert notify_service.is_available() is False

    def test_notify_passes_timeout(self):
        with patch("app.notify.shutil.which", return_value="/usr/bin/notify-send"), \
             patch("app.notify.subprocess.run") as run_mock:
            notify_service.notify("T", "B")
            assert run_mock.call_args.kwargs.get("timeout") is not None


# ---------------------------------------------------------------------------
# TTS-Verfuegbarkeit
# ---------------------------------------------------------------------------

class TestTtsAvailability:
    def test_is_piper_available_false_when_missing(self):
        with patch("app.tts_window._find_piper", return_value=None):
            assert tts_window.is_piper_available() is False

    def test_list_voices_empty_when_no_dir(self):
        with patch.object(tts_window, "VOICES_DIR", Path("/nonexistent/piper-voices")):
            assert tts_window.list_voices() == []

    def test_openai_speed_mapping_inverts_tts_scale(self):
        assert tts_window._tts_speed_to_openai_speed(0.5) == 2.0
        assert tts_window._tts_speed_to_openai_speed(1.0) == 1.0
        assert tts_window._tts_speed_to_openai_speed(2.0) == 0.5

    def test_openai_cloud_service_streams_wav_with_mapped_speed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        cfg.tts_openai_model = "gpt-4o-mini-tts"
        cfg.tts_openai_voice = "marin"
        cfg.tts_speed = 0.5

        response = MagicMock()
        output_path = tmp_path / "cloud-tts.wav"

        def _write_file(path):
            Path(path).write_bytes(b"RIFF\x00WAVE")

        response.stream_to_file.side_effect = _write_file
        client = MagicMock()
        client.audio.speech.create.return_value = response

        service = tts_window.CloudTtsService(cfg, client=client)
        result = service.synthesize("Hallo Welt", output_path=str(output_path))

        assert result == str(output_path)
        client.audio.speech.create.assert_called_once_with(
            model="gpt-4o-mini-tts",
            voice="marin",
            input="Hallo Welt",
            response_format="wav",
            speed=2.0,
            timeout=tts_window.OPENAI_TTS_TIMEOUT,
        )
        assert output_path.read_bytes().startswith(b"RIFF")

    def test_openai_cloud_service_raises_without_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        service = tts_window.CloudTtsService(cfg)
        assert service.client is None
        assert service.is_available() is False
        with pytest.raises(tts_window.CloudTtsServiceError, match="OpenAI API-Key nicht gesetzt") as exc_info:
            service.synthesize("Hallo Welt", output_path=str(tmp_path / "x.wav"))
        assert "OPENAI_API_KEY" in str(exc_info.value)
        assert "openai fehlt" not in str(exc_info.value)

    def test_openai_cloud_service_raises_without_openai_package(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"

        with patch.dict("sys.modules", {"openai": None}):
            service = tts_window.CloudTtsService(cfg)

        assert service.client is None
        assert service.is_available() is False
        with pytest.raises(tts_window.CloudTtsServiceError, match="Python-Paket openai fehlt") as exc_info:
            service.synthesize("Hallo Welt", output_path=str(tmp_path / "x.wav"))
        assert "sk-test" not in str(exc_info.value)
        assert "API-Key nicht gesetzt" not in str(exc_info.value)

    def test_openai_cloud_service_propagates_timeout_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        client = MagicMock()
        client.audio.speech.create.side_effect = TimeoutError("request timed out")
        service = tts_window.CloudTtsService(cfg, client=client)
        with pytest.raises(TimeoutError):
            service.synthesize("Hallo Welt", output_path=str(tmp_path / "x.wav"))

    def test_scrub_secret_removes_api_key(self):
        msg = tts_window._scrub_secret("Fehler mit sk-secret123 im Text", "sk-secret123")
        assert "sk-secret123" not in msg
        assert "***" in msg

    def test_scrub_secret_noop_without_secret(self):
        assert tts_window._scrub_secret("kein key", "") == "kein key"

    def test_consent_defaults_false_and_persists(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config.load(path)
        assert cfg.tts_openai_consent is False
        cfg.tts_openai_consent = True
        cfg.save()
        assert Config.load(path).tts_openai_consent is True


class TestCloudTtsConsentGate:
    """Consent-Logik GUI-frei via Fake-self (Muster wie test_settings_dialog)."""

    def _fake_window(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        return SimpleNamespace(_config=cfg)

    def test_consent_already_granted_skips_dialog(self, tmp_path):
        fake = self._fake_window(tmp_path)
        fake._config.tts_openai_consent = True
        with patch.object(tts_window, "QMessageBox") as box:
            result = tts_window.TtsWindow._ensure_openai_consent(fake)
        assert result is True
        box.question.assert_not_called()

    def test_consent_granted_when_user_accepts(self, tmp_path):
        fake = self._fake_window(tmp_path)
        assert fake._config.tts_openai_consent is False
        with patch.object(tts_window, "QMessageBox") as box:
            box.question.return_value = box.StandardButton.Yes
            result = tts_window.TtsWindow._ensure_openai_consent(fake)
        assert result is True
        assert fake._config.tts_openai_consent is True

    def test_consent_declined_when_user_rejects(self, tmp_path):
        fake = self._fake_window(tmp_path)
        with patch.object(tts_window, "QMessageBox") as box:
            box.question.return_value = box.StandardButton.No
            result = tts_window.TtsWindow._ensure_openai_consent(fake)
        assert result is False
        assert fake._config.tts_openai_consent is False

    def test_revert_provider_to_piper_persists(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        combo = MagicMock()
        fake = SimpleNamespace(_config=cfg, _provider_combo=combo)
        tts_window.TtsWindow._revert_provider_to_piper(fake)
        assert cfg.tts_provider == "piper"
        combo.setCurrentIndex.assert_called_once_with(0)

    def test_start_cloud_tts_blocks_without_consent(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        assert cfg.tts_openai_consent is False
        fake = SimpleNamespace(
            _config=cfg,
            _status_label=MagicMock(),
            _update_speak_button_state=MagicMock(),
        )
        with patch.object(tts_window, "CloudTtsService") as service:
            tts_window.TtsWindow._start_cloud_tts(fake, "Hallo Welt")
        service.assert_not_called()
        fake._status_label.setText.assert_called_once()

    def test_start_cloud_tts_deletes_thread_on_normal_finish(self, tmp_path):
        cfg = Config.load(tmp_path / "config.json")
        cfg.tts_provider = "openai"
        cfg.tts_openai_consent = True
        fake = SimpleNamespace(
            _config=cfg,
            _status_label=MagicMock(),
            _btn_speak=MagicMock(),
            _btn_pause=MagicMock(),
            _update_speak_button_state=MagicMock(),
            _on_cloud_finished=MagicMock(),
            _on_cloud_error=MagicMock(),
            _on_cloud_thread_finished=MagicMock(),
        )
        service = MagicMock()
        service.is_available.return_value = True
        thread = MagicMock()
        worker = MagicMock()

        with patch.object(tts_window, "CloudTtsService", return_value=service), \
                patch.object(tts_window, "QThread", return_value=thread), \
                patch.object(tts_window, "_CloudTtsWorker", return_value=worker):
            tts_window.TtsWindow._start_cloud_tts(fake, "Hallo Welt")

        thread.finished.connect.assert_any_call(worker.deleteLater)
        thread.finished.connect.assert_any_call(thread.deleteLater)
        thread.finished.connect.assert_any_call(fake._on_cloud_thread_finished)
        thread.start.assert_called_once()


class TestDetachCloudThread:
    """Detach-Timeout-Pfad GUI-frei via Fake-self und gemockten QThreads."""

    def _fake_window(self):
        fake = SimpleNamespace(
            _cloud_worker=MagicMock(),
            _cloud_thread=MagicMock(),
            _detached_cloud_threads=[],
        )

        def _cleanup():
            fake._cloud_worker = None
            fake._cloud_thread = None

        fake._cleanup_cloud_state = _cleanup
        return fake

    def test_hanging_thread_is_retained_not_destroyed(self):
        fake = self._fake_window()
        thread = fake._cloud_thread
        worker = fake._cloud_worker
        thread.wait.return_value = False  # Timeout -> Thread haengt noch
        tts_window.TtsWindow._detach_cloud_thread(fake)
        # Referenz wird gehalten, Thread NICHT sofort zerstoert:
        assert thread in fake._detached_cloud_threads
        thread.deleteLater.assert_not_called()
        thread.finished.connect.assert_called_once()
        worker.request_cancel.assert_called_once()
        # Aktiver Slot ist frei, laufender detached Thread bleibt erhalten:
        assert fake._cloud_thread is None

    def test_quick_thread_is_not_detached(self):
        fake = self._fake_window()
        thread = fake._cloud_thread
        thread.wait.return_value = True  # beendet sich rechtzeitig
        tts_window.TtsWindow._detach_cloud_thread(fake)
        assert fake._detached_cloud_threads == []
        thread.setParent.assert_not_called()

    def test_detach_is_idempotent_without_active_thread(self):
        fake = self._fake_window()
        fake._cloud_worker = None
        fake._cloud_thread = None
        tts_window.TtsWindow._detach_cloud_thread(fake)  # darf nicht crashen
        assert fake._detached_cloud_threads == []

    def test_finished_releases_detached_thread(self):
        thread = MagicMock()
        fake = SimpleNamespace(_detached_cloud_threads=[thread])
        tts_window.TtsWindow._on_detached_thread_finished(fake, thread)
        assert thread not in fake._detached_cloud_threads
        thread.deleteLater.assert_called_once()
