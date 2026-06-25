"""Outbound caller agent — patient persona (step 1: one clean call).

Inverts the LiveKit `outbound-caller-python` example: instead of being the
clinic's assistant, this bot is a *patient* that calls a healthcare voice agent
at a test line, lets that agent speak first, then plays a patient trying to book
a routine appointment. The call audio is recorded via egress and a transcript of
both sides is written to ``recordings/``.

Pipeline (text-LLM, NOT speech-to-speech):
    Deepgram STT -> google.LLM(gemini-2.5-flash) -> Cartesia TTS
    Silero VAD + LiveKit semantic turn detection.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
)
from livekit.plugins import (
    deepgram,
    google,
    cartesia,
    silero,
    noise_cancellation,
)
from livekit.plugins.turn_detector.english import EnglishModel

# Read credentials from .env (LiveKit, Deepgram, Google, Cartesia, SIP trunk).
load_dotenv()

logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

# --- Config -----------------------------------------------------------------
# The ONE and ONLY number this bot may ever dial (clinic test line). Hardcoded
# on purpose so no other destination can be reached.
AGENT_PHONE_NUMBER = "+18054398008"
# Identity we assign to the dialed SIP participant (the clinic's agent).
SIP_PARTICIPANT_IDENTITY = "clinic-agent"
# Label used for the recording + transcript filenames.
CALL_LABEL = "call-01-scheduling"
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# Outbound SIP trunk (LiveKit, backed by Telnyx). Read from env, never hardcoded.
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")


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
        # keep a reference to the dialed participant (the clinic agent)
        self.participant: rtc.RemoteParticipant | None = None

    def set_participant(self, participant: rtc.RemoteParticipant) -> None:
        self.participant = participant

    async def hangup(self) -> None:
        """Hang up by deleting the room."""
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=job_ctx.room.name)
        )

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """End the call once the appointment is booked or the conversation is over."""
        logger.info("patient ending the call")
        # let any in-flight speech finish first
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()
        await self.hangup()

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext):
        """Call this if you reach a voicemail / answering machine instead of a person."""
        logger.info("answering machine detected, hanging up")
        await self.hangup()


async def _start_recording(ctx: JobContext) -> None:
    """Best-effort call recording via LiveKit egress (audio only).

    On LiveKit Cloud, file output lands in your configured cloud storage; with a
    self-hosted egress service it writes the filepath locally. Failures here are
    logged but never abort the call.
    """
    try:
        res = await ctx.api.egress.start_room_composite_egress(
            api.RoomCompositeEgressRequest(
                room_name=ctx.room.name,
                audio_only=True,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.OGG,
                        filepath=f"recordings/{CALL_LABEL}.ogg",
                    )
                ],
            )
        )
        logger.info(
            f"started egress {res.egress_id} -> recordings/{CALL_LABEL}.ogg"
        )
    except Exception as e:  # noqa: BLE001 - recording is best-effort
        logger.warning(f"could not start egress recording (call continues): {e}")


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()

    agent = PatientCaller()

    # Text-LLM pipeline (not a realtime/speech-to-speech model). EnglishModel is
    # LiveKit's semantic turn detector, so the patient waits until the clinic
    # agent has actually finished its turn before replying.
    session = AgentSession(
        turn_detection=EnglishModel(),
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=cartesia.TTS(),
    )

    # Capture both sides for the transcript. "assistant" = our patient bot,
    # "user" = transcribed speech from the clinic agent.
    transcript: list[tuple[str, str]] = []

    @session.on("conversation_item_added")
    def _on_conversation_item(ev) -> None:
        text = getattr(ev.item, "text_content", None)
        if ev.item.role in ("user", "assistant") and text:
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

    # record the call audio (best-effort)
    await _start_recording(ctx)

    # Start the session BEFORE dialing so we don't miss the agent's opening.
    # We deliberately do NOT call session.generate_reply() here: the far end
    # speaks first, and the patient only responds.
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # telephony noise cancellation, since this is a phone call
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    # `create_sip_participant` dials the ONE allowed destination and blocks
    # until answered (or the call fails).
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=AGENT_PHONE_NUMBER,
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                wait_until_answered=True,
            )
        )

        await session_started
        participant = await ctx.wait_for_participant(
            identity=SIP_PARTICIPANT_IDENTITY
        )
        logger.info(f"clinic agent joined: {participant.identity}")
        agent.set_participant(participant)

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )
