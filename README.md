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
#    Pick the patient scenario with SCENARIO_ID (defaults to "scheduling").
SCENARIO_ID=refill python -m caller.agent dev

# 2. In another terminal, trigger ONE outbound call.
lk dispatch create --new-room --agent-name outbound-caller
```

This dials the single hardcoded clinic test line (`+18054398008`) over the
outbound SIP trunk; caller ID is the trunk's number (`+15202143958`). The bot
listens first and only responds once the clinic agent speaks.

### Patient scenarios

The patient persona is loaded from a typed library in
[scenarios/scenarios.py](scenarios/scenarios.py). Select one with `SCENARIO_ID`;
its `id` becomes the transcript suffix (e.g. `call-03-refill.txt`). Available:

| `SCENARIO_ID` | What the patient does |
| --- | --- |
| `scheduling` (default) | Books a routine check-up for next week. |
| `reschedule` | Moves or cancels an existing appointment. |
| `refill` | Requests a refill of a named prescription. |
| `info` | Asks informational questions (hours / insurance / parking). |
| `existing_patient_persistent` | Insists they're an existing patient; pushes back on new-profile prompts. |
| `out_of_scope` | Makes an impossible/out-of-scope request to probe boundaries. |

Each scenario layers its persona/goal/facts/behavior on top of the invariant
role rules (the bot is always the *caller*, never the clinic receptionist).

### Batch runner (many calls automatically)

To generate a set of recordings without hand-running each call, use the sequential
batch runner. It drives a **single** long-running worker, passing the scenario id
in each dispatch's job metadata, and waits for each call to finish before starting
the next (real PSTN calls to one test line — sequential avoids overlap).

```bash
# 1. Start ONE worker and leave it running (it now reads the scenario per call
#    from dispatch metadata, so you do NOT need a worker per scenario):
python -m caller.agent dev

# 2. In another terminal, run the batch (default: 2x each of the 6 scenarios = 12):
python -m caller.batch_runner

# Custom plan and timing:
python -m caller.batch_runner --plan scheduling=3,refill=2,info=1
python -m caller.batch_runner --per-call-timeout 240 --delay 10
```

The runner prints an end-of-run summary (scenario, room, transcript filename,
completed/timeout/failed) and flags transcripts that look like empty **stubs** —
a reserved call number whose call failed before any conversation — so you can tell
real calls from stubs when feeding them to the analysis harness later.

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
