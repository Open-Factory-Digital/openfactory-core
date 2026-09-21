# Sustainability and governance

This document describes how the OpenFactory project is funded, what remains free, how the program
is governed, and the path to a foundation. It is public so that anyone investing in a
certification or a partner tier can see who runs the program, how it is paid for, and what
happens to it if the steward changes.

## Separation between the project and partners

| the project | a partner (any company, including the steward's affiliates) |
|---|---|
| Owns the marks, the conformance suite, the exam item bank, the courseware and the partner directory | Owns its customer contracts, staff and prices |
| Earns from certification, conformance listings, partner fees, courseware licences and membership | Earns from implementation, hosting, support, training delivery and add-ons |
| Does not sell services to end customers | Does not grant marks or certifications |
| Sets the roadmap through its maintainers | Advises through the roadmap council |

The steward is currently the company that wrote the platform, and that company also intends to
operate as a partner. The rules below apply from the first day of the program, not from the
formation of a foundation.

## What remains free

- The platform under Apache-2.0, with all features. There is no enterprise edition and no
  feature behind a fee ([core/07-extensibility.md](../core/07-extensibility.md), section 2).
- The documentation, including the program documents.
- The conformance suite and the right to run it.
- Community support through the public issue tracker.
- Descriptive use of the name ("Powered by OpenFactory").
- Conformance listing for open-source distributions and non-profits.

## Revenue lines

| line | payer | proposed pricing | funds | reference |
|---|---|---|---|---|
| Certification exams | Individuals, partners, employers | USD 150–500 per sitting; reduced fee in lower-middle and upper-middle income economies ([03](03-role-certifications.md)) | Exam platform, proctoring, item bank, grading | Training and certification is about 10% of Linux Foundation revenue; CKA USD 445; RHCSA USD 500 |
| Partner program fees | Certified and Premier partners | USD 2,500 / 10,000 per year; reduced fee available ([04](04-partner-program.md)) | Directory, lead routing, audits, escalation channel, release-candidate distribution | Odoo USD 3,950; Drupal minimum USD 1,000; Adobe USD 3,000–25,000 |
| Conformance listing | Commercial distributions and hosting services that are not partners | Equal to the Certified Partner fee, annually | Conformance repository, automated checks, reviewers, hosting audits | CNCF: free for members; non-members pay a fee equal to membership |
| Courseware licence | Authorised Training Partners | 15% of course revenue, or USD 60 per participant, at the partner's annual election | Course maintenance per release; labs | Training-partner royalties in all programs surveyed; 15% is a common marketplace rate |
| Exam resale | Training partners | Partner retains 20% of the exam fee | Same as exams | CNCF training partners resell the CKA |
| Membership (from the foundation phase) | Companies seeking governance participation | Proposed: Silver USD 5,000; Gold USD 25,000; Platinum USD 100,000 per year; headcount discount for small companies | Maintainer time, infrastructure, the programs above | CNCF Silver USD 10k–100k by headcount; Eclipse working groups EUR 4k–260k by revenue |
| Sponsored development | Companies needing a feature or axis the core lacks | At the maintainers' rate; on the public roadmap; merged upstream | The feature | OpenTofu and Valkey funding model |
| Events | Attendees and sponsors | At cost initially | Community | Events are about 19% of Linux Foundation revenue |

The project does not sell hosting, support, implementation or a proprietary edition, and does not
take a share of partner customer revenue. The fixed partner fee is preferred over a revenue
share: it is predictable for small partners and does not create an incentive to under-report.

## Illustrative first-year scale

Not a forecast. The arithmetic of the proposed prices at plausible counts:

| line | count | revenue (USD) |
|---|---|---|
| Exams | 200 sittings at a blended USD 250 | 50,000 |
| Certified Partners | 8 at a blended USD 1,900 | 15,000 |
| Premier Partners | 2 | 20,000 |
| Courseware licences | 10 deliveries at USD 8,000 average | 12,000 |
| Conformance listings | 2 non-partner vendors | 5,000 |
| Total | | about 100,000 |

Costs: exam platform and proctoring (USD 15–25 per sitting), a badge service, reviewers and
graders (the largest line), automation, directory pages. The program is designed to be
self-funding at this scale. Platform development is funded by the steward now and by membership
and sponsored development later.

## Foundation path

| phase | trigger | changes |
|---|---|---|
| 1. Stewardship (current) | Adoption of the program | The steward runs the program under these documents. The marks are registered in the steward's name with a public commitment to assign them. A program committee of three (one maintainer, one partner not affiliated with the steward, one end user) approves fee changes and hears appeals. The conflict-of-interest rules apply. |
| 2. Neutral holder | A second partner of comparable scale, or the first hosting certification by a company other than the steward | The marks, conformance suite, item bank and courseware are assigned to a neutral legal holder: a Dutch stichting or a US 501(c)(6) formed for the purpose, or a programme under an existing fiscal host (see [research](research/oss-monetization-and-market.md), section 4). Program revenue flows to the holder. The steward is one member. |
| 3. Foundation with members | Three independent companies willing to pay Gold membership, or a project of a size that a Linux Foundation directed fund would accept | Membership bands. A governing board (funding) separate from the technical steering committee (maintainers). Programs run by staff. A Linux Foundation home considered when members want it, including the required trademark assignment. |

In every phase the steward keeps its own add-on packages, its own services business, and a
partner tier earned under the same rules as any other company. At phase 2 it gives up the marks,
the program revenue and the ability to change these rules alone.

## Governance

- **Maintainers** decide what the platform is. Technical decisions are recorded in the ADRs. The
  program does not override them. The roadmap council is advisory.
- **Program committee** decides program rules: fees, headcounts, exam domains, the conformance
  table. Three seats in phase 1 as above; a board in phase 3. Minutes are public.
- **Certification board**: item-bank authors and graders, who are OFCT holders or maintainers and
  are never employed by the partner whose candidate they grade.
- **Appeals**: any program decision (failed exam, refused application, revocation) may be
  appealed to the committee within 30 days. Outcomes are written.
- **Transparency**: the fee schedule, partner list, certified-product list and aggregate figures
  (certifications issued, partners by tier, conformance submissions) are published annually.
  Nothing per customer is published.

## Conflict of interest

Because the steward also operates as a partner, the following rules apply from the program's
first day:

1. No one grades exams or audits deployments for their own employer.
2. Leads that reach the project are routed by region and specialisation in rotation. The
   steward's partner business is one entry in the rotation and is not placed first.
3. The steward's partner business is listed with the same information, pays the same fee, and
   has its tier published with the same evidence as every other partner.
4. Changes to fees, headcounts or exam domains require the program committee, in which the
   steward holds one of three seats.
5. Add-ons sold by the steward are listed as OpenFactory Compatible through the same submission
   as anyone else's. The core documentation refers to them only as add-on packages
   ([ADR-0038](../adr/0038-the-platform-is-complete-channels-are-add-ons.md)).
6. Program accounts are kept separate from the steward's services accounts from the first
   invoice, so that the phase 2 assignment is a transfer rather than an audit.
