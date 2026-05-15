# Two Minds

A psychological conversation simulator — two AI characters at a Cape Town dinner party, observed by a narrator model that scores their emotional state, relationship dynamics, and psychological arc in real time.

Built with Flask, Ollama, and local LLMs. Runs entirely on your machine.

---

## What it does

Two characters converse autonomously. A third model (the narrator) watches every exchange and scores:

- **15 emotions** per character — happy, sad, curious, anxious, aroused, guarded, electrified and more — with decay rates and lexical triggers
- **8 relationship traits** — warmth, attraction, tension, depth, hostility, physical — updated every 4 turns
- **Therapist analysis** — plain text psychological interpretation every 4 turns
- **Party environment** — alcohol, hunger, scene events, topic seeds, time of night
- **Memory compression** — conversation history summarised every 30-50 turns so characters remember the evening

Everything runs locally. No API keys. No cloud.

---

## Profiles included

| File | Character |
|---|---|
| `james.json` | James — avoidant, dry wit, Mitchells Plain |
| `samantha.json` | Samantha — secure, sharp, Belhar |
| `james_dark.json` | James — charming predator, extraction playbook |
| `samantha_dark.json` | Samantha — narcissist, runs psychological arrangements |
| `james_psycho.json` | James — psychopath, three murders, nobody knows |
| `samantha_manic.json` | Samantha — manic episode, off meds, aroused by danger |

Swap profiles by changing two lines in the server file.

---

## Requirements

- macOS or Linux (Windows untested)
- Python 3.10+
- [Ollama](https://ollama.com) installed and running
- At least 8GB RAM (16GB recommended for larger models)
- GPU optional but significantly faster

---

## Quick start

```bash
git clone https://github.com/jody-wicomb/two-minds.git
cd two-minds
python3 setup.py
```

The setup script will:
1. Check Python version
2. Create a virtual environment
3. Install Python dependencies
4. Check Ollama is running
5. Pull required models
6. Verify everything works

Then run:

```bash
source venv/bin/activate
python3 two_minds_server.py
```

Open `http://localhost:5000/dashboard`

---

## Manual setup

If you prefer to do it yourself:

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install flask requests

# 3. Install Ollama
# macOS: brew install ollama
# Linux: curl -fsSL https://ollama.com/install.sh | sh

# 4. Pull models
ollama pull llama3.2      # James and Samantha
ollama pull mistral       # Narrator and therapist

# 5. Start Ollama (if not already running)
ollama serve

# 6. Run
python3 two_minds_server.py
```

---

## GPU acceleration (recommended)

If you have a separate GPU machine on your network:

```bash
# On the GPU machine — start Ollama
OLLAMA_HOST=0.0.0.0 ollama serve

# On your main machine — create SSH tunnel
ssh -L 11434:localhost:11434 user@gpu-machine-ip -N &

# Models will now run on the GPU
```

---

## Switching profiles

Edit the top of `two_minds_server.py`:

```python
JAMES    = load_character("james.json")       # change to james_dark.json etc
SAMANTHA = load_character("samantha.json")    # change to samantha_dark.json etc
```

For the dark/evil variants use `two_evil_minds_server.py` instead.

---

## Dashboard

`http://localhost:5000/dashboard` — everything in one view:

- **Left** — conversation feed with scene events, topic seeds, resonance events
- **Right top** — emotion portraits for both characters (15 emotions each)
- **Right middle** — relationship dynamics (8 traits)
- **Right bottom** — therapist psychological arc feed
- **Top bar** — party clock, alcohol, hunger, current scene

Other routes:
- `/` — chat only
- `/traits` — scoring log, nudges, character architecture, therapist arc
- `/emotions` — emotion sparkline history

Export button downloads a full annotated transcript with phase headers, all events, and psychological summary.

---

## Creating your own profiles

Copy any existing profile JSON and edit it. The structure:

```json
{
  "name": "Character name",
  "model": "llama3.2",
  "background": "One sentence biography",
  "self_regulation": 55,
  "attachment": "avoidant|secure|anxious|disorganised",
  "shadow": "What they hide from themselves",
  "essence": ["Array of 4-5 sentences that define them"],
  "voice_rules": ["How they speak"],
  "anti_assistant": ["What they must never do"],
  "forbidden_phrases": ["Phrases to avoid"],
  "messy_human_behaviours": ["Specific behaviour patterns"],
  "texture_examples": ["Example dialogue lines in their voice"],
  "hidden_life": ["Things they carry that haven't come up yet"],
  "goals_sample": ["What they want"],
  "opinions_sample": ["What they think"],
  "triggers": ["Words/topics that activate their wound"],
  "narrator_only": {
    "kink": "Private desires the narrator knows but never injects",
    "wound": "Core psychological wound",
    "pattern": "Relationship pattern"
  }
}
```

Drop the file in `profiles/` and point the server at it.

---

## Model recommendations

| Model | Size | Best for |
|---|---|---|
| `llama3.2` | 2GB | Characters — natural dialogue |
| `mistral` | 4.4GB | Narrator — analytical, JSON reliable |
| `openhermes` | 4.1GB | Characters — conversational fine-tune |
| `heretic-thinking` | 4.9GB | Dark profiles — abliterated |
| `phi4-mini` | 2.5GB | Not recommended — drifts to narration |

---

## Architecture

```
User browser
    │
    ▼
Flask server (two_minds_server.py)
    │
    ├── Character A prompt ──► Ollama (llama3.2) ──► response
    ├── Character B prompt ──► Ollama (llama3.2) ──► response
    ├── Narrator (every 4 turns) ──► Ollama (mistral) ──► JSON scoring
    ├── Therapist (every 4 turns) ──► Ollama (mistral) ──► plain text
    └── Lexical scanner (every turn) ──► no model call ──► instant scoring
```

Scoring layers:
1. **Lexical** — keyword triggers, fires every turn, no model call
2. **Narrator** — structural scoring, every 4 turns, JSON output
3. **Therapist** — psychological interpretation, every 4 turns, plain text
4. **Decay** — pulls scores back toward baseline every 2 turns

---

## Probe script

Test model limits before using in profiles:

```bash
python3 heretic_probe.py         # all 10 probes
python3 heretic_probe.py 1 6 10  # specific probes
```

---

## License

MIT. Do what you want with it. If you build something interesting, open a PR.

---

## Credits
Ruan Bekker for the idea
Ai models for existing
