# Conducting Metamodern Classical for Agents from Codex

These instructions apply to every Codex task in this repository. Metamodern
Classical for Agents (MCFA) is the user's personal macOS noise-performance
instrument: ten independently
controllable sound machines feeding one supervised Python/CoreAudio mixer. Do not
turn it back into a conventional synchronized drum/bass/chord arranger.

Control performances only through `./mcfa`. Never edit runtime JSON, PID, or
socket files. Do not start per-lane CoreAudio processes: the single mixer process
must retain master fade, deadline, persistence, and panic authority while its ten
lane runtimes remain independently killable.

Each engine run has a 128-bit `entropy_stamp` drawn once from SystemRandom. Treat
it as the performance's verifiable entropy identity, preserve it in status/history
reporting, and do not claim that the stamp itself changes the sound. Lane-level
system seeding is a separate explicit choice. `ENTROPY.md` contains the permanent
project anchor; never regenerate or replace that anchor.

## How the user speaks

The user gives ordinary noise/performance directions. They should not need to
name CLI flags, write patterns, or choose lanes unless they want to. Translate
intent into detailed lane choices.

- **"Play", "play something", or "do a set"** means an audible, actively
  conducted performance. Default to 60 seconds when no duration is supplied and
  state that choice briefly.
- A direct request is enough. Never require `/goal`; a durable goal is useful for
  longer work but Python still owns the audio deadline.
- **"Change it", "get stranger", "more chaotic", or "lots happening"** means
  create clearly different simultaneous processes: unrelated clocks and loop
  lengths, register collisions, noise versus pitched sources, modulation,
  filtering, spatial motion, lifecycle changes, and contrasting densities.
- **"Faster/slower"** may change selected free-lane BPMs, the sync master, or
  both. Do not assume every lane must move together.
- **"Bring it in/out"** usually means mute/unmute. **"Kill/destroy that lane"**
  means the hard per-lane `kill`, not merely a mute and never engine panic.
- **"Stop/end"** means a graceful master fade. **"Stop now", "silence", or
  "panic"** means immediate engine panic.

The user is a noise musician. Dense, abrasive, unstable, dissonant, asymmetric,
and overlapping material is welcome. Conventional rhythmic, harmonic, or song
roles are optional and must not become a default quality rubric. This is still a
bounded synth: avoid dangerous gain accumulation and unrestricted feedback.

## Types of example commands the user prefers

The user prefers compact, ordinary-language performance commands that can
describe several timed sound worlds in one request. Treat duration phrases and
section boundaries as conducting instructions, not as a request for the user to
specify lanes or synthesis parameters.

- **"Play for two minutes, but let the first minute go one way and the second go
  completely different"** means arm one 120-second Python deadline, conduct
  actively for the entire duration, and make a decisive structural change near
  60 seconds while preserving emergency control. Do not stop and restart the
  engine between sections.
- **"First minute sparse aleatoric postmodern classical machinery; second minute
  death-industrial gabber or otaku-speedcore"** means the second section must
  replace the first section's rhythmic language, clocks, density, register,
  synthesis, and lane occupancy. A new melody or filter setting alone is not a
  sufficiently different section.
- **"Make the change a hard cut / collision / gradual mutation"** specifies the
  character of the boundary. If the user does not specify it, choose a musically
  decisive transition that fits the requested sound worlds.
- Similar commands may divide any duration into several named or unnamed
  sections. Translate proportional language such as **"first half," "last 30
  seconds," "then,"** and **"for the rest"** into a short live horizon of
  decisions while Python retains the single hard end deadline.

Even when a command names sections in advance, do not pre-script the entire set
or reduce it to a fixed A-to-B arrangement. Each section still requires fresh
inspection and ongoing decisions, and each should evolve internally before the
requested pivot.

## The performance agreement

The user must not have to paste the engine-operating brief before every set. In
this repository, a compact request such as **"play me a one-minute G Mixolydian
drill-marimba noise set"** inherits the performance protocol in this file. It
means: use the audible backend, open one persistent conductor, give Python the
hard duration and fade, use several independently controllable lanes, inspect
and make fresh decisions throughout, preserve emergency control, and verify the
ending. Do not ask the user to restate those requirements or create a `/goal`.

The operating protocol is silent, but creative preference gathering is not. At
the start of a new performance concept, and before creating or substantially
changing a scheduled performance workflow, run the rapid creative intake in
`PERFORMANCE_PALETTES.md`. Ask many small, fast, plain-language questions rather
than one vague request for a genre. Include the mode menu with its short emotive
descriptions. Let the user answer with terse words, option numbers, multiple
choices, ranges, or `skip`; do not demand music theory knowledge.

### Ready-to-play creative presets

The following presets are shortcuts through the creative intake. A request such
as **"play Corroded Machinery for two minutes"** is complete and should begin
promptly; do not ask the intake questions first. The user may override any part
in ordinary language, such as **"Glass Archive, but faster and mostly noise."**
Duration remains independent of the preset and defaults to 60 seconds when it is
not stated.

Treat every preset as a field of choices, never as a saved score or fixed lane
layout. Select a fresh subset of its possibilities, inspect continuously, and
conduct new patterns, clocks, synthesis, spatial behavior, and lane lifecycles
throughout the run. Preserve recognizable named processes when useful for live
follow-ups.

- **Ritual Sinkhole** — glacial-to-lurching motion; half-hidden polymetric pulse;
  spacious low-heavy pressure with puncturing gaps; stable identities that
  gradually contaminate one another; Phrygian and harmonic-minor material,
  loosely held; subterranean clusters, blunt impacts, corroded or submerged
  surfaces; dark filtering, cavernous conflicting spaces, and death-industrial
  crawl; low-to-high perplexity that wanders without a conventional climax;
  leave sparse residue or let the deadline catch it alive.
- **Glass Archive** — slow and drifting; mostly free or unrelated clocks;
  skeletal-to-breathing density; balanced pitched and noise processes; Lydian,
  whole-tone, and detuned-tonal material that may compete; brittle highs against
  isolated low tones; glassy, dusty, blooming, or scraping attacks; spectral
  clusters, aleatoric cells, unstable depth, and long exposed holes; medium-to-
  high perplexity with occasional outside turns; evaporate or end mid-process.
- **Corroded Machinery** — several incompatible speeds; fragmented pulse and
  mixed clock relationships; busy density that repeatedly strips itself bare;
  frequent replacement with a few traceable machine identities; Locrian,
  diminished, and chromatic material with competing centers; full-spectrum
  collisions, metallic/electrical attacks, driven edges, animated filters, and
  sharp stereo jumps; industrial machinery plus triplet-versus-binary conflict;
  high perplexity with sudden regime changes and abrupt dropouts.
- **Break Furnace** — fast-to-feral motion with an occasional oppressive crawl;
  chopped syncopation, extreme subdivisions, and unrelated counter-processes;
  busy or saturated density with ruthless churn; low synthetic thuds, filtered
  noise cracks, ghost ticks, brittle pitched fragments, and contaminated tonal
  cells; gabber pressure, otaku-speedcore splinters, triplet machinery, and a
  synthetic chopped-break contour that is repeatedly replaced or dissolved;
  split high-to-extreme perplexity; hard severing or a deadline cut mid-life.
- **Alien Weather** — no dependable shared pulse; drifting unrelated clocks;
  density that moves between near-silence and swarms; mostly noise with sparse
  atonal, detuned-tonal, or competing-mode signals; violent register distance,
  smeared electrical or submerged matter, slowly moving filters interrupted by
  razor-bright ruptures, orbiting motion, and conflicting spaces; indeterminate
  form with processes entering and disappearing like weather systems; high
  perplexity that breathes freely; avoid genre anchors and tidy resolution.

Save completed answers as a reusable palette in `PERFORMANCE_PALETTES.md` so a
scheduled or later performance can draw on them without asking again. Encourage
several acceptable choices per field: the purpose is to create a field of
possibilities that can be recombined differently, not a fixed score. Never edit
that file during an already-running performance unless the user explicitly asks
for the current feedback to become a lasting preference.

The user may bypass intake by saying **"play now," "surprise me," "skip the
questions,"** or equivalent. Do not interrupt an already-running performance
with intake questions; treat live follow-ups as immediate conducting directions.
Do not repeat the full intake when a usable saved palette already exists unless
the user asks to revise it; offer only a few short refresh questions when useful.

After the creative intent is known, choose the technical details autonomously.
Choose lanes, exact notes, patterns, clocks, loop lengths, synth parameters, mix,
and transitions without asking the user for implementation details. If duration
is omitted, the default above remains authoritative. Audio-device permission or
a genuine safety problem may still require user action.

Once intake is complete or bypassed, do not respond with a long plan while
leaving the room silent. Establish a small audible opening promptly, arm the
deadline, then build and reconsider the set live. Multiple lanes and changing
lane occupancy are the default; all ten are available, not mandatory unless the
user requests all ten. Examples describe interpretation, not a score to replay.
Never turn them into a canned arrangement.

### Translate musical language into this synth

Treat genres, acoustic instruments, production language, moods, and metaphors as
perceptual targets. Produce the closest useful synthesis with MCFA rather than
rejecting a request because no sample or plugin exists.

- A named key, scale, or mode constrains pitched note and chord choices while
  still allowing requested chromatic noise, tension, or outside notes. "Lots of
  chord changes" means genuinely changing pitch collections/voicings across
  steps and lanes, not repeating one triad at different octaves.
- A rhythm or genre reference describes timing, density, accents, rests, register,
  and gesture. For example, "drill-inspired" can use skittering subdivisions,
  displaced low hits, burst rolls, abrupt gaps, and noise transients without
  pretending MCFA contains a sampled drum kit.
- Triplets and other regular tuplets are directly representable. A beat is the
  unit for `step_beats`: use `1/3` for eighth-note triplets, `1/6` for sixteenth-
  note triplets, and `2/3` for quarter-note triplets. JSON sends decimal numbers,
  so use sufficiently precise equivalents. Mix binary and ternary motion with
  separate lanes, a shared fine subdivision, or live pattern rewrites. Do not
  describe an arbitrary off-grid decimal as a triplet when an exact ternary value
  is intended.
- MCFA has no sample playback, so it cannot reproduce an actual sampled Amen
  break or claim the original break's timbre. "Amen break" means an **Amen-like
  synthetic chopped break**: coordinate low sine/triangle thuds, band-passed or
  high-passed noise cracks, short noise ticks, ghost accents, rests, and displaced
  syncopation across independently replaceable lanes. Chop it live by rewriting,
  muting, killing, restarting, changing loop lengths, and switching between
  binary and triplet subdivisions. Preserve the break's perceptual push and
  interruption without pretending it is a sample.
- Postmodern-classical and aleatoric language maps well to probability, changing
  pitch cells, clusters, competing modes, register discontinuities, asymmetric
  loop lengths, independent clocks, silence, indeterminate lane entry/exit, and
  live replacement. Avoid reducing this to a decorative pad behind a beat.
- Industrial, death-industrial, gabber, and otaku-speedcore language maps to
  driven low oscillators, clipped-feeling envelopes, noise impacts, mechanical
  repetition, extreme subdivisions, hostile register collisions, abrupt gaps,
  and destructive lane turnover. The lane BPM limit is 400; imply still faster
  perceptual rates with subdivisions and interlocking lanes. Keep individual
  gains moderate and never use distortion or density as an excuse for unsafe
  accumulation.
- **Musical perplexity** means how difficult the near future is to predict, not
  simply how fast, loud, dense, dissonant, or random the sound is. Low perplexity
  uses legible repetition, longer-lived lane identities, related clocks, stable
  pitch rules, and gradual changes. High perplexity uses asymmetric or coprime
  loop lengths, probability, conflicting clocks and modes, register ruptures,
  misleading recurrences, pattern replacement, and lifecycle discontinuities.
  Keep perplexity independent from density: sparse high-perplexity and dense
  low-perplexity states are both valid. If the user chooses a contour, conduct
  the predictability level through time without turning it into a mandatory
  introduction-build-climax arc.
- A request for a **system-random**, **SysRandom**, or **entropy-seeded** lane
  maps to channel patch field `"random_seed":"system"`. This draws one seed from
  operating-system entropy when the patch is accepted; the fast lane-local RNG
  then drives noise samples and step-probability decisions. It does not
  automatically invent patterns or continuously randomize synthesis parameters.
  Reapply `"system"` when a fresh seed is wanted. Use an integer seed when the
  user wants the same stochastic lane to be reproducible.
- An acoustic instrument name describes a synthesized analogue. "Marimba" can
  become tuned sine/triangle partials, a sharp attack, short decay, little
  sustain, register-aware patterns, and restrained filtering/reverb. Report it as
  marimba-like or synthetic when that distinction matters; never claim a real
  sample or physical model.
- Timbre words should affect more than pitch: use waveform/noise source, ADSR,
  filter type/cutoff/resonance, detune, drive, delay/reverb, and LFO modulation.
  "Wooden," "metallic," "submerged," "broken," "glassy," "radioactive," and
  similar language are valid control input.
- Arrangement words map to lane lifecycle and density. "Bring in," "drop out,"
  "strip down," "rebuild," "interrupt," "replace," "swarm," "collapse," and
  "disintegrate" should cause audible structural actions, not merely rename a
  lane.
- Preserve recognizable lane identities long enough that follow-ups such as
  "bring the marimba back," "leave that scrape alone," or "destroy the siren"
  can refer to them. Names and history should make those references recoverable.

Interpret common follow-ups directly:

- **"Play me a one-minute G Mixolydian drill-marimba noise set"**: make an
  audible timed set using G Mixolydian pitch material, drill-inspired rhythmic
  behaviors, at least one marimba-like pitched process, contrasting noise
  processes, and ongoing live transformations.
- **"Make it faster"**: inspect first, then raise musically relevant free-lane
  BPMs and/or the sync master. Preserve useful slow counter-processes unless
  "everything" is specified.
- **"Use lots of chord changes"**: rewrite one or more pitched patterns with
  clearly changing chords/voicings, potentially at different loop lengths, and
  let rhythm and synthesis keep them audible.
- **"Make it less beep-beep"**: broaden envelopes, chords, noise, register,
  filtering, modulation, effects, silence, and overlapping loop lengths. Do not
  solve this by changing only the waveform.
- **"Take it somewhere uglier/weirder"**: make a coherent structural change—
  kill and replace processes, alter clock relationships, change density or
  register, or introduce contrasting synthesis—not a handful of invisible
  parameter twitches.
- **"Keep this going"**: preserve the engine and current material for further
  conversational edits; do not stop because the Codex turn ends.

The user's newest direction overrides aesthetic examples here. Translate it,
act, inspect the result, and report the audible intention plus verifiable engine
state without burdening the user with implementation details.

## Inspect before touching a performance

Run:

```bash
./mcfa status --compact --history 24 --json
```

If no state exists or saved state is stopped, start one audible engine:

```bash
./mcfa start --bpm <chosen-master-bpm>
```

Use `--backend null` only for explicitly silent testing or when CoreAudio is
unavailable. If status is already running, do not start another engine. Preserve
its deadline and current sound world unless the user asks to replace them.

The repository launcher automatically uses `.venv` for every engine startup when
it exists. If audible startup reports missing sounddevice, perform the one-time
persistent installation (with approval if network access is required):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Never substitute a temporary dependency directory and claim future tasks are
ready. Never call a null-backend run audible.

## Use one persistent conductor session

During a set, do not launch a fresh CLI process for every decision. Start:

```bash
./mcfa session
```

Run it as a long-lived/PTY shell command, retain its session identifier, and send
newline-delimited JSON to its stdin for the rest of the performance. It prints a
ready object first and exactly one response per input. Closing the conductor with
`quit` leaves the mixer running.

Useful messages:

```json
{"command":"spawn","channel":1,"patch":{"name":"slow fracture","pattern":"C1 . C6 . F#2","clock":"free","bpm":61,"step_beats":0.31,"volume":0.16,"synth":{"waveform":"square"}}}
{"command":"spawn","channel":3,"patch":{"name":"fast grit","pattern":"F#5 . C2 F6 . A1","clock":"free","bpm":193,"step_beats":0.17,"volume":0.11,"pan":0.6,"synth":{"waveform":"noise"}}}
{"command":"status","history":20}
{"command":"kill","channel":3}
{"command":"set","channel":3,"patch":{"name":"replacement","pattern":"C7 C1 . Eb6 F#2 . A6","bpm":211}}
{"command":"restart","channel":3,"fade":0.1}
```

Read `./mcfa schema` for the complete session/patch contract. A `pattern` string
is parsed inside the session. `batch` accepts a `channels` object and lands all
updates atomically.

The one-shot CLI remains appropriate for a single conversational edit between
tasks, for safety commands, or for recovery when the conductor connection fails.

## Lane semantics

There are exactly ten slots, numbered 1–10. Each owns its active/muted lifecycle,
free/sync clock, BPM, phase, loop/rhythm/probability, notes or noise source,
waveform/detune/ADSR, filter, drive/delay/reverb, LFO modulation, volume, and pan.

- `clock: "free"` uses the lane's own BPM and phase. Prefer this for unrelated
  noise processes.
- `clock: "sync"` follows the optional master BPM.
- `at: "now"` is an unsynchronized gesture.
- On a one-lane command, `next-step`, `next-beat`, and `next-bar` use that lane's
  free clock or the master for a sync lane. A multi-lane batch uses the master
  grid.
- `mute` fades out while phase continues; `unmute` returns at the current phase.
- `kill` immediately clears only that lane's voices and effects and makes it
  inactive while preserving its configuration.
- `set` can rewrite a killed lane offstage; it remains inactive.
- `restart` activates, unmutes, and starts that lane at step zero.
- `spawn` configures and starts a lane in one message.
- `clear` removes the pattern but retains the remaining configuration.

Prefer moderate individual volumes when many processes overlap. The master soft
limiter is protection, not a mixing strategy.

## Conduct for the entire requested duration

Prepare a small signal-producing opening, verify it with compact status, then
immediately delegate the hard limit to Python:

```json
{"command":"deadline","seconds":60,"deadline_fade":3}
```

The requested duration—not a command count—is the completion quota. Until that
deadline ends:

1. Request compact status with recent history.
2. Make a fresh musical/noise decision.
3. Send one coherent command or small batch.
4. Verify application/history and reconsider the result.
5. Continue until the prescribed duration is actually exhausted.

A decision may deliberately leave a compelling process alone. Do not confuse
that with ending the control loop early. Do not pre-script the whole set and wait
for Python; maintain only a short horizon of pending events and keep making live
choices. Treat new user messages during playback as immediate directions without
resetting the existing deadline unless requested.

### Autonomous agent loop

When the agent environment offers a recurring-loop, self-wake, heartbeat, or
equivalent continuation facility, use that facility throughout every active
timed performance. Before relying on it, consult that environment's own help or
documentation for its syntax, minimum cadence, session lifetime, wakeup rules,
and stop mechanism. Start one recurring conductor prompt immediately after
arming the Python deadline, at a fixed cadence short enough to make meaningful
live decisions and permitted by that environment. The prompt must direct each
wakeup to inspect current state and recent history, make one substantive musical
decision (or deliberately retain a compelling state), verify the result, and
continue conducting. Its completion condition must be status evidence that the
Python deadline has faded the engine to a safe stopped state.

This facility is only the agent's recurring control cycle. The Python deadline
remains the sole hard end time: never use a loop as a second duration timer,
restart the engine merely because a loop fires, or replace an existing deadline
unless the user explicitly requests it. If the environment's minimum cadence is
longer than the set, conduct directly in the initial turn and rely on the Python
deadline; do not pretend a later wakeup will occur before it ends. Respect the
environment's session and loop limits—for example, Hermes Agent supports one
idle-session `/loop` at a time, a fixed cadence configurable down to 30 seconds,
and `LOOP_COMPLETE` as an agent-controlled stop signal. Other harnesses may use
different commands and semantics.

### Low-capability loop conductor

The recurring prompt is a control handoff: after a capable agent has opened the
engine, persistent `./mcfa session`, and deadline, a modest local model must be
able to conduct the already-running performance without rediscovering the whole
project. Give it the conductor session identity and this small, imperative
contract in every wakeup: (1) obtain compact status plus recent history; (2)
preserve the existing engine and deadline; (3) send one coherent session command
or a small atomic batch; (4) obtain status again; (5) end only when the stopped
state is proven. It must operate the existing conductor session, not launch a
new per-edit CLI process or audio engine.

Limit each wakeup to one of these concrete decisions: leave one compelling lane
alone; spawn or restart one inactive lane; rewrite one active or killed lane;
mute, unmute, or hard-kill one lane; or make a small batch that changes a few
lanes together. Select the decision from observed lane count, clocks, recent
history, and the user's latest sound world—not from a need to narrate a complete
composition. It must use actual lane commands and verify their result, not only
describe what it would do. Keep gains moderate, preserve unrelated free clocks,
and never panic or alter the deadline except on the explicit conditions defined
elsewhere in this file. This bounded action vocabulary lets a weak local model
make safe, audible decisions while the persistent mixer retains timing and
safety authority.

### Continuous conducting, not a pre-shaped arc

The central performance idea is an AI continuously conducting a changing ecology
of independent sound machines. A set is not a fixed A-to-B composition, a quirky
techno track, or a prepared sequence of introduction, build, climax, breakdown,
and cacophonous finale. Do not impose that dramatic arc unless the user asks for
one. The deadline fade is a safety boundary, not an instruction to manufacture an
outro.

Throughout the full duration, repeatedly generate genuinely new patterns and
processes, remove old ones, rewrite killed lanes offstage, revive them in altered
forms, and change clock, register, density, synthesis, modulation, filtering,
space, and lane occupancy in response to the current measured state. Keep the
decision horizon short enough that later choices are reactions to what is
actually running rather than steps in a score decided at the beginning. Let
unrelated processes overlap and interfere; avoid converging by default on a
single beat, genre role, or synchronized groove.

Continuous conducting does not mean random twitching or changing every control
on every inspection. A strong process may be left alone while other lanes mutate,
and silence or sparse occupancy may be an active decision. What matters is that
the AI remains engaged, keeps reconsidering the whole sound world, and makes
substantive generative and lifecycle decisions until the deadline begins its
fade. A final pile-up, climax, or tidy resolution is optional rather than the
default.

Possible decisions include spawning unrelated lanes, hard-killing one process,
rewriting it while inactive, reviving it with a different clock/source, changing
loop lengths or probability, moving LFO target/rate/depth, swapping pitched sound
for noise, making immediate non-grid gestures, using an occasional quantized
collision, or deliberately reducing activity before another burst.

The goal is clearly audible ongoing evolution, not a rigid edit every beat and
not random parameter twitching for its own sake. User auditory feedback outranks
an edit count.

## Inspect compactly and use history as proof

In-session inspection:

```json
{"command":"status","history":32}
{"command":"history","limit":100}
```

Compact status exposes engine/deadline health and each lane's active/muted state,
clock/BPM, loop, local beat, source, modulation, meters, and voices. History
records scheduled and applied events with IDs, audio frames/times/beats, affected
lanes, changed fields, pattern previews, synth summaries, and fades.

Use history to avoid contradictory pending changes and to prove that active
control continued. State/history proves the audio path, configuration, timing,
and signal meters; Codex cannot hear the physical speakers. Ask for or respect
the user's auditory judgment and never claim personally to have heard the set.

## Real-time health

The normal audible backend uses a resilient 1024-frame CoreAudio buffer. Prefer
zero underruns. A single isolated startup or huge-batch scheduling miss may be
non-meaningful; a growing count or repeated misses during ordinary control is a
failure. If it grows:

- stop issuing giant all-lane batches;
- mute/kill expensive effect-heavy lanes and simplify voice density;
- keep inspections compact;
- end safely and diagnose rather than claiming a clean performance.

Do not conceal an underrun count. Previous behavior produced 44 underruns and was
not acceptable.

## Ending and emergency safety

- Fixed-duration sets end through the Python deadline. Do not replace it with a
  shell sleep, chat timeout, or promise to return later.
- For a user-requested earlier musical ending, send `stop` with a fade.
- `./mcfa panic` immediately clears all lanes/effects/events/master and exits.
  Use it for unsafe or runaway audio, corrupted state, an unresponsive engine, or
  a direct immediate-silence request.
- If graceful stop times out, panic. Never guess a PID or send `kill -9`.
- If the conductor fails, use `./mcfa status --compact --history 24 --json` and
  `./mcfa logs`; the mixer and deadline continue independently.

## Verification and release bar

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/smoke_demo.py --backend null
```

Use `--backend sounddevice` only for an audible CoreAudio smoke. The project is
not complete merely because tests and a silent smoke pass. Final acceptance also
requires a one-minute actively conducted session in which:

- one persistent conductor remains active;
- lanes 1 and 3 begin as different free-running processes;
- all ten lanes operate concurrently;
- multiple lanes are killed, rewritten/replaced, and revived while others keep
  running;
- immediate/free and quantized/sync transitions both occur;
- the user hears clearly different ongoing changes;
- persistent history proves the decisions and timing;
- CoreAudio has no meaningful underruns;
- the Python deadline fades to master zero and stops safely;
- panic remains available throughout.

Mechanical success and convincing noise performance are separate claims. Be
candid when either one is not proven.
