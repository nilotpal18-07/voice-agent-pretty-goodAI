# Architecture

> Design notes for the outbound voice bot. This is a scaffold — sections are
> outlined and expected to be filled in as the implementation lands.

## Overview

The system places **outbound** phone calls and runs a real-time voice agent on
each call. It is built on the LiveKit Agents framework, with telephony provided
by a Telnyx-backed SIP trunk and the conversational stack provided by Deepgram
(STT), Google Gemini (LLM), and Cartesia (TTS).

## Components

| Component        | Responsibility                                              |
| ---------------- | ----------------------------------------------------------- |
| `caller/agent.py`| LiveKit worker: dials out, hosts the agent session.         |
| SIP trunk        | LiveKit outbound trunk → Telnyx → PSTN. (`SIP_OUTBOUND_TRUNK_ID`) |
| STT / LLM / TTS  | Deepgram (STT) · Google Gemini (LLM) · Cartesia (TTS).      |
| VAD / turn-taking| Silero VAD + LiveKit audio turn detector (`inference`).     |
| `scenarios/`     | Inputs: who to call and the goal/script for each call.      |
| `recordings/`    | Outputs: captured call audio.                               |
| `analysis/`      | Outputs: transcripts, metrics, and evaluation.              |

## Call flow

```
scenario ──> caller worker ──> LiveKit ──> SIP outbound trunk ──> Telnyx ──> callee
                  │                                                            │
                  └────────────── AgentSession (STT ─ LLM ─ TTS) ◀────audio────┘
                                          │
                            recordings/ + analysis/
```

1. A job is dispatched to the worker with dial info (number + scenario).
2. The worker creates a SIP participant via the outbound trunk to ring the callee.
3. On answer, an `AgentSession` runs the STT → LLM → TTS loop in real time.
4. The call is recorded by LiveKit Cloud (`session.start(record=True)`); a local
   transcript of both sides is written to `recordings/`.

## Data flow

- **In:** scenario definitions from `scenarios/`, credentials from `.env`.
- **Out:** audio to `recordings/`, transcripts & metrics to `analysis/`.

## Open questions / TODO

- Scenario file format (JSON/YAML?).
- ~~Recording strategy~~ — resolved: LiveKit Cloud recording (`record=True`),
  audio downloaded from Agent insights; transcript written locally. Egress →
  object storage remains an option if recordings must be auto-saved locally.
- Analysis metrics and evaluation method.
