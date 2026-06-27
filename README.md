# Outbound Patient-Bot Tester

An automated **outbound "patient" bot** that calls a healthcare voice agent and
role-plays a patient across multiple scenarios to test it. Each call is placed over
a Telnyx SIP trunk via LiveKit, recorded and transcribed, and then an offline
**analysis harness** scores every call against its scenario's success criteria and
surfaces grounded, deduplicated bugs in the agent under test.

**Stack:** Telnyx (SIP trunk / telephony) · [LiveKit Agents](https://docs.livekit.io/agents/)
(orchestration, outbound dialing, call recording) · Deepgram (STT) · Google Gemini
2.5 Flash (LLM brain) · Cartesia (TTS) · Silero VAD + the LiveKit turn detector ·
BVCTelephony noise cancellation.

## Prerequisites

- **Python 3.11+** (developed on 3.13)
- A **LiveKit Cloud** project (URL + API key/secret)
- A **Telnyx** account with an **outbound SIP trunk** + a phone number for caller ID
- API keys for **Deepgram**, **Google (Gemini)**, and **Cartesia**
- The [LiveKit CLI](https://docs.livekit.io/home/cli/cli-setup/) (`lk`) for trunk setup and dispatch

## Setup

```bash
git clone <repo> && cd voice-agent-pretty-goodAI
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the values below
```

### Configure `.env`

| Variable | What it is |
| --- | --- |
| `LIVEKIT_URL` | Your LiveKit Cloud project URL (`wss://…livekit.cloud`) |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit Cloud API credentials |
| `SIP_OUTBOUND_TRUNK_ID` | LiveKit outbound trunk id (`ST_…`) backing Telnyx — the only trunk var read at runtime |
| `DEEPGRAM_API_KEY` | Speech-to-text |
| `GOOGLE_API_KEY` | Gemini — the bot's LLM **and** the analysis harness |
| `CARTESIA_API_KEY` | Text-to-speech |

### Register the Telnyx trunk with LiveKit (one-time)

The Telnyx SIP credentials are **not** read by the app — they live in a gitignored
trunk config and are registered with LiveKit once. Put your Telnyx SIP host,
username/password, and caller-ID number in `outbound-trunk.json` (gitignored), then:

```bash
lk sip outbound create outbound-trunk.json
# Copy the returned trunk id (ST_...) into SIP_OUTBOUND_TRUNK_ID in .env.
```

At runtime the app references the trunk solely through `SIP_OUTBOUND_TRUNK_ID`.

## Run

The worker uses **explicit dispatch**: it registers as `outbound-caller` and only
runs when a dispatch creates a call. Start it once and leave it running; then place
calls from another terminal.

```bash
# Terminal 1 — start the long-running worker (leave running)
python -m caller.agent start
```

```bash
# Terminal 2 — place calls

# (a) full batch — the main entry point. Sequential; default 2× each of the
#     6 scenarios = 12 calls. One command generates the whole test set:
python -m caller.batch_runner
python -m caller.batch_runner --plan scheduling=3,refill=2,info=1   # custom plan
python -m caller.batch_runner --per-call-timeout 240 --delay 10     # custom timing

# (b) a single call, default 'scheduling' scenario:
lk dispatch create --new-room --agent-name outbound-caller

# (c) a single call, a specific scenario (passed via dispatch metadata):
lk dispatch create --new-room --agent-name outbound-caller --metadata '{"scenario_id":"refill"}'
```

The only number ever dialed is the hardcoded clinic test line (`+18054398008`);
caller ID is the trunk's number. The bot **listens first** and only responds once
the clinic agent speaks. Scenario selection precedence: dispatch metadata →
`SCENARIO_ID` env var → default (`scheduling`).

### Scenarios

A typed library in [scenarios/scenarios.py](scenarios/scenarios.py). The id becomes
the transcript suffix (e.g. `call-03-refill.txt`):

| `scenario_id` | What the patient does |
| --- | --- |
| `scheduling` (default) | Books a routine check-up for next week. |
| `reschedule` | Moves or cancels an existing appointment. |
| `refill` | Requests a refill of a named prescription. |
| `info` | Asks informational questions (hours / insurance / parking). |
| `existing_patient_persistent` | Insists they're an existing patient; pushes back on new-profile prompts. |
| `out_of_scope` | Makes an impossible / out-of-scope request to probe boundaries. |

### Analyze the calls

```bash
python -m analysis.analyze                                  # score + extract bugs -> analysis/findings.{md,json}
python -m analysis.analyze --model gemini-2.5-pro           # stronger offline model
python -m analysis.analyze --reaggregate-from analysis/findings.json   # re-dedupe only, no API calls
```

## Outputs

- `recordings/call-NN-<scenario>.txt` — local transcript of both sides, auto-numbered per scenario.
- **Call audio** — recorded by LiveKit Cloud (`record=True`); play back / download from
  **Sessions → Agent insights** in the dashboard. Downloaded copies for this run are
  under `recordings/audio recordings/`.
- `analysis/findings.md` / `findings.json` — automated per-call scoring + ranked, deduplicated bugs.
- `analysis/candidate-bugs.md` — hand-verified cross-reference.
- [BUG_REPORT.md](BUG_REPORT.md) — the curated, external-facing bug report.

> **Note:** A few transcripts in `recordings/` may be empty or have no
> `PATIENT (bot)` turns — we exhausted the **Cartesia (TTS) free-tier credits**
> partway through one of the batch run, so the bot couldn't speak on those calls. The analysis harness automatically detects and **skips these empty/stub transcripts**
> (they're logged as skipped), so they don't affect the findings.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q                                # deterministic suite: scenarios, labels, batch runner, analysis
python -m pytest -q tests/test_patient_agent.py    # behavioral tests (call Gemini; free tier ≈ 5 req/min)
```

The deterministic suite needs no telephony or network. The behavioral tests call
Gemini, so run them with a paid key or spaced out to avoid free-tier rate limits.

## Project structure

```
caller/
  agent.py          # LiveKit worker: dials out + runs the patient bot (STT→LLM→TTS)
  batch_runner.py   # sequential driver: dispatches calls across scenarios
scenarios/
  scenarios.py      # typed PatientScenario library + build_instructions()
analysis/
  analyze.py        # offline harness: scores calls + extracts/dedupes bugs
  findings.md/.json # automated results
  candidate-bugs.md # hand-verified cross-reference
recordings/         # local transcripts (+ downloaded call audio)
tests/              # deterministic + behavioral tests
BUG_REPORT.md       # curated bug report (deliverable)
ARCHITECTURE.md     # how it works + design choices
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — call path, components, and key design choices.
- [BUG_REPORT.md](BUG_REPORT.md) — findings on the tested clinic agent.
- [PROMPTS.md](PROMPTS.md) — system-prompt / scenario prompt notes.
