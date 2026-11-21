"""scripts/check_doc_imports.py runs every documented sagaz import (#539)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_doc_imports.py"
spec = importlib.util.spec_from_file_location("check_doc_imports", SCRIPT)
check_doc_imports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_doc_imports)

DOC = """# Title

```python
from sagaz import Saga, action
from sagaz.nope import Thing
from sagaz import (
    SagaConfig,
    NotAName,
)
import sagaz.core.storage
```

```bash
from sagaz.ignored import NotPython
```

```python
from fastapi import FastAPI
from sagaz.integrations.fastapi import no_such_helper  # skipped only if fastapi is missing
```
"""


def test_failing_imports_are_reported_with_their_line(tmp_path):
    doc = tmp_path / "guide.md"
    doc.write_text(DOC)
    failures = check_doc_imports.check([str(doc)])
    assert f"{doc}:5: from sagaz.nope import Thing" in failures[0]
    assert "NotAName" in failures[1]
    assert failures[1].startswith(f"{doc}:6:")
    assert not any("ignored" in failure for failure in failures)  # bash blocks are not run


def test_multi_line_imports_are_joined():
    lines = ["from sagaz import (", "    Saga,", "    action,", ")", "x = 1"]
    assert check_doc_imports.imports_in(lines) == [(0, "from sagaz import ( Saga, action, )")]


def test_comments_are_dropped():
    assert check_doc_imports.imports_in(["from sagaz import Saga  # the class"]) == [
        (0, "from sagaz import Saga")
    ]
