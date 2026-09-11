"""A double without intake answers every turn — the cuts that put the mute back.

ROW 1 IS THE 2026-09-06 SHAPE: the keyword goes to every module once there is an intake, and a
double that does not declare it mutes from turn two.
ROW 2 IS THE OVER-CORRECTION: the keyword goes to nobody, and the shipped module loses its intake.
ROW 3 IS `**kwargs` NOT COUNTING as declaring it.
"""

TEST = "tests/test_a_double_without_intake_answers_every_turn.py"

MUTATIONS = [
    ("the keyword goes to every module once there is an intake — a legacy double mutes on turn two",
     "openfactory/product/channel.py",
     '                           **({"intake": intake} if intake and _accepts_intake(module) '
     'else {}))\n',
     '                           **({"intake": intake} if intake else {}))\n'),

    ("the keyword goes to nobody — the shipped module loses its intake",
     "openfactory/product/channel.py",
     '                           **({"intake": intake} if intake and _accepts_intake(module) '
     'else {}))\n',
     '                           **({}))\n'),

    ("**kwargs does not count as declaring the intake",
     "openfactory/product/channel.py",
     '    return "intake" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD\n'
     '                                     for p in params.values())\n',
     '    return "intake" in params\n'),
]
