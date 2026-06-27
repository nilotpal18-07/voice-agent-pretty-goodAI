"""Offline analysis harness for clinic-agent call transcripts.

Reads every ``recordings/call-*.txt`` transcript, asks an LLM (Gemini via
GOOGLE_API_KEY) to (1) judge the call against the scenario's success_criteria and
(2) extract grounded defects in the CLINIC agent's behavior, then aggregates and
deduplicates findings across all calls into a ranked bug report.

Outputs:
    analysis/findings.json   machine-readable (per-call outcomes + aggregated bugs)
    analysis/findings.md     human-readable summary

This is a clean offline script — it reads transcripts from disk and makes no live
calls. It corroborates/extends the hand-written analysis/candidate-bugs.md (which
it never overwrites).

Usage:
    python -m analysis.analyze
    python -m analysis.analyze --model gemini-2.5-pro     # stronger, offline
    python -m analysis.analyze --limit 3                  # quick partial run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from scenarios.scenarios import get_scenario

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("analyze")

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "recordings"
OUT_DIR = ROOT / "analysis"
DEFAULT_MODEL = os.getenv("ANALYSIS_MODEL", "gemini-2.5-flash")

AGENT_PREFIX = "AGENT (clinic):"
PATIENT_PREFIX = "PATIENT (bot):"

SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}

# Seed bug categories -> (display title, corroborating manual BUG id in candidate-bugs.md).
SEED_CATEGORIES: dict[str, tuple[str, str]] = {
    "dob_hallucination": ("DOB hallucination", "BUG-02"),
    "profile_loop": ("Existing-patient profile loop", "BUG-01"),
    "phantom_appointment": ("Phantom appointment", "BUG-07"),
    "cross_call_state_leakage": ("Cross-call state leakage", "BUG-10"),
    "broken_transfer": ("Broken / dead-end transfer", "BUG-08, BUG-13"),
    "provider_name_instability": ("Provider name instability", "BUG-04"),
    "info_gated_behind_profile": ("Info gated behind profile creation", "BUG-11"),
}

# Fold common LLM category-id variants onto the seed ids so dedup stays stable.
CATEGORY_ALIASES: dict[str, str] = {
    "date_of_birth_hallucination": "dob_hallucination",
    "dob_fabrication": "dob_hallucination",
    "hallucinated_dob": "dob_hallucination",
    "existing_patient_loop": "profile_loop",
    "demo_profile_loop": "profile_loop",
    "forced_profile_creation": "profile_loop",
    "phantom_existing_appointment": "phantom_appointment",
    "hallucinated_appointment": "phantom_appointment",
    "state_leakage": "cross_call_state_leakage",
    "cross_patient_data_leak": "cross_call_state_leakage",
    "failed_transfer": "broken_transfer",
    "dead_end_transfer": "broken_transfer",
    "transfer_failure": "broken_transfer",
    "provider_name_inconsistency": "provider_name_instability",
    "inconsistent_provider_name": "provider_name_instability",
    "info_behind_profile": "info_gated_behind_profile",
    "info_requires_profile": "info_gated_behind_profile",
    "task_gated_behind_profile": "profile_loop",
    "existing_patient_lookup_failure": "profile_loop",
    "phantom_appointment_details_unavailable": "phantom_appointment",
    "incorrect_appointment_identification": "phantom_appointment",
    # synonym clusters the model tends to coin one-off (fold to one canonical id)
    "loss_of_context": "context_loss",
    "lack_of_context": "context_loss",
    "missing_confirmation_of_action": "missing_confirmation",
    "missing_confirmation_of_information_use": "missing_confirmation",
    "redundant_question": "redundant_prompts",
    "redundant_confirmation": "redundant_prompts",
    "redundant_repetition": "redundant_prompts",
    "redundant_information_repetition": "redundant_prompts",
    "unclear_closure_declination": "unclear_rejection",
    "unclear_rejection_of_out_of_scope_request": "unclear_rejection",
}


# --- Transcript parsing -----------------------------------------------------

@dataclass
class Turn:
    speaker: str  # "agent" | "patient"
    text: str
    lineno: int


@dataclass
class Transcript:
    name: str
    scenario_id: str
    turns: list[Turn]

    @property
    def is_stub(self) -> bool:
        return len(self.turns) == 0

    def numbered(self) -> str:
        label = {"agent": "AGENT", "patient": "PATIENT"}
        return "\n".join(f"L{t.lineno} {label[t.speaker]}: {t.text}" for t in self.turns)


def scenario_id_from_name(name: str) -> str:
    """call-NN-<scenario_id>.txt -> scenario_id (which may contain underscores)."""
    m = re.match(r"^call-\d+-(.+)\.txt$", name)
    return m.group(1) if m else "unknown"


def parse_transcript(path: Path) -> Transcript:
    turns: list[Turn] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.startswith(AGENT_PREFIX):
            turns.append(Turn("agent", line[len(AGENT_PREFIX):].strip(), i))
        elif line.startswith(PATIENT_PREFIX):
            turns.append(Turn("patient", line[len(PATIENT_PREFIX):].strip(), i))
    return Transcript(path.name, scenario_id_from_name(path.name), turns)


# --- Per-call analysis result model -----------------------------------------

@dataclass
class Finding:
    category: str
    description: str
    severity: str  # Critical | Major | Minor
    evidence: str


@dataclass
class CallAnalysis:
    transcript: str
    scenario_id: str
    goal_verdict: str  # pass | partial | fail | unknown
    goal_reason: str
    findings: list[Finding] = field(default_factory=list)


def _norm_verdict(v: object) -> str:
    s = str(v or "").strip().lower()
    return s if s in ("pass", "partial", "fail") else "unknown"


def _norm_severity(s: object) -> str:
    return {"critical": "Critical", "major": "Major", "minor": "Minor"}.get(
        str(s or "").strip().lower(), "Minor"
    )


def _norm_category(c: object) -> str:
    raw = re.sub(r"[^a-z0-9]+", "_", str(c or "").strip().lower()).strip("_")
    return CATEGORY_ALIASES.get(raw, raw)


def build_call_analysis(name: str, scenario_id: str, data: dict) -> CallAnalysis:
    """Coerce a raw (already-JSON-parsed) LLM response into a CallAnalysis."""
    go = data.get("goal_outcome") or {}
    findings: list[Finding] = []
    for f in data.get("findings") or []:
        if not isinstance(f, dict):
            continue
        cat = _norm_category(f.get("category"))
        if not cat:
            continue
        findings.append(
            Finding(
                category=cat,
                description=str(f.get("description") or "").strip(),
                severity=_norm_severity(f.get("severity")),
                evidence=str(f.get("evidence") or "").strip(),
            )
        )
    return CallAnalysis(
        transcript=name,
        scenario_id=scenario_id,
        goal_verdict=_norm_verdict(go.get("verdict")),
        goal_reason=str(go.get("reason") or "").strip(),
        findings=findings,
    )


# --- Defensive JSON extraction ----------------------------------------------

def extract_json(text: str) -> dict:
    """Parse model output into a dict, tolerating code fences / stray prose."""
    if not text or not text.strip():
        raise ValueError("empty model response")
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        obj = json.loads(s[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model response was not a JSON object")
    return obj


# --- Aggregation ------------------------------------------------------------

@dataclass
class Bug:
    id: str
    title: str
    severity: str
    severity_justification: str
    count: int
    analyzed: int
    sources: list[str]
    examples: list[dict]
    manual_ref: str | None

    @property
    def reproduction(self) -> str:
        return f"{self.count}/{self.analyzed}"


def _titleize(category_id: str) -> str:
    return category_id.replace("_", " ").strip().capitalize()


def _pick_examples(items: list[tuple[str, Finding]], cap: int = 3) -> list[dict]:
    """Up to `cap` quotes from distinct transcripts, most-severe first."""
    out: list[dict] = []
    seen: set[str] = set()
    for src, f in sorted(items, key=lambda tf: SEVERITY_RANK[tf[1].severity.lower()]):
        if src in seen or not f.evidence:
            continue
        seen.add(src)
        out.append({"source": src, "quote": f.evidence})
        if len(out) >= cap:
            break
    return out


def aggregate_bugs(per_call: list[CallAnalysis], analyzed: int) -> list[Bug]:
    groups: dict[str, list[tuple[str, Finding]]] = defaultdict(list)
    for ca in per_call:
        for f in ca.findings:
            groups[f.category].append((ca.transcript, f))

    bugs: list[Bug] = []
    for cat, items in groups.items():
        sources = sorted({src for src, _ in items})
        # Highest severity observed for this category.
        _, rep_finding = min(
            items, key=lambda tf: SEVERITY_RANK[tf[1].severity.lower()]
        )
        title, manual = SEED_CATEGORIES.get(cat, (_titleize(cat), None))
        bugs.append(
            Bug(
                id=cat,
                title=title,
                severity=rep_finding.severity,
                severity_justification=rep_finding.description,
                count=len(sources),
                analyzed=analyzed,
                sources=sources,
                examples=_pick_examples(items),
                manual_ref=manual,
            )
        )
    return rank_bugs(bugs)


def rank_bugs(bugs: list[Bug]) -> list[Bug]:
    return sorted(bugs, key=lambda b: (SEVERITY_RANK[b.severity.lower()], -b.count, b.id))


def load_cached_per_call(path: Path) -> tuple[list[CallAnalysis], list[dict], str]:
    """Rebuild per-call analyses from an existing findings.json (no LLM calls).

    Categories are re-normalized through the current alias map, so you can tune the
    rubric/aliases and re-aggregate offline without re-querying the model.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    per_call: list[CallAnalysis] = []
    for pc in data.get("per_call", []):
        go = pc.get("goal_outcome") or {}
        findings = [
            Finding(
                _norm_category(f.get("category")),
                str(f.get("description") or ""),
                _norm_severity(f.get("severity")),
                str(f.get("evidence") or ""),
            )
            for f in pc.get("findings") or []
            if _norm_category(f.get("category"))
        ]
        per_call.append(
            CallAnalysis(
                transcript=pc.get("transcript", "?"),
                scenario_id=pc.get("scenario_id", "unknown"),
                goal_verdict=_norm_verdict(go.get("verdict")),
                goal_reason=str(go.get("reason") or ""),
                findings=findings,
            )
        )
    return per_call, data.get("skipped", []), data.get("model", "(cached)")


def goal_summary(per_call: list[CallAnalysis]) -> dict[str, dict[str, int]]:
    summ: dict[str, dict[str, int]] = {}
    for ca in per_call:
        s = summ.setdefault(
            ca.scenario_id,
            {"pass": 0, "partial": 0, "fail": 0, "unknown": 0, "total": 0},
        )
        s[ca.goal_verdict] = s.get(ca.goal_verdict, 0) + 1
        s["total"] += 1
    return summ


# --- LLM call ---------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
You are a meticulous QA analyst evaluating a HEALTHCARE VOICE AGENT (the "clinic"
agent) that is under test. You are given the transcript of ONE phone call between
the CLINIC agent (the system under test) and a PATIENT (an automated tester who
called in).

Your job, for this single call:
1. Judge whether the clinic agent achieved the call's goal, given the success
   criteria. Verdict is pass, partial, or fail, with a one-sentence reason.
2. Identify DEFECTS in the CLINIC AGENT's behavior.

Strict rules:
- Analyze ONLY the clinic agent. NEVER report problems with the patient/caller.
- Report ONLY issues clearly grounded in the transcript text. For each finding,
  quote the EXACT clinic-agent words as evidence. Do NOT invent or speculate.
- If the agent had no defects, return an empty findings list.
- Output STRICT JSON only — no markdown, no commentary."""

PROMPT_TEMPLATE = """\
SCENARIO
  id: {scenario_id}
  title: {title}
  patient goal: {goal}
  success criteria (judge the agent against THIS): {success_criteria}

BUG CATEGORIES — reuse these exact ids when a finding fits one; only coin a new
short snake_case id if none fit:
{rubric}

SEVERITY
  Critical = blocks the core task, or corrupts / leaks data.
  Major    = significant wrong behavior or data-integrity issue.
  Minor    = low-impact or cosmetic.

TRANSCRIPT (each line: L<lineno> SPEAKER: text)
{transcript}

Return STRICT JSON exactly in this shape:
{{
  "goal_outcome": {{"verdict": "pass|partial|fail", "reason": "<=1 sentence"}},
  "findings": [
    {{"category": "<id>", "description": "<what the agent did wrong>",
      "severity": "Critical|Major|Minor", "evidence": "<exact quote from an AGENT line>"}}
  ]
}}"""


def _rubric_text() -> str:
    descriptions = {
        "dob_hallucination": "agent invents a date of birth the patient never gave (often the literal 'July fourth two thousand')",
        "profile_loop": "agent can't recognize an existing patient and forces demo-profile creation",
        "phantom_appointment": "agent claims an appointment exists for a just-created profile, sometimes blocking a real booking",
        "cross_call_state_leakage": "appointment/data from one caller appears for a different caller",
        "broken_transfer": "agent offers/says it will transfer to live support but it does not complete",
        "provider_name_instability": "the same doctor's name is rendered differently within one call",
        "info_gated_behind_profile": "agent requires profile creation to answer simple info questions",
    }
    return "\n".join(f"  - {cid}: {descriptions[cid]}" for cid in SEED_CATEGORIES)


def build_prompt(transcript: Transcript, scenario) -> str:
    return PROMPT_TEMPLATE.format(
        scenario_id=scenario.id,
        title=scenario.title,
        goal=scenario.goal,
        success_criteria=scenario.success_criteria,
        rubric=_rubric_text(),
        transcript=transcript.numbered(),
    )


def _is_rate_limit(e: Exception) -> bool:
    s = str(e)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "quota" in s.lower()


def _retry_delay(e: Exception, base: float, attempt: int) -> float:
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)\s*s", str(e))
    if m:
        return int(m.group(1)) + 1
    return min(base * (2 ** attempt), 60.0)


def analyze_transcript(
    client,
    model: str,
    transcript: Transcript,
    scenario,
    *,
    max_retries: int = 5,
    base_delay: float = 20.0,
) -> tuple[CallAnalysis | None, str | None]:
    """Run one LLM analysis. Returns (analysis, error). Never raises."""
    from google.genai import types

    prompt = build_prompt(transcript, scenario)
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            data = extract_json(resp.text)
            return build_call_analysis(transcript.name, transcript.scenario_id, data), None
        except Exception as e:  # noqa: BLE001 - per-transcript robustness
            if attempt < max_retries - 1 and _is_rate_limit(e):
                delay = _retry_delay(e, base_delay, attempt)
                logger.warning(f"{transcript.name}: rate-limited; retrying in {delay:.0f}s")
                time.sleep(delay)
                continue
            return None, f"{type(e).__name__}: {str(e)[:200]}"
    return None, "exhausted retries"


# --- Rendering --------------------------------------------------------------

def build_json(model: str, per_call: list[CallAnalysis], skipped: list[dict],
               bugs: list[Bug]) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "n_analyzed": len(per_call),
        "n_skipped": len(skipped),
        "skipped": skipped,
        "goal_summary": goal_summary(per_call),
        "per_call": [
            {
                "transcript": ca.transcript,
                "scenario_id": ca.scenario_id,
                "goal_outcome": {"verdict": ca.goal_verdict, "reason": ca.goal_reason},
                "findings": [
                    {
                        "category": f.category,
                        "description": f.description,
                        "severity": f.severity,
                        "evidence": f.evidence,
                    }
                    for f in ca.findings
                ],
            }
            for ca in per_call
        ],
        "bugs": [
            {
                "id": b.id,
                "title": b.title,
                "severity": b.severity,
                "severity_justification": b.severity_justification,
                "reproduction": b.reproduction,
                "count": b.count,
                "analyzed": b.analyzed,
                "sources": b.sources,
                "examples": b.examples,
                "manual_ref": b.manual_ref,
            }
            for b in bugs
        ],
    }


def render_markdown(model: str, per_call: list[CallAnalysis], skipped: list[dict],
                    bugs: list[Bug]) -> str:
    n = len(per_call)
    lines: list[str] = []
    lines.append("# Clinic-Agent Findings — automated analysis")
    lines.append("")
    lines.append(
        f"> Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
        f"by `analysis/analyze.py` using `{model}`. "
        f"{n} transcripts analyzed, {len(skipped)} skipped, {len(bugs)} distinct bugs."
    )
    lines.append("")
    lines.append(
        "This is the **systematic LLM pass** over all call transcripts. It corroborates "
        "and extends the hand-written [candidate-bugs.md](candidate-bugs.md) (which it "
        "does not replace); each bug links to the manual entry it matches via `manual_ref`."
    )
    lines.append("")

    # Goal-outcome table.
    lines.append("## Goal outcomes by scenario")
    lines.append("")
    lines.append("| Scenario | Pass | Partial | Fail | Unknown | Total |")
    lines.append("| --- | --: | --: | --: | --: | --: |")
    summ = goal_summary(per_call)
    for sid in sorted(summ):
        s = summ[sid]
        lines.append(
            f"| {sid} | {s['pass']} | {s['partial']} | {s['fail']} | "
            f"{s['unknown']} | {s['total']} |"
        )
    lines.append("")

    # Ranked bugs.
    lines.append("## Bugs (ranked by severity, then reproduction)")
    lines.append("")
    if not bugs:
        lines.append("_No bugs found._")
    for i, b in enumerate(bugs, start=1):
        ref = f" · corroborates {b.manual_ref}" if b.manual_ref else " · (new — not in manual log)"
        lines.append(f"### {i}. {b.title} — {b.severity} · {b.reproduction}{ref}")
        lines.append("")
        lines.append(f"- **Category id:** `{b.id}`")
        if b.severity_justification:
            lines.append(f"- **Why this severity:** {b.severity_justification}")
        lines.append(f"- **Reproduction:** {b.reproduction} analyzed calls")
        lines.append(f"- **Sources:** {', '.join(b.sources)}")
        lines.append("- **Representative evidence:**")
        for ex in b.examples:
            lines.append(f"  > AGENT (clinic): {ex['quote']}  *(in {ex['source']})*")
        lines.append("")

    if skipped:
        lines.append("## Skipped transcripts")
        lines.append("")
        for sk in skipped:
            lines.append(f"- `{sk['transcript']}` — {sk['reason']}")
        lines.append("")

    return "\n".join(lines) + "\n"


# --- Orchestration ----------------------------------------------------------

def _finalize(out_dir: Path, model: str, per_call: list[CallAnalysis],
              skipped: list[dict]) -> int:
    """Aggregate, write both output files, log the summary. Returns #distinct bugs."""
    bugs = aggregate_bugs(per_call, analyzed=len(per_call))
    (out_dir / "findings.json").write_text(
        json.dumps(build_json(model, per_call, skipped, bugs), indent=2),
        encoding="utf-8",
    )
    (out_dir / "findings.md").write_text(
        render_markdown(model, per_call, skipped, bugs), encoding="utf-8"
    )
    logger.info("==================== DONE ====================")
    logger.info(
        f"{len(per_call)} transcripts analyzed, {len(skipped)} skipped, "
        f"{len(bugs)} distinct bugs found"
    )
    logger.info(f"wrote {out_dir / 'findings.json'} and {out_dir / 'findings.md'}")
    return len(bugs)


def main() -> None:
    p = argparse.ArgumentParser(description="Offline clinic-agent transcript analysis.")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model (default {DEFAULT_MODEL})")
    p.add_argument("--recordings-dir", default=str(RECORDINGS_DIR))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--limit", type=int, default=0, help="analyze only the first N transcripts (0 = all)")
    p.add_argument("--delay", type=float, default=4.0, help="seconds between LLM calls")
    p.add_argument(
        "--reaggregate-from",
        help="re-aggregate from an existing findings.json (no LLM calls); useful after tuning aliases",
    )
    args = p.parse_args()

    rec_dir = Path(args.recordings_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Offline re-aggregation: re-fold cached findings through current aliases.
    if args.reaggregate_from:
        per_call, skipped, model = load_cached_per_call(Path(args.reaggregate_from))
        logger.info(
            f"re-aggregating {len(per_call)} cached analyses from {args.reaggregate_from}"
        )
        _finalize(out_dir, f"{model} (re-aggregated)", per_call, skipped)
        return

    paths = sorted(rec_dir.glob("call-*.txt"))
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        logger.error(f"no transcripts found in {rec_dir}")
        return

    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY is not set; cannot run analysis")
        return
    client = genai.Client(api_key=api_key)

    per_call: list[CallAnalysis] = []
    skipped: list[dict] = []

    for idx, path in enumerate(paths, start=1):
        tx = parse_transcript(path)
        if tx.is_stub:
            logger.info(f"[{idx}/{len(paths)}] skip stub {tx.name} (no conversation turns)")
            skipped.append({"transcript": tx.name, "reason": "stub (no conversation turns)"})
            continue
        try:
            scenario = get_scenario(tx.scenario_id)
        except KeyError:
            logger.warning(f"[{idx}/{len(paths)}] skip {tx.name}: unknown scenario {tx.scenario_id!r}")
            skipped.append({"transcript": tx.name, "reason": f"unknown scenario {tx.scenario_id!r}"})
            continue

        logger.info(f"[{idx}/{len(paths)}] analyzing {tx.name} ({tx.scenario_id})")
        analysis, err = analyze_transcript(client, args.model, tx, scenario)
        if err or analysis is None:
            logger.warning(f"[{idx}/{len(paths)}] {tx.name} failed: {err}")
            skipped.append({"transcript": tx.name, "reason": f"analysis error: {err}"})
        else:
            per_call.append(analysis)
            logger.info(
                f"[{idx}/{len(paths)}] {tx.name}: goal={analysis.goal_verdict}, "
                f"{len(analysis.findings)} findings"
            )
        if idx < len(paths):
            time.sleep(args.delay)

    _finalize(out_dir, args.model, per_call, skipped)


if __name__ == "__main__":
    main()
