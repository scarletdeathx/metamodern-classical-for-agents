"""Opt-in, exact token-row cuts from the supplied chunk_canon.py oracle.

The vendored tokenizer/codec are unchanged. No additional quality filters,
file-size limits, duplicate suppression, overlap or last-chunk merging.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import statistics
import time

MAX_LEN = 2048
MARGIN = 16
ORDER = {n: i for i, n in enumerate([
    "time_signature", "key_signature", "set_tempo", "patch_change", "control_change", "note"])}


class ChunkedOutputError(RuntimeError):
    def __init__(self, piece, error):
        super().__init__(f"piece {piece}: {error}")
        self.piece = piece


def state_key(ev):
    n = ev[0]
    if n == 'time_signature' or n == 'set_tempo':
        return (n,)
    if n == 'key_signature':
        return (n, ev[3])
    if n == 'patch_change':
        return (n, ev[3], ev[4])
    if n == 'control_change':
        return (n, ev[3], ev[4], ev[5])
    return None


def header_rows(state, tok):
    # Stable sort intentionally retains the oracle's insertion order for ties.
    evs = sorted(state.values(), key=lambda e: (e[3], ORDER[e[0]]))
    rows = []
    for e in evs:
        e = [e[0], 0, 0] + e[3:]
        rows.append(tok.event2tokens(e))
    return rows


def split_rows(seq, tok):
    """Literal process() cut/coverage logic; time2 is deliberately retained."""
    BOS = [tok.bos_id] + [tok.pad_id] * (tok.max_token_seq - 1)
    EOS = [tok.eos_id] + [tok.pad_id] * (tok.max_token_seq - 1)
    assert seq[0] == BOS and seq[-1] == EOS
    body_all = seq[1:-1]
    events = [tok.tokens2event(r) for r in body_all]
    assert all(events), 'undecodable row'
    abs_t1, t = [], 0
    for e in events:
        t += e[1]
        abs_t1.append(t)
    state = {}
    chunks, i, n = [], 0, len(events)
    while i < n:
        hdr = header_rows(state, tok)
        cap = MAX_LEN - MARGIN - 2 - len(hdr)
        assert cap > 0
        j = min(n, i + cap)
        rows = []
        for k in range(i, j):
            e = list(events[k])
            if k == i:
                e[1] = 0
            r = tok.event2tokens(e)
            assert r
            rows.append(r)
        chunks.append({'start': i, 'end': j, 'header': len(hdr), 'start_beat': abs_t1[i],
                       'rows': [BOS] + hdr + rows + [EOS]})
        for k in range(i, j):
            sk = state_key(events[k])
            if sk:
                state[sk] = events[k]
        i = j
    assert chunks[0]['start'] == 0 and chunks[-1]['end'] == n
    assert all(a['end'] == b['start'] for a, b in zip(chunks, chunks[1:]))
    recon = []
    for c in chunks:
        recon += c['rows'][1 + c['header']:-1]
    restored = [list(r) for r in recon]
    for c in chunks:
        restored[c['start']] = body_all[c['start']]
    assert restored == body_all
    return chunks


class ChunkedRun:
    def __init__(self, out):
        # Optional imports stay entirely off the normal generation path.
        try:
            import numpy as np
            from ._vendor.skytnt import MIDI
            from ._vendor.skytnt.midi_tokenizer import MIDITokenizerV2
        except ImportError as exc:
            raise RuntimeError("chunked output needs the optional dependencies: pip install '.[chunked]'") from exc
        self.np, self.MIDI = np, MIDI
        self.tok = MIDITokenizerV2()
        self.tok.set_optimise_midi(True)
        self.out = Path(out)
        self.pieces = []
        self.started = time.time()

    def write_piece(self, piece, data):
        from .dataset import atomic_write
        started = time.time()
        try:
            if not piece or Path(piece).name != piece:
                raise ValueError("invalid piece filename")
            score = self.MIDI.midi2score(data)
            seq = self.tok.tokenize(score, tempo_eps=0)
            chunks = split_rows(seq, self.tok)
            prepared, reports, files = [], [], []
            shard = f"{int(piece) // 1000:03d}" if piece.isdigit() else "000"
            for ci, c in enumerate(chunks):
                name = f'{piece}_chunk{ci:03d}'
                arr = self.np.asarray(c['rows'], dtype=self.np.int16)
                assert len(arr) <= MAX_LEN
                buf = io.BytesIO()
                self.np.save(buf, arr, allow_pickle=False)
                mid = self.MIDI.score2midi(self.tok.detokenize(c['rows']))
                re = self.tok.tokenize(self.MIDI.midi2score(mid), tempo_eps=0)
                if len(re) > MAX_LEN:
                    raise ValueError(f"{name} re-tokenizes to {len(re)} rows (limit {MAX_LEN})")
                midi_path = f"midi/{shard}/{name}.mid"
                token_path = f"tokens/{shard}/{name}.npy"
                sha = hashlib.sha256(mid).hexdigest()
                reports.append({'chunk': name, 'rows': len(arr), 'header': c['header'],
                    'body': c['end'] - c['start'], 'start_event': c['start'], 'start_beat': c['start_beat'],
                    'retokenized_rows': len(re), 'mid_bytes': len(mid), 'sha256': sha})
                files.append({'id': name, 'path': midi_path, 'tokens': token_path, 'sha256': sha,
                              'tokens_sha256': hashlib.sha256(buf.getvalue()).hexdigest(), 'rows': len(arr)})
                prepared.append((midi_path, mid, token_path, buf.getvalue()))
            # Validate every serialized chunk before publishing any part of a piece.
            for midi_path, mid, token_path, tokens in prepared:
                atomic_write(self.out / token_path, tokens)
                atomic_write(self.out / midi_path, mid)
            report = {'piece': piece, 'source_rows': len(seq), 'source_events': len(seq)-2,
                      'chunks': reports, 'seconds': time.time()-started}
            self.pieces.append(report)
            self.finish()
            return report, files
        except Exception as exc:
            raise ChunkedOutputError(piece, str(exc) or type(exc).__name__) from exc

    def report(self):
        res = self.pieces
        per = [len(r['chunks']) for r in res]
        allc = [c for r in res for c in r['chunks']]
        src_ev = sum(r['source_events'] for r in res)
        body_ev = sum(c['body'] for c in allc)
        # Field names and types match reports/chunk-canon.json. Empty ranges
        # are null only on a failed run before its first accepted piece.
        summary = {
            'pieces': len(res), 'chunks_total': len(allc),
            'chunks_per_piece': {'min': min(per) if per else None,
                'median': statistics.median(per) if per else None, 'max': max(per) if per else None},
            'source_events_total': src_ev, 'body_events_total': body_ev, 'events_equal': src_ev == body_ev,
            'source_rows_total_incl_bos_eos': sum(r['source_rows'] for r in res),
            'chunk_rows_total': sum(c['rows'] for c in allc),
            'header_rows_total': sum(c['header'] for c in allc),
            'chunk_rows': {'min': min((c['rows'] for c in allc), default=None),
                           'max': max((c['rows'] for c in allc), default=None)},
            'retokenized_rows_max': max((c['retokenized_rows'] for c in allc), default=None),
            'retokenized_over_2048': sum(c['retokenized_rows'] > MAX_LEN for c in allc),
            'distinct_mid_sha256': len({c['sha256'] for c in allc}),
            'wall_seconds': time.time() - self.started,
            'tokenizer': {'class': 'MIDITokenizerV2', 'optimise_midi': True, 'tempo_eps': 0,
                          'cc_eps': 4, 'max_len': MAX_LEN, 'margin': MARGIN},
        }
        return {'summary': summary, 'pieces': res}

    def finish(self):
        from .dataset import atomic_write
        report = self.report()
        atomic_write(self.out / "chunk-report.json", (json.dumps(report, indent=1) + '\n').encode())
        return report
