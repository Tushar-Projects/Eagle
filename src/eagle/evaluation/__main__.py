import sys
from eagle.evaluation.runner import run_synthetic_benchmark
from eagle.evaluation.report import to_summary

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run_synthetic_benchmark()
    print(to_summary(report))
