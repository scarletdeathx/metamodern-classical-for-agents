# Chunked mode result

Date: 2026-10-27 (America/Los_Angeles).

Repository: `/Users/scarletdeath/Downloads/masocore/Codex/PYBEAT`.
Branch: `codex/chunked-output`, created from `nightmare-dataset` at
`5db9f5ac3953c7a05b3187f462ea0db0c1000c2c` after inspecting the working tree and
preserving the unfinished prior-work checkpoint.

**Implementation and acceptance-tested commit:**
`2a3bcf969b04aafab50bb698356e73f6bc714f66`.
This result file is committed separately afterward so it can identify the exact
implementation without a self-referential commit hash. Local commits only;
nothing pushed. No AI/co-author lines. No correspondence was sent to other chats.

## Result

**PASS.** The optional `--chunked` write path matches the supplied oracle for
MIDI and NumPy bytes. The actual Ubuntu reference process was executed in memory
against the same source MIDI samples: **3 pieces, 8 MIDI matches,
8 NumPy matches, zero mismatches**. No VM files were written, and no VM
training work was changed. Bytecode writes were disabled for that comparison.

Without the flag, **all three pre-change MIDI files and all three pre-change
manifest files remain byte-identical** under identical seeded entropy fixtures.
The normal resume, retry, deduplication, musical controls and output layout retain
their previous behavior. The chunker and optional dependencies load only when the
flag is used.

## Reference and exact dependency snapshot

The reference was read over the native macOS SSH client using the identity and
strict host-key verification documented in
`/Users/scarletdeath/Documents/ChatGPT/BUS/VM_ACCESS.md`. No access blocker occurred.

- Cut/serialization oracle:
  `/mnt/nvme/vwsd-rngoddess-20261018/scripts/chunk_canon.py`, `process()`.
- Tokenizer/codec:
  `/mnt/nvme/vwsd-rngoddess-20261018/source/midi_tokenizer.py`, `MIDI.py`.
- Report schema:
  `/mnt/nvme/vwsd-rngoddess-20261018/reports/chunk-canon.json`.
- Source repository revision: `f504d5cb58f769ab0f2909c679238f6621034573`.

| Reference file | SHA256 |
|---|---|
| `scripts/chunk_canon.py` | `44d52a49fef11c70367b7d72400230e5cc498a43336221bd74f1061477e73df6` |
| `source/midi_tokenizer.py` | `ce864ce567cf13efc7bfab7a9104d7e699cfb7d77450f640abd47128582e5bb9` |
| `source/MIDI.py` | `d0d2900a7d25d4b1d75f7ee6ecfc7e3046b1813500407b163bcabca4ba8fae2d` |

Tokenizer and MIDI codec source bytes are vendored unchanged, with their upstream
license and provenance. An unchanged copy of `chunk_canon.py` is the test oracle.
Tests pin all three hashes. The live VM comparison rechecked the hashes too.
Mac NumPy was 2.5.2 and VM NumPy was 2.5.4; serialized `.npy` bytes matched.

## Cut behavior and boundaries

- MIDITokenizerV2; `set_optimise_midi(True)`; `tokenize(score, tempo_eps=0)`;
  default `cc_eps=4`; BOS/EOS enabled.
- `MAX_LEN=2048`, `MARGIN=16`; body capacity exactly
  `MAX_LEN-MARGIN-2-len(header)`.
- Header is the latest time signature, per-track key signatures, tempo,
  per-track/channel patches and per-track/channel/controller CCs, all at t=0,
  stably sorted by `(track, ORDER)`. Ties retain oracle insertion order.
- First body event's `time1` delta is zeroed; fractional `time2` remains unchanged,
  exactly as in `process()`. No reinterpretation into bar/second/byte cuts.
- Bodies are consecutive and cover every source **token body row**. All original
  coverage assertions are kept, including restoring original first-event deltas
  before exact equality. No overlap, dropped tail, row padding to MAX_LEN, or
  merging the final chunk. The fixed-width token rows retain normal PAD tokens.
- `.npy` uses `np.asarray(rows, dtype=np.int16)` and `np.save(..., allow_pickle=False)`.
  MIDI uses the supplied codec and tokenizer detokenization, not a mido rewrite.
- Every serialized MIDI is re-tokenized and must have at most 2048 rows before
  publishing that piece. An oversized result fails loudly; no alternate cuts.
- No added filters, minimum/maximum byte sizes, duplicate suppression or file
  substitution. Chunked mode refuses resume/existing output rather than skipping
  pieces. It has one attempt per piece and stops on the first error with its ID.
  Individual file writes remain atomic.

The tokenizer itself normalizes MIDI: quantization, track/channel remapping,
key detection, CC epsilon suppression, and omission of unsupported event types
including pitch bend. This specification distinction was surfaced during the
work. The explicit exact-oracle requirement is followed; no lossless-raw-MIDI
reinterpretation or extra post-tokenization filtering was introduced. Coverage
means the complete oracle token sequence. Tokenizer augmentation/visualization
and their random routines are never called. Musical entropy remains the existing
required drawd/RNGoddess path, with no Python-random source or fallback.

## Output and manifest

For example:

```text
midi/000/000000_chunk000.mid
tokens/000/000000_chunk000.npy
manifest.jsonl
chunk-report.json
```

No long source MIDI is written in chunked mode. The per-source manifest retains
musical metadata/labels, uses `source_sha256`, and lists every chunk's paths,
MIDI/token SHA256 and row count. Labels never enter MIDI. Optional provenance
logs remain external and are refused inside the dataset directory.

The per-run `chunk-report.json` has the exact reference `summary` and `pieces`
field sets, including per-chunk coverage indices, header/body/row counts,
re-tokenized counts, MIDI byte count/SHA256 and elapsed seconds. The summary
retains all fields from `reports/chunk-canon.json`. Runtime timing values vary;
all stable per-piece/chunk report values matched the actual VM oracle.

## Acceptance results

A fixed seeded SHAKE entropy **test fixture** was used to pin pre-change outputs
and test exact equality; it is not a new production RNG/seed mode. A second sample
used the real required Mac `eshkol-local:moonlab` source through RNGoddess. Its
12 draw calls were recorded and replayed identically for normal/chunked output,
with exact agreement in requested byte count, lane and tag. No source failed or
was substituted.

Each normal source MIDI was processed by the untouched local oracle copy and
also the actual Ubuntu oracle. VM output destinations were in-memory buffers;
source MIDI was passed in memory, with no VM filesystem writes.

| Case | Source token events | Covered body events | Chunks | MIDI byte matches | NPY byte matches | Max re-tokenized rows |
|---|---:|---:|---:|---:|---:|---:|
| short | 14 | 14 | 1 | 1 | 1 | 16 |
| dense | 5,126 | 5,126 | 3 | 3 | 3 | 2032 |
| motion | 7,860 | 7,860 | 4 | 4 | 4 | 2032 |
| **Total** | **13,000** | **13,000** | **8** | **8** | **8** | **2032** |

**Mismatch list: empty.** All arrays are int16 with the tokenizer's eight-token
row width. The short live sample's MIDI is 158 bytes and was retained. Tests also
exercise a one-body-event final chunk, fractional cut timing, stable header ties,
latest state, identical duplicate pieces, corrupted coverage, >2048 re-tokenized
rows, disk-write failures and fatal entropy/validation errors with no redraw.

Additional real CLI smoke: `--count 1 --lanes 1 --bars 1 --chunked`, using the
unchanged default Mac drawd source, passed silently and wrote its paired files
and report. No audio playback occurred anywhere in acceptance. The separate
repository smoke used the null backend and isolated state.

## Tests and commands

Run from the MCFA repository root (artifact scripts are saved at the paths shown):

```sh
git switch -c codex/chunked-output nightmare-dataset
.venv/bin/python -m pip install 'Pillow>=9'
.venv/bin/python -m unittest discover -s tests -p test_chunked.py -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/smoke_demo.py --backend null
.venv/bin/python /Users/scarletdeath/Documents/ChatGPT/Worker/artifacts/mcfa-chunked-reference-20261027/acceptance.py
.venv/bin/python /Users/scarletdeath/Documents/ChatGPT/Worker/artifacts/mcfa-chunked-reference-20261027/compare_vm.py
.venv/bin/python -u tools/mcfa_dataset.py --count 1 --lanes 1 --bars 1 \
  --chunked --out /Users/scarletdeath/Documents/ChatGPT/Worker/artifacts/mcfa-chunked-reference-20261027/cli-live
git diff --check
```

- Baseline: **108 tests passed**, 6.879 seconds.
- Final full suite: **123 tests passed**, 8.386 seconds.
- Silent null smoke: **PASS, 0 underruns**, ten lanes, persistent conductor,
  lifecycle/sync/free changes, history and safe deadline stop.
- CLI smoke: **PASS**.
- Local and actual-VM byte conformance: **PASS**.
- `git diff --check`: passed.

Reproducible user setup is `.venv/bin/python -m pip install -e '.[chunked]'`.
The default dependency group is unchanged; chunked mode adds the optional Pillow
import needed by the exact tokenizer source.

## Files changed and preserved work

| File | Change |
|---|---|
| `src/mcfa/chunked.py` | Exact cut/coverage logic, reference serialization, re-tokenization guard, atomic pairs and report. |
| `src/mcfa/dataset.py` | Opt-in write step and strict chunked-only error/dedup/resume policy; normal path retained. |
| `tools/mcfa_dataset.py` | New optional `--chunked` flag. |
| `src/mcfa/_vendor/skytnt/midi_tokenizer.py`, `MIDI.py` | Exact reference source copies. |
| `src/mcfa/_vendor/skytnt/LICENSE`, `UPSTREAM.md` | Upstream license, revision and byte hashes. |
| `src/mcfa/_vendor/__init__.py`, `src/mcfa/_vendor/skytnt/__init__.py` | Private package containers. |
| `tests/fixtures/chunk_canon.py` | Unmodified VM oracle. |
| `tests/test_chunked.py` | Fifteen conformance, compatibility, boundary and failure tests. |
| `pyproject.toml` | Optional chunked dependencies and packaged vendor notices. |
| `README.md` | Flag, layout, strict behavior and exact-tokenizer normalization. |
| `CHUNKED-MODE-RESULT.md` | This report. |

All existing dataset folders were left untouched; the nightmare dataset was not
regenerated. Its branch remains at `5db9f5ac3953c7a05b3187f462ea0db0c1000c2c`, and
its manifest still has 1000 pieces and SHA256
`bc6a3272be4bdc0890b825f066c5d83d39c1ed834b522b0b94e02a5b370e1b9c`.
The prior nightmare generation was complete, but its final audit/report was
unfinished and temporary audit files had expired. That status was preserved in
`/Users/scarletdeath/Documents/ChatGPT/Worker/artifacts/MCFA-NIGHTMARE-CHECKPOINT.md`
before branching, rather than regenerated or silently presented as complete.
The existing untracked `ALIGNMENT.md`, `BACKBURNER_QRNG_GENESIS.md`, and
`mcfa-eshkol.tar.gz` were neither changed nor committed.

Evidence, source snapshots, scripts and acceptance outputs are retained under
`/Users/scarletdeath/Documents/ChatGPT/Worker/artifacts/mcfa-chunked-reference-20261027`. No pushes, external correspondence, remote training changes or audio
playback occurred.
