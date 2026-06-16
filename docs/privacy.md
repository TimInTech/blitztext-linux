# Privacy Notes

## BlitztextLinux

BlitztextLinux stores the OpenAI API key in:

```text
~/.config/blitztext-linux/config.json
```

That file is written with restrictive permissions (`0600`) so only the current user can read it.

## Data flow

- Local transcription workflows stay on the machine.
- LLM workflows send the transcribed text to OpenAI for rewriting.
- Temporary audio files are created during processing and are removed when the workflow finishes or is cancelled.
- Workflow output may be placed on the clipboard so you can paste it into another app.

## Sensitive content

Do not store secrets in custom prompts, notes, or other free-text fields.
If you work with sensitive content, review the repository code, your OpenAI account settings, and your own privacy requirements first.

## Legacy macOS note

The old macOS preview stored its API key in Keychain. That is not the Linux storage model.
