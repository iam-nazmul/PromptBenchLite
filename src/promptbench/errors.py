"""Exceptions that map to the CLI exit-code contract (SPEC §8.5)."""

EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_CONFIG = 2
EXIT_INFRA = 3


class PromptBenchError(Exception):
    exit_code = EXIT_CONFIG


class ConfigError(PromptBenchError):
    """Invalid promptbench.toml, golden set, rubric or CLI usage."""

    exit_code = EXIT_CONFIG


class InfraError(PromptBenchError):
    """A dependency failed in a way that makes results untrustworthy."""

    exit_code = EXIT_INFRA
