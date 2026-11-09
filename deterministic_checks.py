"""
Deterministic Quality & Rule Checks for Promotional Clips
==========================================================
Enforces hard code-level constraints without trusting LLM self-reporting:
  1. Check_Hook: A spoken line or ACTION begins within 3.0s of the clip's start.
  2. Check_Start: First line is not a mid-sentence continuation ('...' or lowercase).
  3. Check_End: Last line is not a resolution action (e.g., walking away, leaving room).
  4. Check_Context: Every named speaker is introduced in dialogue/action or flagged.
  5. Duration validation: Total clip duration strictly within [20.0, 60.0] seconds.
"""

import re
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd

NON_DIALOGUE_ENTITIES = {"CAMERA", "SOUND FX", "MUSIC", "SFX"}

RESOLUTION_EXIT_PATTERNS = [
    r"\bwalk(?:s|ing|ed)?\s+away\b",
    r"\bwalk(?:s|ing|ed)?\s+out\b",
    r"\bwalk(?:s|ing|ed)?\s+off\b",
    r"\bturn(?:s|ed)?\s+and\s+(?:leave|leaves|left|walk|walks)\b",
    r"\bleave(?:s|ing)?\s+the\s+room\b",
    r"\bstride(?:s|ing)?\s+away\b",
    r"\bexit(?:s|ing|ed)?\b",
    r"\bdoor\s+closes?\b",
    r"\bfade(?:s|d)?\s+to\s+black\b",
    r"\bfade(?:s|d)?\s+out\b",
    r"\bscene\s+fades\b",
]

ARCHETYPE_SPEAKERS = {
    "MATRIARCH", "PATRIARCH", "FATHER", "MOTHER", "SISTER", "BROTHER",
    "PRIEST", "BISHOP", "DOCTOR", "PHYSICIAN", "NURSE", "MAID", "BUTLER",
    "GUARD", "SOLDIER", "ANNOUNCER", "NARRATOR", "HOST", "STRANGER"
}


def timecode_to_seconds(tc: str) -> float:
    """Converts MM:SS.ms string into float seconds."""
    if not tc or not isinstance(tc, str):
        return 0.0
    cleaned = tc.strip().strip("()[] ")
    try:
        parts = cleaned.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return round(float(h) * 3600 + float(m) * 60 + float(s), 3)
        elif len(parts) == 2:
            m, s = parts
            return round(float(m) * 60 + float(s), 3)
        elif len(parts) == 1:
            return round(float(parts[0]), 3)
    except (ValueError, TypeError):
        pass
    return 0.0


def check_hook_start(clip_lines: pd.DataFrame, start_sec: float) -> Tuple[bool, str]:
    """
    Check (a): Must require a spoken dialogue line within 3.0s of the clip's start.
    An ACTION-only opening returns 'WEAK: action only, no dialogue in first 3s'
    (counts as a failure in All_Checks_Passed).
    """
    if clip_lines.empty:
        return False, "FAIL: Clip contains no script lines"

    cutoff_sec = start_sec + 3.0
    early_lines = clip_lines[clip_lines["Start_Sec"] <= cutoff_sec]

    has_dialogue = False
    has_action = False

    for _, row in early_lines.iterrows():
        entity = str(row.get("Entity_Type", "")).strip().upper()
        content = str(row.get("Content", "")).strip()

        # If it's a spoken dialogue line
        if entity not in NON_DIALOGUE_ENTITIES and entity != "ACTION":
            has_dialogue = True
            break
        elif entity == "ACTION" and len(content) > 0:
            has_action = True

    if has_dialogue:
        return True, "PASS"
    elif has_action:
        return False, "WEAK: action only, no dialogue in first 3s"

    return False, f"FAIL: No spoken line or action within first 3.0s (starts at {start_sec:.2f}s)"


def check_start_line(clip_lines: pd.DataFrame) -> Tuple[bool, str]:
    """
    Check (b): First line isn't a mid-sentence continuation ('...' or lowercase).
    """
    if clip_lines.empty:
        return False, "FAIL: No lines in clip"

    # Find first dialogue or action line
    for _, row in clip_lines.iterrows():
        entity = str(row.get("Entity_Type", "")).strip().upper()
        if entity in NON_DIALOGUE_ENTITIES:
            continue

        content = str(row.get("Content", "")).strip()
        cleaned = content.lstrip('"\'‘“').strip()
        if not cleaned:
            continue

        if cleaned.startswith("...") or cleaned.startswith("…"):
            return False, f"FAIL: Starts with ellipsis continuation ('{content[:30]}...')"

        if cleaned[0].islower():
            return False, f"FAIL: Starts with lowercase continuation ('{content[:30]}...')"

        return True, "PASS"

    return False, "FAIL: No dialogue or action line found at start"


def check_end_line(clip_lines: pd.DataFrame) -> Tuple[bool, str]:
    """
    Check (c): Last line is not a clear resolution.
    Inspects the last 2 lines for resolution/exit patterns.
    """
    if clip_lines.empty:
        return False, "FAIL: No lines in clip"

    # Inspect the last 2 lines
    tail_rows = clip_lines.tail(2)
    for _, row in tail_rows.iterrows():
        content = str(row.get("Content", "")).strip().lower()
        for pattern in RESOLUTION_EXIT_PATTERNS:
            if re.search(pattern, content):
                return False, f"FAIL: Ends on resolution/exit action ('{str(row.get('Content', ''))[:40]}')"

    return True, "PASS"


def check_context_speakers(clip_lines: pd.DataFrame) -> Tuple[bool, str]:
    """
    Check (d): Every named speaker in the clip is either introduced/referenced
    in the clip dialogue/action or flagged 'needs context'.
    """
    if clip_lines.empty:
        return True, "PASS"

    # Gather all dialogue speakers
    dialogue_rows = clip_lines[~clip_lines["Entity_Type"].str.upper().isin(NON_DIALOGUE_ENTITIES | {"ACTION"})]
    speakers = list(dialogue_rows["Entity_Type"].unique())

    if not speakers:
        return True, "PASS"

    # Build full transcript text for context search
    full_transcript = " ".join(clip_lines["Content"].astype(str).tolist()).lower()

    unintroduced = []
    for sp in speakers:
        clean_sp = str(sp).strip().upper()
        if clean_sp in ARCHETYPE_SPEAKERS:
            continue

        # Look for the character's name mentioned in text
        # (e.g. for "LADY JULIANA" -> check "juliana", for "GERALD" -> "gerald")
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", clean_sp) if len(t) > 2 and t.lower() not in {"lady", "lord", "the"}]
        introduced = False
        for tok in tokens:
            # Check if mentioned more than 0 times in dialog or action
            if tok in full_transcript:
                introduced = True
                break

        if not introduced:
            unintroduced.append(clean_sp)

    if unintroduced:
        return False, f"needs_context: {', '.join(unintroduced)} not introduced in clip"

    return True, "PASS"


def run_all_deterministic_checks(clip_lines: pd.DataFrame, start_sec: float) -> Dict[str, str]:
    """Runs all 4 deterministic quality checks and returns a summary dict."""
    h_ok, h_msg = check_hook_start(clip_lines, start_sec)
    s_ok, s_msg = check_start_line(clip_lines)
    e_ok, e_msg = check_end_line(clip_lines)
    c_ok, c_msg = check_context_speakers(clip_lines)

    return {
        "Check_Hook": h_msg,
        "Check_Start": s_msg,
        "Check_End": e_msg,
        "Check_Context": c_msg,
        "All_Checks_Passed": (h_ok and s_ok and e_ok and c_ok),
    }


def resolve_segments_and_duration(
    segments: List[Dict[str, str]],
    master_df: pd.DataFrame,
    min_dur: float = 20.0,
    max_dur: float = 60.0
) -> Tuple[bool, float, List[Dict[str, Any]], str]:
    """
    Resolves a list of segments [{'start_line_id': '...', 'end_line_id': '...'}]
    into exact timestamps and lines from master_df.
    Validates that total duration is strictly between min_dur and max_dur.

    Returns:
        (is_valid, total_duration, resolved_segments, error_message)
    """
    if not segments:
        return False, 0.0, [], "Empty segments list"

    # Index master_df by Line_ID for O(1) lookup
    if "Line_ID" not in master_df.columns:
        return False, 0.0, [], "master_df is missing Line_ID column"

    line_map = master_df.set_index("Line_ID")

    resolved_segments = []
    total_duration = 0.0

    for idx, seg in enumerate(segments):
        start_id = str(seg.get("start_line_id", "")).strip()
        end_id = str(seg.get("end_line_id", "")).strip()

        if start_id not in line_map.index:
            return False, 0.0, [], f"start_line_id '{start_id}' not found in script"
        if end_id not in line_map.index:
            return False, 0.0, [], f"end_line_id '{end_id}' not found in script"

        start_row = line_map.loc[start_id]
        end_row = line_map.loc[end_id]

        # Handle multiple matches if index is non-unique
        if isinstance(start_row, pd.DataFrame):
            start_row = start_row.iloc[0]
        if isinstance(end_row, pd.DataFrame):
            end_row = end_row.iloc[-1]

        t_start = float(start_row["Start_Sec"])
        t_end = float(end_row["End_Sec"])
        ep_start = int(start_row["Episode"])
        ep_end = int(end_row["Episode"])

        if t_end < t_start:
            return False, 0.0, [], f"Segment {idx+1} has end time {t_end}s before start time {t_start}s"

        seg_dur = round(t_end - t_start, 2)
        total_duration += seg_dur

        resolved_segments.append({
            "segment_index": idx + 1,
            "start_line_id": start_id,
            "end_line_id": end_id,
            "episode_start": ep_start,
            "episode_end": ep_end,
            "start_sec": t_start,
            "end_sec": t_end,
            "duration_sec": seg_dur,
        })

    total_duration = round(total_duration, 2)

    if total_duration < min_dur or total_duration > max_dur:
        return (
            False,
            total_duration,
            resolved_segments,
            f"Duration {total_duration:.1f}s violates strict 20-60s window [{min_dur:.1f}s, {max_dur:.1f}s]"
        )

    return True, total_duration, resolved_segments, "OK"
