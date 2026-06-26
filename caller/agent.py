"""Outbound caller agent — patient persona (step 1: one clean call).

Inverts the LiveKit `outbound-caller-python` example: instead of being the
clinic's assistant, this bot is a *patient* that calls a healthcare voice agent
at a test line, lets that agent speak first, then plays one of several patient
scenarios (selected via the SCENARIO_ID env var) from ``scenarios/scenarios.py``.

Pipeline (text-LLM, NOT speech-to-speech):
    Deepgram STT -> google.LLM(gemini-2.5-flash) -> Cartesia TTS
    Silero VAD + LiveKit audio turn detector (inference.TurnDetector).

Recording: the mixed call audio + transcript are recorded by LiveKit Cloud via
``session.start(record=True)`` and are available to play back / download from the
Cloud "Agent insights" dashboard. We *also* write a plain-text transcript of both
sides locally to ``recordings/call-NN-<scenario>.txt`` (auto-numbered per call,
so concurrent/repeat calls never overwrite each other) from conversation events.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime
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

from scenarios.scenarios import (
    DEFAULT_SCENARIO_ID,
    build_instructions,
    get_scenario,
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
# Which patient scenario to run this call. Selected via the SCENARIO_ID env var
# (e.g. `SCENARIO_ID=refill python -m caller.agent dev`), defaulting to the
# routine-scheduling persona. The scenario's id becomes the transcript label
# suffix, so files read like call-03-refill.txt.
SCENARIO_ID = os.getenv("SCENARIO_ID", DEFAULT_SCENARIO_ID)
SCENARIO = get_scenario(SCENARIO_ID)
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# Outbound SIP trunk (LiveKit, backed by Telnyx). Read from env, never hardcoded.
# Caller ID (+15202143958) comes from this trunk's configured `numbers`.
SIP_OUTBOUND_TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID")


def next_call_label(scenario: str, recordings_dir: Path) -> str:
    """Reserve and return a unique transcript label like ``call-02-<scenario>``.

    Scans ``recordings_dir`` for existing ``call-NN-<scenario>.txt`` files, takes
    the highest ``NN``, and atomically claims ``NN+1`` (zero-padded to 2 digits)
    by creating the transcript file with ``O_EXCL``. That atomic create *is* the
    lock: if a concurrent call already grabbed that number, ``O_EXCL`` fails and
    we advance to the next free number — so a batch of 10+ simultaneous calls each
    land on a distinct file. As a final guarantee under pathological contention,
    fall back to a short uuid suffix.
    """
    recordings_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^call-(\d+)-{re.escape(scenario)}\.txt$")
    highest = 0
    for path in recordings_dir.glob(f"call-*-{scenario}.txt"):
        match = pattern.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))

    for number in range(highest + 1, highest + 1001):
        label = f"call-{number:02d}-{scenario}"
        try:
            # O_EXCL makes this fail atomically if another call took the slot.
            fd = os.open(
                recordings_dir / f"{label}.txt",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            continue
        os.close(fd)
        return label

    # Pathological contention fallback: a uuid suffix guarantees uniqueness.
    label = f"call-{highest + 1:02d}-{scenario}-{uuid.uuid4().hex[:8]}"
    (recordings_dir / f"{label}.txt").touch()
    return label


# System prompt for the selected scenario. build_instructions() always layers the
# scenario's persona/goal/facts/behavior on top of the invariant role rules (the
# bot is the CALLER, never the clinic receptionist).
PATIENT_INSTRUCTIONS = build_instructions(SCENARIO)


class PatientCaller(Agent):
    """The patient. Listens first, then pursues the scenario's goal as a caller."""

    def __init__(self, instructions: str = PATIENT_INSTRUCTIONS) -> None:
        super().__init__(instructions=instructions)

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

    logger.info(f"scenario: {SCENARIO.id} — {SCENARIO.title}")

    # Reserve a unique, non-overwriting label for this call up front (atomic, so
    # concurrent calls in a batch run never collide on the same file). The
    # scenario id is the label suffix, so files read like call-03-refill.txt.
    call_label = next_call_label(SCENARIO.id, RECORDINGS_DIR)
    logger.info(f"call label: {call_label} (room {ctx.room.name})")

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
        path = RECORDINGS_DIR / f"{call_label}.txt"
        labels = {"user": "AGENT (clinic)", "assistant": "PATIENT (bot)"}
        # Room name + timestamp help correlate this transcript with the matching
        # LiveKit Cloud (Agent insights) audio recording.
        lines = [
            f"# Transcript - {call_label}",
            f"# Room: {ctx.room.name}",
            f"# Recorded: {datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
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
