# Conformance and the marks: what may be called OpenFactory

**The code is free; the name is not; the conformance suite is what makes the name mean
something.** That is the whole of [NOTICE](../../NOTICE), and this page is its operating manual:
which marks exist, who may use each, what a build or a service has to prove, how the proof is
submitted and reviewed, how long it holds, and what happens when it lapses. The mechanism is
Kubernetes's ([research](research/partner-and-certification-programs.md) §2): a permissive
licence, a defended mark, and conformance as the gate — with the three audiences that program
keeps distinct: a **product**, a **company**, and a **person**.

## The marks

| mark | for | granted by | what it asserts |
|---|---|---|---|
| **OpenFactory** (word mark and logo) | the project | owned by the project's steward, to be assigned to the foundation | the platform published from the project's repositories |
| **Powered by OpenFactory** | anyone | no application; the descriptive-use rules below | this product or service runs the platform, unmodified or conformant |
| **Certified OpenFactory** | a build or distribution | a passed conformance submission | this build behaves as the platform does on the properties the suite checks, on the version named |
| **OpenFactory Certified Hosting** | a managed service | a passed conformance submission plus the hosting audit | this service runs a Certified OpenFactory build to the [hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard) |
| **OpenFactory Compatible** | an add-on package | a passed `conformance-adapter` submission | this package's rows satisfy their ports on the version named |
| **OpenFactory Certified Partner**, **Premier Partner** | a company | the [partner program](04-partner-program.md) | this company is on the public partner list at that tier |
| **OpenFactory Certified Associate / Operator / Implementer / Solution Architect / Product Owner / Developer / Trainer** | a person | the [certification program](03-role-certifications.md) | this person holds that credential, unexpired |

Nothing else is a mark. "OpenFactory Certified" on its own, "OpenFactory Enterprise",
"OpenFactory Cloud", "OpenFactory Gold Partner", "Official OpenFactory" and every other
combination are not granted to anyone and may not be used.

## Descriptive use, which needs no permission

Anyone may say, truthfully, that their product, service or company **uses**, **runs**,
**integrates with**, **supports** or **is built on** OpenFactory, and may use the phrase
"Powered by OpenFactory" and the Powered-by logo, provided that:

- the name is written in full and unaltered ("OpenFactory", not "OF", not "Open Factory") and the
  logo is not recoloured, cropped or combined with another mark;
- the mark is not part of the product's, service's or company's own name, domain name, social
  handle or app title;
- the first use on a page links to openfactory.digital and the page carries the attribution
  "OpenFactory is a trademark of [the steward / the foundation]";
- nothing implies the project endorses, certifies or audits the product, service or company;
- a modified build is described as modified ("a fork of OpenFactory", "based on OpenFactory")
  and never as OpenFactory.

A fork may be redistributed under any name that is not confusingly similar. The Apache-2.0
licence grants every right to the code; it grants none to the mark, and a fork that ships with
the name still on it has stepped outside the licence's grant, not inside it.

## Certified OpenFactory: a build

A build is a distribution of the platform somebody ships: the project's own published images, a
partner's rebuild with a client's toolchain, a vendor's packaging for their platform, a fork that
wants to keep the name. Certification asserts that the build **behaves as the platform does on
the properties the suite checks** on the version named. The properties are the ones the project
has decided are the platform's identity, and a build that fails any of them is a different
product:

| property | how it is checked |
|---|---|
| the quality floor is non-negotiable: `test` and `security` required, an unmet floor holds the ticket before an agent runs, no switch exists | the public test suite's floor guards; `openfactory conformance <project>` on the reference project |
| the credential boundary: the container box receives the harness credential and `box.env` only; the worktree box strips the published names | the suite's environment guards; `SECURITY.md`'s derived table matches the code |
| the pipeline owns version control: the agent cannot push, open pull requests or merge; `.github/workflows/**` changes are reverted and listed | the suite's guards |
| production is a person's act: a named approver with a password; never from chat | the suite's guards |
| every refusal names a cause and a remedy; no silent stall | the refusal guards; `doctor` and `preflight` on the reference project |
| the provider axes and the entry-point group: every axis the build ships passes `conformance-adapter`; an unknown kind refuses by name | `openfactory conformance-adapter <kind> <target>` for every row the build ships |
| the CLI surface and the manifest schema of the version named | the suite's contract guards |
| the box proof and the pickup gate on the container box | `openfactory box prove` on the reference project |
| the whole loop runs: a card to a reviewed pull request on the one-machine door with the stub harness | `openfactory env rehearse --yes` transcript |

The suite is the platform's own public tests, run on the build, in both orders, plus the four
commands above on the reference project the program publishes. A build may **add** behaviour; it
may not **remove** or **weaken** any property in the table.

### The submission

A pull request to the public conformance repository (`openfactory-conformance`), one directory
per version and product:

```
v0.4/<vendor>-<product>/
├── PRODUCT.yaml        vendor, product, version, type (distribution | hosting | addon),
│                       website, documentation, contact, the platform version and commit
├── README.md           how to reproduce every result below on that product, step by step,
│                       so a stranger with the product can repeat it — instructions, not links
├── suite-fixed.xml     the public test suite, fixed order, JUnit
├── suite-random.xml    the public test suite, randomised order, JUnit
├── adapters.txt        `openfactory conformance-adapter` output for every row shipped
├── preflight.json      `openfactory preflight --json`
├── doctor.txt          `openfactory doctor <reference-project>`
├── conformance.txt     `openfactory conformance <reference-project>`
├── box-prove.txt       `openfactory box prove <reference-project>`
└── rehearse.txt        `openfactory env rehearse <reference-project> --yes` on the stub harness
```

One squashed commit; title `Conformance results for v0.4/<vendor>-<product>`; a signed
participation form on file ([template](templates/10-conformance-participation-form.md)); the
listing fee where one applies.

### The review

1. **The bot** checks within minutes: every file present and nothing else; every suite result
   green in both orders; every adapter row CONFORMANT; `doctor` and `conformance` green; the
   version in `PRODUCT.yaml` is in the certifiable window; the URLs answer. It labels the pull
   request or lists what failed.
2. **A program reviewer** checks within five business days: the participation form; the
   `README.md` actually reproduces (spot-checked on one product a month); the product's public
   description does not claim more than the certification asserts; any combination name is
   registered (below).
3. **Merge** is the certification. The product is listed on openfactory.digital with its
   version and date, and the vendor may use the mark from that day.

Free for open-source distributions and non-profits; for commercial products the annual listing
fee is the Certified Partner fee unless the vendor is already a partner, in which case nothing
more.

### Validity

A certification names a minor version. It holds for the later of **twelve months** after that
minor's release or **six months** after the next minor's release. The certifiable window is the
current minor and the one before it. A product stays certified without interruption if it
re-certifies on a newer minor at least once a year. A product that lets its certification lapse
removes the mark within thirty days and is moved to the archive list.

### Combination names

A certified hosting service or distribution may use a name of the form "<Vendor> OpenFactory
<Descriptor>" ("Acme OpenFactory Hosting") **only** while certified, only for the certified
offering, and only after registering the exact name on the participation form. The registered
name is listed publicly. It may not be a domain name or a company name.

## OpenFactory Certified Hosting: a service

A managed service is a build somebody runs for clients, so it certifies the build as above and
then the **service** against the [hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard):
one deployment per client organisation, the credential boundary kept between the provider and
the client, the client's data location and retention declared, the backup set exportable, the
panel behind identity, version currency, a tested restore, and a support tier of Premium or
above. The hosting audit is annual and is performed by the program or by an auditor it
designates; the service's public page states which version is certified and when the last audit
was.

## OpenFactory Compatible: an add-on

An add-on package certifies each row it declares with `openfactory conformance-adapter` on the
current and previous minor, submits the outputs and a `README.md` naming the rows, and is listed
as OpenFactory Compatible with the axes it covers. The listing carries the vendor's support
commitment (critical fixes within two business days, others within ten). The core never lists an
add-on inside its own documentation as anything but "an add-on package"; the compatible list is
where a deployment looks for one.

## People and companies

The person marks are granted by a passed examination and expire with the credential; the company
marks are granted by the partner list and expire with the tier. Neither is transferable. A
company may say "our engineers are OpenFactory Certified" only while the named engineers are, and
must say which credential.

## Enforcement

The program watches the marks the way it watches conformance: by reading. A misuse is met with a
written notice naming the use and the rule; thirty days to correct where correction is possible;
then the certification, tier or credential involved is revoked and the misuse listed. The
steward, and the foundation after it, retains the right to act on the marks in law, and the
partner agreement and the participation form say so once, in plain terms, so nobody meets it as
a surprise.

## What this policy does not do

It does not restrict the code, ever. It does not stop anyone forking, selling, hosting, modifying
or embedding the platform under another name. It does not make a partner's clients pay the
project anything. It defends one thing — that when somebody buys "OpenFactory", they get the
platform whose properties are in the table above — and it defends it with a test anyone can run.
