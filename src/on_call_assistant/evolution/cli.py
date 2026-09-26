from __future__ import annotations

import argparse
from pathlib import Path

from .core import Config, read_json, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve an on-call agent harness with RRSI")
    parser.add_argument("config", type=Path, help="experiment JSON configuration")
    args = parser.parse_args()
    result = run(Config.load(args.config))
    summary = read_json(result / "summary.json")
    print(f"Run: {result}")
    print(f"Selected harness: {summary['incumbent_harness_dir']}")
    print(f"Held-out score: {summary['heldout_baseline']['score']:.3f} -> {summary['heldout_final']['score']:.3f}")
    print(f"Report: {result / 'summary.json'}")


if __name__ == "__main__":
    main()
