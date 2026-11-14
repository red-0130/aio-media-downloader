#!/usr/bin/env python3
"""Standalone E2E Test Runner for All-in-One Media Downloader.

Executes and validates all 4 test tiers:
- Tier 1: Feature Coverage (Threshold: >=80 tests)
- Tier 2: Boundary & Corner Cases (Threshold: >=80 tests)
- Tier 3: Cross-Feature Pairwise Combinations (Threshold: >=16 tests)
- Tier 4: Real-World End-to-End Workflows (Threshold: >=8 tests)
- Total Suite Threshold: >=184 tests

Usage:
    python3 e2e_tests/run_e2e.py [OPTIONS]
    ./e2e_tests/run_e2e.py [OPTIONS]

Options:
    --tier <1|2|3|4|all>   Target specific tier or 'all' (default: all)
    -v, --verbose          Enable verbose pytest output
    -k <expression>        Filter tests by keyword expression
    -x, --fail-fast        Stop execution on first failure
    --help                 Show this help message and exit
"""

import argparse
import os
import sys
import time
from pathlib import Path

# ============================================================================
# 1. Environment and Interpreter Bootstrap
# ============================================================================
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
VENV_PYTHON = BACKEND_ROOT / ".venv" / "bin" / "python3"

# If running outside the uv virtual environment, re-exec inside it
try:
    import pytest
except ImportError:
    if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
        os.environ["VIRTUAL_ENV"] = str(BACKEND_ROOT / ".venv")
        os.environ["PATH"] = f"{BACKEND_ROOT / '.venv' / 'bin'}:{os.environ.get('PATH', '')}"
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)
    else:
        sys.stderr.write("ERROR: pytest is not installed in the current environment.\n")
        sys.exit(1)

# Prepend mocks binary directory to PATH for hermetic extractor simulation
MOCK_BIN_DIR = WORKSPACE_ROOT / "e2e_tests" / "mocks" / "bin"
os.environ["PATH"] = f"{MOCK_BIN_DIR}:{os.environ.get('PATH', '')}"
os.environ["TESTING"] = "1"

# Ensure workspace and backend root are in sys.path
for p in (str(WORKSPACE_ROOT), str(BACKEND_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402


# ============================================================================
# 2. ANSI Styling Utilities
# ============================================================================
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"


# ============================================================================
# 3. Pytest Custom Result Collector Plugin
# ============================================================================
class TierResultCollector:
    """Pytest plugin collecting per-tier counts and timing."""

    def __init__(self, target_tiers: list[str]):
        self.target_tiers = target_tiers
        self.start_time = time.time()
        self.duration = 0.0
        self.stats = {
            "1": {"name": "Tier 1 (Features)", "path": "e2e_tests/tier1_features", "threshold": 80, "passed": 0, "failed": 0, "skipped": 0, "duration": 0.0},
            "2": {"name": "Tier 2 (Boundaries)", "path": "e2e_tests/tier2_boundaries", "threshold": 80, "passed": 0, "failed": 0, "skipped": 0, "duration": 0.0},
            "3": {"name": "Tier 3 (Pairwise)", "path": "e2e_tests/tier3_pairwise", "threshold": 16, "passed": 0, "failed": 0, "skipped": 0, "duration": 0.0},
            "4": {"name": "Tier 4 (Real-World)", "path": "e2e_tests/tier4_real_world", "threshold": 8, "passed": 0, "failed": 0, "skipped": 0, "duration": 0.0},
        }

    def _get_tier_for_path(self, fspath: str) -> str | None:
        p = str(fspath).replace("\\", "/")
        if "tier1_features" in p:
            return "1"
        elif "tier2_boundaries" in p:
            return "2"
        elif "tier3_pairwise" in p:
            return "3"
        elif "tier4_real_world" in p:
            return "4"
        return None

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.failed):
            tier_key = self._get_tier_for_path(str(report.fspath))
            if not tier_key:
                return

            bucket = self.stats[tier_key]
            bucket["duration"] += report.duration

            if report.passed:
                bucket["passed"] += 1
            elif report.failed:
                bucket["failed"] += 1
            elif report.skipped:
                bucket["skipped"] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        self.duration = time.time() - self.start_time


# ============================================================================
# 4. Summary Table Renderer
# ============================================================================
def print_summary_table(
    collector: TierResultCollector, active_tiers: list[str], k_filter: bool = False
) -> bool:
    """Print formatted ANSI summary table and validate thresholds.

    Returns True if all tests passed and met thresholds, False otherwise.
    """
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_threshold = 0
    all_thresholds_met = True

    print("\n" + "=" * 90)
    print(f"{Colors.BOLD}{Colors.CYAN}{'ALL-IN-ONE MEDIA DOWNLOADER — E2E TEST EXECUTION REPORT':^90}{Colors.RESET}")
    print("=" * 90)
    header = f" {'Tier':<22} {'Target Path':<28} {'Passed':<8} {'Failed':<8} {'Threshold':<11} {'Status'}"
    print(f"{Colors.BOLD}{header}{Colors.RESET}")
    print("-" * 90)

    for t_key in sorted(active_tiers):
        t_data = collector.stats[t_key]
        p = t_data["passed"]
        f = t_data["failed"]
        thresh = t_data["threshold"]

        total_passed += p
        total_failed += f
        total_skipped += t_data["skipped"]
        total_threshold += thresh

        if k_filter:
            tier_ok = (f == 0)
            status_str = (
                f"{Colors.GREEN}PASSED{Colors.RESET}"
                if f == 0
                else f"{Colors.RED}FAILED ({f} fail){Colors.RESET}"
            )
            thresh_str = "N/A (-k)"
        else:
            tier_ok = (f == 0) and (p >= thresh)
            if not tier_ok:
                all_thresholds_met = False

            status_str = f"{Colors.GREEN}PASSED{Colors.RESET}" if tier_ok else f"{Colors.RED}FAILED{Colors.RESET}"
            if f > 0:
                status_str = f"{Colors.RED}FAILED ({f} fail){Colors.RESET}"
            elif p < thresh:
                status_str = f"{Colors.RED}BELOW THRESH ({p}/{thresh}){Colors.RESET}"
            thresh_str = f">={thresh}"

        row = (
            f" {t_data['name']:<22} "
            f"{t_data['path']:<28} "
            f"{p:<8} "
            f"{f:<8} "
            f"{thresh_str:<11} "
            f"{status_str}"
        )
        print(row)

    print("-" * 90)

    # Suite total row
    if k_filter:
        suite_ok = (total_failed == 0 and total_passed > 0)
        total_thresh_str = "N/A (-k)"
    else:
        suite_ok = all_thresholds_met and (total_failed == 0)
        if "all" in active_tiers or set(active_tiers) == {"1", "2", "3", "4"}:
            if total_passed < 184:
                suite_ok = False
            total_thresh_str = ">=184"
        else:
            total_thresh_str = f">={total_threshold}"

    total_status = f"{Colors.GREEN}{Colors.BOLD}PASSED{Colors.RESET}" if suite_ok else f"{Colors.RED}{Colors.BOLD}FAILED{Colors.RESET}"
    total_row = (
        f" {Colors.BOLD}{'TOTAL':<22} "
        f"{'e2e_tests/':<28} "
        f"{total_passed:<8} "
        f"{total_failed:<8} "
        f"{total_thresh_str:<11} "
        f"{total_status}{Colors.RESET}"
    )
    print(total_row)
    print("=" * 90)
    print(f"Total Execution Time: {collector.duration:.2f}s | Total Tests Run: {total_passed + total_failed + total_skipped}\n")

    return suite_ok


# ============================================================================
# 5. Main Execution Logic
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone E2E Test Runner for All-in-One Media Downloader."
    )
    parser.add_argument(
        "--tier",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Target test tier to execute (default: all)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose test output"
    )
    parser.add_argument(
        "-k", help="Filter tests by keyword expression (passed to pytest -k)"
    )
    parser.add_argument(
        "-x", "--fail-fast", action="store_true", help="Stop on first failure (passed to pytest -x)"
    )

    args = parser.parse_args()

    # Determine directories to execute
    tier_dirs = {
        "1": WORKSPACE_ROOT / "e2e_tests" / "tier1_features",
        "2": WORKSPACE_ROOT / "e2e_tests" / "tier2_boundaries",
        "3": WORKSPACE_ROOT / "e2e_tests" / "tier3_pairwise",
        "4": WORKSPACE_ROOT / "e2e_tests" / "tier4_real_world",
    }

    if args.tier == "all":
        active_tiers = ["1", "2", "3", "4"]
        target_paths = [str(tier_dirs[k]) for k in active_tiers]
    else:
        active_tiers = [args.tier]
        target_paths = [str(tier_dirs[args.tier])]

    # Prepare pytest arguments
    pytest_args = target_paths + ["-q"]
    if args.verbose:
        pytest_args.append("-vv")
    if args.fail_fast:
        pytest_args.append("-x")
    if args.k:
        pytest_args.extend(["-k", args.k])

    # Instantiate custom collector plugin
    collector = TierResultCollector(active_tiers)

    print(f"\n{Colors.BOLD}Starting E2E Test Suite (Tier: {args.tier})...{Colors.RESET}")
    print(f"Target paths: {', '.join(p for p in target_paths)}\n")

    # Run pytest programmatically with collector plugin
    pytest_exit_code = pytest.main(pytest_args, plugins=[collector])

    # Print summary table and check thresholds
    success = print_summary_table(collector, active_tiers, k_filter=bool(args.k))

    if success and pytest_exit_code == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}All test tiers passed and all threshold criteria were met! (Exit Code: 0){Colors.RESET}\n")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}Test suite failed or threshold criteria were not met! (Exit Code: 1){Colors.RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
