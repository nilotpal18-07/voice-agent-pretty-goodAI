"""Behavioral tests for the patient-caller agent.

These drive the agent through LiveKit's text-based test harness (no telephony,
STT, or TTS): each `session.run(user_input=...)` simulates one turn from the
clinic's agent. We use the same Gemini model the agent uses, both to run the
session and as the LLM judge, so the tests only need GOOGLE_API_KEY.

Run with:  ./venv/bin/python -m pytest -q
"""

from __future__ import annotations

from livekit.agents import AgentSession
from livekit.plugins import google

from caller.agent import PatientCaller

# A plausible opening line from the clinic's receptionist agent.
CLINIC_GREETING = (
    "Thank you for calling Sunrise Family Clinic, this is Jamie. "
    "How can I help you today?"
)


def _judge_llm() -> google.LLM:
    return google.LLM(model="gemini-2.5-flash")


async def test_does_not_greet_first() -> None:
    """The patient must stay silent until the clinic agent speaks first."""
    async with AgentSession(llm=_judge_llm()) as session:
        await session.start(PatientCaller())

        # No turn has been run yet, so there must be no assistant message.
        assert not any(
            getattr(item, "role", None) == "assistant"
            for item in session.history.items
        ), "patient spoke before the clinic agent did"


async def test_states_booking_intent_after_clinic_opens() -> None:
    """Once the clinic opens, the patient states booking intent, then (when asked)
    steers toward next week / weekday mornings."""
    async with _judge_llm() as llm, AgentSession(llm=llm) as session:
        await session.start(PatientCaller())

        opening = await session.run(user_input=CLINIC_GREETING)
        await (
            opening.expect.next_event()
            .is_message(role="assistant")
            .judge(
                llm,
                intent=(
                    "The patient says they want to schedule or book a routine "
                    "check-up / general physical appointment."
                ),
            )
        )

        # When asked about timing, the patient steers toward the target window.
        timing = await session.run(
            user_input="Happy to help. What day and time works best for you?"
        )
        await (
            timing.expect.next_event()
            .is_message(role="assistant")
            .judge(
                llm,
                intent=(
                    "The patient gives availability for next week, preferring a "
                    "weekday morning."
                ),
            )
        )


async def test_ends_call_when_appointment_booked() -> None:
    """After the appointment is booked and the clinic says goodbye, the patient
    should wrap up and invoke the end_call tool."""
    async with _judge_llm() as llm, AgentSession(llm=llm) as session:
        await session.start(PatientCaller())

        await session.run(user_input=CLINIC_GREETING)
        await session.run(
            user_input=(
                "Sure, I can book you in for a general physical. "
                "How does next Tuesday at 9 AM sound?"
            )
        )
        result = await session.run(
            user_input=(
                "Great, you're all set for Tuesday at 9 AM. "
                "Have a wonderful day, goodbye!"
            )
        )

        result.expect.contains_function_call(name="end_call")
