"""A card's note names the platform in the project's language, and a person by their name (#546),
proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/546_a_card_note_names_the_platform_in_the_project_s_language.py

A Portuguese project's card read "_Fechado por the workflow._": the door wrote the transition's
`by=` into the note as it came. The claims, each a row:

  1. the platform is named by its words, as the agent with its preposition and as the subject
     (rows 1-2);
  2. every platform actor the code passes to the door has its entry (row 3);
  3. a person's name is written as it is (row 4).
"""

TEST = "tests/test_a_card_note_names_the_platform_in_the_project_s_language.py"

VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the agent is the code's own name, after a bare `por`", VOICE,
     "    named = _PLATFORM_ACTORS.get((who or \"\").strip())\n    if named:\n"
     "        return _pick(named, language)[1]\n",
     "    named = _PLATFORM_ACTORS.get((who or \"\").strip())\n    if False:\n"
     "        return _pick(named, language)[1]\n"),
    ("the subject is the code's own name", VOICE,
     "    return _pick(named, language)[0] if named else who\n",
     "    return who\n"),
    ("an actor the code passes has no words of its own", VOICE,
     "    \"the tech-lead's round\": {\"pt-BR\": (\"a ronda do tech-lead\", \"pela ronda do tech-lead\"),\n"
     "                              \"en\": (\"the tech-lead's round\", \"by the tech-lead's round\")},\n",
     ""),
    ("a person's name is capitalised like the platform's words", VOICE,
     "    if (who or \"\").strip() in _PLATFORM_ACTORS:   # it opens the sentence; a person's name is as is\n",
     "    if True:\n"),
]
