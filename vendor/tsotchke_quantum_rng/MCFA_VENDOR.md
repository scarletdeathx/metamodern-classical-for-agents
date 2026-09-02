# Tsotchke quantum_rng source snapshot

This directory contains the minimal source tree used to build MCFA's optional
local simulated-quantum entropy provider.

- Upstream: `https://github.com/tsotchke/quantum_rng.git`
- Revision: `1a77e77f803c63883349b658361c06401cd8ceb7`
- License: MIT; see `LICENSE` in this directory
- Imported: 2026-09-01

The snapshot is intentionally source-only. Build products remain ignored and
are produced by `tools/build_tsotchke_local.sh`. MCFA does not use the upstream
HTTP API and does not contact Tsotchke at runtime.

The upstream engine performs a classical state-vector simulation whose
measurement sampling is conditioned by host entropy. MCFA must describe it as a
local simulated-quantum representation, never as physical-QPU entropy.
