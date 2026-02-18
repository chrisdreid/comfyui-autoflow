# Contributing to comfyui-autoflow

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/chrisdreid/comfyui-autoflow.git
cd comfyui-autoflow
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

No external dependencies are required — the library is pure stdlib Python.

## Running Tests

**Unit tests** (no network/ComfyUI required):

```bash
python -m unittest discover -s examples/unittests -v
```

**Docs integration tests** (validate README/docs code snippets):

```bash
python docs/docs-test.py
```

## Code Style

- **Type hints** on all public functions
- **Docstrings** on every module and public class/function
- Keep network interactions **explicit and opt-in** (no surprise HTTP calls)
- Prefer **stdlib** over third-party packages

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes and add/update tests as needed
3. Run both test suites (see above)
4. Open a PR with a clear description of what changed and why

## Reporting Issues

Please include:
- Python version and OS
- ComfyUI version (if relevant)
- Minimal reproduction steps or code snippet
- Full traceback (if applicable)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
