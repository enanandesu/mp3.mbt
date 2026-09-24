# Repository guide

- `enanandesu/mp3` is a library. The root package contains the public API; `internal/` holds parsing and Layer III decoding.
- The checked-in `moon.mod.json` and `moon.pkg.json` files match the pinned toolchain in `tools/toolchain.lock.json`. Validate any configuration migration on all four supported backends.
- The decoder is adapted from the fixed `minimp3` commit recorded in `tools/toolchain.lock.json`. Keep `third_party/minimp3` unmodified and preserve source attribution when changing decoder algorithms or tables.
- Run `moon check`, `moon test`, and `moon fmt --check` for ordinary changes. Decoder behavior changes also need `python tools/validate_compatibility.py`; its external tools and versions are listed in `tools/toolchain.lock.json`.
- Keep generated and temporary validation output under ignored `target/`. Treat `tests/reference_policy.json` and corpus hashes as fixed reference expectations; explain and verify any intentional changes to them.
- Update `README.md` for public API or support-boundary changes, and regenerate `pkg.generated.mbti` with `moon info` when the exported interface changes.
