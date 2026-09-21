# How the project funds itself, and where it is going

**The code stays free. The project earns from the things that only the project can grant:
certification, conformance, the partner list, the courseware, and membership in what it
becomes.** This page is the project's own revenue model, distinct from any partner's, and it is
public because a partner deciding to invest in a certification needs to know who runs it, how it
is paid for, and what happens to it if the steward changes.

## The principle: two entities, one line between them

| the project (OpenFactory) | a partner (any company, the steward's affiliates included) |
|---|---|
| owns the marks, the conformance suite, the certification bank, the courseware, the partner list | owns its client contracts, its people, its prices |
| earns from certifying, conforming, listing, licensing courseware, and membership | earns from projects, hosting, support, training delivery, add-ons |
| never sells services to end clients | never grants a mark or a credential |
| decides the platform's roadmap through its maintainers | advises through the roadmap council |

The steward today is the company that wrote the platform, and that company also intends to be
a partner. The line above is what keeps that honest: the partner side of that company pays the
same fees, meets the same counts and appears on the same list as everyone else; the project side
publishes its rules, its prices and its aggregates; and the two are separated in law when the
foundation forms. The [conflict-of-interest rules](#conflict-of-interest) below apply from the
first day, not from the foundation's.

## What stays free, forever

- the platform, under Apache-2.0, with every feature: there is no enterprise edition and no
  feature gated behind a fee ([core/07-extensibility.md](../core/07-extensibility.md) §2 is the
  rule that the open build is never hobbled);
- the documentation, including this program's;
- the conformance suite and the right to run it;
- community support through the public tracker;
- descriptive use of the name ("Powered by OpenFactory");
- conformance listing for open-source distributions and non-profits.

## The revenue lines

| line | who pays | proposed price | what it funds | market reference |
|---|---|---|---|---|
| **certification examinations** | individuals, partners, employers | USD 150–500 per sitting, half in purchasing-power economies ([03](03-role-certifications.md)) | the exam platform, proctoring, the item bank, grading | Linux Foundation training and certification is ~10% of its revenue; CKA USD 445, RHCSA USD 500 |
| **partner program fees** | Certified and Premier partners | USD 2,500 / 10,000 a year, half in purchasing-power economies ([04](04-partner-program.md)) | the directory, lead routing, audits, the escalation channel, the release-candidate channel | Odoo USD 3,950; Drupal minimum USD 1,000; Adobe USD 3,000–25,000 |
| **conformance listing** | commercial distributions and hosting services that are not partners | the Certified Partner fee, annually | the conformance repository, the bot, the reviewers, the hosting audits | CNCF: free for members, a fee equal to membership for others |
| **courseware licence** | Authorised Training Partners | 15% of course revenue, or a per-seat licence of USD 60 per student, whichever the partner chooses annually | the courses' upkeep against every release, the labs | training-partner royalties are gated in every program surveyed; 15% is the marketplace norm |
| **examination delivery through partners** | training partners reselling exam seats | the partner keeps 20% of the exam fee | the same as examinations | CNCF training partners resell the CKA |
| **membership** (from the foundation) | companies that want a seat at the table | proposed bands: Silver USD 5,000, Gold USD 25,000, Platinum USD 100,000 a year, with a headcount discount for small companies | maintainers' time, infrastructure, the programs above | CNCF Silver USD 10k–100k by headcount; Eclipse working groups €4k–260k by revenue; LF Silver USD 5k–20k |
| **sponsored development** | a company that needs a feature or an axis the core lacks | at the maintainers' rate, on the public roadmap, merged upstream | the feature, for everyone | OpenTofu and Valkey are funded this way |
| **events** | attendees, sponsors | at cost in the first years | the community | events are 19% of LF revenue at scale |

What the project does **not** do: sell hosting, sell support, sell implementation, sell a
proprietary edition, or take a share of a partner's client revenue. Odoo's 10–20% commission
model exists because Odoo sells subscriptions; this project has none to commission. Acquia's
"2% of partner revenue to the project" is the nearest thing, and the program prefers the fixed
partner fee: predictable for a small partner, and not a reason to under-report.

## A first-year picture

Not a forecast — the arithmetic of the prices above at plausible counts, so the size of the
program is legible:

| line | count | revenue |
|---|---|---|
| examinations | 200 sittings, blended USD 250 | USD 50,000 |
| Certified Partners | 8, blended USD 1,900 | USD 15,000 |
| Premier Partners | 2 | USD 20,000 |
| courseware licence | 10 courses delivered, USD 8,000 average | USD 12,000 |
| conformance listings | 2 non-partner vendors | USD 5,000 |
| **total** | | **≈ USD 100,000** |

Against it: the exam platform and proctoring (USD 15–25 per sitting), a digital-badge service
(a few thousand a year), the program's reviewers and graders (the largest line), the bot, the
directory pages. The program is designed to be **self-funding at this scale and to grow with the
partner count**, not to fund the platform's development on its own. Development is funded by the
steward now and by membership and sponsored work later, which is why the foundation is the
destination and not a formality.

## The foundation path

Three phases, each triggered by a fact rather than a date:

| phase | trigger | what changes |
|---|---|---|
| **1 · Stewardship** (now) | the program's adoption | the steward runs the program by these documents; the marks are registered in the steward's name with a public commitment to assign them; a program committee of three (one maintainer, one partner not affiliated with the steward, one end user) approves fee changes and adjudicates appeals; the conflict-of-interest rules apply |
| **2 · A neutral holder** | a second partner of scale, or the first hosting certification by a company other than the steward | the marks, the conformance suite, the certification bank and the courseware are assigned to a neutral legal holder: a Dutch stichting or a US 501(c)(6) formed for the purpose, or a programme under an existing fiscal host (the Commons Conservancy holds assets at no cost; the Open Source Collective handles money at 10%). Program revenue flows to the holder; the steward is one member. The [research](research/oss-monetization-and-market.md) §4 has the costs |
| **3 · A foundation with members** | three independent companies willing to pay Gold membership, or a project of a size that a Linux Foundation directed fund would take | membership bands; a governing board (funding) separate from the technical steering committee (maintainers); the programs run by staff; a Linux Foundation home considered when the members want it, with the trademark assignment it requires |

What the steward keeps in every phase: its own add-on packages, its own hosting and services
business, its partner tier earned like anyone else's. What it gives up at phase 2: the marks, the
programs' revenue, and the right to change these rules alone.

## Governance

- **The maintainers** decide what the platform is. The technical decisions are theirs and are
  recorded in the ADRs. The program never overrides them, and a partner's roadmap council is
  advisory.
- **The program committee** decides the program's rules: fees, counts, blueprints, the
  conformance table. Three seats in phase 1 as above; a board in phase 3. Its minutes are
  public.
- **The certification board**: the item-bank authors and graders, who are OFCT or maintainers
  and are never employed by the partner whose candidate they grade.
- **Appeals**: any decision of the program (a failed examination, a refused application, a
  revocation) can be appealed to the committee within thirty days; the outcome is written.
- **Transparency**: the fee schedule, the partner list, the certified-product list, the
  aggregate numbers (credentials issued, partners by tier, conformance submissions) are
  published annually. Nothing per client is.

## Conflict of interest

Because the steward is also a partner, these rules are in force from the program's first day:

1. A person grading an examination or auditing a partner does not grade or audit their own
   employer's candidates or deployments.
2. Leads that reach the project (the contact address, the directory) are routed by region and
   specialisation in rotation; the steward's partner side is one entry in the rotation and is
   not first.
3. The steward's partner side is listed with the same information as every other partner and
   pays the same fee, and its tier is published with the same evidence.
4. Fee changes, count changes and blueprint changes require the program committee, in which the
   steward holds one seat of three.
5. Any add-on the steward sells is listed as OpenFactory Compatible by the same submission as
   anyone else's, and the core's documentation never names it as more than "an add-on package"
   ([ADR-0038](../adr/0038-the-platform-is-complete-channels-are-add-ons.md)).
6. The program's accounts are separate from the steward's services accounts from the first
   invoice, so that the assignment at phase 2 is a transfer and not an audit.
