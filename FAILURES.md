# ⚠️ Concrete Failure Cases & Anti-Patterns (FAILURES.md)

This document catalogs 5 concrete failure modes identified during evaluation where raw LLM candidate selection or naive heuristics produce low-converting promotional clips. It outlines the transcript snippet, the deterministic check triggered, and the exact conversion reason.

---

### Failure Case 1: Mid-Sentence Ellipsis Continuation (Check_Start Failed)
- **Episode:** 2 (`00:06.80` to `00:35.00`)
- **Triggered Check:** `Check_Start` (FAIL: Starts with ellipsis continuation)
- **Transcript Snippet:**
  ```text
  [JULIANA]: "...far too silent..."
  [GERALD]: "Juliana, you cannot mean to create a scene here before the congregation."
  [JULIANA]: "A scene? You broke our vows before God and our families!"
  ```
- **Why It Fails:** 
  The clip begins midway through Juliana's thought (*"...far too silent..."*). In short-form video ads (TikTok/Reels), users decide within 400ms whether to swipe. A fragmented sentence signals bad editing and disorients cold viewers, cutting initial retention by over 40%.
- **System Correction:** The deterministic boundary snapper rejects any start line beginning with `"..."` or lowercase text, automatically advancing to the first clean grammatical dialogue sentence.

---

### Failure Case 2: Silent Atmospheric Establishing Shot (Check_Hook Failed)
- **Episode:** 1 (`00:00.00` to `00:25.00`)
- **Triggered Check:** `Check_Hook` (FAIL: No spoken line or action within first 3.0s)
- **Transcript Snippet:**
  ```text
  [CAMERA]: Symmetrical framing on the heavy church doors as they slowly part, pushing in slightly...
  [ACTION]: Juliana pauses at the threshold, her expression bright with joyful anticipation...
  [CAMERA]: High wide tracking shot following behind Juliana as she steps into the grand cathedral nave...
  ```
- **Why It Fails:** 
  For the first 6.8 seconds, there is zero dialogue or high-stakes action—only ambient architecture and slow pacing. Television dramas use slow reveals; vertical microdramas die without immediate tension in seconds 0-3.
- **System Correction:** `Check_Hook` mandates that a spoken character line or high-impact dramatic action occurs within 3.0 seconds of `Start_Time`.

---

### Failure Case 3: Resolution & Exit Walk-Off (Check_End Failed)
- **Episode:** 4 (`02:15.00` to `02:35.00`)
- **Triggered Check:** `Check_End` (FAIL: Ends on resolution/exit action)
- **Transcript Snippet:**
  ```text
  [ALEXANDER]: "The contract is signed. She is my wife now."
  [FATHER]: "You will regret this, Duke."
  [ACTION]: Alexander turns in his wheelchair and rolls out of the room, the heavy oak doors closing behind him as the scene fades out.
  ```
- **Why It Fails:** 
  Ending on the character leaving the room and the doors closing provides narrative resolution. The viewer feels closure rather than urgency to install the app or unlock Episode 5.
- **System Correction:** `Check_End` detects resolution actions (walking away, leaving the room, door closing, fading out) and penalizes or adjusts the cut point to slice before the tension dissipates.

---

### Failure Case 4: Unanchored Dialogue Without Speaker Introduction (Check_Context Failed)
- **Episode:** 5 (`00:10.00` to `00:35.00`)
- **Triggered Check:** `Check_Context` (needs_context: CLARISSA not introduced in clip)
- **Transcript Snippet:**
  ```text
  [CLARISSA]: "Did you hear what happened in the drawing room?"
  [MAID]: "Yes, my lady. They say the Duke himself intervened."
  [CLARISSA]: "She will pay for humiliating Gerald."
  ```
- **Why It Fails:** 
  A cold viewer has no idea who "Clarissa" is, who "Gerald" is, or why they are plotting. Microdrama ads require instant emotional legibility: either the dialogue explicitly names relationships ("As your sister...", "Father!"), or archetype titles clarify roles immediately.
- **System Correction:** The "Cold Viewer" LLM pass and `Check_Context` flag clips lacking self-contained relationship markers, deprioritizing them during cross-episode ranking.

---

### Failure Case 5: Prolonged Duration Exceeding Ad Placement Limits
- **Episode:** 3 (`01:00.00` to `02:15.00` -> 75.0s)
- **Triggered Check:** `Duration Validation` (Violates strict 20-60s limit)
- **Transcript Snippet:**
  ```text
  [Duration: 75.0s across 3 full scene transitions]
  ```
- **Why It Fails:** 
  Clips over 60 seconds fail Meta and TikTok Spark Ad placement guidelines for short-form video formats, experiencing steep drops in complete watch-through rate.
- **System Correction:** Line-ID anchoring recalculates exact millisecond durations directly from line item timestamps in code, instantly triggering automated retries if a candidate exceeds 60.0s.
