"""Run the engine shipped with this plugin, without pip or a global CLI."""
import sys
from pathlib import Path
if sys.version_info < (3, 11):
    raise SystemExit(
        "Book Studio requires Python 3.11 or newer; this is Python %d.%d. "
        "Run the same command with a newer Python (python3.13, python3.12, or py -3 on Windows), "
        "or install one from https://www.python.org/downloads/ first." % sys.version_info[:2]
    )
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from bookstudio.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
