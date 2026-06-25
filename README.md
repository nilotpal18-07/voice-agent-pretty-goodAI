# Outbound Voice Bot

An outbound voice agent built on [LiveKit Agents](https://docs.livekit.io/agents/),
placing calls over a Telnyx-backed SIP trunk and using OpenAI for the
LLM / STT / TTS stack. Take-home project.

> **Status:** scaffold only. Module bodies are stubbed (`TODO`); no call logic
> is implemented yet.

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
# ...then fill in LiveKit, Telnyx SIP, and OpenAI values in .env
```

You will also need to provision a LiveKit **outbound SIP trunk** backed by a
Telnyx number and set `SIP_OUTBOUND_TRUNK_ID` in `.env`. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the call flow.

## Usage

> Not yet implemented. Once `caller/agent.py` is filled in, the worker will run
> via the LiveKit Agents CLI, e.g.:

```bash
python -m caller.agent dev      # run the worker in dev mode
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — components, call flow, data flow.
- [PROMPTS.md](PROMPTS.md) — agent system prompts and scenario prompt design.
