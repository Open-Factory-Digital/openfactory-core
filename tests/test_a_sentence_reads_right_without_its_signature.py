"""A sentence the product role writes on its own reads right without the signature in front of it.

`_sig(agent_name)` is `"<Name>: "` in a tracker comment and `""` in a conversation, where the
bubble already names the speaker. The catalogue wrote its sentences to follow the signature — in
lowercase — so every one opened mid-sentence in a conversation: "you can already try #1000007…"
(#436). A capital reads right in both places, so the catalogue carries one."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent / "openfactory"
#: `{sig}`, an optional space, and a lowercase letter — Portuguese ones included
AFTER_SIGNATURE = re.compile(r"\{sig\} ?[a-zà-ÿ]")


def _signed_lowercase() -> list[str]:
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and AFTER_SIGNATURE.search(node.value):
                found.append(f"{path.relative_to(ROOT.parent)}:{node.lineno}: "
                             f"{node.value[:60]!r}")
    return found


def test_no_catalogued_sentence_starts_in_lowercase_after_its_signature():
    found = _signed_lowercase()
    assert not found, (
        "a sentence that opens mid-sentence whenever its signature is empty — in every "
        "conversation — start it with a capital:\n  " + "\n  ".join(found))


def test_the_rule_sees_a_lowercase_sentence_and_passes_a_capital():
    """The pattern itself, so the guard cannot pass by matching nothing."""
    assert AFTER_SIGNATURE.search("{sig}you can already try")
    assert AFTER_SIGNATURE.search("{sig} ótimo — considero encerrado")
    assert not AFTER_SIGNATURE.search("{sig}You can already try")
    assert not AFTER_SIGNATURE.search("{sig}{card} did not pass")


def test_the_live_preview_message_reads_right_in_a_conversation():
    from openfactory.product import voice

    for language in ("en", "pt-BR"):
        said = voice.preview_up(ref="7", title="Home", url="http://x", language=language)
        assert said[:1].isupper(), f"{language}: {said[:40]!r} opens mid-sentence"
