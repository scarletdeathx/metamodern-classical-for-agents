# Local Dependency Workspace

MCFA uses `.dependency-work/` as a disposable local workspace for investigating,
building, and testing source dependencies such as Eshkol and Tsotchke projects.
The entire directory is ignored by Git. A checkout of MCFA must never depend on
its contents being present.

## Layout

```text
.dependency-work/
  repos/       upstream Git clones
  builds/      out-of-tree build products
  installs/    private experimental install prefixes
  captures/    temporary output and comparison data
  notes/       disposable investigation notes
```

Do not place MCFA source, permanent design decisions, licenses that ship with
MCFA, or the only copy of a patch in this directory. Promote those materials to
tracked repository files before relying on them.

## Investigation workflow

1. Clone each upstream repository into `.dependency-work/repos/` without adding
   it as a submodule or changing MCFA's dependency graph.
2. Record the upstream URL and exact commit under investigation in the relevant
   tracked design document.
3. Build out of tree under `.dependency-work/builds/`; use
   `.dependency-work/installs/` as an experimental prefix when needed.
4. Exercise the smallest useful native interface locally. For an RNG provider,
   this should initially be a bounded `health` operation and a bounded
   `read_bytes(count)` operation rather than an HTTP service.
5. Put the MCFA-facing adapter behind a narrow interface and test it with a fake
   implementation before connecting the native library.
6. Verify Apple Silicon builds, deterministic capture/replay, provenance,
   failure behavior, and that no work occurs on the real-time audio callback.
7. Decide how to ship the dependency only after the experiment works:
   vendor a pinned source snapshot, consume a stable system/library package, or
   maintain an MCFA fork if sustained upstream changes are truly necessary.
8. When vendoring, copy only the required source and its license into a tracked
   `vendor/` location, record the upstream commit, and provide a reproducible
   build path. Never copy experimental build products into the repository.

## Intended integration boundary

The first local prototype should preserve this division of responsibility:

```text
MCFA Python supervisor
  -> bounded provider ABI
     -> locally built Tsotchke entropy engine
     -> optional MCFA-Eshkol transformation runtime
```

Python retains deadlines, fades, panic authority, lane lifecycle, buffering,
capture/replay, and provenance. Native or Eshkol code supplies bounded entropy
and transformation operations. Network services are optional interoperability
targets and must never be required for an MCFA performance.

## Reproducibility gate

Nothing in `.dependency-work/` becomes an MCFA dependency until a fresh checkout
can reproduce it from tracked instructions and pinned source provenance. The
ignored workspace is a laboratory, not part of the product.

## Current local integration

The exact research revisions are recorded in `DEPENDENCY_SOURCES.json`. The
minimal pinned `quantum_rng` source and its MIT license now live under
`vendor/tsotchke_quantum_rng`. Build the local Apple Silicon library with:

```sh
./tools/build_tsotchke_local.sh
```

The resulting `.dependency-work/builds/libmcfa_tsotchke.dylib` exposes the
upstream v3 C ABI directly. `mcfa.providers.TsotchkeLocalProvider` loads that
library without Node, HTTP, credentials, or network access. This is currently a
source-vendored beta integration; compiled native products are not committed.

The local lane-facing beta uses this source as `fresh:tsotchke-local`: it reads
16 bytes on the engine control plane, records their digest and upstream
provenance, and seeds the lane's chosen deterministic algorithm. It is not yet a
continuous entropy stream.

## Eshkol integration finding

The inspected Eshkol revision already exposes a stable C/Python FFI and routes
its `quantum-random` builtins through `lib/quantum/quantum_rng_wrapper.c`. Its
ordinary build uses an explicitly classical software fallback; an optional
Moonlab build selects a different Bell-verified simulation route. MCFA must not
silently inherit either label.

The smallest useful MCFA/Eshkol change is therefore a provider injection point
at that wrapper boundary: an MCFA-owned Eshkol runtime should accept bounded
entropy chunks or an `eshkol_qrng_bytes` implementation backed by the same local
Tsotchke v3 ABI. Python still owns provider selection, capture, lane assignment,
and safety. Building or modifying the full Eshkol compiler is not required for
the first entropy-seed integration.

The local build audit used LLVM 21.1.8 and Ninja on arm64 macOS. With agent FFI,
GPU, quantum, and tests disabled, Eshkol's core and runtime static archives build
successfully. Its JIT executable and Python extension deliberately register the
full hosted/agent symbol surface, however, so disabling agent FFI leaves those
targets with unresolved symbols. The supported full-FFI configuration also
fetches pinned PCRE2, SQLite, zlib, tree-sitter grammars, and Yoga sources. MCFA
should therefore avoid making the full Eshkol JIT a prerequisite for ordinary
playback; it belongs behind an optional transformation-runtime boundary.
