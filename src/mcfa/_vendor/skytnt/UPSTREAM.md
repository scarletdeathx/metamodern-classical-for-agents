# Exact tokenizer/codec snapshot

Copied without source modifications from the task's reference VM on 2026-10-27:
`/mnt/nvme/vwsd-rngoddess-20261018/source/`.

Upstream: [SkyTNT/midi-model](https://github.com/SkyTNT/midi-model), revision
`f504d5cb58f769ab0f2909c679238f6621034573`. Its Apache-2.0 license is included
as `LICENSE`. The supplied repo also contains the historical Peter Billam MIDI
codec; its original source and notices are retained verbatim.

SHA256:

- `midi_tokenizer.py`: `ce864ce567cf13efc7bfab7a9104d7e699cfb7d77450f640abd47128582e5bb9`
- `MIDI.py`: `d0d2900a7d25d4b1d75f7ee6ecfc7e3046b1813500407b163bcabca4ba8fae2d`

Only MIDITokenizerV2 tokenization/detokenization is used by MCFA. Its visualizer,
augmentation helpers and their random functions are never called. Keeping the
files intact makes the exact serialization dependency auditable. Import is lazy
and only happens when chunked output is requested.

The cut oracle is the separately authored `scripts/chunk_canon.py`, SHA256
`44d52a49fef11c70367b7d72400230e5cc498a43336221bd74f1061477e73df6`.
Its unmodified copy is retained as the test oracle in `tests/fixtures/`.
