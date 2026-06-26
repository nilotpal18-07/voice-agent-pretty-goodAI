# Outbound Voice Bot

An outbound voice agent built on [LiveKit Agents](https://docs.livekit.io/agents/),
placing calls over a Telnyx-backed SIP trunk and using Deepgram (STT),
Google Gemini (LLM), and Cartesia (TTS) for the voice stack. Take-home project.

> **Status:** step 1 implemented — one outbound call with a single hardcoded
> patient scenario. A scenario library, batch runner, and analysis layer are
> future steps.

## Project structure

```
.
├── caller/            # LiveKit agent worker + outbound-call entrypoint
│   ├── __init__.py
│   └── agent.py       # skeleton, based on outbound-caller-python
├── scenarios/         # call scenarios / dial lists (inputs)
├── recordings/        # captured call audio (outputs)
├── analysis/          # transcripts, metrics, evaluation (outputs)
├── .env.example       # config template (copy to .env)
├── requirements.txt
├── ARCHITECTURE.md    # system design & call flow
└── PROMPTS.md         # system prompts & per-scenario prompt notes
```

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# ...then fill in LiveKit, Telnyx SIP, Deepgram, Google, and Cartesia values in .env
```

You will also need to provision a LiveKit **outbound SIP trunk** backed by a
Telnyx number and set `SIP_OUTBOUND_TRUNK_ID` in `.env`. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the call flow.

## Usage

The worker uses **explicit dispatch** (it registers as `outbound-caller` and
never auto-joins a room). Placing one call is two steps:

```bash
# 1. Start the worker (leave running). dev mode uses your LiveKit Cloud creds.
python -m caller.agent dev

# 2. In another terminal, trigger ONE outbound call.
lk dispatch create --new-room --agent-name outbound-caller
```

This dials the single hardcoded clinic test line (`+18054398008`) over the
outbound SIP trunk; caller ID is the trunk's number (`+15202143958`). The bot
listens first and only responds once the clinic agent speaks.

### Recordings

- **Transcript** (automatic, local): written to
  `recordings/call-NN-scheduling.txt` when the call ends. The `NN` auto-increments
  per call (call-01, call-02, …) so repeat/concurrent calls never overwrite each
  other; the scenario suffix is configurable via `SCENARIO` in `caller/agent.py`.
- **Audio** (LiveKit Cloud): the session runs with `record=True`, so LiveKit
  records the mixed call audio + transcript + traces. Play back or download the
  audio from **Sessions → Agent insights** in the LiveKit Cloud dashboard
  (30-day retention). Enable **Agent observability** under the project's
  *Data and privacy* settings for this to be captured.

## Tests

Behavioral tests run on LiveKit's text test harness (no telephony; uses Gemini):

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — components, call flow, data flow.
- [PROMPTS.md](PROMPTS.md) — agent system prompts and scenario prompt design.
