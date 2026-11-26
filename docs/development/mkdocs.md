# MkDocs Documentation Setup

This project uses **MkDocs with Material theme** for ReadTheDocs documentation.

## 🔒 Privacy & Exclusions

The `archive/` folder and internal documentation are **explicitly excluded** from the public docs through:

1. **mkdocs.yml**: `exclude_docs` section
2. **mkdocs.yml**: `nav` section only lists public pages
3. **.readthedocs.yml**: Post-build validation

## 📦 Local Development

### Install dependencies

```bash
# Using pip
pip install -r docs/requirements.txt

# Or using the project venv
source .venv/bin/activate
pip install mkdocs mkdocs-material pymdown-extensions mkdocs-autorefs
```

### Build documentation

```bash
# Build static site
mkdocs build

# Serve locally (with hot reload)
mkdocs serve
# Visit: http://127.0.0.1:8000
```

### Validate build

```bash
# Build with strict mode (fails on warnings)
mkdocs build --strict

# Check no archive content leaked
grep -r "archive" site/ | grep -v "GLACIER_DEEP_ARCHIVE"
```

## 🚀 ReadTheDocs Setup

1. **Connect Repository**
   - Go to https://readthedocs.org/dashboard/
   - Click "Import a Project"
   - Select `brunolnetto/sagaz`

2. **Configuration**
   - ReadTheDocs will automatically detect `.readthedocs.yml`
   - Build will use `mkdocs.yml` configuration
   - Python 3.11 will be used

3. **Build & Deploy**
   - Push changes to `main` branch
   - ReadTheDocs will auto-build and deploy
   - Documentation will be available at: https://sagaz.readthedocs.io

## ✍️ A tour page, or an example

The pages under `docs/tour/` and `docs/examples/` show code that runs. The code is a
file, included in the page with its recorded output, and `tests/unit/docs/` runs it:

1. Write the script in `docs/tour/code/<name>.py` (or `docs/examples/code/`). It must
   run with `python <file>` alone, need no database or broker, and print the same thing
   every time.
2. Record its output: `python docs/tour/code/<name>.py > docs/tour/code/<name>.out`.
3. Include both in the page:

    ````markdown
    ```python title="<name>.py"
    ;--8<-- "docs/tour/code/<name>.py"
    ```

    ```text
    ;--8<-- "docs/tour/code/<name>.out"
    ```
    ````

4. Add the page to `nav:` in `mkdocs.yml`, and run `uv run pytest tests/unit/docs`.

Keep a tour script to about twenty lines and one idea. A scenario that combines several
features belongs in `docs/examples/`. `docs/examples/shipped.md` lists the examples of
`sagaz/examples/`; the test fails when one is added without a row there.

## 📝 Adding New Documentation

1. Create markdown file in appropriate `docs/` subdirectory
2. Add entry to `mkdocs.yml` under `nav:` section
3. Build locally to test: `mkdocs serve`
4. Commit and push

### Example

```yaml
# In mkdocs.yml
nav:
  - Guides:
    - My New Guide: guides/my-new-guide.md
```

## 🔄 Migration to Sphinx (Future)

When ready to migrate to Sphinx:

1. Install Sphinx: `pip install sphinx sphinx-rtd-theme`
2. Run: `sphinx-quickstart docs`
3. Convert navigation from `mkdocs.yml` to `conf.py`
4. Update `.readthedocs.yml` to use Sphinx instead of MkDocs
5. Convert markdown extensions to Sphinx equivalents

## 📚 Documentation Structure

```
docs/
├── README.md              # Documentation home
├── quickstart.md          # Getting started
├── ROADMAP.md            # Project roadmap
├── guides/               # How-to guides
├── architecture/         # System design
├── patterns/             # Implementation patterns
├── monitoring/           # Observability
├── reference/            # API reference
├── development/          # Developer guides
├── integrations/         # Framework integrations
└── archive/              # ⚠️ EXCLUDED from public docs
```

## ✅ What's Excluded

- `docs/archive/` - Historical documentation
- `docs/STRUCTURE.md` - Internal doc structure guide
- `docs/REPLAY_IMPLEMENTATION_COMPLETE.md` - Internal status doc

These exclusions are configured in `mkdocs.yml` and not accessible in the built site.
