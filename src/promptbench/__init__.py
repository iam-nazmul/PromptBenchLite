"""PromptBench Lite: regression-test prompts and LLM outputs in CI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("promptbench-lite")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
