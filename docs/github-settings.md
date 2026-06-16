# GitHub Settings Checklist

These settings are not stored in the repository. Configure them in GitHub before going public.

## Security

- Enable Dependabot alerts.
- Enable secret scanning.
- Enable push protection for supported secret types.
- Enable private vulnerability reporting when available.

## Branch Protection

Protect `main`:

- require pull request before merge
- require at least one approval
- require the CI workflow to pass
- dismiss stale approvals when new commits are pushed
- block force pushes

## Actions

- Keep default workflow permissions read-only.
- Require approval for workflows from first-time contributors.
- Do not add repository secrets unless they are truly needed.

## Community

- Keep Issues enabled for bugs and focused requests.
- Enable Discussions only if you want a lower-friction place for questions.
- Set repository topics after the project is public.
- Review the GitHub community profile before sharing the repo widely.
