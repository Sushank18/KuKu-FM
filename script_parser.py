"""
Microdrama Screenplay Parser
----------------------------
Deterministic parser using Regular Expressions and Pandas to extract structured
screenplay line items, timings, emotions, and scene metadata from raw text scripts.
"""

import os
import re
import logging
from typing import Optional, Dict, Any, List, Union
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def episode_number(x: Any) -> int:
    """
    Extracts the first integer from any episode representation.
    
    Examples:
        'Episode 12' -> 12
        '12' -> 12
        12 -> 12
        'episode-001-Episode 1671703.txt' -> 1
    """
    if isinstance(x, (int, float)) and not pd.isna(x):
        return int(x)
    match = re.search(r"\d+", str(x))
    return int(match.group()) if match else 0


def time_to_seconds(time_str: str) -> float:
    """
    Converts a timestamp string into total seconds as a float.
    
    Supports formats:
      - MM:SS.ms (e.g. '00:11.30' -> 11.3)
      - HH:MM:SS.ms (e.g. '01:02:18.50' -> 3738.5)
      - SS.ms / SS (e.g. '4.80' -> 4.8)
    Strips parentheses, brackets, and whitespace.
    """
    if not time_str or not isinstance(time_str, str):
        return 0.0

    cleaned = time_str.strip().strip("()[] ")
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
    except (ValueError, TypeError) as exc:
        logger.warning("Could not convert timestamp '%s' to seconds: %s", time_str, exc)
    return 0.0


# ==========================================
# REGEX PATTERNS
# ==========================================

# 1. Episode header: e.g. "EPISODE NUMBER: Episode 1" or "EPISODE NUMBER: 1"
EPISODE_PATTERN = re.compile(
    r"^EPISODE(?:\s+NUMBER)?\s*:\s*(?:Episode\s+)?(?P<episode>.+?)$",
    re.IGNORECASE,
)

# 2. Episode logline: e.g. "EPISODE LOGLINE: Lady Juliana arrives..."
LOGLINE_PATTERN = re.compile(
    r"^EPISODE\s+LOGLINE\s*:\s*(?P<logline>.+?)$",
    re.IGNORECASE,
)

# 3. Scene header: e.g. "SCENE 01", "SCENE 1", "SCENE 02A"
# Uses negative lookahead so 'Scene heading:', 'Scene start:', 'Scene end:' are not matched as scenes
SCENE_PATTERN = re.compile(
    r"^SCENE\s+(?!heading|start|end|logline|summary)(?P<scene>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# 4. Scene heading: e.g. "Scene heading: INT. CATHEDRAL – DAY"
SCENE_HEADING_PATTERN = re.compile(
    r"^Scene\s+heading\s*:\s*(?P<heading>.+?)$",
    re.IGNORECASE,
)

# 5. Timestamp line: e.g. "Start: (00:00.00) | End: (00:04.80)"
TIMESTAMP_PATTERN = re.compile(
    r"^Start:\s*\(?(?P<start>[\d:.]+)\)?\s*\|\s*End:\s*\(?(?P<end>[\d:.]+)\)?",
    re.IGNORECASE,
)

# 6. Entity tag in bold: e.g. "**CAMERA:**", "**ACTION:**", "**MATRIARCH (Cold, Commanding):**"
ENTITY_TAG_PATTERN = re.compile(
    r"^\*\*(?P<tag>[^*]+?)\*\*:?",
    re.IGNORECASE,
)

# 7. Combined single-line format:
# e.g. "**CAMERA:** Start: (00:00.00) | End: (00:04.80) Symmetrical framing..."
COMBINED_LINE_PATTERN = re.compile(
    r"^\s*\*\*(?P<tag>[^*]+?)\*\*:?\s*"
    r"Start:\s*\(?(?P<start>[\d:.]+)\)?\s*\|\s*"
    r"End:\s*\(?(?P<end>[\d:.]+)\)?\s*"
    r"(?P<content>.*)$",
    re.IGNORECASE,
)


def extract_entity_and_emotion(raw_tag: str) -> tuple[str, Optional[str]]:
    """
    Separates the entity name from any emotion / context descriptions inside parentheses.
    Handles multiple parentheses like: 'THE FORMER GROOM (Off-screen) (Dismissive)'
    Returns: (entity_name, emotion_string)
    """
    clean_tag = raw_tag.strip().rstrip(":")
    
    # Extract all text inside parentheses
    emotions = re.findall(r"\(([^)]+)\)", clean_tag)
    # Remove all parentheses from entity name
    entity = re.sub(r"\([^)]*\)", "", clean_tag).strip()
    
    emotion = ", ".join(e.strip() for e in emotions) if emotions else None
    return entity, emotion


def parse_screenplay(
    source: Union[str, os.PathLike], 
    include_extended_metadata: bool = True
) -> pd.DataFrame:
    """
    Parses a screenplay from a file path or raw string into a structured Pandas DataFrame.
    Handles both multi-line screenplay blocks and single-line consolidated formats.
    
    Output Columns:
      - Episode: str
      - Scene: str
      - Entity_Type: str (e.g. CAMERA, ACTION, CHARACTER NAME)
      - Emotion: Optional[str] (e.g. Cold, Commanding)
      - Start_Sec: float (timestamp converted to seconds)
      - End_Sec: float (timestamp converted to seconds)
      - Duration_Sec: float (End_Sec - Start_Sec)
      - Content: str (dialogue, action, or camera description)
      
    If include_extended_metadata=True, also includes:
      - Episode_Logline: str
      - Scene_Heading: str
      - Line_Index: int
    """
    if isinstance(source, (str, os.PathLike)) and os.path.exists(source):
        with open(source, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = str(source)

    records: List[Dict[str, Any]] = []
    current_episode: Optional[str] = None
    current_logline: Optional[str] = None
    current_scene: Optional[str] = None
    current_heading: Optional[str] = None

    lines = text.splitlines()
    i = 0
    num_lines = len(lines)

    while i < num_lines:
        raw_line = lines[i]
        line = raw_line.strip()

        if not line:
            i += 1
            continue

        # 1. Episode header
        ep_m = EPISODE_PATTERN.match(line)
        if ep_m:
            current_episode = episode_number(ep_m.group("episode").strip())
            i += 1
            continue

        # 2. Episode logline
        log_m = LOGLINE_PATTERN.match(line)
        if log_m:
            current_logline = log_m.group("logline").strip()
            i += 1
            continue

        # 3. Scene header
        sc_m = SCENE_PATTERN.match(line)
        if sc_m:
            current_scene = sc_m.group("scene").strip()
            current_heading = None
            i += 1
            continue

        # 4. Scene heading
        head_m = SCENE_HEADING_PATTERN.match(line)
        if head_m:
            current_heading = head_m.group("heading").strip()
            i += 1
            continue

        # 5. Check for Action/Dialogue line (starts with **)
        if line.startswith("**"):
            # A) Check if it is a single consolidated line:
            # **CAMERA:** Start: (00:00.00) | End: (00:04.80) Symmetrical framing...
            single_m = COMBINED_LINE_PATTERN.match(line)
            if single_m:
                raw_tag = single_m.group("tag")
                start_sec = time_to_seconds(single_m.group("start"))
                end_sec = time_to_seconds(single_m.group("end"))
                content = single_m.group("content").strip()
                entity, emotion = extract_entity_and_emotion(raw_tag)

                record = {
                    "Episode": current_episode,
                    "Scene": current_scene,
                    "Entity_Type": entity,
                    "Emotion": emotion,
                    "Start_Sec": start_sec,
                    "End_Sec": end_sec,
                    "Duration_Sec": round(max(0.0, end_sec - start_sec), 3),
                    "Content": content,
                }
                if include_extended_metadata:
                    record["Episode_Logline"] = current_logline
                    record["Scene_Heading"] = current_heading
                    record["Line_Index"] = len(records)
                records.append(record)
                i += 1
                continue

            # B) Check multi-line block format:
            # Line 1: **TAG:**
            # Line 2: Start: (...) | End: (...)
            # Line 3+: Content
            tag_m = ENTITY_TAG_PATTERN.match(line)
            if tag_m:
                raw_tag = tag_m.group("tag")
                entity, emotion = extract_entity_and_emotion(raw_tag)
                
                # Advance to check next line for timestamps
                i += 1
                start_sec = 0.0
                end_sec = 0.0
                content_parts = []

                # Find timestamp line
                while i < num_lines and not lines[i].strip():
                    i += 1

                if i < num_lines:
                    ts_m = TIMESTAMP_PATTERN.match(lines[i].strip())
                    if ts_m:
                        start_sec = time_to_seconds(ts_m.group("start"))
                        end_sec = time_to_seconds(ts_m.group("end"))
                        i += 1

                # Gather content until an empty line, a new '**' tag, a new SCENE, or script delimiter
                while i < num_lines:
                    c_line = lines[i].strip()
                    if not c_line:
                        break
                    if c_line.startswith("**") or c_line.startswith("SCENE ") or c_line.startswith("---"):
                        break
                    content_parts.append(c_line)
                    i += 1

                content = " ".join(content_parts).strip()
                record = {
                    "Episode": current_episode,
                    "Scene": current_scene,
                    "Entity_Type": entity,
                    "Emotion": emotion,
                    "Start_Sec": start_sec,
                    "End_Sec": end_sec,
                    "Duration_Sec": round(max(0.0, end_sec - start_sec), 3),
                    "Content": content,
                }
                if include_extended_metadata:
                    record["Episode_Logline"] = current_logline
                    record["Scene_Heading"] = current_heading
                    record["Line_Index"] = len(records)
                records.append(record)
                continue

        # If line does not match known patterns, advance to next
        i += 1

    core_cols = [
        "Episode",
        "Scene",
        "Entity_Type",
        "Emotion",
        "Start_Sec",
        "End_Sec",
        "Duration_Sec",
        "Content",
    ]
    if include_extended_metadata:
        cols = core_cols + ["Episode_Logline", "Scene_Heading", "Line_Index"]
    else:
        cols = core_cols

    df = pd.DataFrame(records, columns=cols)
    if "Episode" in df.columns:
        df["Episode"] = df["Episode"].apply(episode_number).astype(int)
    return df


if __name__ == "__main__":
    # Self-test on single line format
    test_snippet = """
EPISODE NUMBER: Episode 1 
EPISODE LOGLINE: Lady Juliana arrives...
--- SCRIPT START --- 
SCENE 01 
Scene heading: INT. CATHEDRAL   DAY 
Scene start: 00:00.00 
Scene end: 02:18.00 
Actions and dialogue: 
**CAMERA:** Start: (00:00.00) | End: (00:04.80) Symmetrical framing on the heavy church doors...
**ACTION:** Start: (00:01.00) | End: (00:04.80) Juliana pauses at the threshold...
**MATRIARCH (Cold, Commanding):** Start: (00:11.30) | End: (00:13.10) "You should turn around, Juliana."
"""
    df_test = parse_screenplay(test_snippet, include_extended_metadata=False)
    print("Self-test single-line format:")
    print(df_test.to_string())

