"""Sequential batch runner for outbound patient-bot calls.

Drives ONE long-running ``outbound-caller`` worker: it dispatches calls one at a
time, passing the scenario id in each dispatch's job metadata, and waits for each
call to finish before starting the next. No queue, no parallelism — a clean
sequential driver, on purpose (these are real PSTN calls to a single test line, so
overlapping calls would muddy results).

The only number ever dialed is the hardcoded clinic test line in ``caller.agent``;
this runner never sees or sets a phone number. LiveKit creds come from ``.env``.

Prereq — start ONE worker in another terminal and leave it running:

    python -m caller.agent dev

Then run a batch (default plan = 2x each of the 6 scenarios = 12 calls):

    python -m caller.batch_runner
    python -m caller.batch_runner --plan scheduling=3,refill=2,info=1
    python -m caller.batch_runner --per-call-timeout 240 --delay 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from livekit import api

from scenarios.scenarios import SCENARIOS

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("batch-runner")

AGENT_NAME = "outbound-caller"
RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"

# --- Tunables (override via CLI) --------------------------------------------
DEFAULT_REPEAT = 2          # runs per scenario by default -> 6 * 2 = 12 calls
PER_CALL_TIMEOUT = 240.0    # seconds before a hung call is force-ended and skipped
DELAY_BETWEEN_CALLS = 8.0   # seconds to wait between calls
POLL_INTERVAL = 4.0         # seconds between room-status polls
STARTUP_GRACE = 45.0        # seconds to wait for a dispatched call to go active
SETTLE_SECONDS = 3.0        # let the agent flush its transcript before we scan


@dataclass
class CallResult:
    index: int
    scenario_id: str
    room: str
    status: str = "pending"        # completed | timeout | no_show | error
    detail: str = ""
    transcript: str | None = None  # transcript filename, if one appeared
    turns: int = 0                 # PATIENT/AGENT lines in the transcript

    @property
    def stub(self) -> bool:
        """A reserved-but-unused transcript (call failed before any conversation)."""
        return self.transcript is not None and self.turns == 0


def _transcript_turns(path: Path) -> int:
    """Count actual conversation turns so we can flag empty/stub transcripts."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(
        1
        for line in text.splitlines()
        if line.startswith("PATIENT (bot):") or line.startswith("AGENT (clinic):")
    )


def _scenario_transcripts(scenario_id: str) -> set[str]:
    return {p.name for p in RECORDINGS_DIR.glob(f"call-*-{scenario_id}.txt")}


def build_plan(plan_arg: str | None, repeat: int) -> list[str]:
    """Expand a plan into an ordered list of scenario ids (one entry per call)."""
    if plan_arg:
        counts: dict[str, int] = {}
        for part in plan_arg.split(","):
            part = part.strip()
            if not part:
                continue
            sid, _, n = part.partition("=")
            sid = sid.strip()
            if sid not in SCENARIOS:
                raise SystemExit(
                    f"unknown scenario id {sid!r}; valid: {sorted(SCENARIOS)}"
                )
            counts[sid] = int(n) if n.strip() else 1
    else:
        counts = {sid: repeat for sid in SCENARIOS}

    plan: list[str] = []
    for sid, n in counts.items():
        plan.extend([sid] * n)
    return plan


async def _wait_for_call(
    lk: api.LiveKitAPI,
    room: str,
    *,
    per_call_timeout: float,
    startup_grace: float,
    poll_interval: float,
) -> tuple[str, float]:
    """Poll the room until the call ends. Returns (status, elapsed_seconds).

    completed = room went active (>=1 participant) then disappeared/emptied.
    no_show   = room never went active within startup_grace.
    timeout   = still running past per_call_timeout.
    """
    start = time.monotonic()
    seen_active = False
    while True:
        elapsed = time.monotonic() - start
        try:
            resp = await lk.room.list_rooms(api.ListRoomsRequest(names=[room]))
            rooms = list(resp.rooms)
        except Exception as e:  # noqa: BLE001 - transient API error; keep polling
            logger.warning(f"list_rooms failed ({e}); retrying")
            rooms = None

        if rooms is not None:
            present = bool(rooms)
            participants = rooms[0].num_participants if present else 0
            if present and participants > 0:
                seen_active = True
            if seen_active and (not present or participants == 0):
                return "completed", elapsed
            if not seen_active and elapsed > startup_grace:
                return "no_show", elapsed

        if elapsed > per_call_timeout:
            return "timeout", elapsed
        await asyncio.sleep(poll_interval)


async def _run_call(
    lk: api.LiveKitAPI,
    index: int,
    scenario_id: str,
    *,
    per_call_timeout: float,
    startup_grace: float,
    poll_interval: float,
) -> CallResult:
    room = f"batch-{scenario_id}-{index:02d}-{uuid.uuid4().hex[:6]}"
    result = CallResult(index=index, scenario_id=scenario_id, room=room)
    before = _scenario_transcripts(scenario_id)

    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room,
                metadata=json.dumps({"scenario_id": scenario_id}),
            )
        )
    except Exception as e:  # noqa: BLE001 - dispatch failed; record and move on
        result.status = "error"
        result.detail = f"dispatch failed: {e}"
        logger.error(f"[{index}] {result.detail}")
        return result

    logger.info(f"[{index}] dispatched {scenario_id} -> room {room}; waiting...")
    status, elapsed = await _wait_for_call(
        lk,
        room,
        per_call_timeout=per_call_timeout,
        startup_grace=startup_grace,
        poll_interval=poll_interval,
    )
    result.status = status
    result.detail = f"{elapsed:.0f}s"
    logger.info(f"[{index}] {scenario_id}: {status} after {elapsed:.0f}s")

    # On timeout/no_show, force-end the room so the next call can't overlap.
    if status in ("timeout", "no_show"):
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))
            logger.warning(f"[{index}] deleted room {room} to clear {status}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{index}] could not delete room {room}: {e}")

    # Let the agent's shutdown callback flush the transcript, then attribute it.
    # Sequential execution means at most one new file per scenario per call.
    await asyncio.sleep(SETTLE_SECONDS)
    new = sorted(_scenario_transcripts(scenario_id) - before)
    if new:
        result.transcript = new[-1]
        result.turns = _transcript_turns(RECORDINGS_DIR / result.transcript)
    return result


async def run_batch(
    plan: list[str],
    *,
    per_call_timeout: float,
    delay: float,
    startup_grace: float,
    poll_interval: float,
) -> list[CallResult]:
    lk = api.LiveKitAPI()
    results: list[CallResult] = []
    try:
        for i, sid in enumerate(plan, start=1):
            logger.info(f"=== call {i}/{len(plan)}: scenario {sid} ===")
            try:
                res = await _run_call(
                    lk,
                    i,
                    sid,
                    per_call_timeout=per_call_timeout,
                    startup_grace=startup_grace,
                    poll_interval=poll_interval,
                )
            except Exception as e:  # noqa: BLE001 - never let one call kill the batch
                logger.exception(f"[{i}] unexpected error")
                res = CallResult(
                    index=i, scenario_id=sid, room="-", status="error", detail=str(e)
                )
            results.append(res)
            if i < len(plan):
                await asyncio.sleep(delay)
    finally:
        await lk.aclose()
    return results


def print_summary(results: list[CallResult]) -> None:
    completed = sum(1 for r in results if r.status == "completed")
    stubs = [r for r in results if r.stub]

    logger.info("================ BATCH SUMMARY ================")
    logger.info(
        f"{'#':>2}  {'scenario':<28} {'status':<10} {'turns':>5}  "
        f"{'transcript':<34} room"
    )
    for r in results:
        flag = "  [STUB?]" if r.stub else ""
        logger.info(
            f"{r.index:>2}  {r.scenario_id:<28} {r.status:<10} {r.turns:>5}  "
            f"{str(r.transcript):<34} {r.room}{flag}"
        )
    logger.info("----------------------------------------------")
    logger.info(
        f"{len(results)} calls: {completed} completed, "
        f"{len(results) - completed} not completed; "
        f"{len(stubs)} look like empty/stub transcripts"
    )
    if stubs:
        names = ", ".join(str(r.transcript) for r in stubs)
        logger.info(f"likely failed-before-conversation stubs: {names}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Sequential batch runner for outbound patient calls."
    )
    p.add_argument(
        "--plan",
        help="comma list like 'scheduling=3,refill=2'; default: every scenario x --repeat",
    )
    p.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        help="runs per scenario when --plan is omitted (default 2 -> 12 calls)",
    )
    p.add_argument("--per-call-timeout", type=float, default=PER_CALL_TIMEOUT)
    p.add_argument("--delay", type=float, default=DELAY_BETWEEN_CALLS)
    p.add_argument("--startup-grace", type=float, default=STARTUP_GRACE)
    p.add_argument("--poll-interval", type=float, default=POLL_INTERVAL)
    args = p.parse_args()

    plan = build_plan(args.plan, args.repeat)
    logger.info(f"plan: {len(plan)} calls -> {plan}")

    results = asyncio.run(
        run_batch(
            plan,
            per_call_timeout=args.per_call_timeout,
            delay=args.delay,
            startup_grace=args.startup_grace,
            poll_interval=args.poll_interval,
        )
    )
    print_summary(results)


if __name__ == "__main__":
    main()
