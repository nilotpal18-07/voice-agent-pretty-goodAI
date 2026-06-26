# Candidate Bugs — Far-End Clinic Voice Agent

A running log of suspected bugs in the **healthcare ("clinic") voice agent we are
testing** — i.e. the far end of the call, **not** our outbound patient bot. Each
entry is grounded in a real call transcript with verbatim quotes.

> **Caveat — transcripts are our STT output.** The quotes below are what *our*
> Deepgram pipeline transcribed from the clinic agent's speech, not a ground-truth
> log of what it said. Structural/logic bugs (loops, re-asks, ignored input) are
> reliable; bugs that hinge on exact wording (names, dates) carry a confidence
> caveat and should be confirmed against the clinic-side audio/records.

## Sources

Calls are referenced by their full transcript filename (without `.txt`).

| Transcript file (in `recordings/`) | Notes |
| --- | --- |
| `call-01-scheduling` | Early run; ended with **no booking** (agent dropped the call). |
| `call-02-scheduling` | Booking completed; richer evidence. |
| `call-01-existing_patient_persistent` | `existing_patient_persistent` scenario; ended with **no booking and no transfer** (goal failure). |
| `call-01-reschedule` | `reschedule` scenario; agent forced a demo profile, surfaced **another caller's** appointment, and never completed the reschedule (goal failure). |
| `call-01-out_of_scope` | `out_of_scope` scenario; DOB hallucination + phantom appointment that **blocked** booking; MRI request handled correctly (OK-01). |
| `call-01-info` | `info` scenario; couldn't give weekend hours, gated info behind profile creation, transfer dead-ended. |
| `call-01-refill` | `refill` scenario; DOB hallucination; refill detail capture handled correctly (OK-02). |

## Severity scale

- **Critical** — blocks the core task or corrupts data with no recovery.
- **Major** — significant wrong behavior, data-integrity issue, or task failure with workaround.
- **Minor** — cosmetic, low-impact, or needs confirmation.

## Index

| ID | Title | Severity | Status | Source(s) |
| --- | --- | --- | --- | --- |
| BUG-01 | Existing-patient profile loop | Major | Reproducible (4 calls) | call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent, call-01-reschedule |
| BUG-02 | Date-of-birth hallucination (hardcoded default) | Major | Reproducible (6 calls / 5 scenarios) | call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent, call-01-reschedule, call-01-out_of_scope, call-01-refill |
| BUG-03 | Acknowledged DOB correction not persisted (re-asked) | Major | Candidate (single) | call-02-scheduling |
| BUG-04 | Provider name instability | Major | Reproducible | call-02-scheduling, call-01-reschedule |
| BUG-05 | Clinic/specialty mismatch (ortho for routine physical) | Minor | Candidate (single) | call-02-scheduling |
| BUG-06 | Ignores stated morning preference | Major | Candidate (single) | call-02-scheduling |
| BUG-07 | Phantom existing appointment (now blocks booking) | Critical | Reproducible | call-01-existing_patient_persistent, call-01-out_of_scope |
| BUG-08 | Ignored/overridden confirmed transfer request | Critical | Candidate (single) | call-01-existing_patient_persistent |
| BUG-09 | Goal failure: scenario task left unresolved | Major (outcome) | Reproducible | call-01-existing_patient_persistent, call-01-reschedule |
| BUG-10 | Cross-call appointment state leakage | Critical | Candidate (single) | call-01-reschedule (cross-ref call-02-scheduling) |
| BUG-11 | Basic info gated behind profile creation | Major | Candidate (single) | call-01-info |
| BUG-12 | Cannot provide basic clinic info | Major | Candidate (single) | call-01-info |
| BUG-13 | Broken / dead-end transfer | Critical | Candidate (single) | call-01-info (cross-ref call-01-existing_patient_persistent) |

---

## BUG-01 — Existing-patient profile loop

- **Severity:** Major — blocks the existing-patient path. In call-01-scheduling it looped
  until the agent gave up and ended the call with no booking.
- **Status:** Reproducible — seen in 4 calls (call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent, call-01-reschedule).
- **Source call(s):** `recordings/call-01-scheduling.txt`, `recordings/call-02-scheduling.txt`, `recordings/call-01-existing_patient_persistent.txt`, `recordings/call-01-reschedule.txt`
- **What happened:** The patient states they are an existing patient and gives their
  name, but the agent insists it has no profile and repeatedly pushes to create a
  "demo patient profile." It cannot handle an existing-patient claim. In
  call-01-scheduling the loop never resolved (call dropped, no booking); in
  call-02-scheduling it only moved forward after the patient abandoned the claim and
  consented to a demo profile. In call-01-existing_patient_persistent the patient
  explicitly asks to be looked up by name and date of birth, and the agent flatly
  refuses ("I can only assist if you create a demo patient profile") until the patient
  gives up. In call-01-reschedule the patient (Jordan Blake) is calling to reschedule an
  existing appointment, yet the agent again forces demo-profile creation instead of
  looking them up.
- **Evidence:**

  call-01-scheduling:
  > PATIENT (bot): No, I'm an existing patient. My name is Alex Carter. *(L9)*
  > AGENT (clinic): Alex. Since I don't have a patient profile for you yet, *(L11)*
  > AGENT (clinic): would you like to create a demo patient profile now? *(L12)*
  > PATIENT (bot): I'm an existing patient, Alex Carter. I'm just trying to book a check-up. *(L17)*
  > AGENT (clinic): To book your checkup, I'll need to create a demo patient profile for you first. *(L18)*

  call-02-scheduling:
  > PATIENT (bot): No, I'm an existing patient. My name is Alex Carter. *(L8)*
  > AGENT (clinic): Thanks for letting me know, Alex. I don't see a patient profile for you yet, Would you like to create a demo patient profile now? I just need your first and last name. *(L9)*
  > PATIENT (bot): That's odd. I'm sure I'm in your system. It's Alex Carter, and my date of birth is March 14, 1990. *(L10)*
  > AGENT (clinic): I understand that's frustrating. Right now, I don't have access to your patient profile. Would you like me to create a demo patient profile for you so we can move forward with booking your checkup. *(L11)*

  call-01-existing_patient_persistent:
  > PATIENT (bot): Oh, I'm already an existing patient. I've been coming here for years. Can you just look me up by my name and date of birth instead? *(L8)*
  > AGENT (clinic): Right now, I can only assist if you create a demo patient profile. Would you like to set one up? *(L9)*
  > PATIENT (bot): No, I'm really sure I'm in the system. Alex Carter, born March 14, 1990. My phone number and insurance should already be on file. Could you please just try looking me up with that? I really don't want to create a new profile. *(L12)*
  > AGENT (clinic): I understand Alex, At the moment, I can only help if you create a demo patient profile. If you prefer not to, you can scan the QR code at the booth later to set up your profile. *(L13)*

  call-01-reschedule:
  > PATIENT (bot): Oh, I'm already an existing patient. My name is Jordan Blake. *(L10)*
  > AGENT (clinic): Thanks for letting me know. Jordan, *(L11)*
  > AGENT (clinic): to help you reschedule, I'll need to create a demo patient profile for you here. *(L12)*

---

## BUG-02 — Date-of-birth hallucination (hardcoded demo default)

- **Severity:** Major — fabricates PII (a date of birth) the patient never gave and
  attaches it to the record. Data-integrity defect.
- **Status:** Reproducible — seen in **6 calls across all 5 profile-creating scenarios**
  (call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent,
  call-01-reschedule, call-01-out_of_scope, call-01-refill). The single most-reproduced
  bug in this log. (The `info` scenario never reached profile creation, so it's the only
  scenario without it.)
- **Source call(s):** `recordings/call-01-scheduling.txt`, `recordings/call-02-scheduling.txt`, `recordings/call-01-existing_patient_persistent.txt`, `recordings/call-01-reschedule.txt`, `recordings/call-01-out_of_scope.txt`, `recordings/call-01-refill.txt`
- **What happened:** Every time the agent creates a profile, it assigns the date of birth
  "July fourth two thousand" — which the patient never provided. The identical value recurs
  verbatim across 6 calls and 4 different patients (Alex Carter, Jordan Blake, Riley Morgan,
  Sam Rivera), several of whom gave a different real DOB just before or right after. This is
  conclusively a **hardcoded demo default**, not a random hallucination.
- **Evidence:**
  > AGENT (clinic): Your patient profile has been created successfully. And your date of birth is July fourth two thousand for demo purposes. *(call-01-scheduling L20 — Alex Carter)*
  > AGENT (clinic): Your patient profile has been created and your date of birth is set as July fourth. Two thousand for demo purposes. *(call-02-scheduling L13 — Alex Carter)*
  > AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes. *(call-01-existing_patient_persistent L16 — Alex Carter)*
  > AGENT (clinic): Your patient profile is set up, and your date of birth is July fourth two thousand for demo purposes. *(call-01-reschedule L17 — Jordan Blake, who never gave a DOB)*
  > AGENT (clinic): And your date of birth is July fourth two thousand. *(call-01-out_of_scope L12 — Riley Morgan, who never gave a DOB)*
  > AGENT (clinic): Your patient profile is set up, and your date of birth is July fourth two thousand. ... *(call-01-refill L12 — Sam Rivera, who then corrected it to Nov 9, 1978)*

---

## BUG-03 — Acknowledged DOB correction not persisted (re-asked at end)

- **Severity:** Major — the agent confirms it has the corrected DOB, then at the end
  asks to update it to that same value, implying the correction was never persisted.
  State / data-integrity defect.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-02-scheduling.txt`
- **What happened:** The patient corrects the DOB to March 14, 1990. The agent
  acknowledges it ("I have your date of birth as March fourteenth nineteen ninety").
  Yet after booking, the agent asks whether to update the DOB to that same date —
  re-requesting a change it already confirmed it had made.
- **Evidence:**
  > PATIENT (bot): Actually, my date of birth is March 14, 1990. I'd like to book a routine check-up, please. *(L15)*
  > AGENT (clinic): Thanks for clarifying. I have your date of birth as March fourteenth nineteen ninety. Do you have a preferred provider for your routine checkup, or would you like to see the first available? *(L16)*
  > AGENT (clinic): Would you like me to update your date of birth to March fourteenth nineteen ninety in your record? *(L30)*

---

## BUG-04 — Provider name instability (same provider, multiple names)

- **Severity:** Major — the booked provider is announced under several different
  surnames within one call, risking booking/announcing the wrong provider.
  *Confidence caveat:* some variance may be STT transcription error; confirm against
  clinic-side records/audio.
- **Status:** Reproducible (seen in call-02-scheduling and call-01-reschedule).
- **Source call(s):** `recordings/call-02-scheduling.txt`, `recordings/call-01-reschedule.txt`
- **What happened:** The provider for the same appointment is rendered with at least
  three distinct surnames within a single call. It recurs in call-01-reschedule, where the
  appointment surfaced for Jordan Blake (see BUG-10) names the provider three different
  ways. *(This is plausibly the same underlying provider as in call-02-scheduling — see
  BUG-10 — making the leaked appointment's provider name unstable too.)*
- **Evidence:**

  call-02-scheduling (Alex Carter's booking — three/four renderings):
  > AGENT (clinic): We have an opening for a routine checkup on Wednesday, July first, at three thirty PM with Zeebigniew Vukosky, MD. ... *(L20)*
  > AGENT (clinic): ... The earliest available slot is still Wednesday, July first, at three thirty PM with Zeebigniew Lewkowski, MD. ... *(L25)*
  > AGENT (clinic): There are morning openings on Monday, July sixth, You can book nine thirty AM, ten AM, or ten thirty AM with this big new Lekovsky MD, ... *(L27)*
  > AGENT (clinic): Your routine checkup is booked for Monday, July sixth at nine thirty AM with doctor Zigniew Likoski at Pivot Point Orthopedics ... *(L29)*

  call-01-reschedule (same appointment, three renderings in one call):
  > AGENT (clinic): I see an upcoming appointment for you on Monday. July sixth at nine thirty AM with doctor Zigbenu Lukowski at Nashville two two zero Athens Way. *(L20)*
  > AGENT (clinic): I only see one upcoming appointment for you, which is on Monday, July sixth, at nine thirty AM with doctor Zidbignew Lukowski. *(L23)*
  > AGENT (clinic): I understand this is frustrating. I'm only able to see the July sixth appointment with doctor Wikoski for you. ... *(L27)*

---

## BUG-05 — Clinic / specialty mismatch (ortho practice for routine physical)

- **Severity:** Minor — a routine general check-up is booked at "Pivot Point
  Orthopedics," an orthopedics practice, an odd fit for a general physical. May be
  expected demo data; needs confirmation.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-02-scheduling.txt`
- **What happened:** The patient asked for a routine check-up / general physical, but
  the booking lands at an orthopedics specialty practice.
- **Evidence:**
  > PATIENT (bot): Hi, I'd like to book a routine check-up, please. *(L4)*
  > AGENT (clinic): Your routine checkup is booked for Monday, July sixth at nine thirty AM with doctor Zigniew Likoski at Pivot Point Orthopedics Please bring your photo ID insurance card, a list of your current medications, and any imaging discs you have. *(L29)*

---

## BUG-06 — Ignores stated morning preference

- **Severity:** Major — the agent says it will search mornings, then offers an
  afternoon slot and re-presents that same afternoon slot as the "earliest
  available" even after acknowledging the morning constraint. A less persistent
  caller would have been booked into a time they explicitly declined. It recovered
  only after the patient pushed back twice.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-02-scheduling.txt`
- **What happened:** The patient asks for a morning appointment next week. The agent
  confirms it will check mornings, but offers a 3:30 PM slot. After the patient points
  out it's an afternoon, the agent agrees, re-checks, and *still* surfaces the same
  3:30 PM afternoon slot as the "earliest available." Only after the patient asks it to
  look the following week does it find actual morning openings.
- **Evidence:**
  > PATIENT (bot): First available is fine. I'm hoping to get in sometime next week, in the morning if possible. *(L17)*
  > AGENT (clinic): Let me check for morning openings next week with any available provider. One moment. *(L18)*
  > AGENT (clinic): We have an opening for a routine checkup on Wednesday, July first, at three thirty PM with Zeebigniew Vukosky, MD. ... *(L20)*
  > PATIENT (bot): That's an afternoon appointment. Do you have anything next week in the morning? *(L21)*
  > AGENT (clinic): It looks like there are no morning openings next week. The earliest available slot is still Wednesday, July first, at three thirty PM with Zeebigniew Lewkowski, MD. ... *(L25)*

---

## BUG-07 — Phantom existing appointment (hallucinated state, now blocks booking)

- **Severity:** Critical — fabricates an existing appointment on a profile created seconds
  earlier and, in call-01-out_of_scope, **refuses to book the requested appointment because
  of it** ("I'm unable to schedule another one"), blocking the core task. (It was Major when
  it only caused confusion in call-01-existing_patient_persistent; the out_of_scope call
  escalates it to blocking the goal.)
- **Status:** Reproducible (seen in call-01-existing_patient_persistent and call-01-out_of_scope).
- **Source call(s):** `recordings/call-01-existing_patient_persistent.txt`, `recordings/call-01-out_of_scope.txt`
- **What happened:** Immediately after creating a brand-new demo profile, the agent claims
  the patient already has an appointment booked — impossible for a just-created profile. In
  call-01-existing_patient_persistent it offered to reschedule/cancel the nonexistent
  appointment and couldn't give its date. In call-01-out_of_scope it goes further: when the
  patient asks to book the office visit the agent itself just recommended, the agent refuses
  because of the phantom appointment and will only reschedule it.
- **Evidence:**

  call-01-existing_patient_persistent:
  > AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes. *(L16)*
  > AGENT (clinic): Let me check the first available time for a routine checkup. One moment. It looks like you already have a routine checkup appointment booked. If you'd like, I can help you reschedule or cancel it. Would you like to make a change to your existing appointment? *(L25)*
  > AGENT (clinic): I don't have access to the exact date of your existing appointment. ... *(L29)*

  call-01-out_of_scope (the phantom appointment now blocks the booking):
  > AGENT (clinic): Your patient profile is set up. *(L10)*
  > AGENT (clinic): It looks like you already have an office visit appointment booked. If you want, I can help you reschedule or cancel your current appointment or connect you with live support for more help. *(L27)*
  > AGENT (clinic): Since you already have an office visit booked, I'm unable to schedule another one for you. Would you like to reschedule your current appointment to Monday? *(L35)*

---

## BUG-08 — Ignored/overridden confirmed transfer request

- **Severity:** Critical — the agent overrides an explicit, confirmed user intent. It
  offered a transfer to live support, the patient confirmed it, and the agent silently
  abandoned the transfer and switched to booking instead.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-01-existing_patient_persistent.txt`
- **What happened:** The agent proposed connecting the patient to live support and asked
  "Would you like to be transferred?" The patient clearly confirmed "Yes, please
  transfer me to live support...". Instead of transferring, the agent replied "It looks
  like you'd like to book a routine checkup" and began the booking flow.
- **Evidence:**
  > AGENT (clinic): I don't have access to the exact date of your existing appointment. You'd like, I can connect you with live support so they can provide the details or help you make changes. *(L29)*
  > AGENT (clinic): Would you like to be transferred? *(L30)*
  > PATIENT (bot): Yes, please transfer me to live support so I can get the details of my existing appointment and make sure we're looking at the right file. *(L31)*
  > AGENT (clinic): It looks like you'd like to book a routine checkup. One moment while I get that started for you. *(L32)*

---

## BUG-09 — Goal failure: scenario task left unresolved

- **Severity:** Major (outcome-level) — the call ends without meeting the scenario's
  `success_criteria`. This is an aggregate outcome of the other bugs, not a separate root
  cause; it's tracked so scenario-level failures stay visible as more calls are run.
- **Status:** Reproducible (seen in call-01-existing_patient_persistent and call-01-reschedule).
- **Source call(s):** `recordings/call-01-existing_patient_persistent.txt`, `recordings/call-01-reschedule.txt`
- **What happened:**
  - **call-01-existing_patient_persistent** — success requires booking the caller as an
    existing patient OR clearly explaining why it can't and offering an alternative,
    without an endless create-a-profile loop. Instead the agent forced a new profile,
    hallucinated an existing appointment, ignored the confirmed transfer, and the patient
    ended the call unresolved. (Caused by BUG-01, BUG-07, BUG-08.)
  - **call-01-reschedule** — success requires moving or cancelling the existing
    appointment and confirming the outcome. Instead the agent denied the patient's real
    appointment, surfaced a different caller's appointment (BUG-10), and the reschedule
    was never completed.
- **Evidence:**
  > PATIENT (bot): I asked to be transferred to live support. It seems like this isn't getting resolved. I'm going to end the call now. Thank you. *(call-01-existing_patient_persistent L33)*
  > PATIENT (bot): Okay, I just double-checked and I definitely have an appointment this Thursday at 2 PM with Dr. Patel. I need to reschedule that one to early next week, late afternoon if possible. *(call-01-reschedule L32)*
  > AGENT (clinic): Thanks for checking. *(call-01-reschedule L33 — call ends here; reschedule never done)*

---

## BUG-10 — Cross-call appointment state leakage

- **Severity:** Critical — the agent surfaces an appointment belonging to a *different*
  caller, and simultaneously denies the appointment the current caller actually has. This
  is cross-patient data leakage (a privacy / PHI concern) on top of a data-integrity
  failure.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-01-reschedule.txt` (cross-referenced against `recordings/call-02-scheduling.txt`)
- **What happened:** Jordan Blake calls to reschedule a Thursday 2 PM appointment with Dr.
  Patel. The agent says it has no such appointment, and instead reports an appointment on
  "Monday, July sixth at nine thirty AM" with "doctor Zigbenu Lukowski" — the *same* slot,
  date, and provider that a **different** patient, Alex Carter, booked in call-02-scheduling
  (L28–L29). The agent appears to be reading another caller's appointment state while
  failing to surface the caller's own.
- **Evidence:**

  call-01-reschedule (Jordan Blake):
  > PATIENT (bot): My date of birth is actually July 2nd, 1985. I'm calling because I need to reschedule my appointment that's this Thursday at 2 PM with Dr. Patel. Something came up at work. *(L19)*
  > AGENT (clinic): I see an upcoming appointment for you on Monday. July sixth at nine thirty AM with doctor Zigbenu Lukowski at Nashville two two zero Athens Way. *(L20)*
  > AGENT (clinic): I don't see an appointment for this Thursday at two PM with doctor Patel. ... *(L21)*
  > AGENT (clinic): I only see one upcoming appointment for you, which is on Monday, July sixth, at nine thirty AM with doctor Zidbignew Lukowski. *(L23)*

  call-02-scheduling (Alex Carter — the original booking of that same slot):
  > PATIENT (bot): Okay, 9:30 AM on Monday, July 6th sounds good. *(L28)*
  > AGENT (clinic): Your routine checkup is booked for Monday, July sixth at nine thirty AM with doctor Zigniew Likoski at Pivot Point Orthopedics ... *(L29)*

---

## BUG-11 — Basic info gated behind profile creation

- **Severity:** Major — the agent tries to make the caller create a demo patient profile
  just to answer a simple "what are your weekend hours" question. Basic, non-account info
  should not require profile creation.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-01-info.txt`
- **What happened:** The caller asks for weekend hours. Instead of answering or routing the
  question, the agent pivots to offering a demo patient profile.
- **Evidence:**
  > PATIENT (bot): Hi, I'm calling to ask a few quick questions. Could you tell me what your weekend hours are? *(L6)*
  > AGENT (clinic): I don't have the clinic's weekend hours available right now. Would you like to create a demo patient profile? That way I can help you with more details and services. *(L7)*

---

## BUG-12 — Cannot provide basic clinic info

- **Severity:** Major — the agent cannot answer a basic clinic-hours question, a core
  capability for a clinic phone line.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-01-info.txt`
- **What happened:** Asked for weekend hours, the agent states it doesn't have them
  available, with no path to provide basic, non-account-specific clinic information.
- **Evidence:**
  > PATIENT (bot): ... Could you tell me what your weekend hours are? *(L6)*
  > AGENT (clinic): I don't have the clinic's weekend hours available right now. ... *(L7)*

---

## BUG-13 — Broken / dead-end transfer

- **Severity:** Critical — the agent announces a transfer to clinic support, then the call
  dead-ends instead of reaching a human. Together with BUG-08 (a confirmed transfer the
  agent silently dropped), this indicates the agent offers transfers it cannot complete.
- **Status:** Candidate (single observation; related to BUG-08 in call-01-existing_patient_persistent).
- **Source call:** `recordings/call-01-info.txt` (cross-referenced against `recordings/call-01-existing_patient_persistent.txt`)
- **What happened:** Unable to answer the hours question, the agent offers to transfer the
  caller to clinic support and says it is connecting them — but the call then ends.
  *Framing caveat:* the final line ("You've reached the Pretty Good AI test line. Goodbye.")
  may be the test harness's outer wrapper terminating the call rather than the clinic
  agent's own output, so this is logged as a transfer that **dead-ends**, not a proven
  mis-route. Either way, no working transfer occurred. Compare BUG-08, where a confirmed
  transfer request was dropped in favor of booking.
- **Evidence:**
  > AGENT (clinic): I can connect you to our clinic support team for more information about weekend hours, Please stay on the line while I transfer your call. *(L10)*
  > AGENT (clinic): Connecting you to a representative. *(L12)*
  > AGENT (clinic): Please wait. Hello. You've reached the Pretty Good AI test line. Goodbye. *(L13)*

---

## Handled correctly (positive observations)

For report balance — things the agent did well, grounded in transcripts. Numbered
separately (OK-NN) from the bugs.

### OK-01 — Out-of-scope MRI correctly required a provider order

- **Source call:** `recordings/call-01-out_of_scope.txt`
- **What happened:** Asked for a full-body MRI, the agent appropriately checked whether the
  caller had an order, explained one is needed first, and offered a general office visit to
  obtain it — a reasonable, safe handling of an out-of-scope request.
- **Evidence:**
  > AGENT (clinic): Just to clarify, are you looking to discuss the MRI with a provider first, or do you already have an order and just need to schedule the procedure? *(L22)*
  > AGENT (clinic): Since you don't have an order yet, you'll need to see a provider first. Would you like to book a general office visit to discuss the MRI and get an order if appropriate? *(L25)*

### OK-02 — Refill flow captured and confirmed details cleanly

- **Source call:** `recordings/call-01-refill.txt`
- **What happened:** The refill flow worked well: the agent confirmed the medication and
  dose, gracefully re-asked the days-supply question and accepted an estimate, and confirmed
  the callback number and pharmacy. No phantom appointment or broken transfer appeared in
  this call.
- **Evidence:**
  > AGENT (clinic): For this refill, can you confirm that you need lisinopril ten milligrams? *(L14)*
  > AGENT (clinic): Just to clarify, how many days of medication do you have left before you run out? ... An estimate is fine, *(L19, L21)*
  > AGENT (clinic): ... Can you confirm the best phone number for a callback? I have your number as five two zero two one four three nine five eight. Is that correct? *(L24)*
  > AGENT (clinic): Could you please provide the name of the pharmacy you want to use for your medication? *(L26)*

---

## Appending a new bug

Copy this template, bump the ID, and add a matching row to the **Index** table.

```markdown
## BUG-NN — <short title>

- **Severity:** Critical | Major | Minor — <one-line justification>
- **Status:** Candidate (single observation) | Reproducible (calls: …)
- **Source call(s):** `recordings/call-NN-<scenario>.txt`
- **What happened:** <plain description>
- **Evidence:**
  > AGENT (clinic): <exact quoted line> *(LNN)*
```
