# ⚠️ Concrete Failure Cases & Anti-Patterns (FAILURES.md)

This document is automatically generated from the latest pipeline run. It catalogs up to 5 candidate picks that triggered deterministic rule check warnings or scored lowest in ranking.
All transcripts are extracted **verbatim** from the master screenplay lines by Line_ID.

---

### Case 1: Episode 1 (`00:11.00` to `01:05.60`, Duration: `54.6s`)
- **Candidate Source:** `LLM:gemini-3.5-flash-lite`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: THE FORMER GROOM not introduced in clip`
- **Cold Viewer Audit:** `PASS` (The viewer immediately understands the high-stakes dramatic conflict as Juliana arrives at her wedding only to find her groom has betrayed her by marrying another woman.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E1-L007] CAMERA: Medium shot as Juliana stops midway down the aisle, confronted by a haughty matriarch in black velvet stepping into the foreground.
[E1-L008] MATRIARCH: "You should turn around, Juliana."
[E1-L009] LADY JULIANA: "Why?"
[E1-L010] CAMERA: Over-the-shoulder medium close-up past the Matriarch to Juliana, looking past her toward the altar.
[E1-L011] LADY JULIANA: "Gerald is waiting for me."
[E1-L012] CAMERA: Close-up on the Matriarch wearing an ornate tiara and sapphire jewelry, gazing down with merciless disdain.
[E1-L013] MATRIARCH: "Not anymore."
[E1-L014] CAMERA: Close-up on Juliana's stricken face as the weight of the words sinks in.
... [29 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: THE FORMER GROOM not introduced in clip

---

### Case 2: Episode 2 (`00:00.00` to `00:30.50`, Duration: `30.5s`)
- **Candidate Source:** `LLM:gemini-3.5-flash-lite`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `needs_context: THE FORMER GROOM not introduced in clip`
- **Cold Viewer Audit:** `PASS` (The dramatic rejection at the altar clearly establishes the conflict of public betrayal and heartbreak for a first-time viewer.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E2-L002] THE FORMER GROOM: "I cannot marry you, Juliana."
[E2-L003] CAMERA: Medium close-up on Juliana trembling in disbelief, her hands clasped tightly to her chest.
[E2-L004] ACTION: Juliana gasps softly in heartbreak, her eyes wide and brimming with tears.
[E2-L005] CAMERA: Medium shot returning to Gerald, sneering down at Juliana.
[E2-L006] THE FORMER GROOM: "You are far too plain..."
[E2-L007] CAMERA: Close-up on Juliana's tear-streaked face, crushed under his biting words.
[E2-L008] THE FORMER GROOM: "...far too silent..."
[E2-L009] CAMERA: Medium shot on Gerald turning slightly toward Clarissa as she smiles admiringly at him.
... [12 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Context flaw: needs_context: THE FORMER GROOM not introduced in clip

---

### Case 3: Episode 29 (`01:34.20` to `01:56.69`, Duration: `22.5s`)
- **Candidate Source:** `LLM:gemini-3.5-flash-lite`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `PASS`
- **Cold Viewer Audit:** `FAIL` (The viewer is dropped into an unanchored medieval dungeon scene with unexplained names like Duchess, Alexander, and Mother, leaving the core conflict and stakes completely confusing.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E29-L060] JULIANA: "Mother..."
[E29-L061] CAMERA: Medium shot as Juliana pushes herself off the wet stone floor and dashes toward the barred wicket of the heavy door.
[E29-L062] JULIANA: "I have done nothing!"
[E29-L063] CAMERA: Tight profile close-up of Juliana gripping the rusted iron bars, screaming out into the empty stone corridor.
[E29-L064] JULIANA: "I saved her! I healed her!"
[E29-L065] CAMERA: Medium shot from inside the cell as Juliana pounds her fists rhythmically against the reinforced iron door.
[E29-L066] SOUND FX: Muffled, dull metallic clanging reverberates as Juliana hammers against the iron door.
[E29-L067] JULIANA: "I saved the Duchess!"
... [7 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Cold viewer fail: The viewer is dropped into an unanchored medieval dungeon scene with unexplained names like Duchess, Alexander, and Mother, leaving the core conflict and stakes completely confusing.

---

### Case 4: Episode 3 (`01:59.80` to `02:25.75`, Duration: `25.9s`)
- **Candidate Source:** `LLM:gemini-3.5-flash-lite`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `PASS`
- **Cold Viewer Audit:** `FAIL` (The clip drops the viewer into a dramatic wedding interruption without explaining who the characters are, why Juliana's chance at being a wife was stolen, or what the relationship is between the stranger and Gerald.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E3-L101] THE BEARDED STRANGER: "You came here to become a wife."
[E3-L102] CAMERA: Medium shot on The Bearded Stranger extending the ring toward Juliana.
[E3-L103] THE BEARDED STRANGER: "They took that from you."
[E3-L104] CAMERA: Over-the-shoulder medium shot past The Bearded Stranger onto Gerald standing petrified and humiliated in the aisle.
[E3-L105] CAMERA: Medium close-up on The Bearded Stranger presenting the ring directly to Juliana.
[E3-L106] THE BEARDED STRANGER: "I am offering it back."
[E3-L107] CAMERA: Close-up on Juliana glancing down at the ring, breathless and overwhelmed.
[E3-L108] LADY JULIANA: "You don't even know me."
... [10 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Cold viewer fail: The clip drops the viewer into a dramatic wedding interruption without explaining who the characters are, why Juliana's chance at being a wife was stolen, or what the relationship is between the stranger and Gerald.

---

### Case 5: Episode 48 (`00:02.40` to `00:26.50`, Duration: `24.1s`)
- **Candidate Source:** `LLM:gemini-3.5-flash-lite`
- **Triggered Checks:**
  - `Check_Hook`: `PASS`
  - `Check_Start`: `PASS`
  - `Check_End`: `PASS`
  - `Check_Context`: `PASS`
- **Cold Viewer Audit:** `FAIL` (The viewer is given unfamiliar names like Catherine and Alexander with no context about who they are or what healer's crown is at stake.)
- **Verbatim Transcript Snippet (Verified from Source):**
  ```text
[E48-L003] CATHERINE: "Two words, and that healer's crown rolls right back into the gutter where it belongs."
[E48-L004] CAMERA: Close-up on Catherine's profile and jewelry as she speaks with calculating contempt.
[E48-L005] ACTION: Catherine glides across the chamber past a roaring stone hearth, picking up an orange from a silver platter on the table.
[E48-L006] CATHERINE: "Ten days. He gave himself ten days to fix it."
[E48-L007] CAMERA: Medium close-up frontal shot of Catherine turning directly toward the viewer, her expression tightening into ruthless determination.
[E48-L008] CATHERINE: "Ten days for the council to sit."
[E48-L009] ACTION: Catherine raises a gloved index finger, emphasizing each point with sinister precision.
[E48-L010] CATHERINE: "Ten days for witnesses to be gathered."
... [4 additional lines omitted] ...
  ```
- **Why It Fails / Deficiencies:**
  - Cold viewer fail: The viewer is given unfamiliar names like Catherine and Alexander with no context about who they are or what healer's crown is at stake.

---
