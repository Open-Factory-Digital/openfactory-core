"""Concepts: the semantic half of the bundle, authored under a budget the client declares.

WHAT THIS ADDS, AND WHY THE MODULE MAP COULD NOT. `knowledge/` says where things live — path,
purpose, dependencies, public surface. That is the right artifact for an agent that needs to jump
to a file, and it structurally cannot hold the sentence a product owner or a tech lead actually
needs: *what rule does this enforce, and where is that written*. A concept is that sentence, with
the `file:line` that makes it checkable and the fingerprint that makes it expire.

THE BUDGET IS THE WHOLE DESIGN, AND IT AMENDS A RULE THIS PACKAGE ALREADY STATED — deliberately,
in the open, because the rule is a good one. `propose_context` says:

    EXACTLY ONE AGENT PASS. Not a loop, not a per-module fan-out. An onboarding step whose cost
    depends on the size of the client's monolith is one nobody can quote a price for.

What that protects is a QUOTABLE COST, and that protection stands here unchanged: this fan-out is
bounded by a number the project declares (`okf_concept_budget`), never by how many modules the
repository has. Ten modules and ten thousand cost the same declared N. What the original sentence
forbids — a cost that scales with the client's monolith — remains forbidden, and the code enforces
it rather than promising it: the ranking picks N, and N comes from the manifest.

The half that could not be amended away is coverage: N concepts on a 900-module monolith describe
N modules. So the manifest says so, per kind, in `CoverageRow.reason` — a bundle that admits it
described twelve of nine hundred is honest; one that omits the denominator is not.

WHERE THE BUDGET IS SPENT, and none of these signals is new — every one is already measured by
the survey and, until now, read by nothing:

  churn         `file_changes`      where the next change is most likely to land
  blast radius  `depended_on_by`    computed since the survey existed; `score` below is
                                    its FIRST consumer — say it in the row, because a row gets
                                    quoted without the line above it (measured 2026-09-04: it was)
  uncertainty   `purpose_is_folder_name`  the deterministic pass found no purpose at all — the
                                    exact set of modules the platform currently knows nothing about

A module nobody has touched in three years, that nothing depends on, and whose purpose the
deterministic pass already read out of its README, is the last place to spend a model call.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from openfactory.knowledge.contracts import BusinessRule, Concept, ConceptSource, Gap
from openfactory.onboarding.context import RepoSurvey, SurveyedModule, _Anchorer

log = logging.getLogger("openfactory.onboarding.concepts")

AskFn = Callable[[str], str]

#: How many modules a pass will author a concept for when the project declares no number. SMALL ON
#: PURPOSE: the first run on a legacy repository is the one nobody has budgeted for, and a default
#: that spends twenty model calls on a stranger's monolith is a default that gets the feature
#: switched off. A project that wants more says so — that is what the manifest field is for.
DEFAULT_CONCEPT_BUDGET = 5

#: Never author more than this in one pass, whatever the manifest says. A budget is a dial, not a
#: blank cheque, and a typo of two extra zeros must not become a bill.
MAX_CONCEPT_BUDGET = 50


def modules_for_sources(survey: RepoSurvey, paths: list[str]) -> list[SurveyedModule]:
    """The surveyed modules that own `paths` — longest directory prefix wins, each module once,
    in the order the survey lists them.

    A CONCEPT NAMES FILES AND A MODULE IS A DIRECTORY. `ConceptSource.path` is `billing/rules.py`;
    `SurveyedModule.path` is `billing`. Re-authoring is per module, because that is the unit the
    prompt describes and the unit the ranking spends on — so a broken concept is turned back into
    the module(s) it was read from, and those are what get a fresh pass. The longest prefix is the
    owner: `billing/refunds/late.py` belongs to `billing/refunds` when that is a module of its own,
    and to `billing` only when it is not. A root module (`"."` or `""`) owns what nothing else does.
    """
    def parts(rel: str) -> tuple[str, ...]:
        return tuple(x for x in rel.replace("\\", "/").split("/") if x and x != ".")

    owners: list[SurveyedModule] = []
    for path in paths:
        file_parts = parts(path)
        best: SurveyedModule | None = None
        best_len = -1
        for module in survey.modules:
            mod_parts = parts(module.path)
            if file_parts[:len(mod_parts)] == mod_parts and len(mod_parts) > best_len:
                best, best_len = module, len(mod_parts)
        if best is not None and best not in owners:
            owners.append(best)
    return sorted(owners, key=lambda m: [x.path for x in survey.modules].index(m.path))


def rank_modules(survey: RepoSurvey, *, budget: int) -> list[SurveyedModule]:
    """The modules worth a model call, most valuable first, capped at `budget`.

    THE SCORE IS `churn × blast radius × uncertainty`, and it is deliberately crude: this decides
    where to look first, not what is true, and a subtle formula nobody can predict is worse here
    than a blunt one anybody can argue with. Each term is a measurement the survey already holds:

    * **churn** (`file_changes`) — one is added so a module with no recorded history still scores
      on its other terms rather than being multiplied to zero. A repository with no history at all
      (a flattened import, which much enterprise legacy is) then ranks purely on structure, which
      is the honest fallback rather than a refusal.
    * **blast radius** (`depended_on_by`) — the most-depended-on module is rarely the biggest, and
      it is where a wrong belief propagates. The survey has computed this since it existed and
      NOTHING has ever read it.
    * **uncertainty** — a module whose purpose is just its folder name is one the deterministic
      pass could say nothing about, which is precisely where a model call buys the most; one that
      also has no test naming it is worth more still, because nobody could learn it by reading the
      tests either.

    Ties break on name so the same repository always ranks the same way — a pass whose output
    reshuffles between runs makes every diff unreadable.
    """
    if budget <= 0:
        return []

    def score(module: SurveyedModule) -> tuple[int, str]:
        churn = 1 + max(0, module.file_changes)
        radius = 1 + len(module.depended_on_by)
        uncertainty = 1 + (2 if module.purpose_is_folder_name else 0) + (
            1 if module.named_by_no_test else 0)
        return (churn * radius * uncertainty, module.name)

    ranked = sorted(survey.modules, key=score, reverse=True)
    return ranked[:min(budget, MAX_CONCEPT_BUDGET)]


def concept_prompt(module: SurveyedModule, *, language: str | None = None) -> str:
    """The per-module read-only prompt. Exposed rather than inlined for the same reason
    `build_prompt` is: a prompt nobody can read is a prompt nobody can review, and this one asks a
    model to describe a client's business."""
    lang = f"\nAnswer in {language}.\n" if language else ""
    known = module.purpose if not module.purpose_is_folder_name else (
        "(the deterministic pass could not read a purpose — its 'purpose' is just the folder name)")
    depended = ", ".join(module.depended_on_by[:10]) or "(nothing in this repo)"
    tested = ", ".join(module.tested_by[:5]) or "(none — nobody could find its tests by looking)"
    surface = ", ".join(module.public_surface[:15]) or "(none detected)"
    return "\n".join([
        f"# Describe one module of an existing system: `{module.path}`",
        "",
        "You are reading a repository that already exists. Describe THIS MODULE only, for a",
        "reader who has never opened it — a product owner or a tech lead, not a compiler.",
        lang,
        "## What the deterministic pass already knows (do not repeat it, build on it)",
        "",
        f"- path: `{module.path}` · files: {module.files}",
        f"- purpose: {known}",
        f"- depended on by: {depended}",
        f"- tests naming it: {tested}",
        f"- public surface: {surface}",
        "",
        "## The rules, and they are the product",
        "",
        "1. EVERY business rule cites `path:line`. Citations are CHECKED against the repository",
        "   before anything you write is published: a rule whose citations do not resolve is",
        "   dropped and becomes a question. Inventing a source loses the sentence.",
        "2. Describe what the code DOES, never what it should do. This is a reading of an existing",
        "   system, not a specification of it.",
        "3. Anything you cannot establish from the code goes in `caveats` — a gap said out loud is",
        "   worth more than a confident sentence nobody can check.",
        "4. `type` names what this module IS in the domain's own words — `service`, `contract`,",
        "   `integration`, `ui-surface`, `workflow`, `policy`, `configuration` are common, and a",
        "   kind this system needs that is not in that list is a better answer than a bad fit.",
        "",
        "## Answer with ONE fenced json object, and nothing else",
        "",
        "```json",
        _CONCEPT_SHAPE,
        "```",
        "",
        "Empty lists are a real answer. A module whose business rules you cannot see in the code",
        "comes back with `\"business_rules\": []` and a caveat, never with a sentence composed to",
        "fill the field.",
    ])


_CONCEPT_SHAPE = """{
  "type":        "service",
  "title":       "a short name a person would use for this",
  "description": "one sentence",
  "what_it_does": "2-4 sentences, plain language",
  "behaviour":    ["one observable behaviour"],
  "business_rules": [{"text": "the rule the code enforces", "cites": ["path/f.ext:12"]}],
  "depends_on":  ["what it needs to work"],
  "consumed_by": ["who uses it"],
  "caveats":     ["what could not be established from the code alone"]
}"""


def _parse(raw: str) -> dict | None:
    """The model's fenced JSON, or None. Never raises: a pass that cannot be parsed is a gap to
    record, not an exception to propagate into an onboarding session."""
    from openfactory.adapters.reviewer.harness import extract_json

    try:
        data = json.loads(extract_json(raw))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def propose_concepts(
    survey: RepoSurvey,
    *,
    ask: AskFn | None,
    budget: int = DEFAULT_CONCEPT_BUDGET,
    language: str | None = None,
    commit: str = "",
    generated_at: str = "",
    fingerprints: dict[str, str] | None = None,
    modules: list[SurveyedModule] | None = None,
) -> tuple[list[Concept], list[Gap]]:
    """Author up to `budget` concepts, each verified. Returns `(concepts, gaps)`.

    `modules` NAMES THE MODULES OUTRIGHT, for the caller that already knows which ones — the
    refresh re-authoring the concepts a change invalidated (`onboarding/renew.py`). Ranking is
    for spending a budget where the platform knows least; a concept the checker has shown to be
    WRONG is not a candidate to weigh, it is a debt to pay first. Capped at `budget` all the same.

    `ask=None` IS A FIRST-CLASS MODE, exactly as it is for `propose_context`: no harness
    configured yet is the state of every client on the morning of day one, and it must produce a
    real answer rather than an error. With no `ask` there are no concepts and the ranking itself
    is the answer — the gaps say which modules a pass would have described, which is a useful
    thing to hand somebody even before a model is wired.

    A MODULE THAT FAILS IS A GAP, NEVER A CRASH AND NEVER A SILENCE. One unparseable answer among
    five must not lose the other four, and it must not vanish: the bundle records that this module
    was chosen and could not be described, which is the difference between "nothing to say here"
    and "we tried and could not".
    """
    repo = Path(survey.repo)
    chosen = (list(modules)[:min(budget, MAX_CONCEPT_BUDGET)] if modules is not None
              else rank_modules(survey, budget=budget))
    if not chosen:
        return [], []
    if ask is None:
        return [], [
            Gap(kind="not-described", path=m.path,
                detail="ranked for a concept and no agent was configured to write one")
            for m in chosen
        ]

    anchorer = _Anchorer(repo)
    fps = fingerprints or {}
    concepts: list[Concept] = []
    gaps: list[Gap] = []

    for module in chosen:
        try:
            answer = _parse(ask(concept_prompt(module, language=language)))
        except Exception as exc:  # noqa: BLE001 — one module's failure is a gap, not the run's end
            log.warning("concept pass failed for %s (%s)", module.path, str(exc)[:200])
            gaps.append(Gap(kind="not-described", path=module.path,
                            detail=f"the agent pass failed for this module ({str(exc)[:120]})"))
            continue
        if answer is None:
            gaps.append(Gap(kind="not-described", path=module.path,
                            detail="the agent's answer could not be read as the requested json"))
            continue

        rules, sources = _verified_rules(answer.get("business_rules"), anchorer, fps, commit)
        for rejected in _rejected_only(answer.get("business_rules"), anchorer):
            gaps.append(Gap(kind="unresolved", path=module.path, detail=rejected))
        for caveat in _strings(answer.get("caveats"))[:10]:
            gaps.append(Gap(kind="open-question", path=module.path, detail=caveat))

        concepts.append(Concept(
            type=str(answer.get("type") or "module").strip() or "module",
            title=str(answer.get("title") or module.name).strip() or module.name,
            description=str(answer.get("description") or "").strip(),
            generated_by="machine:backfill",
            generated_at=generated_at,
            sources=sources or [ConceptSource(
                path=module.path, commit=commit, fingerprint=fps.get(module.path, ""))],
            what_it_does=str(answer.get("what_it_does") or "").strip(),
            behaviour=_strings(answer.get("behaviour"))[:12],
            business_rules=rules,
            depends_on=_strings(answer.get("depends_on"))[:12],
            consumed_by=_strings(answer.get("consumed_by"))[:12],
            caveats=_strings(answer.get("caveats"))[:10],
        ))
    return concepts, gaps


def _strings(value: object, *, limit: int = 40) -> list[str]:
    """A list of non-empty strings out of whatever the model sent."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value[:limit] if isinstance(v, str) and v.strip()]


def _verified_rules(
    raw: object, anchorer: _Anchorer, fingerprints: dict[str, str], commit: str,
) -> tuple[list[BusinessRule], list[ConceptSource]]:
    """Keep only the rules whose citations survived, and derive the concept's sources from them.

    THE SOURCES ARE NOT DECLARED, THEY ARE EARNED. A concept's `sources` list is built from the
    citations that actually resolved, so the fingerprints that will later invalidate this concept
    describe exactly the files its claims were read from — not a list the model was asked to
    provide, which would be one more unverified field.
    """
    rules: list[BusinessRule] = []
    seen: dict[str, ConceptSource] = {}
    for item in (raw if isinstance(raw, list) else [])[:30]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kept, _rejected = anchorer.anchor(item.get("cites"))
        if not kept:
            continue  # a rule with no surviving citation is a gap, recorded by the caller
        cites: list[str] = []
        for evidence in kept:
            where = f"{evidence.path}:{evidence.line}" if evidence.line else evidence.path
            cites.append(where)
            if evidence.path not in seen:
                seen[evidence.path] = ConceptSource(
                    path=evidence.path, commit=commit,
                    fingerprint=fingerprints.get(evidence.path, ""),
                    lines=str(evidence.line) if evidence.line else "")
        rules.append(BusinessRule(text=text, cites=cites))
    return rules, [seen[k] for k in sorted(seen)]


def _rejected_only(raw: object, anchorer: _Anchorer) -> list[str]:
    """The rules that lost every citation, phrased as the gap they are.

    DEMOTED, NOT DELETED — the same move `_Anchorer`'s own caller makes for a claim that loses its
    citations. A sentence the model believed and could not support is a question worth putting in
    front of a developer, and dropping it silently would hide both the belief and the failure.
    """
    out: list[str] = []
    for item in (raw if isinstance(raw, list) else [])[:30]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kept, rejected = anchorer.anchor(item.get("cites"))
        if not kept:
            cited = ", ".join(rejected[:5]) or "nothing"
            out.append(f"{text} — cited {cited}, which this repository does not contain")
    return out
