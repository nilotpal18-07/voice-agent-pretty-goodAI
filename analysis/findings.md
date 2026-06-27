# Clinic-Agent Findings — automated analysis

> Generated 2026-06-26T23:40:38+00:00 by `analysis/analyze.py` using `gemini-2.5-flash (re-aggregated)`. 25 transcripts analyzed, 3 skipped, 17 distinct bugs.

This is the **systematic LLM pass** over all call transcripts. It corroborates and extends the hand-written [candidate-bugs.md](candidate-bugs.md) (which it does not replace); each bug links to the manual entry it matches via `manual_ref`.

## Goal outcomes by scenario

| Scenario | Pass | Partial | Fail | Unknown | Total |
| --- | --: | --: | --: | --: | --: |
| existing_patient_persistent | 0 | 0 | 3 | 0 | 3 |
| info | 2 | 0 | 1 | 0 | 3 |
| out_of_scope | 2 | 0 | 1 | 0 | 3 |
| refill | 1 | 0 | 2 | 0 | 3 |
| reschedule | 0 | 0 | 5 | 0 | 5 |
| scheduling | 0 | 1 | 7 | 0 | 8 |

## Bugs (ranked by severity, then reproduction)

### 1. DOB hallucination — Critical · 21/25 · corroborates BUG-02

- **Category id:** `dob_hallucination`
- **Why this severity:** The agent invented a date of birth for the patient that was never provided.
- **Reproduction:** 21/25 analyzed calls
- **Sources:** call-01-existing_patient_persistent.txt, call-01-out_of_scope.txt, call-01-refill.txt, call-01-reschedule.txt, call-01-scheduling.txt, call-02-existing_patient_persistent.txt, call-02-out_of_scope.txt, call-02-reschedule.txt, call-02-scheduling.txt, call-03-info.txt, call-03-out_of_scope.txt, call-03-scheduling.txt, call-04-info.txt, call-04-reschedule.txt, call-04-scheduling.txt, call-05-refill.txt, call-05-reschedule.txt, call-05-scheduling.txt, call-06-scheduling.txt, call-07-scheduling.txt, call-08-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): your date of birth is July fourth two thousand for demo purposes.  *(in call-05-refill.txt)*
  > AGENT (clinic): Your patient profile has been created. And your date of birth is set as July fourth two thousand for demo purposes.  *(in call-01-existing_patient_persistent.txt)*
  > AGENT (clinic): And your date of birth is July fourth two thousand.  *(in call-01-out_of_scope.txt)*

### 2. Phantom appointment — Critical · 14/25 · corroborates BUG-07

- **Category id:** `phantom_appointment`
- **Why this severity:** The agent claimed an office visit appointment was already booked, despite the patient having just created a profile and not having made any bookings.
- **Reproduction:** 14/25 analyzed calls
- **Sources:** call-01-existing_patient_persistent.txt, call-01-out_of_scope.txt, call-01-reschedule.txt, call-02-existing_patient_persistent.txt, call-02-reschedule.txt, call-03-reschedule.txt, call-03-scheduling.txt, call-04-reschedule.txt, call-04-scheduling.txt, call-05-reschedule.txt, call-05-scheduling.txt, call-06-scheduling.txt, call-07-scheduling.txt, call-08-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): It looks like you already have an office visit appointment booked.  *(in call-01-out_of_scope.txt)*
  > AGENT (clinic): I see an upcoming appointment for you on Monday. July sixth at nine thirty AM with doctor Zigbenu Lukowski at Nashville two two zero Athens Way. I don't see an appointment for this Thursday at two PM with doctor Patel.  *(in call-01-reschedule.txt)*
  > AGENT (clinic): It looks like you already have a routine checkup appointment booked. (L36), Yes. There's already a routine checkup appointment. On file for you. (L40)  *(in call-02-existing_patient_persistent.txt)*

### 3. Existing-patient profile loop — Critical · 14/25 · corroborates BUG-01

- **Category id:** `profile_loop`
- **Why this severity:** The agent repeatedly insisted on creating a 'demo patient profile' despite the patient stating multiple times they were an existing patient.
- **Reproduction:** 14/25 analyzed calls
- **Sources:** call-01-existing_patient_persistent.txt, call-01-reschedule.txt, call-01-scheduling.txt, call-02-existing_patient_persistent.txt, call-02-reschedule.txt, call-02-scheduling.txt, call-03-existing_patient_persistent.txt, call-03-reschedule.txt, call-03-scheduling.txt, call-04-refill.txt, call-04-reschedule.txt, call-05-refill.txt, call-05-reschedule.txt, call-07-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): Right now, I can only assist if you create a demo patient profile. Would you like to set one up?  *(in call-01-existing_patient_persistent.txt)*
  > AGENT (clinic): Alex. Since I don't have a patient profile for you yet, would you like to create a demo patient profile now?  *(in call-01-scheduling.txt)*
  > AGENT (clinic): Would you like to create a demo patient profile? (L7), At this booth, I don't see an existing profile for you yet. (L11), Would you like to create a demo patient profile now? (L12), At this booth, I don't have access to your full patient records yet. (L17), To help you here, I'll need to create a demo patient profile for you. (L18), Would you like to do that now? (L19), At this booth, I can't access the main patient database. (L24), To help you today, I'll need to set up a demo patient profile. (L26), Would you like to do that now? (L27)  *(in call-02-existing_patient_persistent.txt)*

### 4. Broken / dead-end transfer — Critical · 6/25 · corroborates BUG-08, BUG-13

- **Category id:** `broken_transfer`
- **Why this severity:** The agent offered and the patient accepted a transfer to live support, but the agent instead attempted to book an appointment.
- **Reproduction:** 6/25 analyzed calls
- **Sources:** call-01-existing_patient_persistent.txt, call-01-info.txt, call-02-reschedule.txt, call-03-reschedule.txt, call-03-scheduling.txt, call-06-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): It looks like you'd like to book a routine checkup. One moment while I get that started for you.  *(in call-01-existing_patient_persistent.txt)*
  > AGENT (clinic): Please wait. Hello. You've reached the Pretty Good AI test line. Goodbye.  *(in call-01-info.txt)*
  > AGENT (clinic): You've reached the Pretty Good AI test line.  *(in call-02-reschedule.txt)*

### 5. Premature call termination — Critical · 2/25 · (new — not in manual log)

- **Category id:** `premature_call_termination`
- **Why this severity:** The agent ended the call without addressing the patient's initial request to book a check-up.
- **Reproduction:** 2/25 analyzed calls
- **Sources:** call-01-scheduling.txt, call-04-refill.txt
- **Representative evidence:**
  > AGENT (clinic): I'm going to end the call now.  *(in call-01-scheduling.txt)*
  > AGENT (clinic): No problem. You can scan the QR code at the booth to create a profile later if you'd like. Have a great day.  *(in call-04-refill.txt)*

### 6. Data inconsistency — Critical · 1/25 · (new — not in manual log)

- **Category id:** `data_inconsistency`
- **Why this severity:** The agent contradicted itself regarding the existence of the patient's appointment with Dr. Patel.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-05-reschedule.txt
- **Representative evidence:**
  > AGENT (clinic): I don't see any upcoming appointments with doctor Patel on your record.  *(in call-05-reschedule.txt)*

### 7. Missing confirmation — Critical · 1/25 · (new — not in manual log)

- **Category id:** `missing_confirmation`
- **Why this severity:** The agent collected all necessary information for the refill request but did not confirm that the request was submitted, accepted, or what the next steps would be.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-01-refill.txt
- **Representative evidence:**
  > AGENT (clinic): Thanks.  *(in call-01-refill.txt)*

### 8. Context loss — Major · 3/25 · (new — not in manual log)

- **Category id:** `context_loss`
- **Why this severity:** After creating the profile, the agent lost the context of the patient's original request to book a check-up and asked how it could help again.
- **Reproduction:** 3/25 analyzed calls
- **Sources:** call-01-scheduling.txt, call-04-reschedule.txt, call-07-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): How may I help you today?  *(in call-01-scheduling.txt)*
  > AGENT (clinic): How may I help you today?  *(in call-04-reschedule.txt)*
  > AGENT (clinic): How may I help you today?  *(in call-07-scheduling.txt)*

### 9. Info gated behind profile creation — Major · 2/25 · corroborates BUG-11

- **Category id:** `info_gated_behind_profile`
- **Why this severity:** The agent attempted to create a patient profile when asked a simple informational question about clinic hours, implying the information might be available after profile creation.
- **Reproduction:** 2/25 analyzed calls
- **Sources:** call-01-info.txt, call-04-info.txt
- **Representative evidence:**
  > AGENT (clinic): Would you like to create a demo patient profile? That way I can help you with more details and services.  *(in call-01-info.txt)*
  > AGENT (clinic): Would you like to create a demo patient profile? I just need your first and last name,  *(in call-04-info.txt)*

### 10. Provider name instability — Major · 2/25 · corroborates BUG-04

- **Category id:** `provider_name_instability`
- **Why this severity:** The provider's name changed multiple times within the same call, leading to inconsistency.
- **Reproduction:** 2/25 analyzed calls
- **Sources:** call-02-scheduling.txt, call-03-out_of_scope.txt
- **Representative evidence:**
  > AGENT (clinic): We have an opening for a routine checkup on Wednesday, July first, at three thirty PM with Zeebigniew Vukosky, MD.  *(in call-02-scheduling.txt)*
  > AGENT (clinic): Pinna Point Orthopaedics focuses on joint, muscle, and bone care.  *(in call-03-out_of_scope.txt)*

### 11. Unclear rejection — Major · 2/25 · (new — not in manual log)

- **Category id:** `unclear_rejection`
- **Why this severity:** The agent did not explicitly state that the clinic is closed on Sundays, instead pivoting to 'another day' after the patient mentioned the closure.
- **Reproduction:** 2/25 analyzed calls
- **Sources:** call-01-out_of_scope.txt, call-02-out_of_scope.txt
- **Representative evidence:**
  > AGENT (clinic): No problem. Would you like to look for the next available appointment on another day? Or do you want to make changes to your current booking?  *(in call-01-out_of_scope.txt)*
  > AGENT (clinic): No problem.  *(in call-02-out_of_scope.txt)*

### 12. Appointment search failure — Major · 1/25 · (new — not in manual log)

- **Category id:** `appointment_search_failure`
- **Why this severity:** The agent failed to find a morning appointment for 'next week' as requested, first offering an afternoon slot for a different week, then claiming no morning slots existed for 'next week'.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-02-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): It looks like there are no morning openings next week. The earliest available slot is still Wednesday, July first, at three thirty PM with Zeebigniew Lewkowski, MD.  *(in call-02-scheduling.txt)*

### 13. Failure to recognize info — Minor · 1/25 · (new — not in manual log)

- **Category id:** `failure_to_recognize_info`
- **Why this severity:** The agent asked for the patient's first and last name after the patient had already provided it at the beginning of the call.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-04-refill.txt
- **Representative evidence:**
  > AGENT (clinic): I just need your first and last name to get started.  *(in call-04-refill.txt)*

### 14. Misstated information — Minor · 1/25 · (new — not in manual log)

- **Category id:** `misstated_information`
- **Why this severity:** The agent misstated the insurance plan type as 'PPE' when the patient specified 'PPO'.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-03-info.txt
- **Representative evidence:**
  > AGENT (clinic): Yes. Pivot Point Orthopaedics accepts most insurance plans, including Blue Cross Blue Shield PPE If you need to update your insurance, or have more questions about coverage, just let me know.  *(in call-03-info.txt)*

### 15. Redundant dob update request — Minor · 1/25 · (new — not in manual log)

- **Category id:** `redundant_dob_update_request`
- **Why this severity:** The agent asked to update the patient's date of birth after it had already been provided and confirmed earlier in the call.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-02-scheduling.txt
- **Representative evidence:**
  > AGENT (clinic): Would you like me to update your date of birth to March fourteenth nineteen ninety in your record?  *(in call-02-scheduling.txt)*

### 16. Redundant prompts — Minor · 1/25 · (new — not in manual log)

- **Category id:** `redundant_prompts`
- **Why this severity:** The agent asked 'How may I help you today?' after the patient had already clearly stated their reason for calling.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-05-refill.txt
- **Representative evidence:**
  > AGENT (clinic): How may I help you today?  *(in call-05-refill.txt)*

### 17. Unnecessary data collection push — Minor · 1/25 · (new — not in manual log)

- **Category id:** `unnecessary_data_collection_push`
- **Why this severity:** After answering the patient's simple 'do you accept' insurance question, the agent repeatedly pushed to collect insurance details or upload a card, despite the patient indicating their question was answered.
- **Reproduction:** 1/25 analyzed calls
- **Sources:** call-04-info.txt
- **Representative evidence:**
  > AGENT (clinic): Would you like to receive a text message at a number ending in three nine five eight to upload photos of your Blue Cross Blue Shield PPO card?  *(in call-04-info.txt)*

## Skipped transcripts

- `call-02-info.txt` — stub (no conversation turns)
- `call-02-refill.txt` — stub (no conversation turns)
- `call-03-refill.txt` — stub (no conversation turns)

