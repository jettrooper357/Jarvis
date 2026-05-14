# WSL2 Install

OpenJarvis runs in WSL2 on Windows. Native Windows is not supported.

## One-time WSL setup

In an admin PowerShell:

```powershell
wsl --install
```

Then open the Ubuntu (or Debian) shell that gets installed.

## Install OpenJarvis

```bash
curl -fsSL https://openjarvis.ai/install.sh | bash
```

About 3 minutes. Type `jarvis` to start.

### Local clone (contributors / dev workflow)

If you cloned the repo and want the chat UI running end-to-end, run
`start.bat` from a Windows shell at the repo root. It bootstraps `uv`,
`espeak-ng`, the Python venv, and the frontend in one go. See
[Installation → Browser App → Windows](installation.md#browser-app) for the
full list of steps and pre-reqs.

## WSL-specific notes

- The installer detects WSL via `/proc/sys/kernel/osrelease` and uses `nohup ollama serve &` instead of systemd to start the Ollama daemon (WSL2 doesn't ship systemd by default).
- The first time you run `jarvis`, the WSL kernel may show a "process running in background" notification — that's the bg-orchestrator detaching. It's expected.
- Models are stored in WSL's filesystem (`~/.openjarvis/`), not your Windows drive. To free up space later: `jarvis-uninstall` removes everything.

## See also

- [Full installer reference](install.md)
