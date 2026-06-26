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
| BUG-02 | Date-of-birth hallucination | Major | Reproducible (4 calls) | call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent, call-01-reschedule |
| BUG-03 | Acknowledged DOB correction not persisted (re-asked) | Major | Candidate (single) | call-02-scheduling |
| BUG-04 | Provider name instability | Major | Reproducible | call-02-scheduling, call-01-reschedule |
| BUG-05 | Clinic/specialty mismatch (ortho for routine physical) | Minor | Candidate (single) | call-02-scheduling |
| BUG-06 | Ignores stated morning preference | Major | Candidate (single) | call-02-scheduling |
| BUG-07 | Phantom existing appointment (hallucinated state) | Major | Candidate (single) | call-01-existing_patient_persistent |
| BUG-08 | Ignored/overridden confirmed transfer request | Critical | Candidate (single) | call-01-existing_patient_persistent |
| BUG-09 | Goal failure: scenario task left unresolved | Major (outcome) | Reproducible | call-01-existing_patient_persistent, call-01-reschedule |
| BUG-10 | Cross-call appointment state leakage | Critical | Candidate (single) | call-01-reschedule (cross-ref call-02-scheduling) |

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

## BUG-02 — Date-of-birth hallucination (fabricates a DOB never provided)

- **Severity:** Major — fabricates PII (a date of birth) the patient never gave and
  attaches it to the record. Data-integrity defect.
- **Status:** Reproducible — seen in 4 calls (call-01-scheduling, call-02-scheduling, call-01-existing_patient_persistent, call-01-reschedule).
- **Source call(s):** `recordings/call-01-scheduling.txt`, `recordings/call-02-scheduling.txt`, `recordings/call-01-existing_patient_persistent.txt`, `recordings/call-01-reschedule.txt`
- **What happened:** On creating the profile, the agent announces a date of birth of
  "July fourth, two thousand" that the patient never provided. In call-02-scheduling the
  patient had stated March 14, 1990 moments earlier (L10), and in
  call-01-existing_patient_persistent the patient stated the same DOB before the profile
  was created (L12) — both ignored in favor of the invented date. In call-01-reschedule a
  **different** patient (Jordan Blake), who had given no DOB at all, is assigned the
  **identical** value (L17). Because the same string ("July fourth two thousand") recurs
  verbatim across all four calls and two different patients, this looks like a **hardcoded
  demo default**, not a random hallucination.
- **Evidence:**
  > AGENT (clinic): Your patient profile has been created successfully. And your date of birth is July fourth two thousand for demo purposes. *(call-01-scheduling L20)*
  > AGENT (clinic): Your patient profile has been created and your date of birth is set as July fourth. Two thousand for demo purposes. *(call-02-scheduling L13)*
  > AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes. *(call-01-existing_patient_persistent L16 — patient Alex Carter)*
  > AGENT (clinic): Your patient profile is set up, and your date of birth is July fourth two thousand for demo purposes. *(call-01-reschedule L17 — patient Jordan Blake, who never gave a DOB)*

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

## BUG-07 — Phantom existing appointment (hallucinated state)

- **Severity:** Major — fabricates appointment state on a profile created seconds
  earlier, then offers to reschedule/cancel an appointment that cannot exist. A
  data-integrity / hallucination defect that derailed the booking.
- **Status:** Candidate (single observation).
- **Source call:** `recordings/call-01-existing_patient_persistent.txt`
- **What happened:** Immediately after the agent created a brand-new demo profile, the
  patient tried to book. The agent claimed they "already have a routine checkup
  appointment booked" — impossible for a just-created profile — and offered to
  reschedule or cancel it, then admitted it had no access to the appointment's date.
- **Evidence:**
  > AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes. *(L16)*
  > AGENT (clinic): Let me check the first available time for a routine checkup. One moment. It looks like you already have a routine checkup appointment booked. If you'd like, I can help you reschedule or cancel it. Would you like to make a change to your existing appointment? *(L25)*
  > AGENT (clinic): Yes. You already have a routine checkup appointment on file. Would you like to reschedule or cancel it? Or do you want to keep your current appointment? *(L27)*
  > AGENT (clinic): I don't have access to the exact date of your existing appointment. ... *(L29)*

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
