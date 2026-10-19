# golden

Loads and validates golden sets (`goldens/<suite>.yaml`, SPEC §5).

## Public API
- `load_suite(path) -> Suite`, `load_suites(dir, names=None) -> list[Suite]`, `discover(dir)`
- `Suite`: `suite`, `target`, `description`, `defaults`, `cases`, `source`
  - `evaluator_specs(case)`: suite defaults merged with case overrides. A case-level `null` drops a default.
  - `active_cases(tags=None)`: non-skipped cases, optionally filtered by tag.
- `Case`: `id`, `inputs`, `expected`, `evaluators`, `tags`, `skip`, `criteria`

## Invariants
- Models are frozen and `extra="forbid"`. Unknown keys are errors.
- Suite name and case ids are kebab-case. Case ids are unique within a suite. The file stem must equal `suite`.
- `inputs` / `expected` must be JSON-serialisable. For example, a YAML date is rejected.
- All errors are raised as `ConfigError` and name the file.

## Tests
`uv run pytest tests/test_golden.py`
