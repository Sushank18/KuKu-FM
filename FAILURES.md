# ⚠️ Concrete Failure Cases & Anti-Patterns (FAILURES.md)

This document is automatically generated from the latest pipeline run. It catalogs up to 5 candidate picks that triggered deterministic rule check warnings or scored lowest in ranking.
All transcripts are extracted **verbatim** from the master screenplay lines by Line_ID.

---

### Case 1: Episode 1 (`00:52.80` to `01:50.80`, Duration: `58.0s`)
- **Candidate Source:** `UNKNOWN`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: THE FORMER GROOM not introduced in clip`
- **Cold Viewer Audit:** `PASS` (Cold viewer audit skipped due to API error.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E1-L035] LADY JULIANA: "You let me come here..."
[E1-L036] CAMERA: Close-up on Juliana's tear-streaked face as she shakes with grief.
[E1-L037] LADY JULIANA: "You let me dress in my mother's gown..."
[E1-L038] LADY JULIANA: "You let me believe I was walking toward my husband!"
[E1-L039] CAMERA: Medium shot on Gerald stepping forward, cold and indifferent, with the Lady in Gold Gown lingering in soft focus behind him.
[E1-L040] CAMERA: Tight close-up on Gerald's hardened profile as he glances down.
[E1-L041] THE FORMER GROOM: "I changed my mind."
[E1-L042] CAMERA: Extreme close-up on Juliana's furious, weeping face.
... [33 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: THE FORMER GROOM not introduced in clip

---

### Case 2: Episode 2 (`00:18.20` to `01:12.70`, Duration: `54.5s`)
- **Candidate Source:** `UNKNOWN`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: THE FORMER GROOM, BLOND NOBLEMAN not introduced in clip`
- **Cold Viewer Audit:** `PASS` (Cold viewer audit skipped due to API error.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E2-L015] LADY JULIANA: "You gave me your word before both our families."
[E2-L016] CAMERA: Medium two-shot of Gerald and Clarissa standing side by side before the priest.
[E2-L017] THE FORMER GROOM: "Promises change when a better choice appears."
[E2-L018] CAMERA: Medium close-up on Juliana clutching her chest, her voice quivering with disbelief.
[E2-L019] LADY JULIANA: "A better choice? Is that what she is?"
[E2-L020] CAMERA: Wide shot from behind Juliana looking up the altar stairs at Gerald with Clarissa linked to his arm.
[E2-L021] THE FORMER GROOM: "She is what I should have chosen from the beginning."
[E2-L022] CAMERA: Medium shot of Juliana's father seated prominently in the family pew, clutching his gold-topped cane.
... [30 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: THE FORMER GROOM, BLOND NOBLEMAN not introduced in clip

---

### Case 3: Episode 28 (`00:24.80` to `01:21.90`, Duration: `57.1s`)
- **Candidate Source:** `UNKNOWN`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: BLOND NOBLEMAN not introduced in clip`
- **Cold Viewer Audit:** `PASS` (Cold viewer audit skipped due to API error.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E28-L020] DOWAGER DUCHESS: "Rupert..."
[E28-L021] CAMERA: Medium shot of Rupert pausing mid-stride as he hears his mother's voice, slowly turning his head toward the bed.
[E28-L022] DOWAGER DUCHESS: "Stop this!"
[E28-L023] CAMERA: Wide shot of the bedchamber framed through the bed curtains as the Duchess props herself up on one elbow and points an accusing finger.
[E28-L024] DOWAGER DUCHESS: "She is innocent."
[E28-L025] DOWAGER DUCHESS: "She saved me!"
[E28-L026] CAMERA: Close-up of Juliana, tears of relief welling in her eyes.
[E28-L027] JULIANA: "Your Grace..."
... [34 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: BLOND NOBLEMAN not introduced in clip

---

### Case 4: Episode 33 (`00:57.40` to `01:53.50`, Duration: `56.1s`)
- **Candidate Source:** `UNKNOWN`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: LORD not introduced in clip`
- **Cold Viewer Audit:** `PASS` (Cold viewer audit skipped due to API error.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E33-L035] MAID: "No!"
[E33-L036] CAMERA: Profile medium two-shot as the Lord looms inches from the maid's face.
[E33-L037] LORD: "Think carefully."
[E33-L038] LORD: "Your brother is still a pauper."
[E33-L039] CAMERA: Extreme close-up of the Lord's cold eyes and hawkish profile speaking with chilling finality.
[E33-L040] LORD: "One word from me, and the county gaol will take him before sunrise."
[E33-L041] ACTION: The maid gasps in sheer terror, her chest heaving as tears stream.
[E33-L042] CAMERA: Close-up of the maid clutching her chest with trembling hands, crying desperately.
... [26 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: LORD not introduced in clip

---

### Case 5: Episode 34 (`01:18.80` to `02:14.40`, Duration: `55.6s`)
- **Candidate Source:** `UNKNOWN`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: PRUDENCE, LORD not introduced in clip`
- **Cold Viewer Audit:** `PASS` (Cold viewer audit skipped due to API error.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E34-L045] PRUDENCE: "Yes."
[E34-L046] CAMERA: Medium tracking shot of the Lord stepping into the open aisle of the courtroom with arms spread wide, turning triumphantly toward the Judge.
[E34-L047] LORD: "Your Honor... the witness has confirmed the ritual."
[E34-L048] ACTION: Lady Juliana slams her cuffed hands against the wooden railing of the dock, her voice ringing out in indignant fury.
[E34-L049] CAMERA: Low-angle medium shot of Lady Juliana gripping the railing, leaning forward.
[E34-L050] LADY JULIANA: "It was not a ritual!"
[E34-L051] ACTION: The Judge repeatedly hammers his gavel down onto the desk, roaring over her.
[E34-L052] CAMERA: Medium shot of the Judge striking the wooden block twice in rapid succession.
... [33 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: PRUDENCE, LORD not introduced in clip

---
