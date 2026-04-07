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
