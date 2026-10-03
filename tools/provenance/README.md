# Provenance — per-phase build scripts

These are the scripts that produced each phase package (`prepare_*`, `build_*`, `package_*`) and
audited the car's output (`audit_*`), kept so the derivation of the F8 candidate can be reviewed
(F7 v2.1 ← F7 v2 ← F7 v1.1 ← F6 v3 ← … ← F1). They read private inputs from a sibling
`private-data/mu1320-rgi/` workspace and earlier staged package folders that are **not** in this
repository, so they do not run here. Use `tools/assemble_*.py` to build the release.

Sources of the earlier phase Java classes are intentionally absent: they derive from the upstream
project and proprietary firmware (see ../../NOTICE.md).
