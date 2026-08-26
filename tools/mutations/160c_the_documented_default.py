"""#160 (the documented default): the example tells an operator what the code actually does."""

TEST = "tests/test_the_documented_default_is_the_real_one.py"
EXAMPLE = "deploy/registry.yaml.example"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    ("the example documents a default the code does not have", EXAMPLE,
     "# language: en (default)", "# language: pt-BR (default)"),

    ("…and the reverse: the CODE drifts and the example stays put", VOICE,
     'DEFAULT_LANGUAGE = "en"', 'DEFAULT_LANGUAGE = "pt-BR"'),

    ("the example stops showing a project that NAMES its language", EXAMPLE,
     "    language: pt-BR   # this example project is Brazilian; yours says whatever your client "
     "reads\n", ""),
]
