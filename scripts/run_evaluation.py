#!/usr/bin/env python
"""Run the synthetic benchmark evaluation."""

import sys
from pathlib import Path

# Add project root to path if script is run directly
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from eagle.evaluation.runner import run_synthetic_benchmark
from eagle.evaluation.report import to_summary

if __name__ == "__main__":
    report = run_synthetic_benchmark()
    print(to_summary(report))
