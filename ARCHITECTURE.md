# Architecture

> Design notes for the outbound voice bot. This is a scaffold — sections are
> outlined and expected to be filled in as the implementation lands.

## Overview

The system places **outbound** phone calls and runs a real-time voice agent on
each call. It is built on the LiveKit Agents framework, with telephony provided
by a Telnyx-backed SIP trunk and the conversational stack provided by OpenAI.

## Components

| Component        | Responsibility                                              |
| ---------------- | ----------------------------------------------------------- |
| `caller/agent.py`| LiveKit worker: dials out, hosts the agent session.         |
| SIP trunk        | LiveKit outbound trunk → Telnyx → PSTN. (`SIP_OUTBOUND_TRUNK_ID`) |
| STT / LLM / TTS  | OpenAI — speech-to-text, reasoning, text-to-speech.         |
| VAD              | Silero voice-activity detection for turn-taking.            |
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
4. Audio is optionally recorded; transcripts/metrics are written for analysis.

## Data flow

- **In:** scenario definitions from `scenarios/`, credentials from `.env`.
- **Out:** audio to `recordings/`, transcripts & metrics to `analysis/`.

## Open questions / TODO

- Scenario file format (JSON/YAML?).
- Recording strategy (LiveKit Egress vs. local capture).
- Analysis metrics and evaluation method.
