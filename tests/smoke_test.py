"""
Smoke Tests for Microdrama Promotional Extraction Pipeline
===========================================================
Plain assertion test suite without network dependencies.
Tests:
  1. Parsing all 50 episodes -> asserts exactly 3,727 rows and numeric episode order (1 to 50).
  2. Line-ID generation (E1-L001, E12-L034), loglines, and continuity notes.
  3. Deterministic quality checks:
     - Check_Hook: spoken dialogue or action within first 3.0s.
     - Check_Start: continuation fragment rejection ('...' and lowercase).
     - Check_End: resolution / walk-away action rejection.
     - Check_Context: speaker introduction check.
  4. Line-ID to timestamp resolution and duration enforcement (strictly 20-60s).
  5. Subtitle (.srt) millisecond timestamp rounding carry-over (59.9996 -> 00:01:00,000).
"""

import os
import sys
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from script_parser import parse_screenplay, episode_number, parse_line_id
from phase3_video_pipeline import (
    seconds_to_srt_timestamp,
    snap_clip_to_screenplay_lines,
    is_valid_dialogue_start,
    NON_DIALOGUE_ENTITIES
)
from deterministic_checks import (
    check_hook_start,
    check_start_line,
    check_end_line,
    check_context_speakers,
    resolve_segments_and_duration,
)


def test_srt_rounding_fix():
    print("[TEST 1/5] Testing SRT timestamp rounding carry-over...")
    assert seconds_to_srt_timestamp(59.9996) == "00:01:00,000", (
        f"Expected '00:01:00,000', got '{seconds_to_srt_timestamp(59.9996)}'"
    )
    assert seconds_to_srt_timestamp(0.0) == "00:00:00,000"
    assert seconds_to_srt_timestamp(73.42) == "00:01:13,420"
    assert seconds_to_srt_timestamp(3599.9996) == "01:00:00,000"
    print("  -> PASSED: SRT rounding properly carries over to seconds and hours.")


def test_line_id_and_continuity_extraction():
    print("[TEST 2/5] Testing Line-ID formatting, logline & continuity notes extraction...")
    sample = """EPISODE NUMBER: Episode 12
EPISODE LOGLINE: Juliana confronts Rupert at Ashbury Manor.
CONTINUITY NOTES: Picks up from Episode 11 after the carriage ambush.
--- SCRIPT START ---
SCENE 01
Scene heading: INT. ASHBURY MANOR – DAY
Scene start: 00:00.00
Scene end: 01:20.00
Actions and dialogue:
**CAMERA:** Start: (00:00.00) | End: (00:02.50) Low tracking shot across polished marble floor.
**RUPERT (Cold):** Start: (00:02.50) | End: (00:05.10) "You shouldn't have come back, Juliana."
**JULIANA (Defiant):** Start: (00:05.20) | End: (00:08.00) "This house belongs to my husband."
"""
    df = parse_screenplay(sample, include_extended_metadata=True)
    assert len(df) == 3, f"Expected 3 lines, got {len(df)}"
    assert df.loc[0, "Line_ID"] == "E12-L001"
    assert df.loc[1, "Line_ID"] == "E12-L002"
    assert df.loc[2, "Line_ID"] == "E12-L003"
    assert df.loc[0, "Episode_Logline"] == "Juliana confronts Rupert at Ashbury Manor."
    assert "Picks up from Episode 11" in df.loc[0, "Continuity_Notes"]

    ep, lnum = parse_line_id("E12-L034")
    assert ep == 12 and lnum == 34
    print("  -> PASSED: Line-ID anchoring and continuity notes correctly parsed.")


def test_deterministic_checks():
    print("[TEST 3/5] Testing deterministic rule checks (Hook, Start, End, Context)...")

    # Check_Hook test
    df_hook_pass = pd.DataFrame([
        {"Entity_Type": "CAMERA", "Content": "Door opens", "Start_Sec": 0.0, "End_Sec": 2.0},
        {"Entity_Type": "JULIANA", "Content": '"Stop right there!"', "Start_Sec": 1.5, "End_Sec": 4.0},
    ])
    assert check_hook_start(df_hook_pass, start_sec=0.0)[0] is True

    df_hook_fail = pd.DataFrame([
        {"Entity_Type": "CAMERA", "Content": "Long wide shot of forest", "Start_Sec": 0.0, "End_Sec": 4.5},
        {"Entity_Type": "JULIANA", "Content": '"Hello?"', "Start_Sec": 5.0, "End_Sec": 7.0},
    ])
    assert check_hook_start(df_hook_fail, start_sec=0.0)[0] is False

    # Check_Start test
    df_start_ellipsis = pd.DataFrame([{"Entity_Type": "JULIANA", "Content": '"...and so I left."' }])
    assert check_start_line(df_start_ellipsis)[0] is False

    df_start_lower = pd.DataFrame([{"Entity_Type": "JULIANA", "Content": 'when we arrived in town' }])
    assert check_start_line(df_start_lower)[0] is False

    df_start_good = pd.DataFrame([{"Entity_Type": "JULIANA", "Content": '"Never touch me again!"' }])
    assert check_start_line(df_start_good)[0] is True

    # Check_End test
    df_end_walkaway = pd.DataFrame([
        {"Entity_Type": "JULIANA", "Content": '"You will pay."'},
        {"Entity_Type": "ACTION", "Content": "Juliana turns and walks away as the door closes behind her."}
    ])
    assert check_end_line(df_end_walkaway)[0] is False

    df_end_cliff = pd.DataFrame([
        {"Entity_Type": "ACTION", "Content": "Gerald pulls out the forged ducal will."},
        {"Entity_Type": "GERALD", "Content": '"Sign it, or your mother dies tonight."'}
    ])
    assert check_end_line(df_end_cliff)[0] is True

    # Check_Context test
    df_context_intro = pd.DataFrame([
        {"Entity_Type": "ACTION", "Content": "Gerald approaches the altar with Clarissa."},
        {"Entity_Type": "GERALD", "Content": '"I have made my choice."'}
    ])
    assert check_context_speakers(df_context_intro)[0] is True

    df_context_missing = pd.DataFrame([
        {"Entity_Type": "ACTION", "Content": "A stranger stands in the hallway."},
        {"Entity_Type": "CLARISSA", "Content": '"Did you bring the poison?"'}
    ])
    # Clarissa is not mentioned in dialogue or action text
    assert check_context_speakers(df_context_missing)[0] is False

    print("  -> PASSED: All 4 deterministic checks verified.")


def test_line_id_duration_validation():
    print("[TEST 4/5] Testing Line-ID to timestamp resolution and duration enforcement...")
    master = pd.DataFrame([
        {"Line_ID": "E1-L001", "Episode": 1, "Start_Sec": 0.0, "End_Sec": 5.0},
        {"Line_ID": "E1-L002", "Episode": 1, "Start_Sec": 5.0, "End_Sec": 25.0},
        {"Line_ID": "E1-L003", "Episode": 1, "Start_Sec": 25.0, "End_Sec": 35.0},
        {"Line_ID": "E1-L004", "Episode": 1, "Start_Sec": 35.0, "End_Sec": 80.0},
    ])

    # Valid 30s window (L001 to L003: 0.0 to 35.0 -> 35.0s)
    valid_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L003"}]
    ok, dur, _, _ = resolve_segments_and_duration(valid_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is True and dur == 35.0

    # Under-duration (L001 to L001: 0.0 to 5.0 -> 5.0s < 20s)
    under_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L001"}]
    ok, dur, _, msg = resolve_segments_and_duration(under_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is False and "violates" in msg

    # Over-duration (L001 to L004: 0.0 to 80.0 -> 80.0s > 60s)
    over_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L004"}]
    ok, dur, _, msg = resolve_segments_and_duration(over_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is False and "violates" in msg

    print("  -> PASSED: Duration strictly verified from code-level line timestamps.")


def test_parse_all_50_episodes_and_numeric_order():
    print("[TEST 5/5] Parsing all 50 episodes & asserting 3,727 rows + numeric order...")
    folder = os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
    assert os.path.exists(folder), f"Directory {folder} does not exist."

    txt_files = [f for f in os.listdir(folder) if f.endswith(".txt")]
    assert len(txt_files) == 50, f"Expected 50 episode files, found {len(txt_files)}"

    txt_files.sort(key=lambda f: episode_number(f))

    all_dfs = []
    for f in txt_files:
        p = os.path.join(folder, f)
        df = parse_screenplay(p, include_extended_metadata=True)
        all_dfs.append(df)

    master = pd.concat(all_dfs, ignore_index=True)

    # 1. Row count assertion
    assert len(master) == 3727, f"Expected 3727 parsed lines, got {len(master)}"

    # 2. Episode type assertion
    assert pd.api.types.is_integer_dtype(master["Episode"]), f"Expected integer Episode column, got {master['Episode'].dtype}"

    # 3. Numeric order assertion (episodes 1 to 50 in sequence)
    unique_eps = list(master["Episode"].unique())
    expected_eps = list(range(1, 51))
    assert unique_eps == expected_eps, f"Expected episodes 1..50 in order, got: {unique_eps[:10]}..."

    # 4. Assert required columns exist
    required_cols = [
        "Line_ID", "Episode", "Scene", "Entity_Type", "Emotion",
        "Start_Sec", "End_Sec", "Duration_Sec", "Content",
        "Episode_Logline", "Continuity_Notes"
    ]
    for col in required_cols:
        assert col in master.columns, f"Missing column {col}"

    # Assert Line_ID format on first line of each episode
    sample_lids = master[master["Line_ID"].str.endswith("-L001")]["Line_ID"].tolist()
    assert len(sample_lids) == 50, f"Expected 50 L001 lines, got {len(sample_lids)}"
    assert sample_lids[0] == "E1-L001"
    assert sample_lids[49] == "E50-L001"

    print(f"  -> PASSED: Successfully parsed {len(master)} lines across 50 episodes with valid Line_IDs (E1-L001..E50-L001).")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING EXTENDED SMOKE TEST SUITE (OFFLINE, PLAIN ASSERTS)")
    print("=" * 70)
    test_srt_rounding_fix()
    test_line_id_and_continuity_extraction()
    test_deterministic_checks()
    test_line_id_duration_validation()
    test_parse_all_50_episodes_and_numeric_order()
    print("=" * 70)
    print("ALL 5/5 SMOKE TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
