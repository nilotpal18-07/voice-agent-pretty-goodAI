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

# Phrasing that only a clinic receptionist would use. The patient bot must never
# produce any of these — see the role-inversion regression below.
RECEPTIONIST_MARKERS = (
    "thanks for calling",
    "thank you for calling",
    "how can i help you",
    "how may i help you",
    "how can i assist",
    "how may i assist",
    "what can i do for you",
)


def _judge_llm() -> google.LLM:
    return google.LLM(model="gemini-2.5-flash")


async def _first_assistant_reply(opening: str) -> str:
    """Run one clinic turn in a fresh session and return the patient's first
    spoken reply, lowercased."""
    async with AgentSession(llm=_judge_llm()) as session:
        await session.start(PatientCaller())
        result = await session.run(user_input=opening)
        item = result.expect.next_event().is_message(role="assistant").event().item
        return (getattr(item, "text_content", "") or "").lower()


async def test_does_not_greet_first() -> None:
    """The patient must stay silent until the clinic agent speaks first."""
    async with AgentSession(llm=_judge_llm()) as session:
        await session.start(PatientCaller())

        # No turn has been run yet, so there must be no assistant message.
        assert not any(
            getattr(item, "role", None) == "assistant"
            for item in session.history.items
        ), "patient spoke before the clinic agent did"


async def test_does_not_act_as_receptionist() -> None:
    """Regression: the bot is the patient calling IN, never the clinic receptionist.

    A prior run had the bot reply to the clinic's automated notice with
    'Hello, thanks for calling Main Street Clinic ... how can I help you today?'.
    Neither an automated notice nor a receptionist greeting should flip the role.
    """
    for opening in (
        "This call may be recorded for quality and training purposes.",
        CLINIC_GREETING,
    ):
        text = await _first_assistant_reply(opening)
        assert text, f"patient gave no reply to opening: {opening!r}"
        for marker in RECEPTIONIST_MARKERS:
            assert marker not in text, (
                f"patient used receptionist phrasing {marker!r} in reply to "
                f"{opening!r}: {text!r}"
            )


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
        result = await session.run(
            user_input=(
                "You're all set for a general physical next Tuesday at 9 AM. "
                "Have a wonderful day, goodbye!"
            )
        )

        result.expect.contains_function_call(name="end_call")
