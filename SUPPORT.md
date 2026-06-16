# Support

BlitztextLinux is an experimental Linux desktop app. There is no service-level agreement, paid support channel, or guarantee that issues will be fixed.

## Before Asking For Help

- Make sure you can install the app with `bash scripts/install.sh`.
- Confirm that your OpenAI API key is entered in the app settings if you use online workflows.
- Verify that `bash scripts/verify.sh` succeeds.
- If you expect auto-paste, make sure `ydotool.service` is running and your session has access to the `input` group.
- Read [docs/privacy.md](docs/privacy.md) before testing with sensitive content.

## Where To Ask

Use GitHub Issues for reproducible bugs and focused feature ideas.

Please do not post:

- OpenAI API keys
- access tokens
- private audio recordings
- confidential transcripts
- screenshots that show sensitive content

For security-sensitive reports, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
