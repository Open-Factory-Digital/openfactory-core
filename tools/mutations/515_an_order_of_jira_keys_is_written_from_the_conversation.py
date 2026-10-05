"""On Jira, a backlog order stated in the conversation is staged, confirmed and written (#515).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/515_an_order_of_jira_keys_is_written_from_the_conversation.py

Row 1 is the defect as it shipped: the order marker reads digits only, so `[[ORDEM: DAR-11,
DAR-9]]` matches nothing and nothing is staged. Row 2 reads the marker and keeps only the digits
in it, so `DAR-11` is staged as `11`, a card no Jira site has. Rows 3-5 break `contracts.refs`:
the order is sorted, a card said twice is staged twice, and a ref keeps the `#` a person typed.
Row 6 loses the repository a qualified ref carries. Row 7 widens the marker past a list of refs,
so prose inside the brackets is read as an order.
"""

TEST = "tests/test_an_order_of_jira_keys_is_written_from_the_conversation.py"

ROLE = "openfactory/product/role.py"
REFS = "openfactory/contracts/refs.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the order marker reads digits only, so a Jira key matches nothing", ROLE,
     '_ORDER_RE = re.compile(rf"\\[\\[ORDEM:\\s*(?P<numbers>{REF_AS_WRITTEN}"\n'
     '                       rf"(?:(?:\\s*[,;]\\s*|\\s+){REF_AS_WRITTEN}){{0,49}})\\s*\\]\\]")',
     '_ORDER_RE = re.compile(r"\\[\\[ORDEM:\\s*(?P<numbers>[#\\d][#\\d,;\\s]{0,200})\\]\\]")'),

    ("the marker is read and only its digits are kept, so DAR-11 is staged as 11", ROLE,
     '        order = refs_written(ordered.group("numbers")) if ordered else []',
     '        order = (list(dict.fromkeys(re.findall(r"\\d+", ordered.group("numbers"))))\n'
     '                 if ordered else [])'),

    ("the order is sorted where the refs are read", REFS,
     "    return list(dict.fromkeys(ref for ref in found if ref))",
     "    return sorted(dict.fromkeys(ref for ref in found if ref), key=ref_sort_key)"),

    ("a card said twice is staged twice", REFS,
     "    return list(dict.fromkeys(ref for ref in found if ref))",
     "    return [ref for ref in found if ref]"),

    ("a ref keeps the # a person typed, so #12 and 12 are two cards", REFS,
     '    found = (canonical_ref(m) for m in re.findall(REF_AS_WRITTEN, str(text or "")))',
     '    found = (m for m in re.findall(REF_AS_WRITTEN, str(text or "")))'),

    ("a qualified ref loses its repository: acme/web#1 is not read at all", REFS,
     'REF_AS_WRITTEN = (r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\\d{1,12}"',
     'REF_AS_WRITTEN = (r"(?:(?!)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\\d{1,12}"'),

    ("prose inside the brackets is read as an order", ROLE,
     '                       rf"(?:(?:\\s*[,;]\\s*|\\s+){REF_AS_WRITTEN}){{0,49}})\\s*\\]\\]")',
     '                       rf"(?:(?:\\s*[,;]\\s*|\\s+){REF_AS_WRITTEN}){{0,49}})[^\\]\\n]*\\]\\]")'),
]
