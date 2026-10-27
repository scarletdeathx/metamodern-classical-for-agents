"""Split mcfa-nightmare60 pieces into <=2048-row training chunks with the repo's MIDITokenizerV2.

Tokenizer config matches the A-full training cache (scripts/preflight.py -> cache/tokens-tempo0):
MIDITokenizerV2, set_optimise_midi(True), tokenize(score, tempo_eps=0), cc_eps default 4, add_bos_eos=True.
Each chunk = BOS + state header (time sig, key sigs, tempo, patches, current CC values, all at t=0)
+ consecutive body events + EOS, total rows <= MAX_LEN - MARGIN. Bodies cover the piece end to end,
no overlap. Outputs: .mid chunks + matching .npy token arrays (training-cache format, int16).
"""
import hashlib, json, os, statistics, sys, time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path('/mnt/nvme/vwsd-rngoddess-20261018')
sys.path.insert(0, str(ROOT / 'source'))
import MIDI
import numpy as np
from midi_tokenizer import MIDITokenizerV2

SRC = ROOT / 'dataset'
OUT_MID = ROOT / 'dataset-canon-chunks'
OUT_NPY = ROOT / 'cache/tokens-canon-chunks-tempo0'
REPORT = ROOT / 'reports/chunk-canon.json'
MAX_LEN = 2048
MARGIN = 16  # headroom so re-tokenizing the written .mid (key-sig detection etc.) still fits
ORDER = {n: i for i, n in enumerate(["time_signature", "key_signature", "set_tempo", "patch_change", "control_change", "note"])}

tok = MIDITokenizerV2()
tok.set_optimise_midi(True)
BOS = [tok.bos_id] + [tok.pad_id] * (tok.max_token_seq - 1)
EOS = [tok.eos_id] + [tok.pad_id] * (tok.max_token_seq - 1)


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


def header_rows(state):
    evs = sorted(state.values(), key=lambda e: (e[3], ORDER[e[0]]))
    rows = []
    for e in evs:
        e = [e[0], 0, 0] + e[3:]
        rows.append(tok.event2tokens(e))
    return rows


def process(path):
    pid = path.stem
    t0 = time.time()
    score = MIDI.midi2score(path.read_bytes())
    seq = tok.tokenize(score, tempo_eps=0)
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
        hdr = header_rows(state)
        cap = MAX_LEN - MARGIN - 2 - len(hdr)
        assert cap > 0
        j = min(n, i + cap)
        rows = []
        for k in range(i, j):
            e = list(events[k])
            if k == i:
                e[1] = 0  # rebase: chunk time zero = beat of first body event
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
    # coverage check: bodies concatenate to the source exactly
    assert chunks[0]['start'] == 0 and chunks[-1]['end'] == n
    assert all(a['end'] == b['start'] for a, b in zip(chunks, chunks[1:]))
    recon = []
    for c in chunks:
        recon += c['rows'][1 + c['header']:-1]
    restored = [list(r) for r in recon]
    for c in chunks:  # restore original first-event deltas for exact comparison
        restored[c['start']] = body_all[c['start']]
    assert restored == body_all
    out = []
    for ci, c in enumerate(chunks):
        name = f'{pid}_chunk{ci:03d}'
        arr = np.asarray(c['rows'], dtype=np.int16)
        assert len(arr) <= MAX_LEN
        np.save(OUT_NPY / (name + '.npy'), arr, allow_pickle=False)
        mid = MIDI.score2midi(tok.detokenize(c['rows']))
        (OUT_MID / (name + '.mid')).write_bytes(mid)
        re = tok.tokenize(MIDI.midi2score(mid), tempo_eps=0)
        out.append({'chunk': name, 'rows': len(arr), 'header': c['header'], 'body': c['end'] - c['start'],
                    'start_event': c['start'], 'start_beat': c['start_beat'], 'retokenized_rows': len(re),
                    'mid_bytes': len(mid), 'sha256': hashlib.sha256(mid).hexdigest()})
    return {'piece': pid, 'source_rows': len(seq), 'source_events': n, 'chunks': out, 'seconds': time.time() - t0}


if __name__ == '__main__':
    os.nice(0)
    OUT_MID.mkdir(parents=True, exist_ok=True)
    OUT_NPY.mkdir(parents=True, exist_ok=True)
    paths = sorted(SRC.glob('*.mid'))
    if len(sys.argv) > 1:
        paths = paths[:int(sys.argv[1])]
    t0 = time.time()
    with Pool(int(os.environ.get('WORKERS', '20'))) as p:
        res = []
        for r in p.imap(process, paths, chunksize=2):
            res.append(r)
            print(r['piece'], len(r['chunks']), r['source_events'], f"{r['seconds']:.1f}s", flush=True)
    per = [len(r['chunks']) for r in res]
    allc = [c for r in res for c in r['chunks']]
    src_ev = sum(r['source_events'] for r in res)
    body_ev = sum(c['body'] for c in allc)
    summary = {
        'pieces': len(res), 'chunks_total': len(allc),
        'chunks_per_piece': {'min': min(per), 'median': statistics.median(per), 'max': max(per)},
        'source_events_total': src_ev, 'body_events_total': body_ev, 'events_equal': src_ev == body_ev,
        'source_rows_total_incl_bos_eos': sum(r['source_rows'] for r in res),
        'chunk_rows_total': sum(c['rows'] for c in allc),
        'header_rows_total': sum(c['header'] for c in allc),
        'chunk_rows': {'min': min(c['rows'] for c in allc), 'max': max(c['rows'] for c in allc)},
        'retokenized_rows_max': max(c['retokenized_rows'] for c in allc),
        'retokenized_over_2048': sum(c['retokenized_rows'] > MAX_LEN for c in allc),
        'distinct_mid_sha256': len({c['sha256'] for c in allc}),
        'wall_seconds': time.time() - t0,
        'tokenizer': {'class': 'MIDITokenizerV2', 'optimise_midi': True, 'tempo_eps': 0, 'cc_eps': 4, 'max_len': MAX_LEN, 'margin': MARGIN},
    }
    print(json.dumps(summary, indent=2))
    REPORT.write_text(json.dumps({'summary': summary, 'pieces': res}, indent=1) + '\n')
