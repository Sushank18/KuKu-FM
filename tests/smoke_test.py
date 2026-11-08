"""
Smoke Tests for Microdrama Promotional Extraction Pipeline
===========================================================
Plain assertion test suite without network dependencies.
Tests:
  1. Parsing all 50 episodes -> asserts exactly 3,727 rows and numeric episode order (1 to 50).
  2. Subtitle (.srt) millisecond timestamp rounding carry-over (e.g., 59.9996 -> 00:01:00,000).
  3. Snapping engine guarantees:
     - Start line is strictly dialogue (never CAMERA/ACTION).
     - Start line never begins with an ellipsis ('...') or lowercase continuation.
     - Clip duration is strictly within [20.0, 60.0] seconds.
"""

import os
import sys
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from script_parser import parse_screenplay, episode_number
from phase3_video_pipeline import (
    seconds_to_srt_timestamp,
    snap_clip_to_screenplay_lines,
    is_valid_dialogue_start,
    NON_DIALOGUE_ENTITIES
)


def test_srt_rounding_fix():
    print("[TEST 1/3] Testing SRT timestamp rounding carry-over...")
    assert seconds_to_srt_timestamp(59.9996) == "00:01:00,000", (
        f"Expected '00:01:00,000', got '{seconds_to_srt_timestamp(59.9996)}'"
    )
    assert seconds_to_srt_timestamp(0.0) == "00:00:00,000"
    assert seconds_to_srt_timestamp(73.42) == "00:01:13,420"
    assert seconds_to_srt_timestamp(3599.9996) == "01:00:00,000"
    print("  -> PASSED: SRT rounding properly carries over to seconds and hours.")


def test_snapping_rules_and_ellipsis_rejection():
    print("[TEST 2/3] Testing snapping rules and continuation rejection...")
    # Unit tests for is_valid_dialogue_start
    assert not is_valid_dialogue_start(pd.Series({"Entity_Type": "CAMERA", "Content": "Close-up on face."}))[0]
    assert not is_valid_dialogue_start(pd.Series({"Entity_Type": "ACTION", "Content": "Juliana steps back."}))[0]
    assert not is_valid_dialogue_start(pd.Series({"Entity_Type": "JULIANA", "Content": '"...far too silent..."'}))[0]
    assert not is_valid_dialogue_start(pd.Series({"Entity_Type": "JULIANA", "Content": '...when Clarissa arrives'}))[0]
    assert not is_valid_dialogue_start(pd.Series({"Entity_Type": "JULIANA", "Content": 'when Clarissa arrived'}))[0]
    assert is_valid_dialogue_start(pd.Series({"Entity_Type": "JULIANA", "Content": '"You should turn around."'}))[0]

    # Integration test with Episode 2 (which contains line: '...far too silent...')
    ep2_path = os.path.join("Data", "I Married a Broken Soldier. He was a Duke", "episode-002-Episode 1671704.txt")
    if os.path.exists(ep2_path):
        ep2_df = parse_screenplay(ep2_path)
        # Attempt to snap around 00:06.00 where the continuation line '...far too silent...' is located
        snapped = snap_clip_to_screenplay_lines(ep2_df, episode_id=2, llm_start_tc="00:06.80", llm_end_tc="00:35.00")
        assert snapped is not None, "Snapping should find a valid window"
        start_sec, end_sec, dur_sec = snapped

        # Verify start line does NOT begin with '...'
        matching_start = ep2_df[ep2_df["Start_Sec"] == start_sec].iloc[0]
        start_content = str(matching_start["Content"]).strip().lstrip('"\'').strip()
        start_entity = str(matching_start["Entity_Type"]).strip().upper()

        assert start_entity not in NON_DIALOGUE_ENTITIES, f"Start entity cannot be {start_entity}"
        assert not start_content.startswith("..."), f"Start line must not begin with '...': {start_content}"
        assert not start_content[0].islower(), f"Start line must not begin with lowercase: {start_content}"
        assert 20.0 <= dur_sec <= 60.0, f"Duration {dur_sec}s outside [20, 60]s"

    print("  -> PASSED: Snapping strictly selects dialogue starts and rejects ellipsis/continuations.")


def test_parse_all_episodes_and_numeric_order():
    print("[TEST 3/3] Parsing all 50 episodes & asserting 3,727 rows + numeric order...")
    folder = os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
    assert os.path.exists(folder), f"Directory {folder} does not exist."

    txt_files = [f for f in os.listdir(folder) if f.endswith(".txt")]
    assert len(txt_files) == 50, f"Expected 50 episode files, found {len(txt_files)}"

    # Sort files numerically by episode number
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
    required_cols = ["Episode", "Scene", "Entity_Type", "Emotion", "Start_Sec", "End_Sec", "Duration_Sec", "Content"]
    for col in required_cols:
        assert col in master.columns, f"Missing column {col}"

    print(f"  -> PASSED: Successfully parsed {len(master)} lines across 50 episodes in numeric order 1..50.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING SMOKE TEST SUITE (PLAIN ASSERTS, NO NETWORK)")
    print("=" * 70)
    test_srt_rounding_fix()
    test_snapping_rules_and_ellipsis_rejection()
    test_parse_all_episodes_and_numeric_order()
    print("=" * 70)
    print("ALL SMOKE TESTS PASSED SUCCESSFULLY! (3/3)")
    print("=" * 70)
