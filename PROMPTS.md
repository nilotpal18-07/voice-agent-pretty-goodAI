# Prompts & AI-Assisted Build Log

This project was built iteratively with an AI coding assistant (Claude Code). This
file is an honest, chronological record of the key prompts that drove the build —
each with the goal behind it, a faithful (condensed, not always verbatim) version of
the prompt, and the outcome, including where iteration was needed.

A recurring theme: because the LiveKit Agents SDK moves fast, the assistant was
asked to verify APIs against the installed SDK and live docs rather than memory —
which repeatedly caught deprecated calls before they shipped.

> The agent's *actual runtime prompts* are not reproduced here — they live in code
> (see [Agent runtime prompts](#agent-runtime-prompts) at the end). This file is
> about the development process.

---

## 1. Initial agent build

**Goal.** Get one real outbound call working end to end: a patient bot that dials a
healthcare voice agent and behaves as a caller. Framed as "one clean call I can
listen to" to keep the first iteration small and verifiable.

**Prompt (condensed).**
> Wire up `caller/agent.py` for one outbound call. Use a pipeline (NOT realtime):
> Deepgram STT → `google.LLM(gemini-2.5-flash)` → Cartesia TTS, with Silero VAD +
> the LiveKit turn detector and BVCTelephony noise cancellation. Dispatch the call
> over the SIP trunk (create a SIP participant that dials the one allowed number).
> The far-end clinic agent speaks first, so the bot must **not** greet — listen
> first, then respond as the patient. Record audio to `recordings/` and save a
> both-sides transcript; if egress needs a bucket, propose the lightest
> local-friendly approach. Read all config from `.env`; never hardcode secrets.

**Outcome.** The assistant verified the APIs against the installed SDK and caught two
things before they shipped: the `turn_detector` and Silero plugins were **deprecated**
(switched to `inference.TurnDetector` / `inference.VAD(model="silero")`), and LiveKit
Cloud egress can't write to local disk (switched to `session.start(record=True)` plus
a locally-written transcript). Behavioral tests were added on LiveKit's text harness.

## 2. Persona-inversion bug fix *(the key iteration)*

**Goal.** The first real call exposed a role inversion: the patient bot opened the
call as the clinic's receptionist instead of the caller. This is the centerpiece
find-and-fix loop — a bug only visible from a real transcript.

**The bad behavior** (`recordings/call-01-scheduling.txt`):
> PATIENT (bot): Hello, thanks for calling Main Street Clinic. My name is Sarah, how can I help you today?

**Prompt (condensed).**
> The patient bot's role is inverted — it greeted as the clinic receptionist. Fix
> `PatientCaller`'s instructions so it is unambiguously a PATIENT *calling in*,
> throughout the whole call: never greet as the clinic, never say "thanks for
> calling" or "how can I help you", never name itself a receptionist, keep one
> consistent identity. When the clinic agent (or an automated "this call may be
> recorded" notice) speaks, respond as the caller, e.g. "Hi, I'd like to book a
> check-up." Add a regression test that asserts the bot never produces
> receptionist-style greetings.

**Outcome.** Added an explicit `CRITICAL ROLE — you are the patient, NOT the clinic`
block to the persona, plus `test_does_not_act_as_receptionist`
([tests/test_patient_agent.py](tests/test_patient_agent.py)), which feeds both an
automated-notice opening and a receptionist greeting and asserts none of the
forbidden phrases appear. The next call confirmed the fix held. (A smaller sibling of
this bug recurred later in the `out_of_scope` scenario — the bot *announced the
clinic's hours* — and was fixed the same way: "ask about Sunday, never state the
clinic's policies.")

## 3. Unique, non-overwriting transcripts

**Goal.** Every call was overwriting the same `call-01-scheduling.txt`. Needed
distinct files per call, and concurrency-safe enough for a later batch runner.

**Prompt (condensed).**
> Make each call write a unique transcript: auto-increment `call-NN-<scenario>.txt`,
> with the scenario as a variable. Make it concurrency-safe — if simultaneous calls
> could collide on a number, fall back to a short uuid suffix.

**Outcome.** `next_call_label()` ([caller/agent.py](caller/agent.py)) reserves the
next number by atomically creating the file with `O_EXCL` — the create *is* the lock,
so concurrent calls can't claim the same number — with a uuid fallback. Covered by
deterministic tests.

## 4. Scenario library

**Goal.** Move from one hardcoded persona to a typed, extensible set of scenarios,
with explicit success criteria so later analysis could score outcomes — not just
spot defects.

**Prompt (condensed).**
> Build a typed `PatientScenario` (Pydantic) with `id`, `title`, `persona`, `goal`,
> `key_facts`, `behavior_notes`, `success_criteria`, `end_when`. Add
> `build_instructions(scenario)` that layers the per-scenario details on top of the
> invariant role rules. Define 6 scenarios: scheduling, reschedule, refill, info,
> existing_patient_persistent, out_of_scope. Select per call via `SCENARIO_ID`; the
> id flows into the transcript filename. Tests: every scenario builds valid
> instructions, the no-receptionist invariants survive for all of them, and the id
> reaches the filename.

**Why typed + success_criteria.** Encoding the goal per scenario is what let the
analysis harness (step 6) score pass/partial/fail, turning "seems bad" into measured
task-success rates.

**Outcome.** [scenarios/scenarios.py](scenarios/scenarios.py) with the 6 scenarios and
`build_instructions`; tests parametrized across all scenarios confirm the invariant
role rules survive every render.

## 5. Batch runner

**Goal.** Generate the 10+ calls the assessment needs without hand-running each one —
one worker, many scenarios, clean isolation.

**Prompt (condensed).**
> Build a sequential batch runner that places many calls across the scenario library.
> Use **dispatch job metadata** to pass the scenario (one long-running worker;
> `entrypoint` reads the scenario from metadata, falling back to env then default).
> Run calls one at a time — wait for each to finish before the next — with a per-call
> timeout, a delay between calls, and an end-of-run summary that flags empty/stub
> transcripts. Don't let one call's error crash the batch.

**Why sequential.** Real PSTN calls to a single test line; concurrency would overlap
and muddy the evidence.

**Outcome.** `entrypoint` now selects the scenario per call via
`resolve_scenario_id(ctx.job.metadata, …)`, and
[caller/batch_runner.py](caller/batch_runner.py) dispatches one call at a time, polls
the room lifecycle to detect completion, force-ends hung calls so they can't overlap,
and prints a summary flagging stubs. Default plan: 2× each of the 6 scenarios = 12.

## 6. Analysis harness

**Goal.** Turn a pile of transcripts into a structured, reproducible bug report —
scoring each call against its scenario and quantifying how often each defect repeats.

**Prompt (condensed).**
> Build an offline harness that reads all `recordings/` transcripts and uses an LLM
> to (1) score each call against its scenario's `success_criteria` (pass/partial/fail)
> and (2) extract bugs in the *agent's* behavior — category, severity, and an exact
> quote as evidence, grounded only in the transcript. Deduplicate across calls into
> distinct bugs with reproduction counts (X/N), ranked by severity. Seed the rubric
> with known categories but allow new ones. Skip stub transcripts; handle JSON/LLM
> errors per-transcript without crashing; write `findings.json` + `findings.md`;
> corroborate the hand-written `candidate-bugs.md` without overwriting it. Add
> deterministic tests for parsing and aggregation.

**Outcome.** [analysis/analyze.py](analysis/analyze.py) (google-genai, strict-JSON
output, 429 retry/backoff). The first run reported 27 "distinct" bugs because the LLM
coined many one-off category names; this was iterated by expanding an alias map and
adding a `--reaggregate-from` mode that re-folds the cached results with **no new API
calls** → 17 distinct bugs. The harness independently corroborated the manual findings
(e.g. DOB hallucination in 21/25 calls) and surfaced new ones (premature call
termination). It feeds the curated [BUG_REPORT.md](BUG_REPORT.md).

---

## Agent runtime prompts

The agent's real prompts are **defined in code and are the source of truth** — not
duplicated here, to avoid drift:

- **Persona / system prompts:** [scenarios/scenarios.py](scenarios/scenarios.py) —
  `INVARIANT_ROLE_RULES` (the caller-not-receptionist invariants) and
  `build_instructions(scenario)`, which renders each `PatientScenario`'s `persona`,
  `goal`, `key_facts`, `behavior_notes`, and `end_when` on top of those invariants.
- **Analysis / evaluation prompt:** [analysis/analyze.py](analysis/analyze.py) —
  `SYSTEM_INSTRUCTION` and `PROMPT_TEMPLATE`, which carry the per-scenario
  `success_criteria` and the bug-category rubric.

To see exactly what any call was instructed to do, read the relevant
`PatientScenario` plus `build_instructions`.
