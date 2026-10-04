"""A backlog order confirmed in the conversation reaches the board through the watched writes
(#511).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/511_a_reorder_reaches_the_watched_board.py

Row 1 is the defect as it shipped: the watched wrapper is one class for every adapter, its
capabilities reachable only through `__getattr__`, which `isinstance` against a `runtime_checkable`
protocol never asks — so every confirmed order is refused on the boards that rank. Rows 2-3 keep
the capability visible and lose the watch: the rank is not a watched write, or the name put on the
class reads the adapter straight past the wrapper. Rows 4-5 make the wrapper answer differently
from its adapter: a member the row set to `None` (its own "I do not do that") becomes a forward
that claims it, and a member the row keeps on its instance is not seen. Row 6 is the opposite
mistake to the defect: the wrapper claims a rank its board does not have, so the local board's
one sentence becomes an `AttributeError` caught one level down.
"""

TEST = "tests/test_a_reorder_reaches_the_watched_board.py"

MOD = "openfactory/product/module.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the watched board is one class for every adapter, so it is never Rankable "
     "and every confirmed order is refused", MOD,
     "        return super().__new__(_watched_kind(type(inner), _static_shape(inner)))",
     "        return super().__new__(cls)"),

    ("the rank is not a watched write: a refused or raising placement reaches nobody", MOD,
     '                         "add_item", "set_column", "place_after"})',
     '                         "add_item", "set_column"})'),

    ("the name on the class reads the adapter around the wrapper, so the order is written and "
     "never watched", MOD,
     "        return self if watched is None else watched.__getattr__(self.name)",
     "        return self if watched is None else getattr(watched._inner, self.name)"),

    ("a member the row set to None is forwarded as if it were there, so a row that opted out of "
     "a capability claims it once watched", MOD,
     "                {name: None if absent else _Forwarded(name) for name, absent in shape})",
     "                {name: _Forwarded(name) for name, absent in shape})"),

    ("a member the row keeps on its instance is not seen, so that capability is lost once "
     "watched", MOD,
     '        names |= set(object.__getattribute__(inner, "__dict__"))',
     "        names |= set()"),

    ("the wrapper claims a rank its board does not have, so the local board's sentence becomes "
     "a failure caught one level down", MOD,
     "                {name: None if absent else _Forwarded(name) for name, absent in shape})",
     "                {**{name: None if absent else _Forwarded(name) for name, absent in shape},\n"
     '                 "place_after": _Forwarded("place_after")})'),
]
