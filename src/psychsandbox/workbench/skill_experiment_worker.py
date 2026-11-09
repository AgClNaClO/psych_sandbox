"""One isolated API-only experiment job, never a normal workbench worker."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from .skill_experiment import ExperimentStore, execute_job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    load_dotenv(args.project / ".env")
    asyncio.run(execute_job(ExperimentStore(args.base), args.experiment, args.job, args.project))


if __name__ == "__main__":
    main()
