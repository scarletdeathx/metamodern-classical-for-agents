# Canon dataset result

Date: 2026-10-17 (America/Los_Angeles).

Branch: `canon-dataset`, created directly from
`midi-musical-controls` at `598a6e866173895bf6f3b0951f9e6f2d0cd989c6`.

**Implementation and tested generator commit:**
`8cc7f5b3540d9db9c411769ee679cfc830ac8c83`.
Both generation logs record this exact clean commit for every accepted piece.
This report is saved in a subsequent documentation-only commit so its hash can
identify the implementation without a self-referential commit hash.

All commits are local. Nothing was pushed. MIDI verification used file parsing;
no audio playback occurred. The repository smoke and integration checks used the
silent null backend and isolated temporary state.

## Commands

Run from the repository root:

```sh
git switch -c canon-dataset midi-musical-controls
.venv/bin/python -m pip install 'PyYAML>=6,<7'
.venv/bin/python -m unittest discover -s tests -v > /tmp/mcfa-canon-tests.txt 2>&1
.venv/bin/python scripts/smoke_demo.py --backend null > /tmp/mcfa-canon-smoke.txt 2>&1
git diff --check
```

Local implementation commit:

```sh
git add README.md pyproject.toml src/mcfa/dataset.py src/mcfa/midi_controls.py \
  src/mcfa/midi_timing.py src/mcfa/recipes.py tools/eshkol_midi.py \
  tools/mcfa_dataset.py tools/verify_dataset.py tests/test_dataset.py \
  tests/test_midi_controls.py recipes/canon.yaml recipes/chaos-60s.yaml
git commit -m 'Add canon MIDI recipes with isolated provenance and tempo duration planning'
```

The two generation commands ran independently with local socket access:

```sh
.venv/bin/python tools/mcfa_dataset.py --recipes recipes/canon.yaml \
  --out /tmp/mcfa-canon --log /tmp/mcfa-canon-log.jsonl \
  > /tmp/mcfa-canon-generate.txt 2>&1
.venv/bin/python tools/mcfa_dataset.py --recipes recipes/chaos-60s.yaml \
  --out /tmp/mcfa-chaos60 --log /tmp/mcfa-chaos60-log.jsonl \
  > /tmp/mcfa-chaos60-generate.txt 2>&1
.venv/bin/python tools/verify_dataset.py /tmp/mcfa-canon \
  --recipes recipes/canon.yaml --log /tmp/mcfa-canon-log.jsonl \
  > /tmp/mcfa-canon-verify.json
.venv/bin/python tools/verify_dataset.py /tmp/mcfa-chaos60 \
  --recipes recipes/chaos-60s.yaml --log /tmp/mcfa-chaos60-log.jsonl \
  > /tmp/mcfa-chaos60-verify.json
```

Resume was exercised through `generate_dataset` for both completed outputs with
`recipes=...` and `resume=True`. Every MIDI file's bytes and modification time
were compared before and after; both datasets skipped all 100 files, made zero
pieces, and left MIDI bytes and mtimes unchanged.

## Files changed

| File | Change |
|---|---|
| `src/mcfa/dataset.py` | MIDI-only dataset layout, atomic per-piece manifest updates, manifest/MIDI recovery, SHA256 deduplication, optional external provenance/reject logs, duration and recipe orchestration. |
| `src/mcfa/midi_timing.py` | Entropy-derived tempo values, encoded MIDI tempo jump limits, bar-boundary maps, whole-bar duration planning. |
| `src/mcfa/midi_controls.py` | Validated variation for velocity, length sets, lane layouts, programs, tempo change counts and jump limits. |
| `src/mcfa/recipes.py` | Safe YAML/JSON parsing, recipe validation and schedule construction. |
| `tools/mcfa_dataset.py` | Recipe, log, duration, automation and expanded variation CLI flags. |
| `tools/eshkol_midi.py` | Neutral lane names and correctly merged tempo/note events. |
| `tools/verify_dataset.py` | Independent parsing verifier for inventory, hashes, labels, meter, tempo, scale/range, note pairing, duration, velocity, lengths and programs. |
| `recipes/canon.yaml` | Ten recipes, ten pieces each. |
| `recipes/chaos-60s.yaml` | One 100-piece recipe, 60-second target, all controls varied. |
| `tests/test_dataset.py` | Layout, sharding, fields, logging, labels, automation, duration, recipes, recovery, deduplication and entropy-failure tests. |
| `tests/test_midi_controls.py` | Existing dataset assertions updated for manifest/external-log output; existing musical-control tests retained. |
| `pyproject.toml` | Optional `dataset` dependency group containing mido and PyYAML. |
| `README.md` | Usage, schema, recovery semantics and timing behavior. |
| `CANON-DATASET-RESULT.md` | This result report. |

Unrelated pre-existing untracked files (`ALIGNMENT.md`,
`BACKBURNER_QRNG_GENESIS.md`, `mcfa-eshkol.tar.gz`) were left untouched and were
not committed.

## Test results

- Full suite: **96 tests passed**, 6.785 seconds.
- Silent smoke: **PASS**, ten independent lanes, persistent conductor,
  kill/rewrite/restart, sync/free changes, history, safe deadline; **0 underruns**.
- `git diff --check`: passed.
- Baseline before edits: 80 tests, with 75 passing and five CLI daemon startup
  errors under sandbox restrictions. All five passed with local socket access;
  no unrelated CLI changes were made.
- A separate deterministic 100-piece chaos dry run passed the independent parser
  with 100 distinct hashes, 100% note compliance and all durations in tolerance.
  Its synthetic entropy fixture was test-only; both requested final datasets
  used the real drawd path below.

Tests cover missing/truncated manifests, missing MIDI, stale manifest hashes,
recipe-ID recovery, dedupe after recovery, atomic write failures, log refusal
including symlink paths, logging disabled during rejects, label-free MIDI bytes,
bar-boundary tempo events, encoded maximum jumps (including zero), static and
changing-tempo duration targets, infeasible-map redraws, JSON/YAML recipes, and
fatal entropy failures/short draws without a fallback.

## End-to-end results

| Parsed property | Canon | Chaos 60 s |
|---|---:|---:|
| Accepted pieces | 100 | 100 |
| Distinct MIDI SHA256 | 100 | 100 |
| MIDI bytes | 142,577 | 815,289 |
| Notes | 14,767 | 95,372 |
| Notes in configured scale and lane range | 14,767 / 14,767 (100%) | 95,372 / 95,372 (100%) |
| Duration min (s) | 7.090278 | 58.393680 |
| Duration max (s) | 77.246655 | 61.980246 |
| Duration mean (s) | 19.187453 | 60.027227 |
| Pieces with tempo automation | 20 | 100 |
| Additional tempo events per piece | 0–5 | 1–8 |
| Observed BPM min | 42.299992 | 40.407061 |
| Observed BPM max | 217.481134 | 219.600035 |
| Recipe/preset/source label leaks in MIDI bytes | 0 | 0 |
| Rejected attempts | 0 | 2 |
| Entropy contributor failures | 0 | 0 |

All 100 chaos durations satisfy **60 +/-2 seconds**, including trailing rests
and tempo changes. Canon has no requested duration target. The combined datasets
have **200 distinct hashes**.

Canon counts, parsed from the manifest and checked against the recipes:

| Recipe | Pieces |
|---|---:|
| control | 10 |
| static-tempo-varied-scale | 10 |
| wide-tempo | 10 |
| tempo-automation | 10 |
| odd-meters | 10 |
| sparse | 10 |
| dense | 10 |
| narrow-clustered | 10 |
| wide-registers | 10 |
| everything-varied | 10 |

Chaos contains exactly 100 `chaos-60s` pieces. Observed variation spans all
**12 keys**, **15 canonical scales**, and all **7 listed meters** (`2/4`, `3/4`,
`4/4`, `5/4`, `6/8`, `7/8`, `12/8`), with 95 distinct starting tempos, lane counts
1–8, 46 different bar counts, 87 rest probabilities, all four velocity options,
all four length-set options, all four lane layouts, and 72 GM program choices.
All 128 programs are eligible in the recipe; a finite entropy sample need not
contain every eligible program.

The parser also checked note velocities and allowed lengths (including final
clipped notes), balanced note-on/off events, programs/channels, exact track bar
endpoints, starting/min/max tempo metadata, interior bar boundaries, automation
event counts and maximum tempo jumps against the external provenance logs.

Every recorded contributor is required `eshkol-local:moonlab`, through
RNGoddess's `rngoddess-shake256-v1` mixer and local drawd. Accepted-piece logs
contain 480 draws for canon and 646 for chaos, plus the chaos log's two rejected
attempts. Both rejects were infeasible whole-bar duration maps, then redrawn from
fresh entropy. No Python random is used for musical choices. Source failures
raise immediately; no alternative entropy source is substituted.

## Output locations and recovery decisions

Dataset directories contain only `manifest.jsonl` and sharded MIDI files, here
`midi/000/000000.mid` through `midi/000/000099.mid`. The shard path function is
verified across the 999/1000 boundary (`000/000999.mid`, `001/001000.mid`).

Optional logs and summary cards are outside both dataset directories:

- `/tmp/mcfa-canon-log.jsonl`
- `/tmp/mcfa-canon-log.jsonl.summary.md`
- `/tmp/mcfa-chaos60-log.jsonl`
- `/tmp/mcfa-chaos60-log.jsonl.summary.md`

As explicitly agreed during implementation, a rebuilt manifest takes recipe
membership from ID order in the supplied recipe file. Unrecoverable intent
(key, scale, configured lane ranges) is `null`; valid hash-matching rows retain
it. MIDI facts such as tempo, meter, duration and note counts are reparsed.
Previous-format datasets containing `meta/`, dataset cards or reject sidecars
are refused with an instruction to use a new output directory, preserving those
existing files rather than deleting provenance.

Duration planning searches whole-bar solutions for the encoded tempo map. An
infeasible entropy-drawn map is a logged reject; attempts are bounded at 16 per
piece. An infeasible fixed target or exhausted retries raises explicitly.
