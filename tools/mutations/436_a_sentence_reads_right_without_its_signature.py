"""A sentence the product role writes on its own reads right without its signature (#436)."""

TEST = "tests/test_a_sentence_reads_right_without_its_signature.py"
VOICE = "openfactory/product/voice.py"
GUARD = TEST

MUTATIONS = [
    ("the live preview's message opens in lowercase again", VOICE,
     '    "en": ("{sig}You can already try {card} before it goes into the product: {url}\\n\\n"\n',
     '    "en": ("{sig}you can already try {card} before it goes into the product: {url}\\n\\n"\n'),
    ("the guard forgets the Portuguese lowercase letters", GUARD,
     'AFTER_SIGNATURE = re.compile(r"\\{sig\\} ?[a-zà-ÿ]")\n',
     'AFTER_SIGNATURE = re.compile(r"\\{sig\\} ?[a-z]")\n'),
    ("the guard forgets the signature followed by a space", GUARD,
     'AFTER_SIGNATURE = re.compile(r"\\{sig\\} ?[a-zà-ÿ]")\n',
     'AFTER_SIGNATURE = re.compile(r"\\{sig\\}[a-zà-ÿ]")\n'),
]
