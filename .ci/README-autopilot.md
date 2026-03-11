# CI Autopilot

`ci-autopilot.ps1` reduces manual CI handling.

## Requirements

- GitHub CLI logged in (`gh auth status`)
- Run from repo root on PowerShell

## Modes

- Watch latest run on current branch:
  - `.\ci-autopilot.ps1`
- Continuous watch:
  - `.\ci-autopilot.ps1 -Follow`
- Explicit branch:
  - `.\ci-autopilot.ps1 -Branch main -Follow`

## Auto push + watch

- Auto stage, commit, push, then watch CI:
  - `.\ci-autopilot.ps1 -AutoPush -CommitMessage "fix ci" -Follow`
- Force push variant:
  - `.\ci-autopilot.ps1 -AutoPush -ForcePush -CommitMessage "fix ci" -Follow`

## Output files

When CI fails, the script writes:

- `.ci/failed-run.log`
- `.ci/failed-run-summary.md`

Use this summary with the agent to request focused fixes quickly.
