#!/usr/bin/env python3
"""
Unified Coverage Analyzer & Test Optimizer
Combines strategic test planning with advanced quality assessment in a single tool.

Features:
- Multi-dimensional quality assessment (mutation scores, assertion density, test smells)
- Dynamic Programming & Branch-and-Bound optimization
- Dependency-aware test scheduling
- Historical progress tracking
- AST-based test analysis
- Parallel processing for performance
- Export to JSON/CSV for CI/CD integration

Usage:
    python unified_coverage_analyzer.py coverage.json
    python unified_coverage_analyzer.py coverage.json --mode optimize --budget 150
    python unified_coverage_analyzer.py coverage.json --mode analyze --show-recommendations
    python unified_coverage_analyzer.py coverage.json --mode full --workers 4
"""

import argparse
import ast
import csv
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from glob import glob
from pathlib import Path

# Optional rich output
try:
    from rich.console import Console
    from rich.progress import track
    from rich.table import Table

    console = Console()

    def nice_table(title: str):
        return Table(title=title, show_header=True, header_style="bold magenta")
except Exception:
    console = None

    def track(iterable, description=None):
        if description:
            print(description)
        yield from iterable

    def nice_table(title: str):
        class T:
            def __init__(self, title):
                self.rows = []
                self.title = title

            def add_column(self, *a, **k):
                pass

            def add_row(self, a, b):
                self.rows.append((a, b))

            def __str__(self):
                s = f"\n{self.title}\n"
                for a, b in self.rows:
                    s += f"{a:30} {b}\n"
                return s

        return T(title)


# Configuration Constants
MIN_COVERAGE = 80.0
WARNING_COVERAGE = 60.0
EFFORT_BUDGET = 100
HISTORY_FILE = ".coverage_history.json"
BRANCH_BOUND_THRESHOLD = 1000

# ============================================================================
# DATA STRUCTURES
# ============================================================================


class RiskLevel(Enum):
    CRITICAL = "🔴 CRITICAL"
    HIGH = "🟠 HIGH"
    MEDIUM = "🟡 MEDIUM"
    LOW = "🟢 LOW"
    EXCELLENT = "🟢 EXCELLENT"


@dataclass
class AdvancedMetrics:
    """Test quality metrics from AST analysis"""

    estimated_mutation_score: float
    assertion_density: float
    bug_likelihood_score: int
    hard_to_cover_score: int
    test_smell_count: int
    quality_grade: str
    composite_score: float
    has_tests: bool
    test_files_found: int = 0


@dataclass
class TestingOpportunity:
    """Strategic opportunity to improve coverage"""

    file_path: str
    function_name: str
    layer: str
    missing_lines: list[int]
    complexity_score: float
    current_coverage: float

    lines_gained: int
    effort_lines: int
    efficiency: float
    priority_score: int

    risk_level: RiskLevel
    dependencies: set[str] = field(default_factory=set)

    # Score breakdown
    risk_points: int = 0
    layer_points: int = 0
    coverage_points: int = 0
    complexity_points: int = 0

    # Scheduling
    order: int = 0
    blocked_by: list[str] = field(default_factory=list)

    # Quality metrics
    advanced_metrics: AdvancedMetrics | None = None

    def __lt__(self, other):
        return self.priority_score > other.priority_score

    def to_dict(self):
        """Export-friendly dictionary"""
        d = {
            "function": self.function_name,
            "file": self.file_path,
            "layer": self.layer,
            "priority": self.priority_score,
            "effort": self.effort_lines,
            "efficiency": round(self.efficiency, 2),
            "lines_gained": self.lines_gained,
            "risk": self.risk_level.name,
            "order": self.order,
            "blocked_by": self.blocked_by,
            "coverage": self.current_coverage,
        }
        if self.advanced_metrics:
            d.update(
                {
                    "quality_grade": self.advanced_metrics.quality_grade,
                    "mutation_score": self.advanced_metrics.estimated_mutation_score,
                    "assertion_density": self.advanced_metrics.assertion_density,
                    "bug_likelihood": self.advanced_metrics.bug_likelihood_score,
                    "test_smells": self.advanced_metrics.test_smell_count,
                }
            )
        return d


@dataclass
class CoverageStrategy:
    """Complete strategy for improving coverage"""

    opportunities: list[TestingOpportunity]
    total_effort: int
    expected_new_coverage: float
    files_improved: int
    critical_files_covered: int
    algorithm: str = "DP"
    objective: str = "priority"
    timestamp: str = ""

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "algorithm": self.algorithm,
            "objective": self.objective,
            "total_effort": self.total_effort,
            "expected_coverage": round(self.expected_new_coverage, 2),
            "files_improved": self.files_improved,
            "critical_fixed": self.critical_files_covered,
            "tasks": [opp.to_dict() for opp in self.opportunities],
        }


@dataclass
class AnalysisRun:
    """Historical tracking of analysis runs"""

    timestamp: str
    coverage_before: float
    coverage_after_projected: float
    total_lines: int
    covered_lines: int
    opportunities_found: int
    strategy_selected: str
    budget_used: int
    critical_items: int
    avg_quality_score: float = 0.0
    completed: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class FileAnalysis:
    path: str
    layer: str
    covered: int
    total: int
    percent: float
    advanced_metrics: AdvancedMetrics | None = None


# ============================================================================
# FILE CACHING & I/O
# ============================================================================

_file_cache = {}
_cache_lock = None


def _init_cache_lock():
    """Initialize cache lock for multiprocessing"""
    global _cache_lock
    if _cache_lock is None:
        import threading

        _cache_lock = threading.Lock()


def _read_file_cached(path: str) -> str:
    """Thread-safe cached file reading"""
    _init_cache_lock()

    with _cache_lock:
        if path in _file_cache:
            return _file_cache[path]

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()

        with _cache_lock:
            _file_cache[path] = content

        return content
    except Exception:
        return ""


def load_coverage(path: str) -> dict:
    """Load coverage JSON file"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "files" not in data:
            msg = "coverage JSON missing 'files' key"
            raise KeyError(msg)
        return data
    except FileNotFoundError:
        print(f"❌ Coverage file not found: {path}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in coverage file: {path}")
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to load coverage file {path}: {exc}", file=sys.stderr)
        raise


# ============================================================================
# COVERAGE HISTORY MANAGEMENT
# ============================================================================


class CoverageHistory:
    """Manages historical tracking of coverage optimization"""

    def __init__(self, history_file: str = HISTORY_FILE):
        self.history_file = Path(history_file)
        self.runs: list[AnalysisRun] = []
        self.load()

    def load(self):
        """Load history from file"""
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    data = json.load(f)
                    self.runs = [AnalysisRun(**run) for run in data.get("runs", [])]
            except (json.JSONDecodeError, TypeError):
                self.runs = []

    def save(self):
        """Save history to file"""
        data = {
            "version": "1.0",
            "runs": [run.to_dict() for run in self.runs],
        }
        with open(self.history_file, "w") as f:
            json.dump(data, f, indent=2)

    def add_run(self, run: AnalysisRun):
        """Add a new analysis run"""
        self.runs.append(run)
        self.save()

    def get_trend(self) -> dict:
        """Calculate coverage trend"""
        if len(self.runs) < 2:
            return {"trend": "insufficient_data"}

        completed_runs = [r for r in self.runs if r.completed]
        if len(completed_runs) < 2:
            return {"trend": "no_completed_runs"}

        first = completed_runs[0]
        last = completed_runs[-1]

        improvement = last.covered_lines - first.covered_lines
        coverage_gain = last.coverage_after_projected - first.coverage_before

        return {
            "trend": "improving" if improvement > 0 else "stable",
            "total_improvement": improvement,
            "coverage_gain": round(coverage_gain, 2),
            "runs_completed": len(completed_runs),
        }


# ============================================================================
# AST-BASED TEST ANALYSIS
# ============================================================================


def find_test_candidates(file_path: str, repo_root: str = ".", verbose: bool = False) -> list[str]:
    """Enhanced test discovery with multiple strategies"""
    p = Path(file_path)
    stem = p.stem
    cache_key = f"{repo_root}:{stem}"

    if not hasattr(find_test_candidates, "_cache"):
        find_test_candidates._cache = {}

    if cache_key in find_test_candidates._cache:
        return find_test_candidates._cache[cache_key]

    candidates = []

    # Strategy 1: Direct name matching
    patterns = [
        f"tests/test_{stem}.py",
        f"tests/{stem}/test_*.py",
        f"test_{stem}.py",
        f"{stem}_test.py",
    ]

    for pat in patterns:
        found = glob(str(Path(repo_root) / pat), recursive=False)
        candidates.extend(found)

    # Strategy 2: Recursive search
    if not candidates:
        patterns_recursive = [
            f"tests/**/*{stem}*.py",
            f"tests/**/{stem}_test.py",
            f"tests/**/test_{stem}.py",
        ]
        for pat in patterns_recursive:
            found = glob(str(Path(repo_root) / pat), recursive=True)
            candidates.extend(found)

    # De-duplicate
    seen = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)

    find_test_candidates._cache[cache_key] = result

    if verbose and result:
        print(f"  Found {len(result)} test candidates for {file_path}")

    return result


def _analyze_asserts_ast(source: str) -> dict:
    """Parse test source with AST and return assertion counts"""
    try:
        tree = ast.parse(source)
    except Exception:
        return {
            "assert_count": 0,
            "assert_without_msg": 0,
            "pytest_raises_count": 0,
            "unittest_assert_calls": 0,
            "has_tests": False,
        }

    assert_count = 0
    assert_without_msg = 0
    pytest_raises_count = 0
    unittest_assert_calls = 0

    class Visitor(ast.NodeVisitor):
        def visit_Assert(self, node: ast.Assert):
            nonlocal assert_count, assert_without_msg
            assert_count += 1
            if getattr(node, "msg", None) is None:
                assert_without_msg += 1
            self.generic_visit(node)

        def visit_With(self, node: ast.With):
            nonlocal pytest_raises_count
            for item in node.items:
                expr = item.context_expr
                func = expr if not isinstance(expr, ast.Call) else expr.func
                if isinstance(func, ast.Attribute):
                    if getattr(func.value, "id", "") == "pytest" and func.attr == "raises":
                        pytest_raises_count += 1
                elif isinstance(func, ast.Name) and func.id == "raises":
                    pytest_raises_count += 1
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            nonlocal unittest_assert_calls
            func = node.func
            if isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name) and func.attr.startswith("assert")
                ) or func.attr in ("assert_that", "assertThat"):
                    unittest_assert_calls += 1
            elif isinstance(func, ast.Name):
                if func.id in ("assert_that", "ok", "ensure"):
                    unittest_assert_calls += 1
            self.generic_visit(node)

    v = Visitor()
    v.visit(tree)

    total_asserts = assert_count + unittest_assert_calls
    has_tests = (total_asserts + pytest_raises_count) > 0
    return {
        "assert_count": total_asserts,
        "assert_without_msg": assert_without_msg,
        "pytest_raises_count": pytest_raises_count,
        "unittest_assert_calls": unittest_assert_calls,
        "has_tests": has_tests,
    }


def analyze_assertion_quality(
    file_path: str,
    test_file_path: str | None = None,
    repo_root: str = ".",
    coverage_data: dict | None = None,
    verbose: bool = False,
) -> dict:
    """Analyze assertion quality using AST with improved smell detection"""
    # Check if coverage indicates tests exist
    has_coverage = False
    coverage_percent = 0.0
    if coverage_data:
        covered = coverage_data.get("summary", {}).get("covered_lines", 0)
        coverage_percent = coverage_data.get("summary", {}).get("percent_covered", 0.0)
        has_coverage = covered > 0

    # Fast path: skip test discovery for 0% coverage files
    if not has_coverage and not test_file_path:
        return {
            "has_tests": False,
            "assertion_count": 0,
            "assertion_density": 0.0,
            "estimated_mutation_score": 0.0,
            "test_smells": [],  # No smells for untested code
            "test_files_found": 0,
        }

    candidates = []
    if test_file_path:
        candidates = [test_file_path]
    else:
        candidates = find_test_candidates(file_path, repo_root, verbose)

    default = {
        "has_tests": has_coverage,
        "assertion_count": 0,
        "assertion_density": 0.0,
        "estimated_mutation_score": 0.0,
        "test_smells": [],
        "test_files_found": 0,
    }

    if not candidates:
        if has_coverage:
            # Only add smell if coverage is significant (>10%)
            if coverage_percent > 10:
                default["test_smells"] = ["TEST_FILES_NOT_FOUND"]
            default["estimated_mutation_score"] = max(25.0, coverage_percent * 0.5)
        return default

    # Aggregate assertions from all candidate test files
    total_asserts = 0
    total_lines = 0
    all_smells = set()
    found_any_tests = False
    test_files_with_assertions = []

    for candidate in candidates:
        content = _read_file_cached(candidate)
        if not content:
            continue

        ast_result = _analyze_asserts_ast(content)
        if ast_result["has_tests"]:
            found_any_tests = True
            total_asserts += ast_result["assert_count"]
            total_lines += len(content.splitlines())
            test_files_with_assertions.append(candidate)

            # Collect smells (more nuanced thresholds)
            if total_asserts > 5:  # Only flag smells if there are enough assertions
                # EXCEPTION_ONLY: >90% of assertions are pytest.raises
                if ast_result["pytest_raises_count"] >= total_asserts * 0.9:
                    all_smells.add("EXCEPTION_ONLY_TESTS")
                # ASSERTION_ROULETTE: >90% of assertions lack messages
                if ast_result["assert_without_msg"] >= total_asserts * 0.9:
                    all_smells.add("ASSERTION_ROULETTE")

    if not found_any_tests:
        if has_coverage and coverage_percent > 10:
            default["test_smells"] = ["LOW_ASSERTION_COVERAGE"]
            default["estimated_mutation_score"] = max(30.0, coverage_percent * 0.6)
            default["test_files_found"] = len(candidates)
        return default

    assertion_density = (total_asserts / max(1, total_lines)) * 10

    # Improved mutation score estimation
    if has_coverage and total_asserts == 0:
        estimated_mutation_score = max(35.0, coverage_percent * 0.6)
        if coverage_percent > 10:
            all_smells.add("LOW_ASSERTION_COVERAGE")
    elif total_asserts > 0:
        # Better formula: rewards high assertion density
        coverage_bonus = coverage_percent * 0.35
        assertion_bonus = min(40.0, assertion_density * 7.0)  # Cap at 40
        base_score = 30.0 + assertion_bonus + coverage_bonus

        # Less aggressive smell penalty
        smell_penalty = len(all_smells) * 8
        estimated_mutation_score = max(25.0, min(90.0, base_score - smell_penalty))
    else:
        estimated_mutation_score = max(25.0, coverage_percent * 0.5)

    return {
        "has_tests": True,
        "assertion_count": total_asserts,
        "assertion_density": round(assertion_density, 2),
        "estimated_mutation_score": round(estimated_mutation_score, 1),
        "test_smells": list(all_smells),
        "test_files_found": len(test_files_with_assertions),
    }


# ============================================================================
# LAYER & COMPLEXITY ANALYSIS
# ============================================================================


def extract_layer(file_path: str) -> str:
    """Extract architectural layer from file path"""
    parts = Path(file_path).parts
    layer_map = {
        "domain": "Domain",
        "application": "Application",
        "infrastructure": "Infrastructure",
    }

    for key, layer in layer_map.items():
        if key in parts:
            return layer
    return "Other"


def calculate_complexity_score(info: dict, func_name: str | None = None) -> float:
    """Calculate complexity score"""
    if func_name and func_name in info.get("functions", {}):
        func_info = info["functions"][func_name]
        summary = func_info["summary"]
        total_statements = summary["num_statements"]
        missing_lines = func_info.get("missing_lines", [])
    else:
        summary = info["summary"]
        total_statements = summary["num_statements"]
        missing_lines = info.get("missing_lines", [])

    complexity = total_statements / 10.0

    if missing_lines:
        clusters = 1
        for i in range(1, len(missing_lines)):
            if missing_lines[i] - missing_lines[i - 1] > 1:
                clusters += 1
        complexity += clusters * 0.3

    return round(complexity, 2)


# ============================================================================
# SCORING FUNCTIONS
# ============================================================================


def calculate_bug_likelihood(
    coverage_percent: float,
    complexity_score: float,
    missing_lines: int,
    layer: str,
    has_tests: bool,
) -> int:
    """Smooth continuous bug likelihood scoring (0-100)"""
    score = 0.0

    # Coverage gap (exponential decay)
    coverage_gap = 100 - coverage_percent
    score += 50 * (coverage_gap / 100) ** 1.5

    # Complexity (logarithmic scaling)
    score += min(25, 8 * math.log(complexity_score + 1, 2))

    # Missing lines (logarithmic)
    score += min(15, 10 * math.log(missing_lines + 1, 10))

    # Layer criticality
    critical_layers = {"Domain": 10, "Application": 8, "Services": 6}
    score += critical_layers.get(layer, 0)

    # Test existence penalty
    if not has_tests:
        score += 10

    return int(min(100, score))


def calculate_hard_to_cover_score(
    function_name: str, missing_lines: list[int], complexity_score: float, current_coverage: float
) -> int:
    """Estimate difficulty of covering remaining code (0-100)"""
    score = 0
    func_lower = (function_name or "").lower()

    if any(word in func_lower for word in ["_internal", "_validate", "_check"]):
        score += 25
    elif any(
        word in func_lower for word in ["load", "save", "fetch", "connect", "open", "read", "write"]
    ):
        score += 30
    elif any(word in func_lower for word in ["async", "thread", "lock", "concurrent"]):
        score += 35
    elif func_lower.startswith("__") and func_lower.endswith("__"):
        score += 10

    if complexity_score > 8:
        score += 30
    elif complexity_score > 5:
        score += 20
    elif complexity_score > 3:
        score += 10

    if current_coverage > 80:
        score += 25
    elif current_coverage > 50:
        score += 15

    if missing_lines:
        missing_sorted = sorted(set(missing_lines))
        gaps = sum(
            1
            for i in range(1, len(missing_sorted))
            if missing_sorted[i] - missing_sorted[i - 1] > 2
        )
        if gaps > 3:
            score += 20

    return min(100, score)


def compute_unified_quality_score(
    coverage_percent: float,
    branch_coverage: float,
    mutation_score: float,
    assertion_density: float,
    bug_likelihood: int,
    test_smell_count: int,
) -> tuple[float, str]:
    """Unified scoring function producing composite score and grade"""
    # Normalize all inputs to 0-100 scale
    cov_norm = coverage_percent
    branch_norm = branch_coverage
    mutation_norm = mutation_score
    assertion_norm = min(100.0, assertion_density * 20)
    bug_risk_norm = 100 - bug_likelihood

    # Calculate weighted score
    weights = {
        "coverage": 0.25,
        "branch": 0.20,
        "mutation": 0.25,
        "assertion": 0.15,
        "bug_risk": 0.10,
    }

    base_score = (
        cov_norm * weights["coverage"]
        + branch_norm * weights["branch"]
        + mutation_norm * weights["mutation"]
        + assertion_norm * weights["assertion"]
        + bug_risk_norm * weights["bug_risk"]
    )

    # Apply test smell penalty
    smell_penalty = min(20.0, test_smell_count * 5.0)
    final_score = max(0.0, base_score - smell_penalty)

    # Assign grade
    if final_score >= 85:
        grade = "A"
    elif final_score >= 70:
        grade = "B"
    elif final_score >= 55:
        grade = "C"
    elif final_score >= 40:
        grade = "D"
    else:
        grade = "F"

    return round(final_score, 1), grade


def assess_risk_level(
    percent: float, complexity: float, is_critical_layer: bool = False
) -> RiskLevel:
    """Assess risk level"""
    if is_critical_layer:
        if percent < WARNING_COVERAGE:
            return RiskLevel.CRITICAL
        if percent < MIN_COVERAGE:
            return RiskLevel.HIGH

    if percent >= 90:
        return RiskLevel.EXCELLENT
    if percent >= MIN_COVERAGE:
        return RiskLevel.LOW
    if percent >= WARNING_COVERAGE:
        if complexity > 5:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM
    if complexity > 5:
        return RiskLevel.CRITICAL
    return RiskLevel.HIGH


def estimate_testing_effort(
    missing_lines: list[int], complexity: float, layer: str, function_name: str
) -> int:
    """Estimate effort in test lines"""
    base_effort = len(missing_lines)
    complexity_multiplier = 1.0 + (complexity / 8.0)

    layer_multipliers = {
        "API": 1.5,
        "Application": 2.0,
        "Domain": 1.0,
        "Infrastructure": 2.5,
        "Services": 1.8,
        "Repositories": 2.2,
        "Use Cases": 1.6,
    }

    layer_multiplier = layer_multipliers.get(layer, 1.0)
    func_lower = function_name.lower()
    function_multiplier = 1.0

    if func_lower in ["values", "label", "name", "version"] or func_lower.startswith("get_"):
        function_multiplier = 0.3
    elif func_lower.startswith("__") and func_lower.endswith("__"):
        function_multiplier = 0.4
    elif any(word in func_lower for word in ["is_", "has_", "can_", "should_"]):
        function_multiplier = 0.5
    elif any(word in func_lower for word in ["execute", "calculate", "process", "run_"]):
        function_multiplier = 1.8
    elif any(word in func_lower for word in ["load", "save", "fetch", "send"]):
        function_multiplier = 2.0

    effort = base_effort * complexity_multiplier * layer_multiplier * function_multiplier
    return max(1, min(round(effort), base_effort * 5))


def calculate_priority_score(
    missing_lines: list[int],
    current_coverage: float,
    complexity: float,
    risk_level: RiskLevel,
    layer: str,
    function_name: str,
) -> tuple[int, dict]:
    """Calculate transparent priority score (0-100)"""
    risk_points_map = {
        RiskLevel.CRITICAL: 40,
        RiskLevel.HIGH: 30,
        RiskLevel.MEDIUM: 20,
        RiskLevel.LOW: 10,
        RiskLevel.EXCELLENT: 5,
    }
    risk_points = risk_points_map.get(risk_level, 10)

    layer_points_map = {
        "Domain": 30,
        "Application": 25,
        "Use Cases": 25,
        "Services": 20,
        "API": 15,
        "Repositories": 15,
        "Infrastructure": 10,
    }
    layer_points = layer_points_map.get(layer, 10)

    func_lower = function_name.lower()
    if any(word in func_lower for word in ["execute", "calculate", "process", "validate"]):
        layer_points = min(30, layer_points + 5)

    if current_coverage < 20:
        coverage_points = 20
    elif current_coverage < 40:
        coverage_points = 16
    elif current_coverage < 60:
        coverage_points = 12
    elif current_coverage < 80:
        coverage_points = 8
    else:
        coverage_points = 4

    complexity_points = min(10, int(complexity * 1.5))

    total_score = risk_points + layer_points + coverage_points + complexity_points

    breakdown = {
        "risk_points": risk_points,
        "layer_points": layer_points,
        "coverage_points": coverage_points,
        "complexity_points": complexity_points,
    }

    return total_score, breakdown


# ============================================================================
# ADVANCED METRICS ANALYSIS
# ============================================================================


def analyze_file_advanced(
    file_path: str, info: dict, repo_root: str = ".", verbose: bool = False
) -> AdvancedMetrics:
    """Compute advanced quality metrics for a file"""
    summary = info.get("summary", {})
    coverage_percent = float(summary.get("percent_covered", 0.0))
    branch_cov = float(summary.get("percent_branches_covered", coverage_percent * 0.85))
    num_statements = float(summary.get("num_statements", 0.0))
    missing_lines_raw = info.get("missing_lines", []) or []
    missing_lines_count = len(missing_lines_raw)
    complexity = num_statements / 10.0 if num_statements > 0 else 1.0

    # Assertion analysis
    assertion_analysis = analyze_assertion_quality(
        file_path, None, repo_root, coverage_data=info, verbose=verbose
    )

    has_tests = assertion_analysis["has_tests"]
    mutation_score = assertion_analysis["estimated_mutation_score"]
    assertion_density = assertion_analysis["assertion_density"]
    test_smell_count = len(assertion_analysis.get("test_smells", []))
    test_files_found = assertion_analysis.get("test_files_found", 0)

    # Bug likelihood
    layer = extract_layer(file_path)
    bug_likelihood = calculate_bug_likelihood(
        coverage_percent, complexity, missing_lines_count, layer, has_tests
    )

    # Hard-to-cover: average across functions
    hard_total = 0
    func_count = 0
    for func_name, func_info in (info.get("functions") or {}).items():
        if not func_name:
            continue
        func_summary = func_info.get("summary", {})
        func_missing = func_info.get("missing_lines", []) or []
        func_cov = float(func_summary.get("percent_covered", coverage_percent))
        hard_total += calculate_hard_to_cover_score(func_name, func_missing, complexity, func_cov)
        func_count += 1
    hard_score = int(hard_total / func_count) if func_count > 0 else 0

    # Unified scoring
    composite_score, grade = compute_unified_quality_score(
        coverage_percent,
        branch_cov,
        mutation_score,
        assertion_density,
        bug_likelihood,
        test_smell_count,
    )

    return AdvancedMetrics(
        estimated_mutation_score=round(mutation_score, 1),
        assertion_density=round(assertion_density, 2),
        bug_likelihood_score=bug_likelihood,
        hard_to_cover_score=hard_score,
        test_smell_count=test_smell_count,
        quality_grade=grade,
        composite_score=composite_score,
        has_tests=has_tests,
        test_files_found=test_files_found,
    )


# ============================================================================
# OPPORTUNITY EXTRACTION & OPTIMIZATION
# ============================================================================


def extract_opportunities(
    data: dict, repo_root: str = ".", include_quality: bool = True, verbose: bool = False
) -> list[TestingOpportunity]:
    """Extract all testing opportunities with optional quality metrics"""
    opportunities = []

    for file_path, info in track(data["files"].items(), description="Extracting opportunities..."):
        layer = extract_layer(file_path)
        is_critical_layer = layer in ["Domain", "Application", "Use Cases"]

        # Get advanced metrics if requested
        advanced_metrics = None
        if include_quality:
            try:
                advanced_metrics = analyze_file_advanced(file_path, info, repo_root, verbose)
            except Exception as e:
                if verbose:
                    print(f"Warning: Could not analyze {file_path}: {e}")

        for func_name, func_info in info.get("functions", {}).items():
            if func_name == "":
                continue

            summary = func_info["summary"]
            current_coverage = summary["percent_covered"]
            missing_lines = func_info.get("missing_lines", [])

            if not missing_lines or current_coverage >= 100:
                continue

            summary["num_statements"]
            complexity = calculate_complexity_score(info, func_name)
            risk_level = assess_risk_level(current_coverage, complexity, is_critical_layer)

            effort_lines = estimate_testing_effort(missing_lines, complexity, layer, func_name)
            lines_gained = len(missing_lines)
            efficiency = lines_gained / effort_lines if effort_lines > 0 else 0

            priority_score, breakdown = calculate_priority_score(
                missing_lines, current_coverage, complexity, risk_level, layer, func_name
            )

            opportunity = TestingOpportunity(
                file_path=file_path,
                function_name=func_name,
                layer=layer,
                missing_lines=missing_lines,
                complexity_score=complexity,
                current_coverage=current_coverage,
                lines_gained=lines_gained,
                effort_lines=effort_lines,
                efficiency=efficiency,
                priority_score=priority_score,
                risk_level=risk_level,
                risk_points=breakdown["risk_points"],
                layer_points=breakdown["layer_points"],
                coverage_points=breakdown["coverage_points"],
                complexity_points=breakdown["complexity_points"],
                advanced_metrics=advanced_metrics,
            )

            opportunities.append(opportunity)

    return opportunities


def infer_dependencies(opportunities: list[TestingOpportunity]) -> dict[str, set[str]]:
    """Infer dependencies between test opportunities"""
    deps = defaultdict(set)

    def func_id(o):
        return f"{o.file_path}::{o.function_name}"

    # Layer dependencies
    layer_order = {"Infrastructure": 0, "Domain": 1, "Application": 2, "API": 3}

    for opp in opportunities:
        opp_id = func_id(opp)
        opp_layer_priority = layer_order.get(opp.layer, 99)

        for other in opportunities:
            if opp is other:
                continue

            other_id = func_id(other)
            other_layer_priority = layer_order.get(other.layer, 99)

            # If other is in a foundational layer, opp depends on it
            if other_layer_priority < opp_layer_priority:
                if opp.file_path.split("/")[:-1] == other.file_path.split("/")[:-1]:
                    deps[opp_id].add(other_id)

        # Base class dependencies
        if "Base" in opp.function_name or "__init__" in opp.function_name:
            for other in opportunities:
                if other is opp:
                    continue
                if other.file_path == opp.file_path and "Base" not in other.function_name:
                    deps[func_id(other)].add(opp_id)

    return deps


def topological_sort_with_priorities(
    opportunities: list[TestingOpportunity], dependencies: dict[str, set[str]]
) -> list[TestingOpportunity]:
    """Sort opportunities respecting dependencies and priorities using Kahn's algorithm"""

    def func_id(o):
        return f"{o.file_path}::{o.function_name}"

    id_to_opp = {func_id(o): o for o in opportunities}

    # Calculate in-degrees
    in_degree = {func_id(o): 0 for o in opportunities}
    for node, deps in dependencies.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[node] += 1

    # Priority queue
    from heapq import heappop, heappush

    queue = []

    for opp in opportunities:
        oid = func_id(opp)
        if in_degree[oid] == 0:
            heappush(queue, (-opp.priority_score, oid))

    result = []
    order = 1

    while queue:
        _, oid = heappop(queue)
        opp = id_to_opp[oid]
        opp.order = order
        result.append(opp)
        order += 1

        # Reduce in-degrees for dependent nodes
        for other_id, deps in dependencies.items():
            if oid in deps:
                in_degree[other_id] -= 1
                if in_degree[other_id] == 0:
                    other_opp = id_to_opp[other_id]
                    heappush(queue, (-other_opp.priority_score, other_id))

    # Check for cycles
    if len(result) != len(opportunities):
        print("⚠️  Warning: Circular dependencies detected. Some tasks may be misordered.")
        remaining = [o for o in opportunities if o not in result]
        remaining.sort(key=lambda x: x.priority_score, reverse=True)
        for opp in remaining:
            opp.order = order
            result.append(opp)
            order += 1

    return result


def optimize_coverage_dp(
    opportunities: list[TestingOpportunity],
    effort_budget: int,
    prioritize_critical: bool = True,
    objective: str = "priority",
) -> tuple[CoverageStrategy, list[str]]:
    """Dynamic Programming optimization (0/1 Knapsack)"""
    explanation = []

    # Choose algorithm based on dataset size
    if len(opportunities) > BRANCH_BOUND_THRESHOLD:
        return optimize_coverage_branch_bound(
            opportunities, effort_budget, prioritize_critical, objective
        )

    explanation.append(f"Using Dynamic Programming (optimal for {len(opportunities)} items)")

    # Phase 1: Critical items
    selected_critical = []
    remaining_budget = effort_budget

    if prioritize_critical:
        critical_opps = [o for o in opportunities if o.risk_level == RiskLevel.CRITICAL]
        critical_opps.sort(
            key=lambda o: o.priority_score / o.effort_lines if o.effort_lines > 0 else 0,
            reverse=True,
        )

        for opp in critical_opps:
            if opp.effort_lines <= remaining_budget:
                selected_critical.append(opp)
                remaining_budget -= opp.effort_lines

        explanation.append(
            f"Phase 1: Selected {len(selected_critical)} critical items ({sum(o.effort_lines for o in selected_critical)}L)"
        )

        critical_ids = {id(o) for o in selected_critical}
        opportunities = [o for o in opportunities if id(o) not in critical_ids]

    # Phase 2: DP
    n = len(opportunities)
    explanation.append(f"Phase 2: DP optimization over {n} items with {remaining_budget}L budget")

    def get_value(opp: TestingOpportunity) -> int:
        if objective == "priority":
            return opp.priority_score
        if objective == "coverage":
            return opp.lines_gained * 10
        if objective == "efficiency":
            return int(opp.lines_gained * opp.efficiency * 10)
        if objective == "quality" and opp.advanced_metrics:
            return int(opp.advanced_metrics.composite_score)
        return opp.priority_score

    dp = [0] * (remaining_budget + 1)
    selected = [[] for _ in range(remaining_budget + 1)]

    for i, opp in enumerate(opportunities):
        effort = opp.effort_lines
        value = get_value(opp)

        if effort > remaining_budget:
            continue

        for w in range(remaining_budget, effort - 1, -1):
            new_value = dp[w - effort] + value
            if new_value > dp[w]:
                dp[w] = new_value
                selected[w] = selected[w - effort] + [i]

    selected_indices = selected[remaining_budget]
    selected_non_critical = [opportunities[i] for i in selected_indices]

    explanation.append(
        f"Phase 2: Selected {len(selected_non_critical)} optimal items ({sum(o.effort_lines for o in selected_non_critical)}L)"
    )

    all_selected = selected_critical + selected_non_critical

    files_improved = len({o.file_path for o in all_selected})
    total_effort = sum(o.effort_lines for o in all_selected)
    critical_count = sum(1 for o in all_selected if o.risk_level == RiskLevel.CRITICAL)

    explanation.append(f"Total: {len(all_selected)} items, {total_effort}L effort")
    explanation.append(f"Optimality: GUARANTEED OPTIMAL for '{objective}' objective")

    strategy = CoverageStrategy(
        opportunities=all_selected,
        total_effort=total_effort,
        expected_new_coverage=0.0,
        files_improved=files_improved,
        critical_files_covered=critical_count,
        algorithm="Dynamic Programming",
        objective=objective,
        timestamp=datetime.now().isoformat(),
    )

    return strategy, explanation


def optimize_coverage_branch_bound(
    opportunities: list[TestingOpportunity],
    effort_budget: int,
    prioritize_critical: bool = True,
    objective: str = "priority",
) -> tuple[CoverageStrategy, list[str]]:
    """Branch and Bound optimization for larger datasets"""
    explanation = ["Using Branch & Bound algorithm (optimal for large datasets)"]

    # Phase 1: Critical items
    selected_critical = []
    remaining_budget = effort_budget

    if prioritize_critical:
        critical_opps = [o for o in opportunities if o.risk_level == RiskLevel.CRITICAL]
        critical_opps.sort(
            key=lambda o: o.priority_score / o.effort_lines if o.effort_lines > 0 else 0,
            reverse=True,
        )

        for opp in critical_opps:
            if opp.effort_lines <= remaining_budget:
                selected_critical.append(opp)
                remaining_budget -= opp.effort_lines

        explanation.append(
            f"Phase 1: Selected {len(selected_critical)} critical items ({sum(o.effort_lines for o in selected_critical)}L)"
        )

        critical_ids = {id(o) for o in selected_critical}
        opportunities = [o for o in opportunities if id(o) not in critical_ids]

    # Phase 2: Branch and Bound
    def get_value(opp: TestingOpportunity) -> int:
        if objective == "priority":
            return opp.priority_score
        if objective == "coverage":
            return opp.lines_gained * 10
        if objective == "efficiency":
            return int(opp.lines_gained * opp.efficiency * 10)
        if objective == "quality" and opp.advanced_metrics:
            return int(opp.advanced_metrics.composite_score)
        return opp.priority_score

    # Sort by value/weight ratio
    items = [(get_value(o), o.effort_lines, o) for o in opportunities]
    items.sort(key=lambda x: x[0] / x[1] if x[1] > 0 else 0, reverse=True)

    best_value = 0
    best_solution = []

    def bound(level, current_value, current_weight):
        """Calculate upper bound using fractional knapsack"""
        if current_weight >= remaining_budget:
            return 0

        bound_value = current_value
        available = remaining_budget - current_weight

        for i in range(level, len(items)):
            value, weight, _ = items[i]
            if weight <= available:
                bound_value += value
                available -= weight
            else:
                bound_value += value * (available / weight)
                break

        return bound_value

    def branch_bound(level, current_value, current_weight, current_solution):
        nonlocal best_value, best_solution

        if current_weight <= remaining_budget and current_value > best_value:
            best_value = current_value
            best_solution = current_solution.copy()

        if level >= len(items):
            return

        if bound(level, current_value, current_weight) <= best_value:
            return  # Prune this branch

        value, weight, opp = items[level]

        # Try including this item
        if current_weight + weight <= remaining_budget:
            branch_bound(
                level + 1, current_value + value, current_weight + weight, [*current_solution, opp]
            )

        # Try excluding this item
        branch_bound(level, current_value, current_weight, current_solution)

    branch_bound(0, 0, 0, [])

    selected_non_critical = best_solution
    explanation.append(
        f"Phase 2: B&B selected {len(selected_non_critical)} optimal items ({sum(o.effort_lines for o in selected_non_critical)}L)"
    )

    all_selected = selected_critical + selected_non_critical

    files_improved = len({o.file_path for o in all_selected})
    total_effort = sum(o.effort_lines for o in all_selected)
    critical_count = sum(1 for o in all_selected if o.risk_level == RiskLevel.CRITICAL)

    explanation.append(f"Total: {len(all_selected)} items, {total_effort}L effort")
    explanation.append("Optimality: GUARANTEED OPTIMAL via Branch & Bound")

    strategy = CoverageStrategy(
        opportunities=all_selected,
        total_effort=total_effort,
        expected_new_coverage=0.0,
        files_improved=files_improved,
        critical_files_covered=critical_count,
        algorithm="Branch & Bound",
        objective=objective,
        timestamp=datetime.now().isoformat(),
    )

    return strategy, explanation


# ============================================================================
# STATISTICS & REPORTING
# ============================================================================


def calculate_coverage_statistics(data: dict, file_analyses: list) -> dict:
    """Calculate overall coverage statistics"""
    total_covered = sum(f.covered for f in file_analyses)
    total_statements = sum(f.total for f in file_analyses)
    overall_percent = 100 * total_covered / total_statements if total_statements > 0 else 0

    coverage_ranges = {
        "0-20%": 0,
        "20-40%": 0,
        "40-60%": 0,
        "60-80%": 0,
        "80-100%": 0,
    }

    for f in file_analyses:
        if f.percent < 20:
            coverage_ranges["0-20%"] += 1
        elif f.percent < 40:
            coverage_ranges["20-40%"] += 1
        elif f.percent < 60:
            coverage_ranges["40-60%"] += 1
        elif f.percent < 80:
            coverage_ranges["60-80%"] += 1
        else:
            coverage_ranges["80-100%"] += 1

    layer_coverage = defaultdict(lambda: {"covered": 0, "total": 0})
    for f in file_analyses:
        layer_coverage[f.layer]["covered"] += f.covered
        layer_coverage[f.layer]["total"] += f.total

    for _layer, stats in layer_coverage.items():
        stats["percent"] = 100 * stats["covered"] / stats["total"] if stats["total"] > 0 else 0

    return {
        "total_covered": total_covered,
        "total_statements": total_statements,
        "overall_percent": overall_percent,
        "total_files": len(file_analyses),
        "coverage_ranges": coverage_ranges,
        "layer_coverage": dict(layer_coverage),
    }


def export_strategy_json(strategy: CoverageStrategy, output_file: str):
    """Export strategy to JSON"""
    with open(output_file, "w") as f:
        json.dump(strategy.to_dict(), f, indent=2)
    print(f"\n✓ Strategy exported to: {output_file}")


def export_strategy_csv(strategy: CoverageStrategy, output_file: str):
    """Export strategy to CSV"""
    fieldnames = [
        "order",
        "function",
        "file",
        "layer",
        "priority",
        "effort",
        "efficiency",
        "lines_gained",
        "risk",
        "blocked_by",
        "coverage",
    ]

    # Add quality fields if available
    if strategy.opportunities and strategy.opportunities[0].advanced_metrics:
        fieldnames.extend(["quality_grade", "mutation_score", "assertion_density"])

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for opp in strategy.opportunities:
            row = opp.to_dict()
            # Only include fields that exist in fieldnames
            row = {k: v for k, v in row.items() if k in fieldnames}
            writer.writerow(row)
    print(f"✓ Strategy exported to: {output_file}")


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================


def print_section_header(title: str):
    """Print formatted section header"""
    width = 90
    print("\n" + "═" * width)
    print(f"  {title}")
    print("═" * width)


def print_history_trend(history: CoverageHistory):
    """Print coverage improvement trend"""
    if len(history.runs) == 0:
        return

    print_section_header("📈 COVERAGE HISTORY")
    print()

    trend = history.get_trend()

    if trend["trend"] == "insufficient_data":
        print(f"  Analysis runs: {len(history.runs)}")
        print("  Need at least 2 runs to show trends")
        return

    if trend["trend"] == "no_completed_runs":
        print(f"  Analysis runs: {len(history.runs)} (none completed)")
        print("  Mark runs as completed with: --mark-complete")
        return

    print(f"  Total runs: {len(history.runs)}")
    print(f"  Completed: {trend['runs_completed']}")
    print(f"  Total improvement: +{trend['total_improvement']} lines covered")
    print(f"  Coverage gain: +{trend['coverage_gain']:.1f}%")
    print()

    print("  Recent runs:")
    for run in history.runs[-5:]:
        status = "✓" if run.completed else "○"
        print(
            f"    {status} {run.timestamp[:19]} | {run.coverage_before:.1f}% → "
            f"{run.coverage_after_projected:.1f}% | {run.strategy_selected}"
        )
    print()


def print_optimization_summary(
    strategy: CoverageStrategy,
    budget: int,
    current_stats: dict,
    explanation: list[str] | None = None,
):
    """Print optimization results"""
    print_section_header(f"🎯 OPTIMIZATION SUMMARY - {strategy.algorithm.upper()}")
    print()

    if explanation:
        print("  Decision Process:")
        for line in explanation:
            print(f"    • {line}")
        print()

    total_lines_gained = sum(o.lines_gained for o in strategy.opportunities)
    avg_efficiency = (
        sum(o.efficiency for o in strategy.opportunities) / len(strategy.opportunities)
        if strategy.opportunities
        else 0
    )
    avg_priority = (
        sum(o.priority_score for o in strategy.opportunities) / len(strategy.opportunities)
        if strategy.opportunities
        else 0
    )

    efficiency_pct = strategy.total_effort / budget * 100 if budget > 0 else 0

    print("  Results:")
    print(
        f"    Effort Budget:      {strategy.total_effort}/{budget} test lines ({efficiency_pct:.0f}%)"
    )
    print(f"    Coverage Gained:    {total_lines_gained} source lines")
    print(f"    Avg Efficiency:     {avg_efficiency:.1f}× (coverage lines per test line)")
    print(f"    Avg Priority:       {avg_priority:.0f}/100")
    print(f"    Files Improved:     {strategy.files_improved}")
    print(f"    Critical Fixes:     {strategy.critical_files_covered}")

    # Show quality metrics if available
    if strategy.opportunities and strategy.opportunities[0].advanced_metrics:
        avg_quality = sum(
            o.advanced_metrics.composite_score for o in strategy.opportunities if o.advanced_metrics
        ) / len(strategy.opportunities)
        avg_mutation = sum(
            o.advanced_metrics.estimated_mutation_score
            for o in strategy.opportunities
            if o.advanced_metrics
        ) / len(strategy.opportunities)
        print(f"    Avg Quality Score:  {avg_quality:.1f}/100")
        print(f"    Avg Mutation Est:   {avg_mutation:.1f}%")

    print()

    # Calculate projected outcomes
    current_coverage = current_stats["overall_percent"]
    current_covered = current_stats["total_covered"]
    total_statements = current_stats["total_statements"]

    new_covered = current_covered + total_lines_gained
    new_coverage = 100 * new_covered / total_statements if total_statements > 0 else 0
    coverage_increase = new_coverage - current_coverage

    print("  Projected Impact:")
    print(f"    Current Coverage:    {current_coverage:.1f}%")
    print(f"    Projected Coverage:  {new_coverage:.1f}%")
    print(f"    Improvement:         +{coverage_increase:.1f} percentage points")

    # Progress bar
    current_bar = int(current_coverage / 2)
    new_bar = int(new_coverage / 2)
    bar = ("█" * current_bar) + ("▓" * (new_bar - current_bar)) + ("░" * (50 - new_bar))
    print(f"    Progress:            [{bar}]")
    print()


def print_strategic_plan(
    strategy: CoverageStrategy, show_quality: bool = False, min_priority: int = 0
):
    """Print priority testing plan"""
    print_section_header("📋 PRIORITY TESTING PLAN")
    print()
    print("  Priority Score = Risk(0-40) + Layer(0-30) + Coverage Gap(0-20) + Complexity(0-10)")
    if show_quality:
        print("  Quality Grade = Unified assessment of coverage, mutation, assertions, and smells")
    if min_priority > 0:
        print(f"  Filtering: Showing only items with priority ≥ {min_priority}")
    print()

    by_risk = defaultdict(list)
    for opp in strategy.opportunities:
        # Filter by minimum priority
        if opp.priority_score >= min_priority:
            by_risk[opp.risk_level].append(opp)

    priority_order = [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]

    total_shown = sum(len(opps) for opps in by_risk.values())
    total_filtered = len(strategy.opportunities) - total_shown

    if total_filtered > 0:
        print(
            f"  ℹ️  Showing {total_shown}/{len(strategy.opportunities)} items (filtered {total_filtered} below priority {min_priority})"
        )
        print()

    for risk_level in priority_order:
        opps = by_risk.get(risk_level, [])
        if not opps:
            continue

        if risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]:
            print(f"  {risk_level.value}")
            print()

        for opp in opps:
            effort_bar = "█" * min(int(opp.effort_lines / 3), 5) or "·"

            line = (
                f"  [{opp.order:2}] {opp.function_name:40} "
                f"P:{opp.priority_score:3}/100  "
                f"Eff:{opp.efficiency:4.1f}×  "
                f"{effort_bar} {opp.effort_lines:2}L"
            )

            if show_quality and opp.advanced_metrics:
                line += f"  Grade:{opp.advanced_metrics.quality_grade}"

            print(line)

            # Show breakdown for top 5
            if opp.order <= 5:
                print(
                    f"       └─ Risk:{opp.risk_points} Layer:{opp.layer_points} "
                    f"Gap:{opp.coverage_points} Complex:{opp.complexity_points}  │ {opp.layer}"
                )
                if show_quality and opp.advanced_metrics:
                    print(
                        f"          Mutation:{opp.advanced_metrics.estimated_mutation_score:.0f}% "
                        f"Assertions:{opp.advanced_metrics.assertion_density:.1f} "
                        f"BugRisk:{opp.advanced_metrics.bug_likelihood_score}"
                    )
                print(f"       {opp.file_path}")

            if opp.order % 5 == 0:
                print()


def print_quality_dashboard(file_analyses: list[FileAnalysis]):
    """Print test quality dashboard"""
    files_with_metrics = [f for f in file_analyses if f.advanced_metrics]

    if not files_with_metrics:
        return

    print_section_header("📊 TEST QUALITY DASHBOARD")
    print()

    avg_mutation = sum(
        f.advanced_metrics.estimated_mutation_score for f in files_with_metrics
    ) / len(files_with_metrics)
    avg_score = sum(f.advanced_metrics.composite_score for f in files_with_metrics) / len(
        files_with_metrics
    )
    files_with_smells = sum(
        1 for f in files_with_metrics if f.advanced_metrics.test_smell_count > 0
    )

    table = nice_table("Quality Metrics")
    if console:
        table.add_column("Metric", justify="left")
        table.add_column("Value", justify="right")
    table.add_row("Avg Estimated Mutation Score", f"{avg_mutation:.1f}% (target >80%)")
    table.add_row("Avg Composite Quality Score", f"{avg_score:.1f}/100")
    table.add_row("Files with Test Smells", f"{files_with_smells}/{len(files_with_metrics)}")

    grade_dist = defaultdict(int)
    for f in files_with_metrics:
        grade_dist[f.advanced_metrics.quality_grade] += 1

    for grade in ["A", "B", "C", "D", "F"]:
        count = grade_dist[grade]
        table.add_row(f"Grade {grade}", f"{count} files")

    if console:
        console.print(table)
    else:
        print(table)

    # Show critical quality issues
    critical_quality = [
        f for f in files_with_metrics if f.advanced_metrics.quality_grade in ["F", "D"]
    ][:10]
    if critical_quality:
        print()
        print("  ⚠️  Files Needing Quality Improvement:")
        for i, f in enumerate(critical_quality, 1):
            print(
                f"    [{i:2}] {Path(f.path).name:50} "
                f"Grade:{f.advanced_metrics.quality_grade} "
                f"Mutation:{f.advanced_metrics.estimated_mutation_score:.0f}% "
                f"Smells:{f.advanced_metrics.test_smell_count}"
            )
    print()


def print_execution_guide(mode: str):
    """Print execution guide"""
    print_section_header("🚀 NEXT STEPS")
    print()

    if mode in ["optimize", "full"]:
        print("  1. Review dependency-aware execution order (🔗 section)")
        print("  2. Start with high-efficiency tests (⚡ section)")
        print("  3. Follow priority plan ([1], [2], [3]...)")
        print("  4. Import CSV into project management tool if needed")
        print("  5. Re-run after completing tests")
        print("  6. Mark run as completed: --mark-complete")

    if mode in ["analyze", "full"]:
        print("  Quality Improvement:")
        print("    • Focus on files with F/D grades")
        print("    • Add meaningful assertions (not just execution)")
        print("    • Reduce test smells (assertion roulette, exception-only tests)")

    print()
    print("  Common Commands:")
    print("    --mode analyze              Quality assessment only")
    print("    --mode optimize             Test planning only")
    print("    --mode full                 Complete analysis + planning")
    print("    --budget 200                Adjust effort budget")
    print("    --objective quality         Optimize for quality instead of priority")
    print("    --show-recommendations      Get actionable improvement advice")
    print("    --no-deps                   Disable dependency analysis")
    print("    --verbose                   Show detailed diagnostic info")
    print()


def print_dependency_info(strategy: CoverageStrategy, dependencies: dict):
    """Print dependency-aware execution order"""
    print_section_header("🔗 DEPENDENCY-AWARE EXECUTION ORDER")
    print()

    def func_id(o):
        return f"{o.file_path}::{o.function_name}"

    has_deps = any(len(deps) > 0 for deps in dependencies.values())

    if not has_deps:
        print("  ℹ️  No dependencies detected. Execute in priority order.")
        return

    print("  Tasks are ordered to respect dependencies:")
    print("  • Foundational layers (Infrastructure, Domain) before dependent layers")
    print("  • Base classes/functions before derived implementations")
    print()

    shown = 0
    for opp in strategy.opportunities:
        if shown >= 10:
            break

        oid = func_id(opp)
        deps = dependencies.get(oid, set())

        if deps:
            dep_names = [d.split("::")[-1] for d in deps]
            print(f"  [{opp.order:2}] {opp.function_name:40} Priority:{opp.priority_score:3}")
            print(f"       ⚠️  Blocked by: {', '.join(dep_names[:3])}")
            if len(dep_names) > 3:
                print(f"       ... and {len(dep_names) - 3} more")
            shown += 1

    if shown == 0:
        print("  ℹ️  Top 10 items have no blocking dependencies.")

    print()


def print_efficiency_wins(opportunities: list[TestingOpportunity]):
    """Highlight most efficient tests"""
    print_section_header("⚡ TOP 10 MOST EFFICIENT TESTS")
    print()
    print("  Efficiency = Coverage Lines Gained ÷ Test Lines Written")
    print()

    efficient = [o for o in opportunities if o.efficiency >= 2.0 and o.effort_lines <= 15]
    efficient.sort(key=lambda x: x.efficiency, reverse=True)

    if not efficient:
        print("  No high-efficiency opportunities found (≥2.0× with ≤15L effort).")
        return

    for i, opp in enumerate(efficient[:10], 1):
        print(
            f"  {i:2}. {opp.function_name:45} "
            f"{opp.efficiency:4.1f}× efficiency  "
            f"({opp.lines_gained}÷{opp.effort_lines})"
        )
        if i <= 3:
            print(f"      {opp.file_path}")

    if len(efficient) > 10:
        print(f"\n  ... +{len(efficient) - 10} more efficient opportunities")
    print()


def print_actionable_recommendations(
    file_analyses: list[FileAnalysis], opportunities: list[TestingOpportunity]
):
    """Provide specific, actionable recommendations"""
    print_section_header("💡 ACTIONABLE RECOMMENDATIONS")
    print()

    # Analyze patterns
    low_cov_files = [f for f in file_analyses if f.percent < 50]
    weak_test_files = [
        f
        for f in file_analyses
        if f.percent > 70
        and f.advanced_metrics
        and f.advanced_metrics.estimated_mutation_score < 50
    ]
    high_bug_risk = [
        f
        for f in file_analyses
        if f.advanced_metrics and f.advanced_metrics.bug_likelihood_score > 70
    ]

    print("🎯 Priority Actions (by effort/impact):\n")

    # Recommendation 1: High-risk, low-coverage files
    critical = [f for f in low_cov_files if f in high_bug_risk]
    if critical:
        print(f"1. 🚨 URGENT: Add tests to {len(critical)} high-risk files with low coverage")
        print(
            f"   Files like: {Path(critical[0].path).name}"
            + (f", {Path(critical[1].path).name}" if len(critical) > 1 else "")
        )
        print("   → These have highest bug probability AND low coverage")
        print()

    # Recommendation 2: Strengthen weak tests
    if len(weak_test_files) > 10:
        print(f"2. 🔬 Improve test quality for {len(weak_test_files)} files with weak tests")
        print("   → Tests execute code but lack meaningful assertions")
        print("   → Add assertions that verify behavior, not just execution")
        print("   → Target: Increase assertion density to >1.0 per 10 lines")
        print()

    # Recommendation 3: Low-hanging fruit
    easy_wins = [
        o
        for o in opportunities
        if 40 < o.current_coverage < 70
        and o.advanced_metrics
        and o.advanced_metrics.hard_to_cover_score < 50
    ]
    if easy_wins:
        print(
            f"3. ✅ Quick wins: {len(easy_wins)} opportunities between 40-70% coverage, easy to improve"
        )
        print("   → These have moderate coverage and low complexity")
        print("   → Small effort can push them to >70% threshold")
        print()

    # Recommendation 4: Layer focus
    layer_stats = defaultdict(lambda: {"count": 0, "avg_cov": 0.0, "avg_score": 0.0})
    for f in file_analyses:
        if f.advanced_metrics:
            layer = f.layer
            layer_stats[layer]["count"] += 1
            layer_stats[layer]["avg_cov"] += f.percent
            layer_stats[layer]["avg_score"] += f.advanced_metrics.composite_score

    weak_layers = []
    for layer, stats in layer_stats.items():
        if stats["count"] > 0:
            stats["avg_cov"] /= stats["count"]
            stats["avg_score"] /= stats["count"]
            if stats["avg_cov"] < 60 or stats["avg_score"] < 50:
                weak_layers.append((layer, stats))

    if weak_layers:
        print("4. 🏗️  Focus on weak architectural layers:")
        for layer, stats in sorted(weak_layers, key=lambda x: x[1]["avg_score"]):
            print(
                f"   • {layer}: {stats['avg_cov']:.0f}% coverage, {stats['avg_score']:.0f} quality score"
            )
        print()

    print("📚 General Guidelines:")
    print("   • Aim for >80% line coverage on critical business logic")
    print("   • Focus on mutation-killing tests (meaningful assertions)")
    print("   • Prioritize Domain and Application layers")
    print("   • Don't chase 100% - focus on high-risk, high-value code")
    print()


# ============================================================================
# MAIN EXECUTION MODES
# ============================================================================


def run_analyze_mode(data: dict, args):
    """Run analysis-only mode (quality assessment)"""
    print("\n🔬 Advanced Test Quality Analysis\n")

    start_time = time.time()

    # Build file analyses with quality metrics
    file_analyses = []
    for file_path, info in track(data["files"].items(), description="Analyzing test quality..."):
        summary = info["summary"]
        try:
            metrics = analyze_file_advanced(file_path, info, args.repo_root, args.verbose)
            file_analyses.append(
                FileAnalysis(
                    path=file_path,
                    layer=extract_layer(file_path),
                    covered=summary["covered_lines"],
                    total=summary["num_statements"],
                    percent=summary["percent_covered"],
                    advanced_metrics=metrics,
                )
            )
        except Exception as e:
            if args.verbose:
                print(f"Warning: Could not analyze {file_path}: {e}")
            continue

    analysis_time = time.time() - start_time

    if args.verbose:
        print(f"\n⏱️  Analysis completed in {analysis_time:.2f} seconds")
        print(f"   Files processed: {len(file_analyses)}")
        if len(file_analyses) > 0:
            print(f"   Throughput: {len(file_analyses) / analysis_time:.1f} files/sec")

    stats = calculate_coverage_statistics(data, file_analyses)

    # Print current coverage
    print_section_header("📊 CURRENT COVERAGE STATISTICS")
    print()
    print(f"  Overall Coverage: {stats['overall_percent']:.1f}%")
    print(f"  Lines: {stats['total_covered']}/{stats['total_statements']} covered")
    print(f"  Files: {stats['total_files']} total")
    print()

    print("  Coverage Distribution:")
    for range_label, count in stats["coverage_ranges"].items():
        pct = 100 * count / stats["total_files"] if stats["total_files"] > 0 else 0
        bar = "█" * int(pct / 5)
        print(f"    {range_label:>10}: {count:3} files  {bar}")
    print()

    print("  Layer Coverage:")
    for layer, layer_stats in sorted(
        stats["layer_coverage"].items(), key=lambda x: x[1]["percent"], reverse=True
    ):
        pct = layer_stats["percent"]
        status = "✓" if pct >= MIN_COVERAGE else "⚠" if pct >= WARNING_COVERAGE else "✗"
        print(
            f"    {status} {layer:20} {pct:5.1f}%  "
            f"({layer_stats['covered']}/{layer_stats['total']})"
        )

    # Quality dashboard
    print_quality_dashboard(file_analyses)

    # Show recommendations if requested
    if args.show_recommendations:
        opportunities = extract_opportunities(
            data, args.repo_root, include_quality=True, verbose=args.verbose
        )
        print_actionable_recommendations(file_analyses, opportunities)

    return file_analyses, stats


def run_optimize_mode(data: dict, args):
    """Run optimization-only mode (test planning)"""
    print("\n🎯 Strategic Test Coverage Optimizer\n")

    # Load history
    history = CoverageHistory()
    if history.runs:
        print_history_trend(history)

    # Build file analyses
    file_analyses = []
    for file_path, info in data["files"].items():
        summary = info["summary"]
        file_analyses.append(
            FileAnalysis(
                path=file_path,
                layer=extract_layer(file_path),
                covered=summary["covered_lines"],
                total=summary["num_statements"],
                percent=summary["percent_covered"],
            )
        )

    stats = calculate_coverage_statistics(data, file_analyses)

    # Print current coverage
    print_section_header("📊 CURRENT COVERAGE STATISTICS")
    print()
    print(f"  Overall Coverage: {stats['overall_percent']:.1f}%")
    print(f"  Lines: {stats['total_covered']}/{stats['total_statements']} covered")
    print(f"  Files: {stats['total_files']} total")
    print()

    # Extract opportunities (without quality analysis for speed)
    opportunities = extract_opportunities(
        data, args.repo_root, include_quality=False, verbose=args.verbose
    )

    if not opportunities:
        print("\n✅ Perfect! No testing opportunities found - coverage is complete!")
        return None, stats

    print(f"  Found {len(opportunities)} testing opportunities")

    # Run optimization
    strategy, explanation = optimize_coverage_dp(
        opportunities,
        args.budget,
        prioritize_critical=not args.no_critical_first,
        objective=args.objective,
    )

    # Dependency analysis
    dependencies = {}
    if not args.no_deps:
        dependencies = infer_dependencies(strategy.opportunities)
        strategy.opportunities = topological_sort_with_priorities(
            strategy.opportunities, dependencies
        )

        def func_id(o):
            return f"{o.file_path}::{o.function_name}"

        for opp in strategy.opportunities:
            oid = func_id(opp)
            if oid in dependencies:
                opp.blocked_by = [d.split("::")[-1] for d in dependencies[oid]]

    # Calculate projected coverage
    total_lines_gained = sum(o.lines_gained for o in strategy.opportunities)
    new_covered = stats["total_covered"] + total_lines_gained
    new_coverage = (
        100 * new_covered / stats["total_statements"] if stats["total_statements"] > 0 else 0
    )
    strategy.expected_new_coverage = new_coverage

    # Print results
    print_optimization_summary(strategy, args.budget, stats, explanation)

    if not args.no_deps and dependencies:
        print_dependency_info(strategy, dependencies)

    print_strategic_plan(strategy, show_quality=False, min_priority=args.min_priority)
    print_efficiency_wins(strategy.opportunities)

    # Export if requested
    if not args.no_export:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = f"{args.export_prefix}_{timestamp}.json"
        csv_file = f"{args.export_prefix}_{timestamp}.csv"

        export_strategy_json(strategy, json_file)
        export_strategy_csv(strategy, csv_file)

    # Save to history
    run = AnalysisRun(
        timestamp=strategy.timestamp,
        coverage_before=stats["overall_percent"],
        coverage_after_projected=new_coverage,
        total_lines=stats["total_statements"],
        covered_lines=stats["total_covered"],
        opportunities_found=len(opportunities),
        strategy_selected=f"{strategy.algorithm} - {args.objective}",
        budget_used=strategy.total_effort,
        critical_items=strategy.critical_files_covered,
        completed=False,
    )
    history.add_run(run)

    return strategy, stats


def run_full_mode(data: dict, args):
    """Run complete analysis + optimization"""
    print("\n🔬🎯 Unified Coverage Analysis & Test Planning\n")

    start_time = time.time()

    # Load history
    history = CoverageHistory()
    if history.runs:
        print_history_trend(history)

    # Build file analyses with quality metrics
    file_analyses = []
    for file_path, info in track(data["files"].items(), description="Analyzing files..."):
        summary = info["summary"]
        try:
            metrics = analyze_file_advanced(file_path, info, args.repo_root, args.verbose)
            file_analyses.append(
                FileAnalysis(
                    path=file_path,
                    layer=extract_layer(file_path),
                    covered=summary["covered_lines"],
                    total=summary["num_statements"],
                    percent=summary["percent_covered"],
                    advanced_metrics=metrics,
                )
            )
        except Exception as e:
            if args.verbose:
                print(f"Warning: Could not analyze {file_path}: {e}")
            continue

    stats = calculate_coverage_statistics(data, file_analyses)

    # Print current coverage
    print_section_header("📊 CURRENT COVERAGE STATISTICS")
    print()
    print(f"  Overall Coverage: {stats['overall_percent']:.1f}%")
    print(f"  Lines: {stats['total_covered']}/{stats['total_statements']} covered")
    print(f"  Files: {stats['total_files']} total")
    print()

    print("  Layer Coverage:")
    for layer, layer_stats in sorted(
        stats["layer_coverage"].items(), key=lambda x: x[1]["percent"], reverse=True
    ):
        pct = layer_stats["percent"]
        status = "✓" if pct >= MIN_COVERAGE else "⚠" if pct >= WARNING_COVERAGE else "✗"
        print(
            f"    {status} {layer:20} {pct:5.1f}%  "
            f"({layer_stats['covered']}/{layer_stats['total']})"
        )

    # Quality dashboard
    print_quality_dashboard(file_analyses)

    # Extract opportunities with quality metrics
    opportunities = extract_opportunities(
        data, args.repo_root, include_quality=True, verbose=args.verbose
    )

    if not opportunities:
        print("\n✅ Perfect! No testing opportunities found - coverage is complete!")
        return None, stats

    print(f"\n  Found {len(opportunities)} testing opportunities")

    # Run optimization
    strategy, explanation = optimize_coverage_dp(
        opportunities,
        args.budget,
        prioritize_critical=not args.no_critical_first,
        objective=args.objective,
    )

    # Dependency analysis
    dependencies = {}
    if not args.no_deps:
        dependencies = infer_dependencies(strategy.opportunities)
        strategy.opportunities = topological_sort_with_priorities(
            strategy.opportunities, dependencies
        )

        def func_id(o):
            return f"{o.file_path}::{o.function_name}"

        for opp in strategy.opportunities:
            oid = func_id(opp)
            if oid in dependencies:
                opp.blocked_by = [d.split("::")[-1] for d in dependencies[oid]]

    # Calculate projected coverage
    total_lines_gained = sum(o.lines_gained for o in strategy.opportunities)
    new_covered = stats["total_covered"] + total_lines_gained
    new_coverage = (
        100 * new_covered / stats["total_statements"] if stats["total_statements"] > 0 else 0
    )
    strategy.expected_new_coverage = new_coverage

    analysis_time = time.time() - start_time

    if args.verbose:
        print(f"\n⏱️  Complete analysis in {analysis_time:.2f} seconds")

    # Print results
    print_optimization_summary(strategy, args.budget, stats, explanation)

    if not args.no_deps and dependencies:
        print_dependency_info(strategy, dependencies)

    print_strategic_plan(strategy, show_quality=True, min_priority=args.min_priority)
    print_efficiency_wins(strategy.opportunities)

    # Show recommendations if requested
    if args.show_recommendations:
        print_actionable_recommendations(file_analyses, opportunities)

    # Export if requested
    if not args.no_export:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = f"{args.export_prefix}_{timestamp}.json"
        csv_file = f"{args.export_prefix}_{timestamp}.csv"

        export_strategy_json(strategy, json_file)
        export_strategy_csv(strategy, csv_file)

    # Save to history
    avg_quality = (
        sum(
            o.advanced_metrics.composite_score for o in strategy.opportunities if o.advanced_metrics
        )
        / len(strategy.opportunities)
        if strategy.opportunities
        else 0
    )

    run = AnalysisRun(
        timestamp=strategy.timestamp,
        coverage_before=stats["overall_percent"],
        coverage_after_projected=new_coverage,
        total_lines=stats["total_statements"],
        covered_lines=stats["total_covered"],
        opportunities_found=len(opportunities),
        strategy_selected=f"{strategy.algorithm} - {args.objective}",
        budget_used=strategy.total_effort,
        critical_items=strategy.critical_files_covered,
        avg_quality_score=avg_quality,
        completed=False,
    )
    history.add_run(run)

    return strategy, stats


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================


def main(argv: list[str] | None = None):
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Unified Coverage Analyzer & Test Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full analysis (default)
  %(prog)s coverage.json

  # Quality assessment only
  %(prog)s coverage.json --mode analyze

  # Test planning only
  %(prog)s coverage.json --mode optimize --budget 150

  # Full analysis with recommendations
  %(prog)s coverage.json --mode full --show-recommendations

  # Optimize for quality instead of priority
  %(prog)s coverage.json --mode optimize --objective quality

  # Mark completed run
  %(prog)s --mark-complete

  # Custom settings
  %(prog)s coverage.json --budget 200 --no-deps --verbose
        """,
    )

    parser.add_argument(
        "coverage_file", nargs="?", default="coverage.json", help="Path to coverage.json file"
    )
    parser.add_argument(
        "--mode",
        choices=["analyze", "optimize", "full"],
        default="full",
        help="Execution mode: analyze=quality only, optimize=planning only, full=both (default: full)",
    )
    parser.add_argument(
        "--repo-root", default=".", help="Repository root to search for test files (default: .)"
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=EFFORT_BUDGET,
        help=f"Effort budget in test lines (default: {EFFORT_BUDGET})",
    )
    parser.add_argument(
        "--objective",
        choices=["priority", "coverage", "efficiency", "quality"],
        default="priority",
        help="Optimization objective (default: priority)",
    )
    parser.add_argument(
        "--no-critical-first", action="store_true", help="Don't prioritize critical issues"
    )
    parser.add_argument(
        "--export-prefix",
        default="coverage_strategy",
        help="Prefix for export files (default: coverage_strategy)",
    )
    parser.add_argument("--no-export", action="store_true", help="Skip exporting JSON/CSV files")
    parser.add_argument("--no-deps", action="store_true", help="Disable dependency analysis")
    parser.add_argument(
        "--show-recommendations",
        action="store_true",
        help="Show actionable recommendations for improvement",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output for debugging"
    )
    parser.add_argument(
        "--mark-complete", action="store_true", help="Mark the most recent run as completed"
    )
    # 10/10 Enhancement Arguments
    parser.add_argument(
        "--show-delta",
        action="store_true",
        help="Show coverage delta from last session (10/10 feature)",
    )
    parser.add_argument(
        "--export-todos",
        action="store_true",
        help="Export top priorities as GitHub-compatible TODO list (10/10 feature)",
    )
    parser.add_argument(
        "--check-threshold",
        type=float,
        metavar="PCT",
        help="Fail if coverage below threshold (CI/CD, 10/10 feature)",
    )
    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="Fail if coverage dropped vs last run (CI/CD, 10/10 feature)",
    )
    parser.add_argument(
        "--export-badge", action="store_true", help="Generate shields.io badge JSON (10/10 feature)"
    )
    parser.add_argument(
        "--show-low-coverage",
        type=float,
        metavar="PCT",
        default=None,
        help="Show files below coverage threshold (10/10 feature)",
    )
    parser.add_argument(
        "--max-coverage",
        type=float,
        metavar="PCT",
        default=None,
        help="Upper bound for coverage filtering (use with --show-low-coverage for range)",
    )
    parser.add_argument(
        "--sort-by",
        nargs="+",
        default=["priority"],
        metavar="FIELD[:ORDER]",
        help="Sort by one or more fields with optional direction. "
             "Fields: priority, coverage, layer, missing, missing_pct. "
             "Append :asc or :desc per field. Example: --sort-by missing:desc coverage:asc",
    )
    parser.add_argument(
        "--sort-order",
        choices=["asc", "desc"],
        default="desc",
        help="Default sort order when not specified per-field (default: desc)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of files to display (default: 20, use 0 for all)",
    )
    parser.add_argument(
        "--min-priority",
        type=int,
        metavar="SCORE",
        default=0,
        help="Filter priority plan to show only items with priority >= SCORE (e.g., --min-priority 85)",
    )
    parser.add_argument(
        "--show-lines",
        action="store_true",
        help="Display actual missing line numbers for each file in low-coverage output",
    )

    args = parser.parse_args(argv)

    # Handle mark-complete
    if args.mark_complete:
        history = CoverageHistory()
        if history.runs:
            history.runs[-1].completed = True
            history.save()
            print(f"\n✓ Marked run as completed: {history.runs[-1].timestamp}")
        else:
            print("\n⚠️  No runs to mark as completed")
        return

    # Load coverage data
    if args.verbose:
        print(f"📁 Coverage file: {args.coverage_file}")
        print(f"📂 Repo root: {args.repo_root}")
        print(f"🎮 Mode: {args.mode}")
        print(f"💰 Budget: {args.budget}L")
        print(f"🎯 Objective: {args.objective}")
        print()

    try:
        data = load_coverage(args.coverage_file)
        file_count = len(data.get("files", {}))
        if args.verbose:
            print(f"📊 Loaded coverage data: {file_count} files\n")
    except Exception:
        sys.exit(1)

    # STANDALONE MODE: Show low-coverage files only (skip full analysis)
    if args.show_low_coverage is not None:
        # Use 0 for "show all" - convert to None for the function
        display_count = args.top_n if args.top_n > 0 else None
        show_low_coverage_files(
            data,
            threshold=args.show_low_coverage,
            max_threshold=args.max_coverage,
            top_n=display_count,
            sort_by=args.sort_by,
            sort_order=args.sort_order,
            show_lines=args.show_lines,
        )
        return  # Exit early - don't run the full analysis

    # Run appropriate mode
    if args.mode == "analyze":
        file_analyses, stats = run_analyze_mode(data, args)
        opportunities = []
    elif args.mode == "optimize":
        strategy, stats = run_optimize_mode(data, args)
        opportunities = strategy.opportunities
    else:  # full
        strategy, stats = run_full_mode(data, args)
        opportunities = strategy.opportunities

    # 10/10 ENHANCEMENTS: Apply new features
    current_coverage = stats.get(
        "current_coverage", data.get("totals", {}).get("percent_covered", 0.0)
    )
    history = CoverageHistory()

    # Show session delta
    if args.show_delta or args.mode == "full":
        show_session_delta(history, current_coverage)

    # Export GitHub TODO list
    if args.export_todos and opportunities:
        export_github_issues(opportunities, "test-todos.md", top_n=20)

    # CI/CD threshold check
    if args.check_threshold is not None:
        fail_if_below_threshold(current_coverage, args.check_threshold, exit_code=True)

    # CI/CD regression check
    if args.check_regression:
        if not check_coverage_regression(history, current_coverage):
            print("\n⚠️  Consider this a warning - review regression before merging")

    # Export badge data
    if args.export_badge:
        badge_data = generate_coverage_badge_data(current_coverage)
        with open("coverage-badge.json", "w") as f:
            json.dump(badge_data, f, indent=2)
        print("\n✅ Badge data exported to coverage-badge.json")

    # Print execution guide
    print_execution_guide(args.mode)

    print("═" * 90)
    print(f"✓ {args.mode.capitalize()} complete.\n")


# ============================================================================
# 10/10 ENHANCEMENTS - Session Tracking & CI/CD Integration
# ============================================================================


def show_session_delta(history: CoverageHistory, current_coverage: float):
    """Show coverage delta from last session with visual feedback"""
    if not history.runs:
        print("\n📊 First Analysis Session")
        print(f"   Current Coverage: {current_coverage:.1f}%")
        print("   Target: 90.0%")
        print(f"   Remaining: {90.0 - current_coverage:.1f}pp")
        return

    last_run = history.runs[-1]
    delta = current_coverage - last_run.coverage_before

    print("\n" + "═" * 70)
    print("📈 SESSION IMPACT ANALYSIS")
    print("═" * 70)

    # Visual progress bar
    def progress_bar(percent, width=50):
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent:.1f}%"

    print(f"\n  Before:  {progress_bar(last_run.coverage_before)}")
    print(f"  Current: {progress_bar(current_coverage)}")

    # Delta with color
    arrow = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
    sign = "+" if delta > 0 else ""
    print(f"\n  {arrow} Delta: {sign}{delta:.2f}pp")

    if delta > 0:
        remaining = 90.0 - current_coverage
        sessions_needed = int(remaining / delta) + 1 if delta > 0 else "∞"
        print(f"  🎯 Est. sessions to 90%: ~{sessions_needed}")
        print(f"  ⚡ Velocity: {delta:.2f}pp/session")

    print("═" * 70)


def export_github_issues(
    opportunities: list[TestingOpportunity], output_file: str = "test-todos.md", top_n: int = 20
):
    """Export top opportunities as GitHub-compatible markdown issues"""
    selected = sorted(opportunities, key=lambda x: x.priority_score, reverse=True)[:top_n]

    with open(output_file, "w") as f:
        f.write("# 🎯 Test Coverage TODO List\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Top {len(selected)} Priority Items**\n\n")
        f.write("---\n\n")

        for i, opp in enumerate(selected, 1):
            f.write(f"## {i}. Test `{opp.function_name}` ({opp.priority_score}/100)\n\n")
            f.write(f"**File:** `{opp.file_path}`\n\n")
            f.write("**Details:**\n")
            f.write(f"- 📊 Priority: {opp.priority_score}/100 ({opp.risk_level.value})\n")
            f.write(f"- ⚡ Effort: ~{opp.effort_lines} test lines\n")
            f.write(f"- 📈 Lines Gained: {opp.lines_gained}\n")
            f.write(f"- 🎯 Current Coverage: {opp.current_coverage:.1f}%\n")
            f.write(f"- 🏗️ Layer: {opp.layer}\n")
            f.write(f"- 🔧 Complexity: {opp.complexity_score:.1f}\n\n")

            if opp.advanced_metrics:
                f.write("**Quality Metrics:**\n")
                f.write(f"- Grade: {opp.advanced_metrics.quality_grade}\n")
                f.write(f"- Mutation Score: {opp.advanced_metrics.estimated_mutation_score:.1f}%\n")
                f.write(f"- Assertion Density: {opp.advanced_metrics.assertion_density:.2f}\n")
                if opp.advanced_metrics.test_smell_count > 0:
                    f.write(f"- ⚠️ Test Smells: {opp.advanced_metrics.test_smell_count}\n")
                f.write("\n")

            f.write("**Action Items:**\n")
            f.write("- [ ] Create test file if missing\n")
            f.write(f"- [ ] Add tests for lines: {', '.join(map(str, opp.missing_lines[:10]))}")
            if len(opp.missing_lines) > 10:
                f.write(f" (+ {len(opp.missing_lines) - 10} more)")
            f.write("\n")
            f.write("- [ ] Verify edge cases\n")
            f.write("- [ ] Add assertions for error paths\n\n")
            f.write("---\n\n")

        # Summary
        total_effort = sum(o.effort_lines for o in selected)
        total_gain = sum(o.lines_gained for o in selected)
        f.write("## 📊 Summary\n\n")
        f.write(f"- **Total Items:** {len(selected)}\n")
        f.write(f"- **Estimated Effort:** ~{total_effort} test lines\n")
        f.write(f"- **Expected Coverage Gain:** ~{total_gain} source lines\n")
        f.write(
            f"- **Critical Items:** {sum(1 for o in selected if o.risk_level == RiskLevel.CRITICAL)}\n"
        )

    print(f"\n✅ Exported {len(selected)} TODO items to {output_file}")


def fail_if_below_threshold(current_coverage: float, target: float = 90.0, exit_code: bool = True):
    """CI/CD helper: fail if coverage below threshold"""
    if current_coverage < target:
        print("\n❌ COVERAGE CHECK FAILED")
        print(f"   Current: {current_coverage:.1f}%")
        print(f"   Target:  {target:.1f}%")
        print(f"   Gap:     {target - current_coverage:.1f}pp")
        if exit_code:
            sys.exit(1)
        return False
    else:
        print("\n✅ COVERAGE CHECK PASSED")
        print(f"   Current: {current_coverage:.1f}% >= {target:.1f}% target")
        return True


def check_coverage_regression(
    history: CoverageHistory, current_coverage: float, tolerance: float = 0.5
):
    """CI/CD helper: detect coverage regression"""
    if not history.runs:
        return True

    last_run = history.runs[-1]
    delta = current_coverage - last_run.coverage_after_projected

    if delta < -tolerance:
        print("\n⚠️  COVERAGE REGRESSION DETECTED")
        print(f"   Previous: {last_run.coverage_after_projected:.1f}%")
        print(f"   Current:  {current_coverage:.1f}%")
        print(f"   Drop:     {delta:.2f}pp")
        return False

    return True


def _format_line_ranges(lines: list[int], max_display: int = 100) -> str:
    """Format a list of line numbers into compact ranges.
    
    Examples:
        [1, 2, 3, 5, 6, 10] -> "1-3, 5-6, 10"
        [1, 3, 5, 7] -> "1, 3, 5, 7"
    """
    if not lines:
        return ""
    
    sorted_lines = sorted(set(lines))
    
    # If too many lines, truncate with ellipsis
    if len(sorted_lines) > max_display:
        sorted_lines = sorted_lines[:max_display]
        truncated = True
    else:
        truncated = False
    
    ranges = []
    start = sorted_lines[0]
    end = start
    
    for line in sorted_lines[1:]:
        if line == end + 1:
            end = line
        else:
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            start = end = line
    
    # Add the last range
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")
    
    result = ", ".join(ranges)
    if truncated:
        result += f" ... (+{len(lines) - max_display} more)"
    
    return result


def show_low_coverage_files(
    data: dict,
    threshold: float = 50.0,
    max_threshold: float | None = None,
    top_n: int = 20,
    sort_by: list[str] | str = "priority",
    sort_order: str = "desc",
    show_lines: bool = False,
):
    """Show files with coverage below threshold, with flexible sorting options.

    Args:
        data: Coverage data dictionary
        threshold: Coverage threshold percentage (files below this are shown)
        max_threshold: Optional upper bound for coverage (files above this are excluded)
        top_n: Maximum number of files to display (None for all)
        sort_by: Field(s) to sort by. Can be a single field or list of fields.
                 Each field can optionally include :asc or :desc suffix.
                 Options: 'priority', 'coverage', 'layer', 'missing', 'missing_pct'
        sort_order: Default order when not specified per-field ('asc' or 'desc')
        show_lines: If True, display the actual missing line numbers for each file
    """
    # Normalize sort_by to a list
    if isinstance(sort_by, str):
        sort_by = [sort_by]

    # Parse field:order syntax
    valid_fields = {"priority", "coverage", "layer", "missing", "missing_pct"}
    parsed_sorts = []  # List of (field, is_descending) tuples

    for field_spec in sort_by:
        if ":" in field_spec:
            field, order = field_spec.rsplit(":", 1)
            if order not in ("asc", "desc"):
                # Invalid order, treat as part of field name
                field = field_spec
                order = sort_order
        else:
            field = field_spec
            order = sort_order

        # Validate field
        if field not in valid_fields:
            print(f"⚠️  Unknown sort field '{field}', using 'priority'")
            field = "priority"

        parsed_sorts.append((field, order == "desc"))

    # Build display label
    sort_labels = []
    for field, is_desc in parsed_sorts:
        arrow = "↓" if is_desc else "↑"
        sort_labels.append(f"{field}{arrow}")
    sort_fields_display = ", ".join(sort_labels)

    # Build title based on filtering mode
    if max_threshold is not None:
        title = f"📊 COVERAGE RANGE FILES ({threshold:.0f}% - {max_threshold:.0f}%) — Sorted by: {sort_fields_display}"
    else:
        title = f"📉 LOW COVERAGE FILES (below {threshold:.0f}%) — Sorted by: {sort_fields_display}"

    print("\n" + "═" * 100)
    print(title)
    print("═" * 100)

    files_info = []

    for file_path, info in data.get("files", {}).items():
        summary = info.get("summary", {})
        percent = summary.get("percent_covered", 0.0)
        total_lines = summary.get("num_statements", 0)
        missing_lines = len(info.get("missing_lines", []))

        # Check if file matches the coverage criteria
        if max_threshold is not None:
            # Range mode: between threshold (lower) and max_threshold (upper)
            matches_criteria = total_lines > 0 and threshold <= percent < max_threshold
        else:
            # Single threshold mode: below threshold
            matches_criteria = total_lines > 0 and percent < threshold

        if matches_criteria:
            layer = extract_layer(file_path)

            # Calculate priority: lower coverage + critical layer = higher priority
            priority = 0
            if percent < 10:
                priority += 40
            elif percent < 30:
                priority += 30
            elif percent < 50:
                priority += 20
            else:
                priority += 10

            # Layer bonus
            layer_bonus = {"Domain": 30, "Application": 25, "Services": 20}.get(layer, 10)
            priority += layer_bonus

            # Size bonus (more missing lines = higher priority)
            if missing_lines > 50:
                priority += 20
            elif missing_lines > 20:
                priority += 10

            files_info.append(
                {
                    "path": file_path,
                    "coverage": percent,
                    "total": total_lines,
                    "missing": missing_lines,
                    "missing_pct": 100.0 - percent,  # What % is NOT covered
                    "missing_lines_list": info.get("missing_lines", []),  # Actual line numbers
                    "layer": layer,
                    "layer_order": {
                        "Domain": 1, "Application": 2, "Services": 3,
                        "Use Cases": 4, "Repositories": 5, "Infrastructure": 6,
                        "API": 7, "Schemas": 8, "Models": 9, "Other": 10,
                    }.get(layer, 10),
                    "priority": priority,
                }
            )

    # Define single field extractors
    field_extractors = {
        "priority": lambda x: x["priority"],
        "coverage": lambda x: x["coverage"],
        "layer": lambda x: x["layer_order"],
        "missing": lambda x: x["missing"],
        "missing_pct": lambda x: x["missing_pct"],
    }

    # Create composite sort key for multi-field sorting with per-field directions
    def make_composite_key(sorts: list[tuple[str, bool]]):
        """Create a sort key that handles multiple fields with individual sort directions.

        Args:
            sorts: List of (field_name, is_descending) tuples
        """
        def key_func(item):
            values = []
            for field, is_desc in sorts:
                extractor = field_extractors.get(field)
                if extractor:
                    value = extractor(item)
                    # Apply sort direction per field
                    if is_desc:
                        # Negate for descending order
                        if isinstance(value, (int, float)):
                            value = -value
                    values.append(value)
            return tuple(values)
        return key_func

    # Apply multi-field sorting with per-field directions
    composite_key = make_composite_key(parsed_sorts)
    files_info.sort(key=composite_key)

    if not files_info:
        if max_threshold is not None:
            print(f"\n✅ No files in coverage range {threshold:.0f}% - {max_threshold:.0f}%!")
        else:
            print(f"\n✅ No files below {threshold:.0f}% coverage!")
        print("═" * 100)
        return

    if max_threshold is not None:
        print(f"\nFound {len(files_info)} files in coverage range {threshold:.0f}% - {max_threshold:.0f}%")
    else:
        print(f"\nFound {len(files_info)} files below {threshold:.0f}%")
    print(f"\n{'#':<4} {'Prio':<6} {'Coverage':<10} {'Missing':<18} {'Layer':<15} File")
    print("─" * 100)

    # Determine files to show (None means all)
    display_files = files_info if top_n is None else files_info[:top_n]

    for i, file_info in enumerate(display_files, 1):
        # Color coding based on coverage
        if file_info["coverage"] < 20:
            status = "🔴"
        elif file_info["coverage"] < 40:
            status = "🟠"
        else:
            status = "🟡"

        # Format missing as "lines (percentage)"
        missing_display = f"{file_info['missing']:>4} ({file_info['missing_pct']:>5.1f}%)"

        print(
            f"{i:<4} {status} {file_info['priority']:<4} "
            f"{file_info['coverage']:>6.1f}%    "
            f"{missing_display:<16}  "
            f"{file_info['layer']:<15} {file_info['path']}"
        )
        
        # Show missing lines if requested
        if show_lines and file_info.get("missing_lines_list"):
            lines_str = _format_line_ranges(file_info["missing_lines_list"])
            # Wrap long lines for readability
            indent = "                                              "  # Align with File column
            if len(lines_str) > 80:
                # Split into multiple lines
                print(f"{indent}📍 Lines: {lines_str[:80]}")
                remaining = lines_str[80:]
                while remaining:
                    print(f"{indent}          {remaining[:80]}")
                    remaining = remaining[80:]
            else:
                print(f"{indent}📍 Lines: {lines_str}")

    if top_n is not None and len(files_info) > top_n:
        print(f"\n... and {len(files_info) - top_n} more files")

    # Calculate overall project stats from coverage data
    totals = data.get("totals", {})
    project_total_statements = totals.get("num_statements", 0)
    project_covered_lines = totals.get("covered_lines", 0)
    project_current_coverage = totals.get("percent_covered", 0.0)

    # If totals not in expected format, calculate from files
    if project_total_statements == 0:
        for file_path, info in data.get("files", {}).items():
            summary = info.get("summary", {})
            project_total_statements += summary.get("num_statements", 0)
            project_covered_lines += summary.get("covered_lines", 0)
        if project_total_statements > 0:
            project_current_coverage = (project_covered_lines / project_total_statements) * 100

    # Summary stats for low-coverage files
    total_missing = sum(f["missing"] for f in files_info)
    total_statements_low_cov = sum(f["total"] for f in files_info)
    avg_coverage = sum(f["coverage"] for f in files_info) / len(files_info)
    overall_missing_pct = (total_missing / total_statements_low_cov * 100) if total_statements_low_cov > 0 else 0

    # Calculate projected coverage if all these files hit 100%
    projected_covered = project_covered_lines + total_missing
    projected_coverage = (projected_covered / project_total_statements * 100) if project_total_statements > 0 else 0
    coverage_gain = projected_coverage - project_current_coverage

    print("\n" + "─" * 100)
    print("📊 SUMMARY")
    print("─" * 100)
    print(f"   📁 Total low-coverage files: {len(files_info)}")
    print(f"   📈 Avg coverage of these files: {avg_coverage:.1f}%")
    print(f"   🔴 Total missing lines: {total_missing:,} ({overall_missing_pct:.1f}% of statements in these files)")
    print(f"   📋 Total statements in low-coverage files: {total_statements_low_cov:,}")

    print("\n" + "─" * 100)
    print("🚀 COVERAGE PROJECTION")
    print("─" * 100)
    print(f"   📊 Current project coverage: {project_current_coverage:.1f}%")
    print(f"   🎯 If all {len(files_info)} files reach 100%: {projected_coverage:.1f}%")
    print(f"   📈 Potential gain: +{coverage_gain:.1f} percentage points")
    print(f"   📋 Lines to cover: {total_missing:,} / {project_total_statements:,} total")

    # Attack recommendations
    print("\n" + "─" * 100)
    print("🎯 RECOMMENDED ATTACK ORDER (Top 5)")
    print("─" * 100)

    # Re-sort by priority for recommendations
    attack_order = sorted(files_info, key=lambda x: x["priority"], reverse=True)[:5]
    for i, f in enumerate(attack_order, 1):
        impact = "HIGH" if f["missing"] > 30 else ("MEDIUM" if f["missing"] > 15 else "LOW")
        effort = "EASY" if f["missing"] < 20 else ("MODERATE" if f["missing"] < 50 else "HARD")
        print(
            f"   {i}. [{f['layer']}] {f['path']}"
            f"\n      → {f['missing']} lines missing ({f['missing_pct']:.1f}%) | "
            f"Impact: {impact} | Effort: {effort}"
        )

    print("\n" + "═" * 100)


def generate_coverage_badge_data(current_coverage: float) -> dict:
    """Generate shields.io badge data"""
    if current_coverage >= 90:
        color = "brightgreen"
    elif current_coverage >= 80:
        color = "green"
    elif current_coverage >= 70:
        color = "yellowgreen"
    elif current_coverage >= 60:
        color = "yellow"
    else:
        color = "red"

    return {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{current_coverage:.1f}%",
        "color": color,
    }


# ============================================================================
# ENHANCED MAIN FUNCTION
# ============================================================================


if __name__ == "__main__":
    main()
