"""Outbound caller agent — patient persona (step 1: one clean call).

Inverts the LiveKit `outbound-caller-python` example: instead of being the
clinic's assistant, this bot is a *patient* that calls a healthcare voice agent
at a test line, lets that agent speak first, then plays a patient trying to book
a routine appointment.

Pipeline (text-LLM, NOT speech-to-speech):
    Deepgram STT -> google.LLM(gemini-2.5-flash) -> Cartesia TTS
    Silero VAD + LiveKit audio turn detector (inference.TurnDetector).

Recording: the mixed call audio + transcript are recorded by LiveKit Cloud via
``session.start(record=True)`` and are available to play back / download from the
Cloud "Agent insights" dashboard. We *also* write a plain-text transcript of both
sides locally to ``recordings/call-01-scheduling.txt`` from conversation events.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from livekit import api
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    RunContext,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
    function_tool,
    get_job_context,
    inference,
)
from livekit.plugins import (
    cartesia,
    deepgram,
    google,
    noise_cancellation,
)

# Read credentials from .env (LiveKit, Deepgram, Google, Cartesia, SIP trunk).
load_dotenv()

logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

# --- Config -----------------------------------------------------------------
# The ONE and ONLY number this bot may ever dial (clinic test line). Hardcoded
# on purpose so no other destination can be reached.
AGENT_PHONE_NUMBER = "+18054398008"
# Identity assigned to the dialed SIP participant (the clinic's agent).
SIP_PARTICIPANT_IDENTITY = "clinic-agent"
# Label used for the local transcript filename.
CALL_LABEL = "call-01-scheduling"
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# Outbound SIP trunk (LiveKit, backed by Telnyx). Read from env, never hardcoded.
# Caller ID (+15202143958) comes from this trunk's configured `numbers`.
SIP_OUTBOUND_TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID")


# One fixed patient scenario for this step. The bot steers toward booking a
# routine check-up next week, speaks naturally, and does NOT read a script.
PATIENT_INSTRUCTIONS = """
You are Alex Carter, a patient phoning a medical clinic to book a routine
check-up. This is a real phone call and your words are spoken aloud, so talk
like a normal person on the phone: short, natural turns, a little informal,
never scripted.

YOUR GOAL: schedule a routine check-up (general physical) for sometime next
week. Drive the conversation toward getting that appointment booked. If things
drift, gently steer back to booking the check-up.

HOW TO BEHAVE:
- Do NOT speak first. Wait for the clinic's agent to greet you, then respond.
- Keep each reply short, like real phone speech. Don't monologue or over-explain.
- Answer questions naturally and stay consistent. Use this profile:
    - Name: Alex Carter
    - Date of birth: March 14, 1990
    - Reason for visit: routine annual check-up, nothing urgent
    - Availability: any weekday next week, mornings preferred
    - Existing patient, has insurance (invent plausible details if pressed)
- If they offer a time that works, accept it and confirm the details back.
- Once the appointment is booked (or it's clear it can't be), briefly thank them
  and use the end_call tool to hang up.
- If you reach a voicemail or automated menu instead of a person, use the
  detected_answering_machine tool.
"""


class PatientCaller(Agent):
    """The patient. Listens first, then steers toward booking the appointment."""

    def __init__(self) -> None:
        super().__init__(instructions=PATIENT_INSTRUCTIONS)

    async def hangup(self) -> None:
        """Hang up by deleting the room. No-ops outside a running job (e.g. tests)."""
        try:
            job_ctx = get_job_context()
        except RuntimeError:
            return
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=job_ctx.room.name)
        )

    @function_tool()
    async def end_call(self, ctx: RunContext) -> None:
        """End the call once the appointment is booked or the conversation is over."""
        logger.info("patient ending the call")
        # Let any in-flight speech finish playing before hanging up.
        await ctx.wait_for_playout()
        await self.hangup()

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext) -> None:
        """Call this if you reach a voicemail / answering machine instead of a person."""
        logger.info("answering machine detected, hanging up")
        await self.hangup()


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()

    # Text-LLM pipeline (not a realtime/speech-to-speech model). The LiveKit
    # audio turn detector (inference.TurnDetector) + Silero VAD make the patient
    # wait until the clinic agent has actually finished its turn before replying.
    session = AgentSession(
        vad=inference.VAD(model="silero"),
        stt=deepgram.STT(),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=cartesia.TTS(),
        turn_handling=TurnHandlingOptions(turn_detection=inference.TurnDetector()),
    )

    # Capture both sides for the local transcript. "assistant" = our patient bot,
    # "user" = transcribed speech from the clinic agent.
    transcript: list[tuple[str, str]] = []

    @session.on("conversation_item_added")
    def _on_conversation_item(ev) -> None:
        text = getattr(ev.item, "text_content", None)
        if getattr(ev.item, "role", None) in ("user", "assistant") and text:
            transcript.append((ev.item.role, text))

    async def write_transcript() -> None:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        path = RECORDINGS_DIR / f"{CALL_LABEL}.txt"
        labels = {"user": "AGENT (clinic)", "assistant": "PATIENT (bot)"}
        lines = [f"# Transcript - {CALL_LABEL}", ""]
        for role, text in transcript:
            lines.append(f"{labels.get(role, role)}: {text}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"wrote transcript to {path}")

    ctx.add_shutdown_callback(write_transcript)

    if not SIP_OUTBOUND_TRUNK_ID:
        logger.error("SIP_OUTBOUND_TRUNK_ID is not set in .env; cannot place the call")
        ctx.shutdown()
        return

    # Start the session BEFORE dialing so we don't miss the clinic agent's
    # opening line. record=True -> LiveKit Cloud records the mixed call audio +
    # transcript + traces (play back / download from the Agent insights tab).
    # We deliberately do NOT call session.generate_reply(): the far end (clinic)
    # speaks first, and the patient only responds.
    session_started = asyncio.create_task(
        session.start(
            agent=PatientCaller(),
            room=ctx.room,
            record=True,
            room_input_options=RoomInputOptions(
                # telephony noise cancellation, since this is a phone call
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    # `create_sip_participant` dials the ONE allowed destination through the
    # outbound trunk and blocks until answered (or the call fails).
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=SIP_OUTBOUND_TRUNK_ID,
                sip_call_to=AGENT_PHONE_NUMBER,
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                wait_until_answered=True,
            )
        )
    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()
        return

    await session_started
    participant = await ctx.wait_for_participant(identity=SIP_PARTICIPANT_IDENTITY)
    logger.info(f"clinic agent joined: {participant.identity}")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )
