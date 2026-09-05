# Apex AI V7 — Better Images + 1M Local Knowledge

V7 fixes the biggest two limitations in V6:

1. Tiny-SD has been replaced by a much higher-quality DreamShaper-7 LCM image engine.
2. Apex now supports a local 1,000,000-record searchable Q&A knowledge pack.

## Better images

V7 uses a quantized DreamShaper-7 LCM model through stable-diffusion.cpp.

Default rendering:

- 512×512
- LCM sampler
- 6 steps
- CFG 1.0
- auto prompt style detection
- stronger anatomy / hands / face negative prompting

Image styles:

- Auto
- Anime / 2D
- Illustration
- Photo
- Cinematic
- Fantasy
- Comic
- Pixel art

Typing something like:

```text
2D girl with black hair wearing a blue jacket in a city at night
```

automatically switches to the Anime / 2D prompt booster instead of sending the raw phrase to a tiny generic model.

## 1,000,000 Q&A knowledge pack

Apex builds a local SQLite FTS5 database containing exactly 1,000,000 searchable Q&A records.

The builder prioritizes general-purpose QA first:

- SQuAD
- TriviaQA
- WikiQA

Then it uses Math-1M reasoning Q&A to fill the database to exactly 1,000,000 rows.

At chat time Apex does NOT dump all one million records into the prompt. It searches the local FTS index and inserts only the most relevant 1–10 Q&As into the model context. That is much faster and more useful.

You can control it in:

```text
Settings → Knowledge
```

Features include:

- enable / disable local retrieval
- choose number of retrieved Q&As
- see installed record count
- test local knowledge searches

## One command

```bash
cd ~/Downloads && rm -rf apex-ai-v7 && unzip -o apex-ai-v7.zip && cd apex-ai-v7 && chmod +x setup-and-run.sh run.sh install-image-engine.sh install-knowledge.sh image-engine/start-image-engine.sh && ./setup-and-run.sh
```

Open:

```text
http://localhost:8765
```

## First-run downloads

V7 intentionally keeps the ZIP small. The first setup downloads/builds the components locally:

- DreamShaper-7 LCM Q4 image model: about 1.63 GB
- stable-diffusion.cpp source/build
- QA source datasets used to construct the local 1M SQLite index

The Q&A data is stored locally after the one-time build in:

```text
data/knowledge_1m.db
```

## Skip optional installers

Chat only:

```bash
SKIP_IMAGE_ENGINE=1 SKIP_KNOWLEDGE=1 ./setup-and-run.sh
```

Skip only knowledge:

```bash
SKIP_KNOWLEDGE=1 ./setup-and-run.sh
```

Rebuild/install knowledge later:

```bash
./install-knowledge.sh
```

Install the better image engine later:

```bash
./install-image-engine.sh
```
