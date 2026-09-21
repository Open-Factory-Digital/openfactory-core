# Conformance and trademark policy

This document defines the OpenFactory marks, who may use them, and the conformance program
through which builds, hosted services and add-ons qualify. It implements the rule stated in
[NOTICE](../../NOTICE): the code is licensed under Apache-2.0; the name and marks are not, and
are reserved for what passes the published conformance requirements. The structure follows the
Kubernetes conformance program (see [research](research/partner-and-certification-programs.md),
section 2): self-tested, submitted in public, reviewed, valid per version, refreshed annually.

## Marks

| mark | applies to | granted by | meaning |
|---|---|---|---|
| OpenFactory (word mark and logo) | The project | Owned by the steward; to be assigned to the neutral holder | The platform published from the project's repositories |
| Powered by OpenFactory | Anyone | No application required; descriptive-use rules below | The product or service runs the platform, unmodified or conformant |
| Certified OpenFactory | A build or distribution | A passed conformance submission | The build behaves as the platform does on the checked properties, on the named version |
| OpenFactory Certified Hosting | A managed service | A passed conformance submission plus the hosting audit | The service runs a Certified OpenFactory build to the [hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard) |
| OpenFactory Compatible | An add-on package | A passed `conformance-adapter` submission | The package's rows satisfy their ports on the named version |
| OpenFactory Certified Partner, OpenFactory Premier Partner | A company | The [partner program](04-partner-program.md) | The company is on the public partner list at that tier |
| OpenFactory Certified Associate, Operator, Implementer, Solution Architect, Product Owner, Developer, Trainer | A person | The [certification program](03-role-certifications.md) | The person holds an unexpired certification |

No other combinations are granted. "OpenFactory Certified" alone, "OpenFactory Enterprise",
"OpenFactory Cloud", "OpenFactory Gold Partner", "Official OpenFactory" and similar forms may not
be used.

## Descriptive use

Anyone may state that a product, service or company uses, runs, integrates with, supports or is
built on OpenFactory, and may use the phrase "Powered by OpenFactory" and the Powered-by logo,
subject to the following:

1. The name is written in full and unaltered. The logo is not recoloured, cropped or combined
   with another mark.
2. The mark is not part of the product, service or company name, domain name, social media
   handle or application title.
3. The first use on a page links to openfactory.digital, and the page carries the attribution
   "OpenFactory is a trademark of [the steward or holder]".
4. Nothing implies that the project endorses, certifies or audits the product, service or
   company.
5. A modified build is described as modified ("a fork of OpenFactory", "based on OpenFactory")
   and not as OpenFactory.

A fork may be redistributed under any name that is not confusingly similar. The Apache-2.0
licence grants rights to the code and no rights to the marks.

## Certified OpenFactory (builds)

A build is any distribution of the platform: the project's published images, a partner's rebuild
with a customer toolchain, a vendor's packaging, or a fork that wants to keep the name.
Certification asserts that the build preserves the following properties on the named version.
A build may add behaviour. It may not remove or weaken any property in this table.

| property | check |
|---|---|
| The quality floor is non-negotiable: `test` and `security` required; an unmet floor holds the ticket before an agent runs; no disable switch | Public test suite floor guards; `openfactory conformance <project>` on the reference project |
| Credential boundary: the container box receives the harness credential and `box.env` only; the worktree box strips the published names | Suite environment guards; the derived table in `SECURITY.md` matches the code |
| The pipeline controls version control: the agent cannot push, open pull requests or merge; `.github/workflows/**` changes are reverted and listed | Suite guards |
| Production release requires a named approver with a password; never from chat | Suite guards |
| Every refusal names a cause and a remedy; no silent stalls | Refusal guards; `doctor` and `preflight` on the reference project |
| Provider axes and entry-point group: every shipped axis passes `conformance-adapter`; unknown kinds refuse by name | `openfactory conformance-adapter <kind> <target>` for every shipped row |
| CLI surface and manifest schema of the named version | Suite contract guards |
| Box proof and pickup gate on the container box | `openfactory box prove` on the reference project |
| End-to-end loop: a card to a reviewed pull request on the one-machine door with the stub harness | `openfactory env rehearse --yes` transcript |

### Submission

Open a pull request against the public conformance repository (`openfactory-conformance`) with
one directory per version and product:

```
v0.4/<vendor>-<product>/
├── PRODUCT.yaml        vendor, product, version, type (distribution | hosting | addon),
│                       website, documentation, contact, platform version and commit
├── README.md           step-by-step instructions to reproduce every result below on the product
├── suite-fixed.xml     public test suite, fixed order, JUnit format
├── suite-random.xml    public test suite, randomised order, JUnit format
├── adapters.txt        `openfactory conformance-adapter` output for every shipped row
├── preflight.json      `openfactory preflight --json`
├── doctor.txt          `openfactory doctor <reference-project>`
├── conformance.txt     `openfactory conformance <reference-project>`
├── box-prove.txt       `openfactory box prove <reference-project>`
└── rehearse.txt        `openfactory env rehearse <reference-project> --yes` with the stub harness
```

Requirements:

- One squashed commit. Title: `Conformance results for v0.4/<vendor>-<product>`.
- A signed [participation form](templates/10-conformance-participation-form.md) on file.
- The listing fee, where applicable.

### Review

1. **Automated checks** (minutes): all required files present and no others; suite results green
   in both orders; every adapter row CONFORMANT; `doctor` and `conformance` green; the version in
   `PRODUCT.yaml` is within the certifiable window; URLs resolve. Failures are listed on the pull
   request.
2. **Program review** (within five business days): participation form on file; `README.md`
   reproduction spot-checked on one product per month; the product's public description does not
   exceed what certification asserts; any combination name is registered.
3. **Merge** constitutes certification. The product is listed on openfactory.digital with its
   version and date. The mark may be used from that date.

### Fees

Free for open-source distributions and non-profits. Commercial products pay an annual listing fee
equal to the Certified Partner fee, unless the vendor is already a partner.

### Validity

- A certification names a minor version. It is valid until the later of twelve months after
  that minor's release or six months after the next minor's release.
- The certifiable window is the current minor and the previous one.
- A product remains continuously certified if it re-certifies on a newer minor at least once a
  year.
- After a lapse, the mark must be removed within 30 days and the product moves to the archive
  list.

### Combination names

A certified hosting service or distribution may use a name of the form
"<Vendor> OpenFactory <Descriptor>" (for example "Acme OpenFactory Hosting") only while
certified, only for the certified offering, and only after registering the exact name on the
participation form. Registered names are published. A combination name may not be used as a
domain name or company name.

## OpenFactory Certified Hosting (services)

A managed service certifies its build as above, then certifies the service against the
[hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard): one deployment
per customer organisation, the credential boundary maintained between provider and customer,
declared data location and retention, exportable backup set, panel behind identity, version
currency, tested restore, and Premium support or above. The hosting audit is annual and is
performed by the program or an auditor it designates. The service's public page states the
certified version and the date of the last audit.

## OpenFactory Compatible (add-ons)

An add-on package submits `openfactory conformance-adapter` output for each declared row on the
current and previous minor, plus a `README.md` naming the rows. It is listed as OpenFactory
Compatible with the axes it covers and the vendor's support commitment (critical fixes within two
business days, others within ten). The core's documentation refers to add-ons generically; the
Compatible list is where deployments find them.

## People and companies

Person marks are granted by a passed exam and expire with the certification. Company marks are
granted by the partner list and expire with the tier. Neither is transferable. A company may
state that its engineers are OpenFactory Certified only while the named engineers hold valid
certifications, and must name the certification.

## Enforcement

Misuse of a mark results in a written notice identifying the use and the rule, 30 days to
correct where correction is possible, then revocation of the related certification, tier or
credential, and publication of the misuse. The steward, and the holder after it, retains the
right to enforce the marks at law. The partner agreement and the participation form state this.

## Scope

This policy does not restrict the code. Anyone may fork, sell, host, modify or embed the
platform under another name. It does not require a partner's customers to pay the project. It
protects one thing: that a product called OpenFactory has the properties in the table above,
verified by a test anyone can run.
