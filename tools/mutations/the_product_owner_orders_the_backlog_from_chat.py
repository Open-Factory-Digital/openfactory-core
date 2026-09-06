"""The product owner orders the backlog from chat — the cuts that lose the order or start work.

ROW 1 IS THE ORDER SORTED WHERE IT IS READ. ROW 2 IS THE MARKER READ AND NOT DECLARED. ROW 3 IS
THE CHANNEL STAGING A QUEUE, so the yes STARTS the cards instead of ordering them. ROW 4 IS THE
EXECUTOR REACHING THE WRONG VERB. ROW 5 IS THE REPLY SORTED. ROW 6 IS THE EXECUTOR UNREGISTERED.
ROW 7 IS THE ASK NOT SAYING THAT NOTHING STARTS.
"""

TEST = "tests/test_the_product_owner_orders_the_backlog_from_chat.py"

MUTATIONS = [
    ("the order is sorted where it is read",
     "openfactory/product/role.py",
     '        order = list(dict.fromkeys(re.findall(r"\\d+", ordered.group("numbers")))) if ordered else []',
     '        order = sorted(set(re.findall(r"\\d+", ordered.group("numbers")))) if ordered else []'),

    ("the marker is read and never declared",
     "openfactory/product/role.py",
     "                             is_reorder=bool(order), order=order,",
     "                             is_reorder=False, order=order,"),

    ("the channel stages a QUEUE, so the yes starts the cards instead of ordering them",
     "openfactory/product/channel.py",
     '        replaced = remember(thread, {"kind": "reorder", "numbers": order, "channel": channel},',
     '        replaced = remember(thread, {"kind": "queue", "numbers": order, "channel": channel},'),

    ("the executor reaches the wrong verb",
     "openfactory/product/confirm.py",
     "    results = module.reorder(numbers, actor=user)",
     "    results = module.promote(numbers, actor=user)"),

    ("the reply is sorted",
     "openfactory/product/confirm.py",
     '    placed = [str(r.ref).lstrip("#") for r in results if r.ok and r.ref]',
     '    placed = sorted(str(r.ref).lstrip("#") for r in results if r.ok and r.ref)'),

    ("the executor is not registered",
     "openfactory/product/confirm.py",
     '    "reorder": _confirm_reorder,\n',
     ''),

    ("the ask does not say that nothing starts",
     "openfactory/product/voice.py",
     '''    "pt-BR": "Coloco o backlog nesta ordem, de cima para baixo: {order}. Isso só grava a ordem — "
             "nada começa agora; a próxima leva segue ela. Confirma?",''',
     '''    "pt-BR": "Coloco o backlog nesta ordem, de cima para baixo: {order}. Confirma?",'''),
]
