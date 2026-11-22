# Run the tests yourself

Which model works best depends on your voice, accent and microphone. The lab in `lab/` lets you record your own
test lines and compare models on them, the same way we did for the [lab report](lab-report.md).

All commands run from `~/wowvoice` in Desktop Mode, after `source env.sh`. Close WoW first: it competes for the
CPU and GPU and makes every timing slower.

## 1. Write your lines

`lab/lines.txt` holds 51 typical WoW chat lines, `lab/lines-fresh.txt` 28 more for a second check. Edit them freely,
one message per line (`#` starts a comment). Put the names you actually use (friends, guild, characters) in a few
lines, and in `lab/names.txt`; `lab/names-big.txt` adds 200 names that are never said, to catch wrongly inserted
names.

## 2. Record them

```bash
python3 lab/record.py                 # lines.txt       -> lab/recordings/
python3 lab/record.py --set fresh     # lines-fresh.txt -> lab/recordings-fresh/
```

Hold **Space**, read the line, let go. ← / → move between lines, **P** plays a recording back, **Esc** quits.
Speak as you would in the game. Your recordings stay on your Deck.

## 3. Transcribe them

Each runner writes one result file per run to `lab/results/` (or `results-fresh/` with `--set fresh`).

**The shipped setup** (Parakeet unified-en on the GPU) and its names step:

```bash
envs/sherpa/bin/python lab/run_transcribe.py \
  models/gguf/handy-computer--parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-F16.gguf parakeet-gpu
python3 lab/namefix_eval.py parakeet-gpu --names lab/names-big.txt      # saves parakeet-gpu+fix
```

**Other engines** (each needs its own model download; see the script's first lines):

| Script | Engine | Environment |
|---|---|---|
| `run_transcribe.py` | transcribe.cpp (GGUF models, Vulkan GPU or `--cpu`); `--names` for Qwen3-ASR | `envs/sherpa` |
| `run_crisp.py` | CrispASR (GGUF models, Vulkan) | `envs/sherpa` + the CrispASR binary in `tools/crispasr/` |
| `run_sherpa.py` | sherpa-onnx (ONNX models, CPU); `--hotwords` | `envs/sherpa` |
| `run_whisper.py` | faster-whisper (CPU); `--prompt` for names | `envs/sherpa` |
| `run_nemo.py` | NVIDIA NeMo (CPU, full precision); `--beam`, `--boost` for names | `envs/nemo` |
| `run_qwen.py` | Qwen3-ASR via transformers (CPU) | `envs/nemo` |

The NeMo environment is large (PyTorch, about 5 GB):

```bash
uv venv --python 3.12 envs/nemo
uv pip install --python envs/nemo/bin/python -r envs/requirements-nemo.txt \
  --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cpu
```

## 4. Compare

```bash
python3 lab/score.py --names lab/names-big.txt
python3 lab/score.py --set fresh --names lab/names-big.txt
python3 lab/score.py -v parakeet-gpu+fix          # every mistake of one run
```

| Column | Meaning |
|---|---|
| WER | word error rate: wrong, missing and extra words per word said (lower is better) |
| exact | lines without a single mistake |
| names | names and terms from the list that came out right |
| false | list terms written although you didn't say them |
| sec/line | compute time per line with the model loaded |

Numbers are normalised before comparing (lowercase, no punctuation, "twenty five" = 25), so only real
mistakes count. With 50-80 lines, differences of one or two points are within noise.

## 5. Play-testing (optional)

`lab/game_test.py`, `lab/game_series.sh` and `lab/fps_analyze.py` measure WoW's frame rate while a model
transcribes. They need the small frame-logging addon in `lab/WowVoiceFPS` (copy it into WoW's AddOns folder like the main addon).

## Share your results

If you test other voices, accents or headsets, we'd love to hear how the models compare: open an issue with
your `score.py` tables (not your recordings).
