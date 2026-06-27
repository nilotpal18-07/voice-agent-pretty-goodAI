# Architecture

How the outbound patient-bot tester works, and the key design choices behind it.

## How it works

**Call path.** A LiveKit dispatch creates a room and passes the chosen
`scenario_id` in its job metadata. That wakes the long-running `outbound-caller`
worker ([caller/agent.py](caller/agent.py)), which connects to the room and places
an outbound call to the hardcoded clinic test line through the Telnyx-backed SIP
trunk (referenced only by `SIP_OUTBOUND_TRUNK_ID`). Once the callee answers, the
patient bot runs a streaming **Deepgram → Gemini 2.5 Flash → Cartesia** pipeline
with Silero VAD + the LiveKit turn detector and BVCTelephony noise cancellation.
It is configured **listen-first** — it never greets, so the clinic agent (the
system under test) speaks first and the bot responds as a caller. The call audio is
recorded to LiveKit Cloud (`session.start(record=True)`), and a plain-text
transcript of both sides is written locally to `recordings/call-NN-<scenario>.txt`.

**Testing layer.** Scenarios are a typed library
([scenarios/scenarios.py](scenarios/scenarios.py)): each `PatientScenario` carries a
persona, goal, key facts, behavior notes, and an explicit `success_criteria`, and
`build_instructions()` renders it onto a fixed block of invariant role rules. The
sequential batch runner ([caller/batch_runner.py](caller/batch_runner.py))
dispatches one call at a time across the scenarios (scenario passed via metadata),
waiting for each room to finish before the next. The offline analysis harness
([analysis/analyze.py](analysis/analyze.py)) then reads every transcript, asks an
LLM to score each call against its scenario's `success_criteria` and extract
defects grounded in exact quotes, and **aggregates findings across calls into
distinct bugs with reproduction counts**. Results land in `analysis/findings.{md,json}`,
cross-checked by the hand-verified `analysis/candidate-bugs.md` and curated into
[BUG_REPORT.md](BUG_REPORT.md).

## Block diagram

```
            ┌────────────────────────────────────────────────┐
            │  TEST DRIVER (local)                            │
            │  caller/batch_runner.py  ·  scenarios/scenarios.py │
            └───────────────────────┬────────────────────────┘
                                    │ dispatch (scenario_id in job metadata)
                                    v
   ┌──────────────────────────────────────────────────────────────────┐
   │  LIVEKIT CLOUD                                                     │
   │                                                                    │
   │   Agent Dispatch ──> outbound-caller worker  (caller/agent.py)     │
   │                          │                                         │
   │     ┌────────────────────┴── AgentSession: patient bot ────────┐  │
   │     │  Deepgram STT ──> Gemini 2.5 Flash ──> Cartesia TTS       │  │
   │     │  Silero VAD + LiveKit turn detector · BVCTelephony NC      │  │
   │     │  (listen-first — the clinic agent speaks first)           │  │
   │     └───────────────────────────────────────────────────────────┘  │
   │                          │                                         │
   │   SIP service            └── record=True ──> Cloud audio (insights)│
   └───────────┬────────────────────────────────────────────────────────┘
               │ outbound call via trunk ST_…
               v
   ┌───────────────┐      ┌──────┐      ┌──────────────────────────┐
   │ Telnyx SIP    │ ───> │ PSTN │ ───> │ CLINIC VOICE AGENT       │
   │ trunk         │ <─── │      │ <─── │ (system under test)      │
   └───────────────┘      └──────┘      └──────────────────────────┘

   Outputs ─ recordings/*.txt (transcripts) + Cloud audio (downloaded
             to recordings/audio recordings/)
                          │
                          v
   ┌──────────────────────────────────────────────────────────────────┐
   │  ANALYSIS (offline)                                               │
   │  analysis/analyze.py ─ score vs success_criteria + dedupe bugs ─> │
   │  analysis/findings.{md,json} ─> candidate-bugs.md ─> BUG_REPORT.md │
   └──────────────────────────────────────────────────────────────────┘
```

## Components

| Component | Responsibility |
| --- | --- |
| `caller/agent.py` | LiveKit worker: dials out, runs the patient pipeline, writes transcripts. |
| `caller/batch_runner.py` | Sequential driver: dispatches calls across scenarios, summarizes results. |
| `scenarios/scenarios.py` | Typed `PatientScenario` library + `build_instructions()`. |
| `analysis/analyze.py` | Offline harness: scores calls vs. success criteria, extracts + dedupes bugs. |
| SIP trunk | LiveKit outbound trunk → Telnyx → PSTN (`SIP_OUTBOUND_TRUNK_ID`). |
| STT / LLM / TTS | Deepgram · Google Gemini 2.5 Flash · Cartesia. |
| VAD / turn-taking | Silero VAD + LiveKit turn detector; BVCTelephony noise cancellation. |

## Call flow

```
dispatch (scenario in metadata)
   └─> outbound-caller worker ──> LiveKit ──> SIP outbound trunk ──> Telnyx ──> clinic agent
            │                                                                       │
            └──────── AgentSession (Deepgram ─ Gemini ─ Cartesia), listen-first ◀── audio
                              │
              recordings/*.txt (transcript) + LiveKit Cloud (audio)
                              │
              analysis/analyze.py ──> findings.{md,json} ──> BUG_REPORT.md
```

1. A dispatch creates a room and passes the `scenario_id` in job metadata.
2. The worker joins, builds the patient persona for that scenario, and dials the trunk.
3. On answer, the STT→LLM→TTS loop runs; the bot waits for the clinic agent to open.
4. Audio is recorded to LiveKit Cloud; a both-sides transcript is written locally.
5. The analysis harness scores and aggregates across all transcripts.

## Key design choices

- **Pipeline (STT-LLM-TTS), not speech-to-speech.** A discrete Deepgram→Gemini→
  Cartesia pipeline gives control and debuggability — each stage is inspectable, the
  text transcript is a first-class artifact, and iteration is cheaper than a single
  realtime speech model.
- **Listen-first turn handling.** The bot is the *caller*, so it must not greet. It
  is started without an opening turn and uses VAD + the LiveKit turn detector to let
  the clinic agent speak first, which keeps the test faithful to a real inbound call.
- **Typed scenarios with explicit `success_criteria`.** Encoding the goal per
  scenario lets the analysis harness score *task outcomes* (pass/partial/fail), not
  just spot defects — turning "the agent seems bad" into measured success rates.
- **Sequential calling to one test line.** Calls are placed one at a time and the
  runner waits for each to end (and force-ends hung ones). Real PSTN calls to a
  single number are kept isolated, so evidence and recordings stay clean and
  attributable.
- **Offline analysis as an eval.** Bug-finding is a separate, reproducible pass that
  deduplicates findings and counts how many calls each defect appears in — converting
  anecdotes into quantified, ranked failure rates that a developer can act on.
