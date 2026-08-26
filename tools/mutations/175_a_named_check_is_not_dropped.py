"""#175: a CI command in none of our roles is proposed under the client's own name."""

TEST = "tests/test_a_named_check_is_not_dropped.py"
INFER = "openfactory/onboarding/infer.py"
READS = "tests/test_the_platform_reads_a_repository_and_proposes.py"

MUTATIONS = [
    ("an unclassified command is dropped again", INFER,
     '            if not role and slug_for(named):', "            if False:"),

    ("the value goes back to the shredded fragment", INFER,
     "                role, command = NAMED_CHECK, script.strip()",
     "                role = NAMED_CHECK"),

    # THE CUT THAT REACHES IT IS AT THE READER, not at the assignment. `named` is non-empty
    # whenever the role is NAMED_CHECK — the gate `if not role and slug_for(named)` guarantees it
    # — so `(named or job)` there is equivalent code and a mutation of it proves nothing. Where a
    # job name can actually be substituted for a step name is the place the step is read.
    ("the key is invented from the job instead of taken from the client", INFER,
     '                    named=str(step.get("name") or ""),',
     '                    named=str(step.get("name") or job_name),'),

    ("deploy plumbing is proposed as a validation again", INFER,
     "             if c.role == NAMED_CHECK and slug_for(c.named)\n"
     "             and c.evidence.path in with_roles]",
     "             if c.role == NAMED_CHECK and slug_for(c.named)]"),

    ("the proposal stops saying WHY it is being asked", INFER,
     '                    f"your pipeline runs this as \\"{cmd.named}\\" and it fills none of the '
     'roles "', '                    f"" + f"'),

    ("Azure's spelling of the step name is dropped", INFER,
     '                found.append((name, obj[key], str(obj.get("displayName") or "")))',
     '                found.append((name, obj[key], ""))'),

    ("…and CircleCI's", INFER,
     '                named=str(run.get("name") or "") if isinstance(run, dict) else "",',
     '                named="",'),

    ("the slug stops being deterministic about punctuation", INFER,
     '    words = re.findall(r"[a-z0-9]+", (name or "").lower())\n    return "-".join(words)[:60]',
     '    return (name or "").lower()'),

    ("classify starts guessing a role for what it does not know", INFER,
     '    for pattern, role in _COMPILED_ROLES:\n        if pattern.match(command):\n'
     '            return role\n    return ""',
     '    for pattern, role in _COMPILED_ROLES:\n        if pattern.match(command):\n'
     '            return role\n    return "test"'),
]
