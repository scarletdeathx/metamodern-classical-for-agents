# Metamodern Classical for Agents (MCFA)

> **Platform requirement:** MCFA currently works on macOS only. Its audible
> engine and process control are built around CoreAudio and macOS Unix sockets;
> Windows and Linux are not supported.

MCFA is a persistent local noise-performance instrument for macOS. One Python
process owns CoreAudio, the master mix, deadlines, fades, state, and panic. Inside
that supervised mixer are ten independently controllable sound-machine lanes.

Each lane can be free-running at its own BPM or attached to the optional master
grid. Lanes may have unrelated loop lengths, rhythms, pitches or noise, phase,
synthesis, modulation, filtering, effects, volume, and pan. Killing, rewriting,
or restarting one lane never restarts the mixer or the other nine lanes.

This is deliberately a small live instrument, not a DAW, tracker, plug-in host,
or GUI. It is optimized for Codex rapidly operating many strange overlapping
processes.

## Install once

You need macOS and Python 3.10 or newer. These installation instructions are not
expected to produce a working instrument on Windows or Linux.

The repository launcher automatically uses `.venv` for every engine startup when
the environment exists:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

After that, future tasks can use `./mcfa` directly. Runtime state lives at
`~/Library/Application Support/Metamodern Classical for Agents` unless
`MCFA_STATE_DIR` is set.

## Start one mixer

```bash
./mcfa status --compact --history 16 --json
./mcfa start --bpm 127
```

`start` defaults to the audible sounddevice/CoreAudio backend, a resilient
1024-frame output block, and ten empty free-running lanes initialized to the
chosen BPM. Use `--backend null` only for silent testing. Never start a second
engine when status already reports `running: true`.

## Keep one conductor session open

The normal performance interface is a newline-delimited JSON session:

```bash
./mcfa session
```

It prints one ready object, then accepts any number of commands on the same Unix
socket. Each input produces exactly one JSON response. Closing the session does
not stop the mixer.

```json
{"command":"spawn","channel":1,"patch":{"name":"slow fracture","pattern":"C1 . C6 . F#2","clock":"free","bpm":61,"step_beats":0.31,"volume":0.16,"synth":{"waveform":"square"}}}
{"command":"spawn","channel":3,"patch":{"name":"fast grit","pattern":"F#5 . C2 F6 . A1","clock":"free","bpm":193,"step_beats":0.17,"volume":0.11,"pan":0.6,"synth":{"waveform":"noise","modulation":{"target":"pan","waveform":"triangle","rate_hz":6.1,"depth":0.8}}}}
{"command":"status","history":20}
{"command":"kill","channel":3}
{"command":"set","channel":3,"patch":{"name":"reborn splinters","pattern":"C7 C1 . Eb6 F#2 . A6","bpm":211,"synth":{"waveform":"saw"}}}
{"command":"restart","channel":3,"fade":0.1}
{"command":"quit"}
```

Compact session commands are:

- `spawn`, `set`, and atomic `batch`;
- `mute`, `unmute`, `clear`, `kill`, and `restart`;
- `status` and `history`;
- `tempo`, `master`, `deadline`, `stop`, and `panic`;
- `quit`, which closes only the client session.

The full machine-readable contract remains available through `./mcfa schema`.

## Lane lifecycle

These operations intentionally mean different things:

- `mute` fades a lane to silence while its clock and pattern phase continue.
  Muted lanes stop creating voices, and DSP becomes idle when their fade/tails end.
- `unmute` returns at the lane's current phase.
- `kill` immediately discards that lane's voices and effect memory, marks it
  inactive, and leaves every other lane untouched.
- `set` may rewrite an inactive lane without starting it.
- `restart` marks a killed lane active, unmutes it, and starts its loop at step 0.
- `clear` removes the pattern without changing the rest of the lane configuration.
- `spawn` is `set` plus active/unmuted startup and works for empty or killed lanes.

This makes it cheap to destroy a sound machine, prepare something unrelated in
its slot, and throw the replacement back into the mix.

## Independent and synchronized time

A lane patch accepts:

- `clock: "free"` and its own `bpm` for an independent phase and tempo;
- `clock: "sync"` to follow the master BPM;
- `step_beats` and any 1–256-step pattern, producing arbitrary loop lengths.

For a one-lane command, `next-step`, `next-beat`, and `next-bar` use that free
lane's clock. For sync lanes they use the master grid. Atomic multi-lane batches
use the master grid. `now` is deliberately unsynchronized and is the normal
choice for abrupt noise gestures. `+Nbeats` is relative to the addressed free
lane or the master when no single lane is addressed.

```json
{"command":"set","channel":2,"patch":{"volume":0.2},"at":"now","fade":0.03}
{"command":"mute","channel":6,"at":"next-step","fade":0.2}
{"command":"set","channel":10,"patch":{"pan":0.8},"at":"next-bar","fade":1.0}
```

The one-shot commands (`./mcfa set`, `mute`, `batch`, and so on) remain useful
for conversational edits between tasks, but a conducted set should use one
persistent `session` instead of launching a process for every choice.

## Patterns and sound controls

Compact patterns use spaces for steps, `.` for rests, and `+` for simultaneous
notes. Modifiers are `velocity:gate:probability`:

```text
C1 . C7:0.25:0.08 F#2+C3:0.4:2:0.7 .
```

Every lane owns:

- active/muted lifecycle, free/sync clock, BPM, loop, rhythm, probability, and
  notes/chords/noise triggers;
- an optional `random_seed`: an integer for repeatability, `"system"` to draw a
  one-time 128-bit seed from `random.SystemRandom`, or `"default"` to restore the
  stable lane-derived seed; status and history return exact JSON-safe `0x` hex
  strings that can be supplied again later;
- sine, triangle, saw, square, or noise waveform plus detune and ADSR;
- off/low-pass/high-pass/band-pass filtering;
- drive, delay, feedback, reverb, volume, and stereo pan;
- a sine/triangle/square LFO targeting amplitude, pan, or cutoff, with independent
  rate and depth.

The synthesis is intentionally lo-fi and bounded. It has no samples, acoustic
models, third-party plug-ins, or unrestricted feedback graph.

System entropy is resolved once when the patch is accepted, then the real-time
renderer uses fast lane-local generators. It affects noise samples and
probability decisions; it does not make operating-system entropy calls in the
audio loop or automatically randomize synth parameters.

Every engine run also draws one 128-bit `entropy_stamp` from `random.SystemRandom`
at startup. The stamp is exposed in live status and persisted in the final saved
state as a run identity; it does not alter the music by itself.

## Compact inspection and event history

```bash
./mcfa status --compact --history 24 --json
./mcfa history --limit 100
```

Compact state reports each lane's lifecycle, clock/BPM, loop, local beat, source,
modulation target, meters, and voice count without dumping entire patterns.
History records both scheduling and application with an event ID, audio frame,
time, beat, affected lanes, fade, changed fields, pattern size/preview, and synth
summary. It persists into the final saved state, so a stopped performance remains
auditable.

## Agent automation cadence

MCFA is intended for active, automation-forward conducting rather than loading a
pattern and leaving it untouched. The default agent protocol inspects the running
state every 1–3 seconds and makes a verified lane intervention or small batch
roughly every 2–6 seconds, targeting 10–30 substantive interventions per minute.
Local-model turns should produce perceptible reconfiguration—often a coherent
2–4-lane batch—not spend their tokens on invisible parameter nudges. Faster
continuous motion belongs inside lanes through LFOs, probability, independent
clocks, modulation, and effects rather than a flood of control commands. Slower
or more disruptive intervention rates can be requested in ordinary language.

## Deadlines, fades, and panic

For a timed performance, load a signal-producing opening and then send the hard
deadline through the session:

```json
{"command":"deadline","seconds":60,"deadline_fade":3}
```

Python owns that sample-frame deadline even if the conductor disconnects. Normal
ending is `stop` with a fade. `panic` immediately clears all voices, effect
buffers, queued events, and master output before terminating the mixer.

One-shot safety commands remain available:

```bash
./mcfa stop --fade 2
./mcfa panic
```

## Verification

The repository contains unit, renderer, backend, daemon, lifecycle, history, and
persistent-session integration tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The end-to-end smoke demo uses one conductor connection to spawn lanes 1 and 3,
expand to ten independent machines, kill/rewrite/restart lanes, exercise free and
quantized changes, verify history, set a Python deadline, and stop safely:

```bash
python3 scripts/smoke_demo.py --backend null
python3 scripts/smoke_demo.py --backend sounddevice --duration 8
```

The null backend is a real-time silent test, not audible proof. Release acceptance
also requires a one-minute actively conducted CoreAudio set through
`./mcfa session`, clearly audible evolution, a saved decision history, safe
deadline stop, and no sustained underruns.

Operational instructions for future Codex tasks are in [AGENTS.md](AGENTS.md).
