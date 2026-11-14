"""Discovery of the bundled Sagaz examples (directories, domains, descriptions)."""

import os
from pathlib import Path


def get_examples_dir() -> Path:
    """
    Get the directory containing examples.

    Priority:
    1. Installed package (sagaz.examples) — works in both editable and
       regular installs.
    2. ``sagaz/examples/`` relative to the repository root detected from
       the current working directory — fallback for unusual setups.
    """
    import importlib.resources as pkg_resources

    # Prefer the installed package so discovery always finds all examples
    # regardless of where the user invokes the CLI from.
    try:
        pkg_path = Path(str(pkg_resources.files("sagaz.examples")))
        if pkg_path.exists() and any(
            p.is_dir() and not p.name.startswith("_") for p in pkg_path.iterdir()
        ):
            return pkg_path
    except (ModuleNotFoundError, TypeError):
        pass

    # Last resort: sagaz/examples/ relative to CWD (covers editable installs
    # where importlib.resources may resolve to a namespace package path).
    for candidate in (
        Path.cwd() / "sagaz" / "examples",
        Path.cwd() / "examples",
    ):
        if candidate.exists() and candidate.is_dir():
            return candidate

    return Path.cwd() / "sagaz" / "examples"  # non-existent; caller handles it


# Maps display domain names → folder name under sagaz/examples/.
DOMAIN_FOLDERS = {
    "Business": "business",
    "Technology": "technology",
    "Healthcare": "healthcare",
    "Infrastructure": "infrastructure",
    "Public Services": "public_services",
    "Digital Media": "digital_media",
    "Platform": "platform",
}

# Maps display domain names → subdomain folder names within that domain folder.
DOMAIN_MAPPING = {
    "Business": [
        "commerce",
        "finance",
    ],
    "Technology": [
        "ai",
        "data",
        "telecom",
        "iot",
    ],
    "Healthcare": [
        "healthcare",
    ],
    "Infrastructure": [
        "operations",
    ],
    "Public Services": [
        "government",
        "education",
    ],
    "Digital Media": [
        "media",
        "gaming",
    ],
    "Platform": [
        "integrations",
        "monitoring",
        "visualization",
    ],
}

# Reverse map: subdomain folder → domain folder name (for fast lookup).
_SUBDOMAIN_TO_DOMAIN_FOLDER: dict[str, str] = {
    subdomain: DOMAIN_FOLDERS[display]
    for display, subdomains in DOMAIN_MAPPING.items()
    for subdomain in subdomains
}


def _check_subdomain_for_main_file(subdomain_dir: Path) -> bool:
    """Check if a subdomain directory contains main.py or demo.py files recursively."""
    for _root, _, files in os.walk(subdomain_dir):
        if "main.py" in files or "demo.py" in files:
            return True
    return False


def get_categories() -> list[str]:
    """Get list of available subdomain categories (second-level directories)."""
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return []

    categories = []
    for domain_dir in examples_dir.iterdir():
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        for item in domain_dir.iterdir():
            if (
                item.is_dir()
                and not item.name.startswith("_")
                and _check_subdomain_for_main_file(item)
            ):
                categories.append(item.name)

    return sorted(set(categories))


def get_domains() -> dict[str, list[str]]:
    """Get consolidated domain groups with their categories."""
    available_cats = set(get_categories())
    domains = {}

    for domain, categories in DOMAIN_MAPPING.items():
        # Only include domains that have at least one available category
        present_cats = [cat for cat in categories if cat in available_cats]
        if present_cats:
            domains[domain] = present_cats

    return domains


def _find_example_files(search_dir: Path, examples_dir: Path) -> dict[str, Path]:
    """Find example files in directory."""
    found = {}
    for root, _, files in os.walk(search_dir):
        if "main.py" in files or "demo.py" in files:
            path = Path(root)
            try:
                rel_path = path.relative_to(examples_dir)
                name = str(rel_path).replace(os.sep, "/")
                if "demo.py" in files and "integrations" in name:
                    found[name] = path / "demo.py"
                elif "main.py" in files:
                    found[name] = path / "main.py"
            except ValueError:
                continue
    return found


def discover_examples(category: str | None = None) -> dict[str, Path]:
    """
    Scan examples directory for valid examples.

    Args:
        category: Optional subdomain filter (e.g., 'commerce', 'ai')

    Returns: Dict[example_name, path_to_main_py]
    """
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return {}

    if category:
        domain_folder = _SUBDOMAIN_TO_DOMAIN_FOLDER.get(category)
        if not domain_folder:
            return {}
        search_dir = examples_dir / domain_folder / category
        if not search_dir.exists():
            return {}
    else:
        search_dir = examples_dir

    return _find_example_files(search_dir, examples_dir)


def _collect_examples_by_subdomain(examples_dir: Path) -> dict[str, list[tuple[str, Path]]]:
    """Walk examples directory and collect examples grouped by subdomain."""
    all_examples: dict[str, list[tuple[str, Path]]] = {}

    for root, _, files in os.walk(examples_dir):
        if "main.py" not in files and "demo.py" not in files:
            continue

        path = Path(root)
        try:
            rel_path = path.relative_to(examples_dir)
            parts = rel_path.parts
            if len(parts) < 3:  # Need domain/subdomain/example
                continue

            category = parts[1]  # subdomain folder
            if category not in all_examples:
                all_examples[category] = []

            name = str(rel_path).replace(os.sep, "/")
            if "demo.py" in files and "integrations" in name:
                all_examples[category].append((name, path / "demo.py"))
            elif "main.py" in files:
                all_examples[category].append((name, path / "main.py"))
        except ValueError:
            continue

    return all_examples


def discover_examples_by_domain() -> dict[str, dict[str, Path]]:
    """
    Discover all examples grouped by domain.

    Returns: {domain_name: {example_name: path_to_main_py}}
    """
    examples_dir = get_examples_dir()
    if not examples_dir.exists():
        return {}

    all_examples = _collect_examples_by_subdomain(examples_dir)

    # Group by domain
    by_domain: dict[str, dict[str, Path]] = {}
    for domain, categories in DOMAIN_MAPPING.items():
        domain_examples: dict[str, Path] = {}
        for category in categories:
            if category in all_examples:
                for name, path in all_examples[category]:
                    domain_examples[name] = path

        if domain_examples:
            by_domain[domain] = domain_examples

    return by_domain


def get_example_description(path: Path) -> str:
    """Extract description from example's main.py docstring."""
    try:
        with path.open() as f:
            for line in f:
                stripped = line.strip()
                # Skip shebang and empty lines
                if stripped.startswith("#!") or not stripped:
                    continue
                # Found docstring
                if stripped.startswith(('"""', "'''")):
                    desc = stripped.strip("\"'- ").strip()
                    if not desc:
                        # Multi-line docstring, read next line
                        desc = f.readline().strip()
                    return desc if desc else "No description"
                # No docstring found
                break
    except Exception:
        pass
    return "No description"
