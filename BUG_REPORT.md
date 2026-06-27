# Bug Report — Clinic Scheduling Voice Agent

**Prepared for:** Pretty Good AI · **Date:** 2026-06-26
**Scope:** Behavior of the inbound "clinic" voice agent under automated test calling.

## Summary

Across **25 recorded test calls** spanning **6 patient scenarios**, the agent **failed to complete the caller's task in 19 of 25 calls (76%)**, and did not fully succeed in a single one of the 16 core scheduling, rescheduling, or existing-patient calls. Several **Critical** defects reproduced at high rates. Most striking, the agent **fabricated a patient's date of birth in 21 of 25 calls (84%)** — always the same value, "July fourth two thousand" — for callers who never provided one. It also routinely **hallucinated a pre-existing appointment on brand-new profiles** (14/25), which in some calls actively blocked the booking the caller requested, and it **could not recognize an existing patient** (14/25), forcing demo-profile creation in a loop. Transfers to live support were offered but never completed (6/25). These are data-integrity and task-completion failures that would be unacceptable in a real healthcare deployment; the agent is not currently fit for booking, rescheduling, or patient-identification tasks.

## Methodology

Bugs were found by an automated **patient bot** that placed outbound calls to the agent across 6 scenarios — `scheduling`, `reschedule`, `refill`, `info`, `existing_patient_persistent`, and `out_of_scope` — each call recorded and transcribed. An offline analysis harness then evaluated every transcript with an LLM: it scored each call **against that scenario's predefined success criteria** (pass / partial / fail) and extracted **defects in the agent's behavior, each grounded in an exact transcript quote**. Findings were deduplicated across calls into distinct bugs with **reproduction counts**. Of 28 recordings, 3 were empty/stub calls and excluded, leaving **25 analyzed calls**. All findings below are corroborated by a separate hand-verified review of the transcripts.

## Task-success overview

The agent rarely achieves the caller's goal. Per-scenario outcomes (judged against each scenario's success criteria):

| Scenario | Pass | Partial | Fail | Total |
| --- | --: | --: | --: | --: |
| scheduling | 0 | 1 | 7 | 8 |
| reschedule | 0 | 0 | 5 | 5 |
| existing_patient_persistent | 0 | 0 | 3 | 3 |
| refill | 1 | 0 | 2 | 3 |
| info | 2 | 0 | 1 | 3 |
| out_of_scope | 2 | 0 | 1 | 3 |
| **Total** | **5** | **1** | **19** | **25** |

The few successes are concentrated in informational and out-of-scope handling. The agent's core purpose — booking and managing appointments — failed in every one of the 16 scheduling/reschedule/existing-patient calls.

## Critical bugs

### 1. Date-of-birth hallucination — Critical · 21/25

When creating a patient profile, the agent assigns a date of birth the caller never provided — always the identical value, "July fourth two thousand." It recurred verbatim across 21 calls and four different patients, including callers who stated a real, different DOB moments earlier. Writing fabricated identifiers into a patient record is a serious data-integrity and patient-safety risk: it can mis-identify patients and corrupt downstream records.

> AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes. *(call-01-existing_patient_persistent.txt)*

### 2. Phantom appointment — Critical · 14/25

Immediately after creating a brand-new profile, the agent claims the patient already has an appointment on file. In several calls this hallucinated state **blocks the requested action** — the agent refuses to book a new visit because of an appointment that does not exist, and cannot produce its details. This both derails the caller's task and signals unreliable appointment state.

> AGENT (clinic): It looks like you already have an office visit appointment booked. *(call-01-out_of_scope.txt)*

### 3. Cannot recognize an existing patient (profile loop) — Critical · 14/25

When a caller says they are an existing patient and offers their name and date of birth for lookup, the agent cannot locate them and instead insists on creating a "demo patient profile," sometimes repeating the demand several times until the caller gives up. There is no working patient-lookup path, so returning patients cannot be served as themselves.

> AGENT (clinic): Right now, I can only assist if you create a demo patient profile. Would you like to set one up? *(call-01-existing_patient_persistent.txt)*

### 4. Broken / dead-end transfer — Critical · 6/25

The agent offers to transfer the caller to live support and the caller accepts, but the transfer never completes: in some calls the agent silently abandons it and starts booking instead; in others the call simply dead-ends. Callers who need a human are left with no path to one — a significant gap for a healthcare line where escalation matters.

> AGENT (clinic): It looks like you'd like to book a routine checkup. One moment while I get that started for you. *(call-01-existing_patient_persistent.txt — said immediately after the caller confirmed "yes, transfer me to live support")*

### 5. Premature call termination — Critical · 2/25

In some calls the agent ends the call without ever addressing the caller's stated request. The caller's task is abandoned with no resolution and no handoff.

> AGENT (clinic): I'm going to end the call now. *(call-01-scheduling.txt — caller had asked to book a check-up and it was never booked)*

## Major bugs

### Context loss after profile creation — Major · 3/25

After creating a profile, the agent forgets the caller's original request and asks how it can help again, forcing the caller to repeat themselves.

> AGENT (clinic): How may I help you today? *(call-01-scheduling.txt — asked after the caller had already requested a check-up)*

### Basic info gated behind profile creation — Major · 2/25

Asked a simple informational question (e.g. weekend hours), the agent pushes profile creation rather than answering, gating public information behind an account.

> AGENT (clinic): Would you like to create a demo patient profile? That way I can help you with more details and services. *(call-01-info.txt)*

### Provider-name instability — Major · 2/25

The same provider is named several different ways within a single call (e.g. "Vukosky," then "Lewkowski," then "Likoski"), making it unclear who the appointment is actually with.

> AGENT (clinic): We have an opening for a routine checkup on Wednesday, July first, at three thirty PM with Zeebigniew Vukosky, MD. *(call-02-scheduling.txt — the same doctor is renamed later in the call)*

### Unclear out-of-scope / closed-day rejection — Major · 2/25

When a request can't be fulfilled (e.g. a Sunday when the clinic is closed), the agent pivots to "another day" without clearly stating the limitation, leaving the caller to infer why.

> AGENT (clinic): No problem. Would you like to look for the next available appointment on another day? *(call-01-out_of_scope.txt)*

## Notable single observations

Credible one-off findings (seen once; recorded without claiming reproducibility):

- **Ignored stated time preference** — surfaced an afternoon slot as the "earliest available" after the caller explicitly asked for mornings. *(appointment_search_failure)*
- **Acknowledged correction not persisted** — after confirming a corrected DOB, asked again at the end of the call whether to apply it. *(redundant_dob_update_request)*
- **Missing confirmation** — completed an action without confirming it back to the caller. *(missing_confirmation)*
- **Redundant prompts** — repeated the same question or confirmation unnecessarily. *(redundant_prompts)*
- **Unnecessary data-collection push** — pressed for profile/data when it wasn't needed. *(unnecessary_data_collection_push)*
- **Internal data inconsistency** — details that conflicted within a single call. *(data_inconsistency)*
- **Didn't act on provided info** — failed to use information the caller had already given. *(failure_to_recognize_info)*
- **Misstated information** — stated a detail incorrectly. *(misstated_information)*

## What worked

The agent was not uniformly broken, and a few flows were handled well. The **prescription-refill flow** captured details cleanly: it confirmed the medication and dose, gracefully re-asked the days-supply question and accepted an estimate, and confirmed the callback number and pharmacy (`call-01-refill.txt`). For an **out-of-scope MRI request**, it correctly recognized that an order was required and routed the caller to a provider visit rather than fabricating a booking (`call-01-out_of_scope.txt`). These cases account for most of the passing outcomes (informational and out-of-scope scenarios passed 2 of 3 each). The strengths are real but narrow — they sit alongside, not in place of, the Critical scheduling and data-integrity failures above.

---

*Evidence and reproduction counts are drawn from an automated analysis of all call transcripts (`analysis/findings.md`, `analysis/findings.json`), cross-checked against a hand-verified review (`analysis/candidate-bugs.md`). Quotes are verbatim from the cited transcripts.*
