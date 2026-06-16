# Local Transcription Backends

BlitztextLinux does **not** use WhisperKit/CoreML model bundles.
On Linux, transcription runs through the Whisper Python backends configured in the app:

- `openai-whisper` (default)
- `faster-whisper` (optional)

Supported model names in the Linux app are:
`tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3`, `large-v3-turbo`.

## Linux install path

The recommended installer sets up the backend environment automatically:

```bash
bash scripts/install.sh
```

Under the hood, the installer prepares a Python 3.11-compatible virtual environment, installs `openai-whisper`, and can inject `faster-whisper`.

## Notes

- No separate WhisperKit/CoreML cache directory is used on Linux.
- The Linux transcription path is CPU-oriented and meant to work with the repo's current `run.sh` launcher.
- The original macOS version used a different local-model story (WhisperKit/CoreML); that is not part of this Linux repository.
