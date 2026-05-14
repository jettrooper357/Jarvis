# Voice — real-time speech in OpenJarvis

OpenJarvis ships with a fully local, real-time voice loop:

- **Streaming STT** — microphone audio is streamed to the server over a
  WebSocket; [silero-vad](https://github.com/snakers4/silero-vad) segments it
  into utterances and `faster-whisper` transcribes each segment in-memory.
  Interim transcripts appear as you speak; the final transcript auto-submits
  to the chat when you stop talking.
- **Streaming TTS** — assistant replies are spoken aloud as they stream.
  Tokens are buffered per-sentence and rendered by the local
  [kokoro](https://github.com/hexgrad/kokoro) TTS model. Audio chunks play
  back-to-back without gaps.

Nothing leaves your machine — both whisper and kokoro run locally.

## Install

```bash
uv sync --extra speech --extra speech-tts-kokoro
```

- `speech` — `faster-whisper`, `silero-vad`, `soundfile` (the STT pipeline
  and audio I/O used by streaming TTS).
- `speech-tts-kokoro` — `kokoro` plus the `transformers<5` /
  `huggingface_hub<1.0` pins it needs. Without those pins, `pip install
  kokoro` resolves to the bleeding-edge `transformers==5.x` whose
  `is_offline_mode` import is broken against modern `huggingface_hub`.

`speech-tts-kokoro` is declared in `pyproject.toml` as mutually exclusive
with `inference-mlx` (mlx-lm requires the very `transformers` 5.x line we
pin away from). On Apple Silicon, pick one or the other.

Kokoro officially supports Python 3.10–3.12; it works on 3.13 with the
pinned extra above but is not officially supported there.

Kokoro's phonemizer also needs the **espeak-ng** system binary:

- Linux/WSL: `sudo apt install espeak-ng`
- macOS: `brew install espeak`
- Windows native: install from <https://github.com/espeak-ng/espeak-ng/releases>

On Windows the bundled `start.bat` installs `espeak-ng` inside WSL Ubuntu
automatically on first run (as `root`, so no WSL user password is needed).

The `server` extra already pulls in `uvicorn[standard]`, which provides the
`websockets` library needed for `/v1/speech/stream`. If you upgraded from an
older OpenJarvis checkout that didn't, re-sync the extra and restart the
server.

When the server starts you should see both backends discovered:

```
  Speech: faster-whisper
  TTS:    kokoro
```

## Enable in the UI

Open **Settings → Speech** and toggle:

- **Speech-to-Text** — required for any mic input.
- **Real-time streaming** — uses the streaming WebSocket (default).
  Disable to fall back to push-to-talk (record → stop → transcribe).
- **Speak responses** — autoplays assistant messages through TTS as they
  stream.

The mic button in the chat composer now opens a streaming session: click
to start listening, click again (or simply stop speaking for ~700 ms) to
finalize. The detected text appears in a banner above the input and is
submitted automatically.

Each assistant message also has a small speaker icon to replay it on demand.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `WebSocket /v1/speech/stream` | Streaming STT. Send 16 kHz mono int16 PCM frames; receive `partial`/`final` JSON events. |
| `POST   /v1/speech/transcribe` | Batch STT (file upload). Unchanged. |
| `POST   /v1/speech/synthesize` | Synthesize text to a single WAV. |
| `POST   /v1/speech/synthesize/stream` | Synthesize and stream sentence-sized WAV chunks as SSE. |
| `GET    /v1/speech/voices` | List available TTS voices. |
| `GET    /v1/speech/health` | STT + TTS backend status. |

## Privacy

All audio is processed locally. The streaming WebSocket terminates inside the
OpenJarvis server; whisper runs on your CPU/GPU; kokoro likewise. No audio
or transcripts are sent to any third party.

If you have cloud STT/TTS keys configured (Deepgram, OpenAI, Cartesia), they
are **not** used by the real-time loop — only by the existing batch
endpoints, and only when explicitly selected.

## Troubleshooting

- **"Streaming STT requires the faster-whisper backend"** — your speech
  backend is not whisper. Set `speech.backend = "faster-whisper"` in
  `~/.openjarvis/config.toml` or remove cloud STT env vars.
- **"silero-vad not installed"** — run `uv sync --extra speech`.
- **The mic button is greyed out** — open Settings → Speech and enable
  both *Speech-to-Text* and (optionally) *Real-time streaming*. Also check
  that the browser has microphone permission.
- **Sample-rate errors in the console** — Chrome and Firefox both support
  16 kHz `AudioContext`s, but Safari does not. On Safari the streaming hook
  falls back to push-to-talk automatically (toggle *Real-time streaming* off
  if it doesn't).
- **No TTS audio / kokoro import errors** — the project ships the right pins
  in the `speech-tts-kokoro` extra; if you installed kokoro manually you
  may have ended up with `huggingface_hub` 1.x or `transformers` 5.x.
  Re-sync the extra (`uv sync --extra speech --extra speech-tts-kokoro`) and
  restart the server.
- **`/v1/speech/synthesize` returns 500 with `espeak-ng` not found** — install
  the system binary (`sudo apt install espeak-ng` on Linux/WSL, `brew install
  espeak` on macOS, the Windows installer on bare Windows) and restart the
  server. The Windows `start.bat` does this automatically on first run.
- **No TTS audio (other)** — check `GET /v1/speech/voices` returns voices. If
  empty, the `speech-tts-kokoro` extra isn't installed in the active venv.
