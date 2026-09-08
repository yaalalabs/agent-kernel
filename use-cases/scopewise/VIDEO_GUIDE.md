# ScopeWise demo video guide — 3:50 target

Record the interface silently in short clips, then add one AI voice in CapCut. Do not record model waiting time, passwords, invitation codes, personal material, Telegram setup, or browser notifications.

## Prepare before recording

1. Open `http://127.0.0.1:8080/`, hard-refresh, and sign in.
2. Confirm the module switcher contains **DSA - Data structures and Algorithms** and **ScopeWise competition demo**.
3. In **DSA - Data structures and Algorithms** (lecturer: **Dr Piumal**), open **Check results**. This is the prepared real local-model run from the two uploaded PDFs: 16 grounded objectives, 17 extracted questions and a completed comparison.
4. In **ScopeWise competition demo**, open **Check results**. This is the fresh original synthetic material with human-authored judgments; describe it exactly that way. Do not edit this module until recording Clip 6.
5. Close other apps and notifications. Use browser zoom around 110%. Hide or crop the username.
6. Create a folder on the Desktop named `ScopeWise Demo Clips`.

## Record these silent clips

Use `Shift + Command + 5` on macOS, choose **Record Selected Portion**, select only the browser, and leave the microphone off.

### Clip 1 — `01-title-home.mov` — 0:00–0:20

- Start on **DSA - Data structures and Algorithms → Home**.
- Hold for two seconds.
- Slowly move to **Upload materials**.
- Show the two PDF cards. Do not reopen or expose private page content.

### Clip 2 — `02-real-results.mov` — 0:20–1:05

- Open **Check results** in **DSA - Data structures and Algorithms**.
- Show the prepared summary.
- Expand **Inspect or correct individual questions**.
- Open one question and its original source citation.
- Open **Review both decisions**.

### Clip 3 — `03-agent-kernel.mov` — 1:05–1:35

- In the same question, show **Compared by the local ScopeWise agent**.
- Expand **Technical details for judges**.
- Pause on `AgentService`, `scopewise_align`, retrieval mode, candidate count, exclusions checked and the human-decision reminder.

### Clip 4 — `04-synthetic-evidence.mov` — 1:35–2:15

- Switch to **ScopeWise competition demo**.
- Open **Check results**.
- State in the voiceover that this module is synthetic and human-reviewed.
- Show the definition question with separate syllabus/assessment judgments.
- Show the BCNF proof with its explicit exclusion.
- Show the indexing question remaining uncertain.

### Clip 5A — `05-pack-request.mov` — 2:15–2:35

- Click **Make recommended pack**.
- Request **8** questions.
- Keep **Generate missing questions** enabled.
- Select **Medium**.
- Click **Make pack**, then stop recording immediately.

Wait off-camera until the pack finishes.

### Clip 5B — `06-pack-result.mov` — 2:35–3:00

- Open the finished pack.
- Show uploaded questions first.
- Show an **AI-generated practice** label and **Medium** difficulty.
- Show grounding/source information, coverage and **Download / print**.

### Clip 6 — `07-change-impact.mov` — 3:00–3:30

- In **ScopeWise competition demo**, open **More options → Module settings**.
- Change the lecturer name to `Dr. Silva` and save.
- Show the change-impact card, stale analysis/pack counts and the requirement to reconfirm current guidance.
- Do this only after recording the pack clips because the change intentionally makes that pack stale.

### Clip 7 — `08-proof-close.mov` — 3:30–3:50

- Record the terminal output of `.venv/bin/python -m scripts.judge_check --full`, or use the already verified result.
- End on the repository README or a simple title card:

  `ScopeWise — current scope, relevant practice, visible evidence.`

  `Local Agent Kernel + Ollama • No mandatory paid API • No exam predictions`

## Exact AI voiceover script

Paste each paragraph into a separate CapCut text block so each scene can be timed independently.

**0:00–0:20**

> A student searching one topic finds hundreds of videos and questions, but many are too basic, too advanced, or based on an older lecturer's format. ScopeWise finds practice that fits the exact material being studied now.

**0:20–1:05**

> The student uploads current module material and a past paper. ScopeWise extracts text by page, keeps exact citations, and prepares the comparison locally. This prepared Data Structures and Algorithms run for Dr Piumal used the two uploaded PDFs and produced sixteen grounded scope items and seventeen paper questions. The files stay in the private SQLite workspace, while local embeddings and keyword retrieval help find relevant evidence.

**1:05–1:35**

> Every question receives two independent judgments: does it fit the current syllabus, and does it match current answer-format guidance? Agent Kernel is on the real execution path. AgentService runs the registered alignment agent, exclusions are checked first, and the server validates every returned reference and citation. The agent proposes; the student keeps the final decision.

**1:35–2:15**

> This next module is clearly labelled synthetic demonstration material with human-authored judgments. A key-definition question is still in scope, but its old standalone format differs from current worked-example guidance. A BCNF proof is beyond scope only because the current outline explicitly excludes it. Indexing stays uncertain because absence from the notes is not proof of exclusion.

**2:15–3:00**

> ScopeWise now builds an eight-question medium practice pack. Reviewed uploaded questions are used first. When there are too few, a local generation agent fills only the missing slots from confirmed objectives and current guidance. Generated questions are clearly labelled, grounded, and presented as practice rather than exam predictions. Exact duplicates are removed and remaining coverage gaps stay visible.

**3:00–3:30**

> A lecturer change does not prove that the examination changed. ScopeWise records the change, marks dependent comparisons and packs as stale, withdraws the earlier assessment guidance, and asks the student to confirm current evidence. Curriculum change becomes inspectable instead of guessed.

**3:30–3:50**

> ScopeWise reduces wasted study time while keeping evidence, uncertainty and human review visible. It runs with Agent Kernel and local Ollama, needs no mandatory paid model API, and supports quality education without claiming to predict the next exam.

## Edit in CapCut

1. Open CapCut Desktop → **Create project** → set the canvas to **16:9**.
2. Import the eight `.mov` clips and arrange them in filename order.
3. Remove pauses, loading screens and accidental cursor movement.
4. Add a four-second opening title: **ScopeWise — Practice the module you have now**.
5. For each narration paragraph: **Text → Add text → paste paragraph → Text to speech → choose one calm English voice → Generate speech**.
6. Keep one voice throughout. Use roughly normal speed; shorten the visuals instead of making the voice unnaturally fast.
7. Generate automatic captions from the finished voice track. Correct `ScopeWise`, `Agent Kernel`, `Ollama`, `BCNF` and `SQLite` manually.
8. Use simple cuts and one subtle zoom when opening evidence. Avoid loud music, animated stickers and repeated transitions.
9. Export as **MP4, 1920×1080, 30 fps, H.264**, with high/recommended bitrate.

## Final checks

- Duration is below four minutes.
- Text is readable at normal playback size.
- No credentials, invitation codes, personal PDFs, email addresses or Telegram codes appear.
- The real **DSA - Data structures and Algorithms** result is described as a prepared local-model run.
- The synthetic module is described as synthetic and human-authored.
- The video never claims exam prediction, public production deployment, live Telegram or measured general accuracy.
- Upload the final MP4 to Google Drive, set **Anyone with the link → Viewer**, then test the link in a private browser window before submitting it.
