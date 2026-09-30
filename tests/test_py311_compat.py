"""Guards that keep the codebase importable on Python 3.11 (pyproject: requires-python >= 3.11)."""

import importlib
import inspect
import io
import pathlib
import pkgutil
import re
import sys
import tokenize

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIRS = [ROOT / "src", ROOT / "evaluation"]


def _quote_of(token: str):
    m = re.match(r"[A-Za-z]*('''|\"\"\"|'|\")", token)
    return m.group(1) if m else None


def _nested_same_quote_fstrings(source: str):
    """Positions of strings nested in an f-string that reuse an enclosing quote (PEP 701, 3.12+ only)."""
    if not hasattr(tokenize, "FSTRING_START"):
        return []  # Pre-3.12 tokenizer: such code would already fail to import.
    found, stack = [], []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.FSTRING_START:
            quote = _quote_of(tok.string)
            if quote in stack:
                found.append(tok.start)
            stack.append(quote)
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif tok.type == tokenize.STRING and stack and _quote_of(tok.string) in stack:
            found.append(tok.start)
    return found


@pytest.mark.skipif(not hasattr(tokenize, "FSTRING_START"), reason="needs the 3.12+ tokenizer")
def test_detector_flags_pep701_fstrings():
    assert _nested_same_quote_fstrings('t = {}\nx = f"{t["a"]}"\n')
    assert not _nested_same_quote_fstrings("t = {}\nx = f\"{t['a']}\"\n")


def test_no_pep701_only_fstrings():
    offenders = []
    for base in SOURCE_DIRS:
        for path in base.rglob("*.py"):
            for line, _ in _nested_same_quote_fstrings(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert offenders == [], offenders


def _agent_runtime_modules():
    import src.agent_runtime as pkg
    return [m.name for m in pkgutil.walk_packages(pkg.__path__, "src.agent_runtime.")]


@pytest.mark.parametrize("module_name", _agent_runtime_modules())
def test_annotations_resolve_eagerly(module_name):
    """Python < 3.14 evaluates annotations at definition time; undefined names raise NameError."""
    module = importlib.import_module(module_name)
    if sys.version_info < (3, 14):
        return  # The import above already evaluated every annotation eagerly.
    import annotationlib

    targets = [module]
    for _, obj in inspect.getmembers(module):
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if inspect.isfunction(obj):
            targets.append(obj)
        elif inspect.isclass(obj):
            targets.append(obj)
            targets.extend(f for f in vars(obj).values() if inspect.isfunction(f))
    for obj in targets:
        annotationlib.get_annotations(obj, format=annotationlib.Format.VALUE)
