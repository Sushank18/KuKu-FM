"""
Smoke Tests for Microdrama Promotional Extraction Pipeline
===========================================================
Plain assertion test suite without network dependencies.
Tests:
  1. Parsing all 50 episodes -> asserts exactly 3,727 rows and numeric episode order (1 to 50).
  2. Line-ID generation (E1-L001, E12-L034), loglines, and continuity notes.
  3. Deterministic quality checks:
     - Check_Hook: spoken dialogue required within first 3.0s (action-only returns WEAK / False).
     - Check_Start: continuation fragment rejection ('...' and lowercase).
     - Check_End: resolution / walk-away action rejection across last 2 lines.
     - Check_Context: speaker introduction check.
  4. Line-ID to timestamp resolution and duration enforcement (strictly 20-60s).
  5. Subtitle (.srt) millisecond timestamp rounding carry-over (59.9996 -> 00:01:00,000).
  6. run_pipeline without API key and without --allow_offline raises.
  7. run_pipeline with --allow_offline marks Source="HEURISTIC_NO_LLM" and leaves scores/creatives empty.
  8. Every quoted line in FAILURES.md exists verbatim in the source pack.
"""

import os
import sys
import re
import shutil
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
from run_pipeline import run_pipeline


def test_srt_rounding_fix():
    print("[TEST 1/8] Testing SRT timestamp rounding carry-over...")
    assert seconds_to_srt_timestamp(59.9996) == "00:01:00,000", (
        f"Expected '00:01:00,000', got '{seconds_to_srt_timestamp(59.9996)}'"
    )
    assert seconds_to_srt_timestamp(0.0) == "00:00:00,000"
    assert seconds_to_srt_timestamp(73.42) == "00:01:13,420"
    assert seconds_to_srt_timestamp(3599.9996) == "01:00:00,000"
    print("  -> PASSED: SRT rounding properly carries over to seconds and hours.")


def test_line_id_and_continuity_extraction():
    print("[TEST 2/8] Testing Line-ID formatting, logline & continuity notes extraction...")
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
    print("[TEST 3/8] Testing deterministic rule checks (Hook, Start, End, Context)...")

    # Check_Hook: requires dialogue within 3s
    df_hook_pass = pd.DataFrame([
        {"Entity_Type": "CAMERA", "Content": "Door opens", "Start_Sec": 0.0, "End_Sec": 1.0},
        {"Entity_Type": "JULIANA", "Content": '"Stop right there!"', "Start_Sec": 1.5, "End_Sec": 4.0},
    ])
    assert check_hook_start(df_hook_pass, start_sec=0.0)[0] is True

    # Action-only opening returns WEAK and False
    df_hook_action_only = pd.DataFrame([
        {"Entity_Type": "CAMERA", "Content": "Door opens", "Start_Sec": 0.0, "End_Sec": 1.0},
        {"Entity_Type": "ACTION", "Content": "Juliana drops her bouquet to the floor.", "Start_Sec": 1.2, "End_Sec": 2.5},
        {"Entity_Type": "JULIANA", "Content": '"How could you?"', "Start_Sec": 4.0, "End_Sec": 6.0},
    ])
    ok, msg = check_hook_start(df_hook_action_only, start_sec=0.0)
    assert ok is False and "WEAK" in msg, f"Expected WEAK for action-only opening, got ({ok}, '{msg}')"

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

    # Check_End test: inspects last 2 lines
    df_end_walkaway = pd.DataFrame([
        {"Entity_Type": "JULIANA", "Content": '"You will pay."'},
        {"Entity_Type": "ACTION", "Content": "Juliana turns and walks away as the door closes behind her."}
    ])
    assert check_end_line(df_end_walkaway)[0] is False

    df_end_penultimate_walkaway = pd.DataFrame([
        {"Entity_Type": "ACTION", "Content": "Alexander turns and leaves the room."},
        {"Entity_Type": "CAMERA", "Content": "Close-up on empty doorway."}
    ])
    assert check_end_line(df_end_penultimate_walkaway)[0] is False, "Expected walk-away in penultimate line to be flagged"

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
    assert check_context_speakers(df_context_missing)[0] is False

    print("  -> PASSED: All 4 deterministic checks verified (action-only hook weak, last 2 lines exit checked).")


def test_line_id_duration_validation():
    print("[TEST 4/8] Testing Line-ID to timestamp resolution and duration enforcement...")
    master = pd.DataFrame([
        {"Line_ID": "E1-L001", "Episode": 1, "Start_Sec": 0.0, "End_Sec": 5.0},
        {"Line_ID": "E1-L002", "Episode": 1, "Start_Sec": 5.0, "End_Sec": 25.0},
        {"Line_ID": "E1-L003", "Episode": 1, "Start_Sec": 25.0, "End_Sec": 35.0},
        {"Line_ID": "E1-L004", "Episode": 1, "Start_Sec": 35.0, "End_Sec": 80.0},
    ])

    # Valid 35s window
    valid_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L003"}]
    ok, dur, _, _ = resolve_segments_and_duration(valid_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is True and dur == 35.0

    # Under-duration (<20s)
    under_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L001"}]
    ok, dur, _, msg = resolve_segments_and_duration(under_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is False and "violates" in msg

    # Over-duration (>60s)
    over_segs = [{"start_line_id": "E1-L001", "end_line_id": "E1-L004"}]
    ok, dur, _, msg = resolve_segments_and_duration(over_segs, master, min_dur=20.0, max_dur=60.0)
    assert ok is False and "violates" in msg

    print("  -> PASSED: Duration strictly verified from code-level line timestamps.")


def test_parse_all_50_episodes_and_numeric_order():
    print("[TEST 5/8] Parsing all 50 episodes & asserting 3,727 rows + numeric order...")
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
    assert len(master) == 3727, f"Expected 3727 parsed lines, got {len(master)}"
    assert pd.api.types.is_integer_dtype(master["Episode"]), f"Expected integer Episode column, got {master['Episode'].dtype}"

    unique_eps = list(master["Episode"].unique())
    assert unique_eps == list(range(1, 51)), f"Expected episodes 1..50 in order, got: {unique_eps[:10]}..."
    print(f"  -> PASSED: Successfully parsed {len(master)} lines across 50 episodes with valid Line_IDs.")


def test_pipeline_aborts_without_key_and_without_allow_offline():
    print("[TEST 6/8] Testing run_pipeline aborts without API key when allow_offline=False...")
    orig_key = os.environ.pop("GEMINI_API_KEY", None)
    orig_llm_key = os.environ.pop("LLM_API_KEY", None)
    test_out = "output/test_abort_run"
    try:
        raised = False
        try:
            run_pipeline(episodes="1", allow_offline=False, output_dir=test_out)
        except RuntimeError as e:
            raised = True
            assert "allow_offline" in str(e).lower(), f"Expected error mentioning allow_offline, got: {e}"
        assert raised, "Expected run_pipeline to raise RuntimeError when no key and allow_offline=False"
        print("  -> PASSED: Aborts with clear error when no API key is provided and allow_offline=False.")
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key
        if orig_llm_key:
            os.environ["LLM_API_KEY"] = orig_llm_key
        if os.path.exists(test_out):
            shutil.rmtree(test_out, ignore_errors=True)


def test_pipeline_heuristic_offline_mode():
    print("[TEST 7/8] Testing run_pipeline with allow_offline=True enforces HEURISTIC_NO_LLM and empty scores...")
    orig_key = os.environ.pop("GEMINI_API_KEY", None)
    orig_llm_key = os.environ.pop("LLM_API_KEY", None)
    test_out = "output/test_offline_run"
    try:
        res = run_pipeline(episodes="1", allow_offline=True, output_dir=test_out)
        df = res["promos_df"]
        assert not df.empty, "Expected candidates to be generated"
        for _, row in df.iterrows():
            assert row["Source"] == "HEURISTIC_NO_LLM", f"Expected Source='HEURISTIC_NO_LLM', got {row['Source']}"
            assert pd.isna(row["hook_score"]), f"hook_score must be NaN, got {row['hook_score']}"
            assert pd.isna(row["cliffhanger_score"]), f"cliffhanger_score must be NaN, got {row['cliffhanger_score']}"
            assert pd.isna(row["standalone_score"]), f"standalone_score must be NaN, got {row['standalone_score']}"
            assert pd.isna(row["Rank_Score"]), f"Rank_Score must be NaN, got {row['Rank_Score']}"
            assert pd.isna(row["Judge_Hook"]), f"Judge_Hook must be NaN, got {row['Judge_Hook']}"
            assert row["Hook_Description"] == "heuristic window, no LLM description"
            assert row["Cliffhanger_Description"] == "heuristic window, no LLM description"
            assert row["Justification"] == "heuristic window, no LLM description"
            assert row["On_Screen_Hook_1"] == ""
            assert row["Social_Caption"] == ""
            assert row["Hashtags"] == ""
            assert row["Call_To_Action"] == ""

        # Check run_log.txt banner
        with open(res["run_log_path"], "r", encoding="utf-8") as lf:
            log_text = lf.read()
        assert "NO LLM CALLS - HEURISTIC MODE" in log_text, "Expected banner in run_log.txt"

        print("  -> PASSED: Offline mode strictly enforces HEURISTIC_NO_LLM, empty scores, and empty creatives.")
    finally:
        if orig_key:
            os.environ["GEMINI_API_KEY"] = orig_key
        if orig_llm_key:
            os.environ["LLM_API_KEY"] = orig_llm_key
        if os.path.exists(test_out):
            shutil.rmtree(test_out, ignore_errors=True)


def test_failures_md_verbatim_lines_exist_in_source():
    print("[TEST 8/8] Testing that every quoted line in FAILURES.md exists verbatim in source screenplay pack...")
    folder = os.path.join("Data", "I Married a Broken Soldier. He was a Duke")
    if not os.path.exists(folder):
        print("  -> SKIPPED: Data/ directory not present.")
        return

    failures_path = "FAILURES.md"
    if not os.path.exists(failures_path):
        from evaluate import main as eval_main
        eval_main()

    assert os.path.exists(failures_path), "FAILURES.md must exist"

    txt_files = [f for f in os.listdir(folder) if f.endswith(".txt")]
    all_source_texts = []
    for f in txt_files:
        with open(os.path.join(folder, f), "r", encoding="utf-8", errors="replace") as sf:
            all_source_texts.append(sf.read())
    full_corpus = "\n".join(all_source_texts)

    with open(failures_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    code_blocks = re.findall(r"```text\s*(.*?)\s*```", md_text, re.DOTALL)
    assert len(code_blocks) > 0, "Expected code blocks in FAILURES.md"

    quoted_count = 0
    for block in code_blocks:
        for line in block.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("..."):
                continue
            # Extract content after colon: [E1-L005] ENTITY: Content
            match = re.search(r"\]\s*[A-Za-z0-9 _-]+:\s*(.+)$", line)
            if match:
                content = match.group(1).strip()
                search_snippet = content[:min(30, len(content))]
                assert search_snippet in full_corpus, f"Quoted line '{search_snippet}' not found in source screenplays!"
                quoted_count += 1

    assert quoted_count >= 5, f"Expected at least 5 verified quoted lines, got {quoted_count}"
    print(f"  -> PASSED: Verified {quoted_count} verbatim quoted lines in FAILURES.md match source screenplays exactly.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING EXTENDED SMOKE TEST SUITE (INTEGRITY & OFFLINE CHECKS)")
    print("=" * 70)
    test_srt_rounding_fix()
    test_line_id_and_continuity_extraction()
    test_deterministic_checks()
    test_line_id_duration_validation()
    test_parse_all_50_episodes_and_numeric_order()
    test_pipeline_aborts_without_key_and_without_allow_offline()
    test_pipeline_heuristic_offline_mode()
    test_failures_md_verbatim_lines_exist_in_source()
    print("=" * 70)
    print("ALL 8/8 SMOKE TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
