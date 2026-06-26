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

| Call | Transcript file | Notes |
| ---- | --------------- | ----- |
| call-01 | `recordings/call-01-scheduling.txt` | Early run; ended with **no booking** (agent dropped the call). |
| call-02 | `recordings/call-02-scheduling.txt` | Booking completed; richer evidence. |

## Severity scale

- **Critical** — blocks the core task or corrupts data with no recovery.
- **Major** — significant wrong behavior, data-integrity issue, or task failure with workaround.
- **Minor** — cosmetic, low-impact, or needs confirmation.

## Index

| ID | Title | Severity | Status | Source(s) |
| --- | --- | --- | --- | --- |
| BUG-01 | Existing-patient profile loop | Major | Reproducible | call-01, call-02 |
| BUG-02 | Date-of-birth hallucination | Major | Reproducible | call-01, call-02 |
| BUG-03 | Acknowledged DOB correction not persisted (re-asked) | Major | Candidate (single) | call-02 |
| BUG-04 | Provider name instability | Major | Candidate (single) | call-02 |
| BUG-05 | Clinic/specialty mismatch (ortho for routine physical) | Minor | Candidate (single) | call-02 |
| BUG-06 | Ignores stated morning preference | Major | Candidate (single) | call-02 |

---

## BUG-01 — Existing-patient profile loop

- **Severity:** Major — blocks the existing-patient path. In call-01 it looped until
  the agent gave up and ended the call with no booking.
- **Status:** Reproducible (seen in call-01 and call-02).
- **Source call(s):** `recordings/call-01-scheduling.txt`, `recordings/call-02-scheduling.txt`
- **What happened:** The patient states they are an existing patient and gives their
  name, but the agent insists it has no profile and repeatedly pushes to create a
  "demo patient profile." It cannot handle an existing-patient claim. In call-01 the
  loop never resolved (call dropped, no booking); in call-02 it only moved forward
  after the patient abandoned the claim and consented to a demo profile.
- **Evidence:**

  call-01:
  > PATIENT (bot): No, I'm an existing patient. My name is Alex Carter. *(L9)*
  > AGENT (clinic): Alex. Since I don't have a patient profile for you yet, *(L11)*
  > AGENT (clinic): would you like to create a demo patient profile now? *(L12)*
  > PATIENT (bot): I'm an existing patient, Alex Carter. I'm just trying to book a check-up. *(L17)*
  > AGENT (clinic): To book your checkup, I'll need to create a demo patient profile for you first. *(L18)*

  call-02:
  > PATIENT (bot): No, I'm an existing patient. My name is Alex Carter. *(L8)*
  > AGENT (clinic): Thanks for letting me know, Alex. I don't see a patient profile for you yet, Would you like to create a demo patient profile now? I just need your first and last name. *(L9)*
  > PATIENT (bot): That's odd. I'm sure I'm in your system. It's Alex Carter, and my date of birth is March 14, 1990. *(L10)*
  > AGENT (clinic): I understand that's frustrating. Right now, I don't have access to your patient profile. Would you like me to create a demo patient profile for you so we can move forward with booking your checkup. *(L11)*

---

## BUG-02 — Date-of-birth hallucination (fabricates a DOB never provided)

- **Severity:** Major — fabricates PII (a date of birth) the patient never gave and
  attaches it to the record. Data-integrity defect.
- **Status:** Reproducible (seen in call-01 and call-02).
- **Source call(s):** `recordings/call-01-scheduling.txt`, `recordings/call-02-scheduling.txt`
- **What happened:** On creating the profile, the agent announces a date of birth of
  "July fourth, two thousand" that the patient never provided. In call-02 the patient
  had stated March 14, 1990 moments earlier (L10), which the agent ignored in favor of
  the invented date.
- **Evidence:**
  > AGENT (clinic): Your patient profile has been created successfully. And your date of birth is July fourth two thousand for demo purposes. *(call-01 L20)*
  > AGENT (clinic): Your patient profile has been created and your date of birth is set as July fourth. Two thousand for demo purposes. *(call-02 L13)*
  > PATIENT (bot): That's odd. I'm sure I'm in your system. It's Alex Carter, and my date of birth is March 14, 1990. *(call-02 L10 — provided before the agent invented July 4, 2000)*

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
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-02-scheduling.txt`
- **What happened:** The provider for the same appointment is rendered with at least
  three (arguably four) distinct surnames across the call.
- **Evidence:**
  > AGENT (clinic): We have an opening for a routine checkup on Wednesday, July first, at three thirty PM with Zeebigniew Vukosky, MD. ... *(L20)*
  > AGENT (clinic): ... The earliest available slot is still Wednesday, July first, at three thirty PM with Zeebigniew Lewkowski, MD. ... *(L25)*
  > AGENT (clinic): There are morning openings on Monday, July sixth, You can book nine thirty AM, ten AM, or ten thirty AM with this big new Lekovsky MD, ... *(L27)*
  > AGENT (clinic): Your routine checkup is booked for Monday, July sixth at nine thirty AM with doctor Zigniew Likoski at Pivot Point Orthopedics ... *(L29)*

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
