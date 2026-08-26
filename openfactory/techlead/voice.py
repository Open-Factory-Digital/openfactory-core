"""What the tech-lead says to an OPERATOR, in the language that operator's project speaks (#124).

`product/voice.py` is the client's phrasebook and has worked for months; this is its counterpart
for the other audience, and it is the same shape on purpose — a per-language table plus `_pick`,
so a language nobody has translated for degrades to English rather than raising in a channel
listener.

THE RULE IT IMPLEMENTS, set by the product owner on 2026-08-16:

    a message the project sends FIRST — a park alert, a scheduled round, a remedy, a comment on a
    ticket nobody asked for — is written in the project's configured `language`;

    a REPLY follows the language of the question. Somebody who writes in English gets English,
    whatever the project is configured for.

Everything in this file is the FIRST kind. The second is the agents' own, and they already obey
it: `adapters/agent/roles.py::language_directive` states exactly that rule and is prepended to
every harness prompt, so a model answering a question sees the question. Canned replies are the
one stated exception — there is no language detector in this codebase, so they use the configured
language too.

WHY KEYS AND NOT SENTENCES IN THE CALLERS. `Verdict.detail` is authored in `classify.py`,
`Remedy.say` in the same file, `Finding.action` in `watch.py`, and all three are rendered in a
fourth place that is the only one holding a language. A sentence cannot survive that trip; a key
can. It is also what stopped the classifier reading its own output back as evidence (#124 step 1).

AND EVERYTHING HERE IS PROSE — never an identity, never a key somebody matches on. That line was
paid for four times over: the exhaustion regex, the impediment dedup title, the operator grammar's
verbs, and a workflow line that substring-matched the very sentence it was about to render. If a
value in this file is ever compared to something rather than shown to somebody, it is in the wrong
file.
"""

from __future__ import annotations

#: English, because a deployment that never says otherwise is not a Brazilian one — the same
#: default `product/voice.py` settled on.
DEFAULT_LANGUAGE = "en"


def pick(catalogue: dict[str, str], language: str | None) -> str:
    """The text for a language, falling back to the default and then to English.

    A language nobody has translated for gets understandable English rather than a KeyError in a
    channel listener — the failure mode matters more here than in a test: this runs on the path
    that reports that the factory is stuck."""
    lang = (language or DEFAULT_LANGUAGE).strip()
    return catalogue.get(lang) or catalogue.get(DEFAULT_LANGUAGE) or catalogue["en"]


def say(table: dict[str, dict[str, str]], key: str, language: str | None, **params: object) -> str:
    """One catalogue entry, rendered.

    An UNKNOWN KEY RETURNS THE KEY, deliberately. The alternative — raising — takes down the
    message that was reporting a problem, and the alternative to that — returning "" — is the
    silence this platform's whole invariant is written against. A reader seeing `park.stuck`
    where a sentence should be knows exactly what to report; a reader seeing nothing does not
    know there was anything to see."""
    entry = table.get(key)
    if entry is None:
        return key
    try:
        return pick(entry, language).format(**params)
    except (KeyError, IndexError):
        # A template asking for a value the caller did not pass. Better the raw template than a
        # crash inside a park announcement — and the shape is obvious to whoever reads it.
        return pick(entry, language)


# ── what a failure IS, in the taxonomy's own terms (`Verdict.detail`) ────────────────────────────
#
# Short noun phrases: they are interpolated into a sentence ("Isso é {detail} e passa sozinho"),
# so each has to read as a thing rather than as a clause.

DETAIL: dict[str, dict[str, str]] = {
    "throttled": {"en": "throttling", "pt-BR": "limite de taxa"},
    "network": {"en": "a network hiccup", "pt-BR": "uma falha de rede"},
    "cloud-capacity": {"en": "cloud capacity", "pt-BR": "capacidade da nuvem"},
    "race": {"en": "a race with another change, or something still running",
             "pt-BR": "uma corrida com outra mudança, ou algo que ainda estava rodando"},
    "engine-interrupted": {
        "en": "the machine under the job being interrupted (a worker restart or an "
              "infrastructure kill) — the work itself is untouched",
        "pt-BR": "a máquina sob o job foi interrompida (um restart do worker ou um corte de "
                 "infraestrutura) — o trabalho em si está intacto"},
    "credential": {"en": "a credential", "pt-BR": "uma credencial"},
    "policy-rule": {"en": "an organisation rule, working",
                    "pt-BR": "uma regra da organização, funcionando"},
    "project-config": {"en": "the project's own configuration",
                       "pt-BR": "a configuração do próprio repo"},
    "permission-or-infra": {"en": "permission or infrastructure",
                            "pt-BR": "permissão ou infraestrutura"},
    "the-ticket": {"en": "the ticket itself", "pt-BR": "o próprio ticket"},
    "the-change": {"en": "the change", "pt-BR": "a mudança"},
    "empty-branch": {"en": "a branch with no change in it",
                     "pt-BR": "um branch sem nenhuma mudança"},
    "forge-repo-or-credential": {"en": "the repository or the forge credential",
                                 "pt-BR": "o repositório ou a credencial do forge"},
    "undecided-pr": {"en": "a pull request nobody decided in time",
                     "pt-BR": "um PR que ninguém decidiu no prazo"},
    "ticket-too-big": {"en": "a ticket bigger than one pass",
                       "pt-BR": "um ticket maior do que uma passada"},
}


# ── what the factory intends to do about it (`Remedy.reason` / `Remedy.say`) ─────────────────────
#
# `reason` is the short WHY, quoted inside a longer escalation line. `say` is the whole sentence a
# channel receives. Both are proactive by definition: nobody asked.

#: The two verbs a channel reply may carry. Interpolated rather than written into each sentence so
#: the grammar in `contracts/commands.py` and the words a message teaches cannot drift apart —
#: a guard feeds every rendered sentence's backticked verbs to that parser.
WAYS_OUT: dict[str, str] = {
    "en": "Reply `resume` and I will try again once you have adjusted it, or `skip` to free the "
          "queue.",
    "pt-BR": "Responda `resume` para eu tentar de novo depois de ajustar, ou `skip` para liberar "
             "a fila.",
}

REMEDY: dict[str, dict[str, str]] = {
    "transient.reason": {
        "en": "{detail} — it passes on its own; the window just has to close",
        "pt-BR": "{detail} — passa sozinho, é esperar a janela"},
    "transient.say": {
        "en": "This is {detail} and it passes on its own. Trying again in {minutes} min.",
        "pt-BR": "Isso é {detail} e passa sozinho. Tento de novo em {minutes} min."},
    "credential.reason": {
        "en": "every credential failed this pass; some recover on their own",
        "pt-BR": "todas as credenciais falharam nesta passada; algumas se recuperam"},
    "credential.say": {
        "en": "The credentials failed this pass. Trying again in {minutes} min.",
        "pt-BR": "As credenciais falharam nesta passada. Tento de novo em {minutes} min."},
    "requirement.reason": {
        "en": "the problem is in the ticket, not in the run",
        "pt-BR": "o problema está no ticket, não na execução"},
    "requirement.say": {
        "en": "This is the requirement, not the execution: the ticket needs rewriting by whoever "
              "asked for it. Running it again would land in the same place — `skip` frees the "
              "queue meanwhile.",
        "pt-BR": "Isto é do requisito, não da execução: o ticket precisa ser reescrito por quem o "
                 "pediu. Repetir a execução daria no mesmo — `skip` libera a fila enquanto isso."},
    "policy.say": {
        "en": "The organisation refused that write on purpose (CI/CD is a human responsibility). "
              "Do not ask for permission for the bot — the way through is to take those files out "
              "of scope: edit the ticket to say not to touch `.github/workflows/**` and reply "
              "`resume`; the CI part goes into a comment for a person to apply. Or `skip` to free "
              "the queue.",
        "pt-BR": "A organização recusou essa escrita de propósito (CI/CD é responsabilidade "
                 "humana). Não peça permissão para o bot — o caminho é tirar esses arquivos do "
                 "escopo: edite o ticket dizendo para não tocar em `.github/workflows/**` e "
                 "responda `resume`; a parte de CI vai num comentário para uma pessoa aplicar. "
                 "Ou `skip` para liberar a fila."},
    "project.say": {
        "en": "The project's own command failed (the command and its exit code are in the note "
              "above — `setup:`/`validate:` in `{manifest}`, or the manifest). Fix it in the "
              "project's repository and reply `resume`; `skip` frees the queue.",
        "pt-BR": "O comando do próprio projeto falhou (veja o comando e o código de saída na "
                 "nota acima — `setup:`/`validate:` em `{manifest}`, ou o manifest). Conserte no "
                 "repositório do projeto e responda `resume`; `skip` libera a fila."},
    "policy.reason": {
        "en": "an organisation rule refused the write — and the rule is right",
        "pt-BR": "uma regra da organização recusou a escrita — e a regra está certa"},
    "project.reason": {
        "en": "the project's own configuration failed — the fix is there, not here",
        "pt-BR": "a configuração do próprio repositório falhou — o conserto é lá, não aqui"},
    "why.code": {
        "en": "the change itself is wrong — repeating it does not change that",
        "pt-BR": "a mudança em si está errada — repetir não muda isso"},
    "why.environment": {
        "en": "this is infrastructure configuration; no attempt fixes it",
        "pt-BR": "é configuração de infraestrutura; nenhuma tentativa conserta"},
    "why.unknown": {
        "en": "I could not identify the cause from the error alone, so I will not retry "
              "blindly — my full diagnosis is on its way to the ticket and this channel",
        "pt-BR": "não consegui identificar a causa só pelo erro, então não vou tentar às cegas — "
                 "meu diagnóstico completo está a caminho do ticket e deste canal"},
    "escalate.say": {
        "en": "I need you: {why}. {ways_out}",
        "pt-BR": "Preciso de vocês: {why}. {ways_out}"},
    "exhausted.reason": {
        "en": "the message itself says the automatic attempts are already spent",
        "pt-BR": "a própria mensagem diz que as tentativas automáticas já se esgotaram"},
    "exhausted.say": {
        "en": "This has already been tried automatically and it continues. {ways_out}",
        "pt-BR": "Isso já foi tentado automaticamente e continua. {ways_out}"},
    "spent.reason": {
        "en": "I have already tried {spent} and the problem continues",
        "pt-BR": "já tentei {spent} e o problema continua"},
    "spent.say": {
        "en": "I have already tried {spent} and it continues — this needs you now.",
        "pt-BR": "Já tentei {spent} e continua — agora precisa de vocês."},
}

#: How many attempts, in words, because the sentence reads "I have already tried ONE ATTEMPT".
ATTEMPTS: dict[str, dict[str, str]] = {
    "one": {"en": "one attempt", "pt-BR": "uma tentativa"},
    "many": {"en": "{n} attempts", "pt-BR": "{n} tentativas"},
}


# ── what a ROUND says about the floor (`Finding.detail` / `Finding.action`) ──────────────────────
#
# Every one of these is the factory speaking first, on a schedule nobody asked for — the purest
# case of the rule this file implements.

FINDING: dict[str, dict[str, str]] = {
    "park.self-healing": {
        "en": "stopped {hours:.0f}h ago on something that passes by itself",
        "pt-BR": "parado há {hours:.0f}h por algo que passa sozinho"},
    "park.retrying": {
        "en": "trying again now — {detail}",
        "pt-BR": "vou tentar de novo agora — {detail}"},
    "park.needs-you": {
        "en": "stopped {hours:.0f}h ago, waiting on a decision from you",
        "pt-BR": "parado há {hours:.0f}h esperando uma decisão de vocês"},

    "gate.ci.detail": {
        "en": "open {hours:.0f}h with auto-merge armed and CI still not finished",
        "pt-BR": "aberto há {hours:.0f}h com o merge automático armado e o CI sem fechar"},
    "gate.ci.action": {
        "en": "nobody needs to do anything: it lands by itself when CI passes. If CI is never "
              "going to pass, discarding the pull request on the panel frees the queue",
        "pt-BR": "ninguém precisa fazer nada: ele entra sozinho quando o CI passar. Se o CI não "
                 "vai passar, descartar o PR no painel libera a fila"},
    "gate.deaf.detail": {
        "en": "open {hours:.0f}h with the pull request waiting, and this gate cannot hear",
        "pt-BR": "aberto há {hours:.0f}h com o PR esperando, e este portão não escuta"},
    "gate.approval.detail": {
        "en": "waiting {hours:.0f}h for a production approval from you",
        "pt-BR": "esperando uma aprovação de produção há {hours:.0f}h"},
    "gate.approval.action": {
        "en": "the approval is on the panel, by somebody allowed to give it — the job holds the "
              "queue until then, and that is how it should be",
        "pt-BR": "a aprovação é no painel, por quem tem permissão para aprovar — o job segura a "
                 "fila até lá, e é assim que tem que ser"},
    "gate.merge.detail": {
        "en": "waiting {hours:.0f}h on you — the pull request is ready and the gate is yours",
        "pt-BR": "esperando vocês há {hours:.0f}h — o PR está pronto e o portão é de vocês"},
    "gate.merge.action": {
        "en": "nothing is broken: on the panel the card carries *Merge*, *Adjust…* and "
              "*Discard* — or just ask here in the chat",
        "pt-BR": "nada quebrou: no painel, o cartão tem *Merge*, *Ajustar…* e *Descartar* — ou é "
                 "só pedir aqui pelo chat"},

    "wedged.detail": {
        "en": "running {hours:.0f}h without stopping or finishing — longer than any real pass "
              "takes",
        "pt-BR": "rodando há {hours:.0f}h sem parar nem terminar — mais do que qualquer passada "
                 "real leva"},
    # #127 REPLACED THE HONEST SENTENCE WITH A USABLE ONE. This read "the way out is in the
    # engine: open Temporal and terminate the workflow" — true, and a raw-engine operation being
    # asked of an operator on the one surface this product promises they will never need. There is
    # a row now, and it says what stopping costs, because `stop` does not resume.
    "wedged.action": {
        "en": "the job is not parked (it asked for nothing) and it is not advancing either, so "
              "nothing else here reaches it. `stop #{ticket}` ends it and frees the queue — it "
              "does NOT resume: the ticket goes back to the board and a fresh job starts from the "
              "beginning, so whatever this run had in flight is lost. The panel offers it on the "
              "floor card",
        "pt-BR": "o job não está parado (não pediu nada) e também não avança, então nada mais "
                 "aqui alcança ele. `stop #{ticket}` encerra e libera a fila — ele NÃO retoma: o "
                 "ticket volta para o board e um job novo começa do zero, então o que esta "
                 "passada tinha em andamento se perde. O painel oferece isso no cartão do chão"},

    "idle.detail": {
        "en": "nothing running for {minutes:.0f} min with {queued} in the queue",
        "pt-BR": "nada rodando há {minutes:.0f} min com {queued} na fila"},
    "idle.action": {
        "en": "this should not happen — the queue should be being pulled",
        "pt-BR": "isso não deveria acontecer — a fila deveria estar sendo puxada"},
    "recurring.detail": {
        "en": "{times} different tickets failed for {cause}",
        "pt-BR": "{times} tickets diferentes falharam por {cause}"},
    "recurring.action": {
        "en": "this is one problem, not three — the common cause is worth a look",
        "pt-BR": "isso é um problema só, não três — vale olhar a causa comum"},
}

#: What the round says it ACTUALLY DID, filled in after acting — never what it meant to do.
OUTCOME: dict[str, dict[str, str]] = {
    "resumed": {
        "en": "it was something that passes by itself, so I resumed it — I will say so if it "
              "stops again",
        "pt-BR": "era algo que passa sozinho, então retomei — se parar de novo eu aviso"},
    "resume-failed": {
        "en": "I tried to resume it and could not — this needs somebody; reply `resume {ticket}` "
              "or `skip {ticket}`",
        "pt-BR": "tentei retomar e não consegui — precisa de alguém, responda `resume {ticket}` "
                 "ou `skip {ticket}`"},
    "still-holding": {
        "en": "it goes on holding the queue until somebody answers",
        "pt-BR": "segue segurando a fila até alguém responder"},
}

# ── what the LIFECYCLE says, unprompted, as a job moves (#160) ───────────────────────────────────
#
# Every sentence here was welded into the code that emits it — eleven of them in `workflow.py`
# alone, half in Portuguese and half in English, so an English-configured client heard "Dividi o
# #12" and a Portuguese one heard "staging did not verify". Both directions of the same defect, in
# one file, next to each other.
#
# THE WORKFLOW MAY RENDER THESE. It holds `params.language` — a FIELD on `JobParams` precisely so
# a park announcement need not do IO to know what language to speak (see `io.py`) — and `pick` is
# a dict lookup plus `format`, which is deterministic and therefore safe inside a replay. The
# activities that render the rest hold the project row itself.

NARRATION: dict[str, dict[str, str]] = {
    # ── a job being picked up and landing ────────────────────────────────────────────────────────
    "pickup": {
        "en": "▶ Picking up #{issue}",
        "pt-BR": "▶ Pegando o #{issue}"},
    "merged": {
        "en": "✅ #{issue} merged to main",
        "pt-BR": "✅ #{issue} mergeado na main"},
    # ── a park somebody has to answer ────────────────────────────────────────────────────────────
    "park.needs-you": {
        "en": "⏸ #{issue} stopped and needs you{who}\n{note}\n{ways}",
        "pt-BR": "⏸ #{issue} parou e precisa de vocês{who}\n{note}\n{ways}"},
    #: The two ways out of a park, as commands. Split because a park the factory itself judges
    #: unretryable must not teach `resume` — it would be answered, fail, and teach the reader that
    #: the messages are decoration. The verbs come from `contracts/commands.py`'s grammar.
    "park.both-verbs": {
        "en": "Reply *resume #{issue}* to try again, or *skip #{issue}* to free the queue.",
        "pt-BR": "Responda *resume #{issue}* para tentar de novo, ou *skip #{issue}* para "
                 "liberar a fila."},
    "park.skip-only": {
        "en": "Reply *skip #{issue}* to free the queue.",
        "pt-BR": "Responda *skip #{issue}* para liberar a fila."},
    #: A park that carries a DecisionRequest: the question is the agent's own words and arrives
    #: already written, so only the frame is translated.
    "park.decision": {
        "en": "⏸ #{issue}: {question}\n{note}\n"
              "Reply `decision: <option>` ({keys}) — or use the panel.",
        "pt-BR": "⏸ #{issue}: {question}\n{note}\n"
                 "Responda `decisão: <opção>` ({keys}) — ou use o painel."},
    "self-heal": {
        "en": "⏳ #{issue} — {say}",
        "pt-BR": "⏳ #{issue} — {say}"},
    # ── what this platform's own review found, after the merge ───────────────────────────────────
    "review.flag": {
        "en": "⚠️ #{issue} merged, but the review {what} (score {score}). {detail}\n\n"
              "This did not block the delivery — review is advisory. I am flagging it for "
              "somebody to look at.",
        "pt-BR": "⚠️ #{issue} mergeou, mas a revisão {what} (nota {score}). {detail}\n\n"
                 "Isto não bloqueou a entrega — revisão é consultiva. Estou marcando para "
                 "alguém olhar."},
    "review.rejected": {"en": "REJECTED it", "pt-BR": "REJEITOU"},
    "review.critical": {"en": "raised something critical",
                        "pt-BR": "levantou algo crítico"},
    # ── the tail of the chain: a last stage with no production behind it ─────────────────────────
    "stage.no-environment": {
        "en": "✅ #{issue} merged. This project declares no environment to observe and no "
              "production stage, so nothing further is waiting on anybody.",
        "pt-BR": "✅ #{issue} mergeado. Este projeto não declara nenhum ambiente para observar "
                 "nem estágio de produção, então não há mais nada esperando ninguém."},
    "stage.confirm-at": {
        "en": "✅ #{issue}: {stage} is green and there is no production stage after it — please "
              "confirm the change is right: {where}",
        "pt-BR": "✅ #{issue}: {stage} está verde e não há estágio de produção depois dele — "
                 "confirmem, por favor, que a mudança está certa: {where}"},
    "stage.confirm-no-url": {
        "en": "✅ #{issue}: {stage} is green and there is no production stage after it, so a "
              "person confirming it is the only check left — and this project declares no `url:` "
              "for {stage} in `.openfactory/project.yaml`, so I cannot say where to look.",
        "pt-BR": "✅ #{issue}: {stage} está verde e não há estágio de produção depois dele, "
                 "então alguém confirmar é a única checagem que resta — e este projeto não "
                 "declara `url:` para {stage} em `.openfactory/project.yaml`, então não tenho "
                 "como dizer onde olhar."},
    "stage.unverified": {
        "en": "⚠️ #{issue}: staging did not verify ({why}) — production is not waiting on "
              "anybody until this is looked at",
        "pt-BR": "⚠️ #{issue}: o staging não verificou ({why}) — a produção não está esperando "
                 "ninguém até alguém olhar isto"},
    # ── the production gate ──────────────────────────────────────────────────────────────────────
    "prod.window-elapsed": {
        "en": "⏰ #{issue}: the production approval window ({days}d) elapsed with no answer. "
              "Nothing shipped. Re-run the promotion when somebody can approve it.",
        "pt-BR": "⏰ #{issue}: a janela de aprovação de produção ({days}d) passou sem resposta. "
                 "Nada foi publicado. Rode a promoção de novo quando alguém puder aprovar."},
    "prod.released": {
        "en": "#{issue} released to production",
        "pt-BR": "#{issue} publicado em produção"},
    "prod.failed": {
        "en": "❌ #{issue}: the production release did not complete ({why}) — it was approved, "
              "so somebody is waiting on an outcome that has not arrived",
        "pt-BR": "❌ #{issue}: a publicação em produção não terminou ({why}) — foi aprovada, "
                 "então tem gente esperando um desfecho que não chegou"},
    # ── a ticket too large for one pass, split into children ─────────────────────────────────────
    "split.head": {
        "en": "✂️ I split {parent} — {title} into {n}: it was too large ({why}).",
        "pt-BR": "✂️ Dividi o {parent} — {title} em {n}: era grande demais ({why})."},
    "split.created": {
        "en": " I created them and sent them to {where}:\n{children}",
        "pt-BR": " Criei e mandei pra {where}:\n{children}"},
    #: ONE STRAGGLER AND SEVERAL ARE DIFFERENT SENTENCES, and the difference is the half a person
    #: acts on. The first version of this row said "drag them" for a single stuck card, next to a
    #: list of three — measured on the pilot, where the reader could not tell from the sentence
    #: whether one card or all three needed moving. Portuguese hid it (`arrasta` is impersonal),
    #: which is exactly why a per-language table needs both rows rather than one clever one.
    "split.straggler-one": {
        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag that one onto the "
              "board, after the others, or it will never run:\n{children}",
        "pt-BR": " Criei os {n}, mas não consegui mover {stuck} pra TO-DO — arrasta esse no "
                 "quadro, depois dos outros, senão ele fica sem rodar:\n{children}"},
    "split.stragglers": {
        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag those onto the "
              "board, in order, or they will never run:\n{children}",
        "pt-BR": " Criei os {n}, mas não consegui mover {stuck} pra TO-DO — arrasta esses no "
                 "quadro, na ordem, senão ficam sem rodar:\n{children}"},
    #: WHICH CHILD IS THE STUCK ONE, on its own line. The sentence names the ref and the list
    #: repeated three near-identical titles under it, so a reader had to cross-reference a number
    #: against them. A list that shows a problem must show it where the problem is.
    "split.not-queued": {"en": "NOT QUEUED — drag this one",
                         "pt-BR": "FORA DA FILA — arrasta este"},
    "split.to-todo": {
        "en": "TO-DO (they run one at a time, in order)",
        "pt-BR": "TO-DO (rodam um por vez, em ordem)"},
    "split.to-backlog": {"en": "Backlog", "pt-BR": "Backlog"},
    # ── the deploy watch, and the budget that stops pickup ───────────────────────────────────────
    "deploy.outcome": {
        "en": "{icon} {project}#{issue}: {env} deploy {status}{where}{invite}",
        "pt-BR": "{icon} {project}#{issue}: deploy de {env} {status}{where}{invite}"},
    "deploy.invitation": {
        "en": " — please take a look: {url}",
        "pt-BR": " — deem uma olhada, por favor: {url}"},
    "deploy.status.success": {"en": "success", "pt-BR": "OK"},
    "deploy.status.failure": {"en": "failure", "pt-BR": "falhou"},
    "deploy.status.timeout": {"en": "timeout", "pt-BR": "estourou o tempo"},
    "rate-pause": {
        "en": "⏸️ the factory is not taking cards right now: this deployment's {forge} {resource} "
              "budget is spent ({remaining} left). It refills at {when} and pickup resumes on its "
              "own — nothing is lost and nothing needs restarting. If this repeats every hour, "
              "the board reads are costing more than they should: `openfactory doctor {project}` "
              "prints the budget and what is spending it.",
        "pt-BR": "⏸️ a fábrica não está pegando cartões agora: o orçamento de {resource} do "
                 "{forge} deste deployment acabou (restam {remaining}). Ele recompõe às {when} e "
                 "o pickup volta sozinho — nada se perde e nada precisa ser reiniciado. Se isso "
                 "repetir toda hora, as leituras do quadro estão custando mais do que deveriam: "
                 "`openfactory doctor {project}` mostra o orçamento e o que está gastando."},
    #: When the forge did not say WHEN the budget refills. A word, because it lands inside the
    #: sentence above — "it refills at soon" is what a welded English literal produced in a
    #: Portuguese message.
    "rate-pause.soon": {"en": "soon", "pt-BR": "daqui a pouco"},
    # ── what the in-job machine says on the ticket and in the channel ────────────────────────────
    #
    # THE REASON IS NEVER TRANSLATED, and that is not an oversight. A park's `note` travels on the
    # RunResult, and `classify()` reads it to decide what kind of failure it was, `memory` hashes
    # it to recognise the same failure twice, and the self-heal gates on both. It is an IDENTITY.
    # What a person reads is the FRAME around it, and the frame is what these entries are.
    "job.hold": {"en": "{mention}{verb} — {reason}", "pt-BR": "{mention}{verb} — {reason}"},
    "job.verb.on-hold": {"en": "on hold", "pt-BR": "em espera"},
    "job.verb.needs-refinement": {"en": "needs refinement", "pt-BR": "precisa de refinamento"},
    "job.on-hold": {"en": "{mention}On hold — {reason}",
                    "pt-BR": "{mention}Em espera — {reason}"},
    "job.needs-you": {"en": "{ticket} needs you: {state} — {reason}",
                      "pt-BR": "{ticket} precisa de vocês: {state} — {reason}"},
    "job.pr-ready": {"en": "PR ready for review: {pr}{review}",
                     "pt-BR": "PR pronto para revisão: {pr}{review}"},
    "job.merged": {"en": "{ticket} merged: {pr}", "pt-BR": "{ticket} mergeado: {pr}"},
    # ── the pull request's OWN review section, when a pass has rewritten the code under it ──────
    #
    # THE SAME FACT THE GATE SHOWS, ON THE OTHER SURFACE (#187). `review.verdict.headline` says
    # "Review out of date" on the card; the pull request said nothing at all, and the pull request
    # is where a reviewer naturally goes and the only place a collaborator without the panel token
    # can look. The vocabulary is pinned to the panel's by a guard, so the two cannot drift into
    # two answers about one pull request — which is #164, in a second surface.
    "pr.review.out-of-date": {
        "en": "> **Review out of date** — a pass rewrote this pull request after the reviewer "
              "read it, and nothing re-ran the reviewer. What follows judged the diff BEFORE "
              "that; it is not evidence about what is on this pull request now.",
        "pt-BR": "> **Revisão desatualizada** — uma passada reescreveu este pull request depois "
                 "que o revisor o leu, e nada rodou o revisor de novo. O que vem abaixo julgou o "
                 "diff ANTES disso; não é evidência sobre o que está neste pull request agora."},
    #: The stamp on every clause after the caveat, because a reader applies a warning to the
    #: clause it was standing next to and not to the six below it (#154).
    "pr.review.was": {"en": "was: ", "pt-BR": "antes: "},
    "job.e2e-passed": {"en": "e2e passed — {url}", "pt-BR": "o e2e passou — {url}"},
    "job.assumption": {
        "en": "planner assumption (auto — review it in the PR): {note}",
        "pt-BR": "premissa do planner (automática — confira no PR): {note}"},
    "job.paused-rate": {
        "en": "⏸ paused: the agent's usage limit was reached{until}. Will resume automatically.",
        "pt-BR": "⏸ pausado: o limite de uso do agente foi atingido{until}. Retoma sozinho."},
    "job.paused-rate.until": {"en": " — resumes after {retry_at}",
                              "pt-BR": " — retoma depois de {retry_at}"},
    "job.auth-failed": {
        "en": "⛔ on hold: the coding agent could not authenticate — fix its token.",
        "pt-BR": "⛔ em espera: o agente de código não conseguiu autenticar — corrija o token."},
    # ── the pre-flight, on the client's own ticket ───────────────────────────────────────────────
    "preflight.unsized": {
        "en": "⚠️ pre-flight sizing did **not** run ({why}) — this ticket proceeds UNSIZED. If it "
              "turns out too large, this is why; fix the gate (see the worker logs) rather than "
              "trusting the sizing was clean.",
        "pt-BR": "⚠️ o dimensionamento de pré-voo **não** rodou ({why}) — este ticket segue SEM "
                 "DIMENSIONAR. Se ele for grande demais, é por isto; conserte o portão (veja os "
                 "logs do worker) em vez de confiar que o dimensionamento saiu limpo."},
    "preflight.unclear": {
        "en": "Pre-flight: can't size this ticket — please clarify:\n{questions}",
        "pt-BR": "Pré-voo: não consigo dimensionar este ticket — esclareçam, por favor:"
                 "\n{questions}"},
    "preflight.no-questions": {
        "en": "- (no questions emitted)", "pt-BR": "- (nenhuma pergunta foi emitida)"},
    "preflight.too-large": {
        "en": "Pre-flight: too large for one ticket ({why})\nProposed split:\n{children}",
        "pt-BR": "Pré-voo: grande demais para um ticket só ({why})\nDivisão proposta:"
                 "\n{children}"},
    # ── the factory's OWN impediment ticket, read by a supervisor ────────────────────────────────
    #
    # The TITLE is not here and must never be: it is the dedup key, matched exactly, and a
    # deployment that changed its language would stop recognising its own open tickets and file a
    # fresh duplicate on every occurrence. `ops/impediment.py` states that split at length — and
    # then wrote the body, which it names as the translatable half, in one welded language.
    "ops.impediment.preamble": {
        "en": "_Opened automatically by the platform: a capability it promises is not working._"
              "\n\n**While this lasts**, the product agent goes on answering, and tells the client "
              "honestly that it could not verify what it says. It asks the client for nothing — "
              "this ticket is the ask.\n\n**How it closes:** by itself, the next time the "
              "capability works. Nobody has to mark it resolved; if you fix it, the close comes "
              "from the evidence.",
        "pt-BR": "_Aberto automaticamente pela plataforma: uma capacidade que ela promete não está "
                 "funcionando._\n\n**Enquanto isto durar**, a agente de produto continua "
                 "respondendo, e diz honestamente ao cliente que não pôde verificar o que afirma. "
                 "Ela não pede nada ao cliente — o pedido é este ticket.\n\n**Como fecha:** "
                 "sozinho, na próxima vez que a capacidade funcionar. Ninguém precisa marcar como "
                 "resolvido; se você consertar, o fechamento vem da evidência."},
    "ops.impediment.body": {
        "en": "{preamble}\n\n- **Deployment:** `{project}`\n- **Cause:** `{cause}`\n"
              "- **Owner:** {owner}\n\n## What the platform observed\n\n{detail}\n",
        "pt-BR": "{preamble}\n\n- **Deployment:** `{project}`\n- **Causa:** `{cause}`\n"
                 "- **Responsável:** {owner}\n\n## O que a plataforma observou\n\n{detail}\n"},
    "ops.impediment.no-owner": {
        "en": "**nobody** — this deployment named no factory supervisor, and an impediment with "
              "no owner is the silent wait all over again",
        "pt-BR": "**ninguém** — este deployment não nomeou um supervisor da fábrica, e um "
                 "impedimento sem dono é a espera silenciosa outra vez"},
    "ops.impediment.no-detail": {"en": "(no detail)", "pt-BR": "(sem detalhe)"},
    "ops.impediment.closed": {
        "en": "Closed by the evidence: {evidence}",
        "pt-BR": "Fechado pela evidência: {evidence}"},
    # ── the box gate, which holds pickup for a whole project ─────────────────────────────────────
    "gate.pickup-held": {
        "en": "⏸️ *{project}* — tickets are not being picked up.\n{reason}",
        "pt-BR": "⏸️ *{project}* — os tickets não estão sendo pegos.\n{reason}"},
    # ── the promotion chain, on the ticket and in the channel ────────────────────────────────────
    #
    # THESE REACH THE TICKET, which is the one surface every project has whether or not a channel
    # is configured — so a client with no Slack read the whole promotion in English regardless of
    # what their project declares.
    "promo.merged": {"en": "✅ merged.", "pt-BR": "✅ mergeado."},
    "promo.verified": {"en": " {stages} verified.", "pt-BR": " {stages} verificado(s)."},
    "promo.no-production": {
        "en": " This project declares no production environment, so there is no release step.",
        "pt-BR": " Este projeto não declara ambiente de produção, então não há passo de "
                 "publicação."},
    "promo.awaiting-head": {
        "en": "{stages} verified — ", "pt-BR": "{stages} verificado(s) — "},
    "promo.awaiting-head-none": {"en": "merged — ", "pt-BR": "mergeado — "},
    "promo.awaiting": {
        "en": "awaiting a human's approval to promote to {production}",
        "pt-BR": "esperando a aprovação de uma pessoa para promover para {production}"},
    "promo.awaiting-ticket": {
        "en": "Awaiting {production} approval.",
        "pt-BR": "Esperando a aprovação de {production}."},
    "promo.confirm.no-stage": {
        "en": "merged; this project declares no environment to observe",
        "pt-BR": "mergeado; este projeto não declara nenhum ambiente para observar"},
    "promo.confirm.at": {
        "en": "{stage} is green — please confirm it is right: {where}",
        "pt-BR": "{stage} está verde — confirmem, por favor, que está certo: {where}"},
    "promo.confirm.no-url": {
        "en": "{stage} is green, and this project declares no address for it, so nobody can be "
              "sent to look. Add `url:` under `environments.{stage}` in "
              "`.openfactory/project.yaml`{tail}",
        "pt-BR": "{stage} está verde, e este projeto não declara endereço para ele, então não há "
                 "para onde mandar alguém olhar. Adicione `url:` em `environments.{stage}` no "
                 "`.openfactory/project.yaml`{tail}"},
    "promo.confirm.only-check": {
        "en": " — with no production stage, that confirmation is the only check left before this "
              "is what users get",
        "pt-BR": " — sem estágio de produção, essa confirmação é a única checagem que resta antes "
                 "de isto ser o que os usuários recebem"},
    "promo.where.confirm": {
        "en": "\n\nSomebody should confirm {stage} is right: {where}",
        "pt-BR": "\n\nAlguém precisa confirmar que {stage} está certo: {where}"},
    "promo.where.no-url": {
        "en": "\n\nNobody can be sent to look at {stage}: this project declares no `url:` for it "
              "in `.openfactory/project.yaml`.",
        "pt-BR": "\n\nNão há para onde mandar alguém olhar {stage}: este projeto não declara "
                 "`url:` para ele no `.openfactory/project.yaml`."},
    "promo.release-approved": {
        "en": "Production release approved by @{approver} — {tag}{extra}",
        "pt-BR": "Publicação em produção aprovada por @{approver} — {tag}{extra}"},
    "promo.live": {"en": "live in production", "pt-BR": "no ar em produção"},
    "promo.verify-failed": {
        "en": "prod verification failed — rolling back",
        "pt-BR": "a verificação de produção falhou — revertendo"},
    "promo.rollback-ticket": {
        "en": "❌ prod health failed — rolling back to the last-good release.",
        "pt-BR": "❌ a saúde de produção falhou — revertendo para a última publicação boa."},
    "promo.env-failed": {
        "en": "{env} deploy/health failed", "pt-BR": "o deploy/saúde de {env} falhou"},
    "promo.env-failed-ticket": {
        "en": "❌ {env} deploy/health failed — see the pipeline.",
        "pt-BR": "❌ o deploy/saúde de {env} falhou — veja o pipeline."},
    # ── a review finding nobody acknowledged ─────────────────────────────────────────────────────
    "finding.unacked.detail": {
        "en": "delivered with the review raising something serious: {detail}",
        "pt-BR": "entregue com a revisão apontando algo sério: {detail}"},
    "finding.unacked.action": {
        "en": "nobody has looked yet — reply `ack {ticket}` when somebody picks it up",
        "pt-BR": "ninguém olhou ainda — responda `ack {ticket}` quando alguém assumir"},
}

#: The round's opening line. Two of them, because a list whose every item is a gate working
#: exactly as configured must not be introduced as trouble (pilot, 2026-08-16).
HEADLINE: dict[str, dict[str, str]] = {
    "gates-only": {
        "en": "I looked at how things are going — nothing is stuck, just things waiting on you:",
        "pt-BR": "Olhei o andamento — nada travado, só coisa esperando vocês:"},
    "trouble": {
        "en": "I looked at how things are going and something has stopped:",
        "pt-BR": "Olhei o andamento e tem coisa parada:"},
}
