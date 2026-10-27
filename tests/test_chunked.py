import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import mido

from mcfa import dataset
from mcfa.midi_controls import MidiControls

ROOT = Path(__file__).resolve().parents[1]
HAS_DEPS = importlib.util.find_spec('PIL') is not None


def fixture_draw(n, lane, tag):
    return hashlib.shake_256(f'chunked-acceptance-seed-20261027/{tag}/{lane}'.encode()).digest(n), {'provider':'test-only-shake-fixture'}


def constant_draw(n, lane, tag):
    return bytes([200])*n, {'provider':'constant-fixture'}


def midi_bytes():
    mid = mido.MidiFile()
    mid.tracks.append(mido.MidiTrack([
        mido.MetaMessage('set_tempo', tempo=500000),
        mido.Message('program_change', program=5),
        mido.Message('note_on', note=62, velocity=90),
        mido.Message('note_off', note=62, velocity=0, time=480)]))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def load_oracle():
    from mcfa._vendor.skytnt import MIDI, midi_tokenizer
    path = ROOT/'tests/fixtures/chunk_canon.py'
    spec = importlib.util.spec_from_file_location('chunk_canon_oracle', path)
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'MIDI': MIDI, 'midi_tokenizer': midi_tokenizer}), mock.patch.object(sys, 'path', list(sys.path)):
        spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAS_DEPS, 'install optional chunked dependencies')
class ChunkedTests(unittest.TestCase):
    def setUp(self):
        from mcfa.chunked import ChunkedRun
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.writer = ChunkedRun(self.root/'chunks')

    def generate(self, out, count=1, **kwargs):
        kwargs.setdefault('draw_fn',fixture_draw)
        kwargs.setdefault('lanes',2)
        kwargs.setdefault('bars',2)
        return dataset.generate_dataset(out,count,**kwargs)

    def test_vendored_sources_and_oracle_are_exact_snapshots(self):
        paths = {
            'src/mcfa/_vendor/skytnt/midi_tokenizer.py':'ce864ce567cf13efc7bfab7a9104d7e699cfb7d77450f640abd47128582e5bb9',
            'src/mcfa/_vendor/skytnt/MIDI.py':'d0d2900a7d25d4b1d75f7ee6ecfc7e3046b1813500407b163bcabca4ba8fae2d',
            'tests/fixtures/chunk_canon.py':'44d52a49fef11c70367b7d72400230e5cc498a43336221bd74f1061477e73df6'}
        for path, sha in paths.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_same_entropy_output_is_byte_identical_to_reference(self):
        oracle = load_oracle()
        cases = {
            'short': {'lanes':2,'bars':1,'controls':MidiControls(key='D',scale='dorian',programs=[5,33])},
            'dense': {'lanes':4,'bars':40,'controls':MidiControls(key='F#',scale='chromatic',lengths=(0.125,),rest_probability=0,programs=[0,5,33,127])},
            'motion': {'lanes':3,'bars':8,'duration':6,'tempo_change_range':(20,400),
                'controls':MidiControls(programs=[0,40,80],velocity=(1,127)),
                'motion':{'min_notes_per_sec':15,'max_gap_s':0.25,'tempo_interval_beats':0.25,
                          'harmony_interval_beats':0.25,'cc_interval_beats':0.125,'pitch_bend_interval_beats':0.125}}}
        for name, options in cases.items():
            with self.subTest(case=name):
                plain, chunks = self.root/name/'plain', self.root/name/'chunked'
                self.generate(plain,**options)
                self.generate(chunks,chunked=True,**options)
                oracle.OUT_MID, oracle.OUT_NPY = self.root/name/'expected-mid', self.root/name/'expected-npy'
                oracle.OUT_MID.mkdir(); oracle.OUT_NPY.mkdir()
                expected = oracle.process(plain/'midi/000/000000.mid')
                actual = json.loads((chunks/'chunk-report.json').read_text())['pieces'][0]
                self.assertEqual({k:v for k,v in actual.items() if k!='seconds'}, {k:v for k,v in expected.items() if k!='seconds'})
                self.assertEqual(len(list((chunks/'midi').rglob('*.mid'))),len(expected['chunks']))
                for c in expected['chunks']:
                    for ext, folder, oracle_dir in (('mid','midi',oracle.OUT_MID),('npy','tokens',oracle.OUT_NPY)):
                        self.assertEqual((chunks/f'{folder}/000/{c["chunk"]}.{ext}').read_bytes(),
                                         (oracle_dir/f'{c["chunk"]}.{ext}').read_bytes())
                self.assertFalse((chunks/'midi/000/000000.mid').exists())
                if name=='dense':
                    self.assertGreater(len(expected['chunks']),1)

    def test_unchunked_midi_matches_pre_change_baseline_hashes(self):
        cases = {
            'short': ({'lanes':2,'bars':1,'controls':MidiControls(key='D',scale='dorian',programs=[5,33])},
                      '3d454e76030ddc88d815f40377761e26785acd76a0b9c4ad1ab3eac84055e9f3'),
            'dense': ({'lanes':4,'bars':40,'controls':MidiControls(key='F#',scale='chromatic',lengths=(0.125,),rest_probability=0,programs=[0,5,33,127])},
                      'b5244c6be754c8e6c83ac2a231eebc5b8b7e39a41e5131dbd0beac5b0ab40b53'),
            'motion': ({'lanes':3,'bars':8,'duration':6,'tempo_change_range':(20,400),
                       'controls':MidiControls(programs=[0,40,80],velocity=(1,127)),
                       'motion':{'min_notes_per_sec':15,'max_gap_s':0.25,'tempo_interval_beats':0.25,
                                 'harmony_interval_beats':0.25,'cc_interval_beats':0.125,'pitch_bend_interval_beats':0.125}},
                       'f59b093722c1f3c2eccf585552ac25edfeadd88a314bbb0127ece5c30df50f33')}
        for name,(options,sha) in cases.items():
            out=self.root/name
            with mock.patch('mcfa.chunked.ChunkedRun',side_effect=AssertionError('normal path invoked chunker')):
                self.generate(out,**options)
            self.assertEqual(hashlib.sha256((out/'midi/000/000000.mid').read_bytes()).hexdigest(),sha)
            self.assertEqual({p.name for p in out.iterdir()},{'midi','manifest.jsonl'})

    def test_state_header_cut_coverage_fractional_time_and_single_row_tail(self):
        from mcfa.chunked import split_rows, state_key
        tok=self.writer.tok
        events=[['time_signature',0,0,0,4,1],['key_signature',0,0,2,9,1],
                ['set_tempo',0,0,0,180],['patch_change',0,0,2,3,40],
                ['control_change',0,0,2,3,91,70],['control_change',0,0,2,1,1,90]]
        events += [['note',1,i%16,2,3,40+i%30,90,2] for i in range(4055-len(events))]
        events[2030][1:3]=[5,7]
        rows=[tok.event2tokens(e) for e in events]
        bos=[tok.bos_id]+[tok.pad_id]*7; eos=[tok.eos_id]+[tok.pad_id]*7
        cuts=split_rows([bos]+rows+[eos],tok)
        self.assertEqual([(c['start'],c['end'],c['header']) for c in cuts],[(0,2030,0),(2030,4054,6),(4054,4055,6)])
        first=tok.tokens2event(cuts[1]['rows'][1+cuts[1]['header']])
        self.assertEqual(first[1:3],[0,7])
        header=[tok.tokens2event(r) for r in cuts[1]['rows'][1:7]]
        self.assertTrue(all(e[1:3]==[0,0] for e in header))
        self.assertEqual([e[0] for e in header],['time_signature','set_tempo','key_signature','patch_change','control_change','control_change'])
        self.assertEqual([e[5] for e in header[-2:]],[91,1])  # stable insertion order, not controller sorting
        restored=[]
        for c in cuts:
            body=[list(r) for r in c['rows'][1+c['header']:-1]]
            body[0]=rows[c['start']]
            restored.extend(body)
        self.assertEqual(restored,rows)
        self.assertEqual(len(cuts[-1]['rows']),9)  # BOS + six header rows + one body + EOS

    def test_short_files_are_retained_and_arrays_are_int16(self):
        report, files=self.writer.write_piece('tiny',midi_bytes())
        arr=self.writer.np.load(self.writer.out/files[0]['tokens'],allow_pickle=False)
        self.assertEqual(arr.dtype,self.writer.np.int16)
        self.assertEqual(arr.shape[1],8)
        self.assertEqual(report['chunks'][0]['rows'],len(arr))
        self.assertLess((self.writer.out/files[0]['path']).stat().st_size,200)
        self.assertEqual(len(files),1)

    def test_duplicate_pieces_are_not_filtered_or_skipped(self):
        out=self.root/'dupes'
        summary=self.generate(out,3,chunked=True,draw_fn=constant_draw)
        report=json.loads((out/'chunk-report.json').read_text())
        self.assertEqual((summary['pieces'],summary['made'],summary['skipped'],summary['rejected']),(3,3,0,0))
        self.assertEqual(report['summary']['pieces'],3)
        self.assertEqual(report['summary']['chunks_total'],3)
        self.assertEqual(report['summary']['distinct_mid_sha256'],1)
        self.assertEqual(len(list((out/'midi').rglob('*.mid'))),3)

    def test_resume_and_existing_outputs_are_refused_without_entropy(self):
        out=self.root/'existing'
        draw=mock.Mock(side_effect=AssertionError('unexpected entropy'))
        with self.assertRaisesRegex(ValueError,'never skips'):
            self.generate(out,chunked=True,resume=True,draw_fn=draw)
        out.mkdir(); (out/'keep.txt').write_text('preserved')
        with self.assertRaises(FileExistsError):
            self.generate(out,chunked=True,draw_fn=draw)
        self.assertEqual((out/'keep.txt').read_text(),'preserved')
        draw.assert_not_called()

    def test_any_piece_error_stops_without_retry_or_substitution(self):
        from mcfa.chunked import ChunkedOutputError
        for failure in (ValueError('invalid piece'),RuntimeError('drawd down')):
            out=self.root/type(failure).__name__
            draw=mock.Mock(side_effect=failure)
            with self.assertRaisesRegex(ChunkedOutputError,'piece 000000'):
                self.generate(out,3,chunked=True,draw_fn=draw)
            self.assertEqual(draw.call_count,1)
            self.assertFalse(list(out.rglob('*.mid')))
        with mock.patch.object(dataset,'validate_midi',side_effect=ValueError('empty piece')) as validate:
            with self.assertRaisesRegex(ChunkedOutputError,'piece 000000: empty piece'):
                self.generate(self.root/'invalid',3,chunked=True)
            self.assertEqual(validate.call_count,1)

    def test_oversized_retokenization_fails_loudly_before_writes(self):
        from mcfa.chunked import ChunkedOutputError
        real=self.writer.tok.tokenize
        calls=[]
        def oversized(score,**kwargs):
            calls.append(1)
            return real(score,**kwargs) if len(calls)==1 else [[0]*8]*2049
        with mock.patch.object(self.writer.tok,'tokenize',side_effect=oversized):
            with self.assertRaisesRegex(ChunkedOutputError,'piece overflow:.*2049 rows'):
                self.writer.write_piece('overflow',midi_bytes())
        self.assertFalse(list(self.writer.out.rglob('*.mid')))
        self.assertFalse(list(self.writer.out.rglob('*.npy')))

    def test_coverage_asserts_reject_corrupt_or_undecodable_rows(self):
        from mcfa.chunked import split_rows
        tok=self.writer.tok
        seq=tok.tokenize(self.writer.MIDI.midi2score(midi_bytes()),tempo_eps=0)
        broken=[list(r) for r in seq]; broken[1]=[32700]*8
        with self.assertRaisesRegex(AssertionError,'undecodable row'):
            split_rows(broken,tok)
        with mock.patch.object(tok,'event2tokens',return_value=seq[1]):
            with self.assertRaises(AssertionError):
                split_rows(seq,tok)

    def test_report_schema_and_manifest_labels(self):
        out=self.root/'labels'; log=self.root/'log.jsonl'
        recipes=[{'name':'forbidden-recipe-label','count':1,'fixed':{'preset':'forbidden-preset-label'}}]
        self.generate(out,None,chunked=True,recipes=recipes,log=log)
        report=json.loads((out/'chunk-report.json').read_text())
        self.assertEqual(set(report),{'summary','pieces'})
        self.assertEqual(set(report['summary']),{'pieces','chunks_total','chunks_per_piece','source_events_total',
            'body_events_total','events_equal','source_rows_total_incl_bos_eos','chunk_rows_total','header_rows_total',
            'chunk_rows','retokenized_rows_max','retokenized_over_2048','distinct_mid_sha256','wall_seconds','tokenizer'})
        self.assertEqual(report['summary']['tokenizer'],{'class':'MIDITokenizerV2','optimise_midi':True,'tempo_eps':0,'cc_eps':4,'max_len':2048,'margin':16})
        self.assertTrue(report['summary']['events_equal'])
        row=json.loads((out/'manifest.jsonl').read_text())
        self.assertEqual(row['recipe'],'forbidden-recipe-label')
        self.assertEqual(row['preset'],'forbidden-preset-label')
        self.assertNotIn('path',row)
        self.assertIn('source_sha256',row)
        for c in row['chunks']:
            data=(out/c['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),c['sha256'])
            self.assertEqual(hashlib.sha256((out/c['tokens']).read_bytes()).hexdigest(),c['tokens_sha256'])
            for word in (b'forbidden-recipe-label',b'forbidden-preset-label',b'eshkol',b'moonlab',b'rngoddess'):
                self.assertNotIn(word,data.lower())

    def test_tokenizer_does_not_draw_randomness(self):
        with mock.patch('random.randint',side_effect=AssertionError('randomness forbidden')), \
             mock.patch('numpy.random.randint',side_effect=AssertionError('randomness forbidden')):
            self.writer.write_piece('deterministic',midi_bytes())

    def test_final_report_error_also_names_the_last_piece(self):
        from mcfa.chunked import ChunkedOutputError
        with mock.patch.object(dataset,'finalize',side_effect=OSError('final report failed')):
            with self.assertRaisesRegex(ChunkedOutputError,'piece 000000: final report failed'):
                self.generate(self.root/'finalfail',1,chunked=True)

    def test_cli_flag_is_opt_in(self):
        spec=importlib.util.spec_from_file_location('mcfa_dataset_cli',ROOT/'tools/mcfa_dataset.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for flag in ([],['--chunked']):
            with mock.patch.object(module,'generate_dataset',return_value={'pieces':1}) as generate, mock.patch('builtins.print'):
                self.assertEqual(module.main(['--count','1','--out',str(self.root/'cli')]+flag),0)
                self.assertEqual(generate.call_args.kwargs['chunked'],bool(flag))

    def test_atomic_write_failure_names_piece_and_stops(self):
        from mcfa.chunked import ChunkedOutputError
        real=dataset.atomic_write
        def fail(path,data):
            if path.suffix=='.npy':
                raise OSError('disk full')
            return real(path,data)
        with mock.patch.object(dataset,'atomic_write',side_effect=fail):
            with self.assertRaisesRegex(ChunkedOutputError,'piece 000000: disk full'):
                self.generate(self.root/'diskfail',2,chunked=True)
        self.assertFalse(list((self.root/'diskfail').rglob('*.mid')))


if __name__=='__main__':
    unittest.main()
