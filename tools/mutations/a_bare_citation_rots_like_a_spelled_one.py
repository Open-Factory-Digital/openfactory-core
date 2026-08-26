"""The document-pointer scan sees a citation written without its extension (`docs/core/04`) —
the blind spot the pre-launch audit measured on 2026-08-26, one of whose instances is a runtime
error string an operator reads on a real failure.

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_a_remedy_names_a_document_that_exists.py"

MUTATIONS = [
    ("the scan requires an extension again (the blind spot as it was)",
     "tests/test_a_remedy_names_a_document_that_exists.py",
     'DOC_PATH = re.compile(r"docs/[\\w./-]*[\\w-]")',
     'DOC_PATH = re.compile(r"docs/[\\w./-]+\\.md")'),
    ("a bare citation resolves even when nothing in the directory begins with it",
     "tests/test_a_remedy_names_a_document_that_exists.py",
     '    return bool(stem) and directory.is_dir() and any(directory.glob(f"{stem}*"))',
     "    return True"),
    ("a spelled-out path stops having to be a file",
     "tests/test_a_remedy_names_a_document_that_exists.py",
     "    target = ROOT / doc\n    if target.is_file() or target.is_dir():",
     "    target = ROOT / doc\n    if True or target.is_file() or target.is_dir():"),
    ("the judgement stops asking whether the pointer resolves",
     "tests/test_a_remedy_names_a_document_that_exists.py",
     "    out = {rel: [(line, doc) for line, doc in hits if not resolves(doc)]",
     "    out = {rel: [(line, doc) for line, doc in hits if False]"),
    ("the judgement reports every pointer as dead",
     "tests/test_a_remedy_names_a_document_that_exists.py",
     "    return {rel: gone for rel, gone in out.items() if gone}",
     "    return dict(found)"),
]
