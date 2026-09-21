# The partner program: the companies

**Three tiers, five specialisations, one roster.** A partner is a company that implements,
hosts, supports, teaches or extends OpenFactory for clients and is counted, like every program in
the [market](research/partner-and-certification-programs.md) §1, in the **certified people it
employs**, the **deployments it can show**, and what it **gives back** to the project. The mark
"OpenFactory Certified Partner" is reserved by the [trademark policy](05-conformance-and-marks.md)
to companies on this program's public list, and to nobody else — a company that is merely a
member of a future foundation, or merely running the software, is not a partner and may not say
it is.

The program is run by the project's steward today and moves with the marks into the foundation
when one is formed ([07](07-sustainability.md)). Its rules apply identically to every company,
**including the steward's own commercial affiliates**: they hold the same tier by the same count,
pay the same fee, and appear on the same list. That neutrality is the program's whole value to the
next partner who joins.

## The tiers

| | **Registered** | **Certified Partner** | **Premier Partner** |
|---|---|---|---|
| who | any company that has registered and accepted the code of conduct | a company that has delivered at least one certified implementation | a company whose OpenFactory practice is a business line with a support desk and an upstream record |
| certified people (named roster) | none required | **3**, holding at least one OFCI and one OFCO, the third any credential above OFCA | **6**, holding at least two OFCI, two OFCO and one OFCSA, plus one OFCPO or OFCT |
| deployments it can show | none | **1** referenceable, attested at Standard profile or above, with the [evidence table](01-delivery-method.md#the-evidence-in-one-table) producible | **3** referenceable, at least one at Enterprise profile, across at least two client organisations |
| support | — | a named first line and a tier from the [standard](06-support-and-maintenance-standard.md) | a support desk audited against the standard, Premium or above |
| upstream | — | field defects reported with journals | a maintained contribution: an add-on listed as OpenFactory Compatible, or twelve merged pull requests in the trailing twelve months, or one sponsored maintainer-day per month |
| agreement | the code of conduct | the partner agreement and the trademark licence | the same, plus the premier addendum (audit, roadmap council) |
| annual fee (proposed) | none | USD 2,500 | USD 10,000 |
| purchasing-power tier | none | USD 1,250 | USD 5,000 |
| marks | "Powered by OpenFactory" | "OpenFactory Certified Partner" | "OpenFactory Premier Partner" |

The counts are the market's floor and not more: three certified people is where KCSP, GitLab's
PSP and Odoo's Silver all land, and six is Odoo's Gold. The fees sit in the band SMB-oriented
programs charge (Drupal's minimum USD 1,000, Odoo's USD 3,950, Adobe's USD 3,000 to 25,000) and
are the project's revenue, not a vendor's ([07](07-sustainability.md)).

**A person counts once.** The roster names each certified person with their credential number;
a person may be on one partner's roster at a time; the partner notifies the program within thirty
days when a rostered person leaves, and has ninety days to replace the count before the tier is
reviewed.

**A deployment is referenceable** when the client has signed an attestation
([template](templates/08-client-attestation.md)) that the implementation followed the method, the
profile claimed is the profile in place, and the program may contact them to verify. The
attestation is not a testimonial and the program never publishes it; it is a right to ask.

## The specialisations

A Certified or Premier partner may hold one or more. Each is listed beside the partner's name and
is where a client looks for the kind of help they need.

| specialisation | what it says | requirements beyond the tier | audited by |
|---|---|---|---|
| **Implementation** | the partner runs the method from assessment to go-live | the tier's own (every Certified Partner holds this) | the evidence table on one deployment a year |
| **Managed Hosting** | the partner runs deployments for clients as a service | the service holds the **OpenFactory Certified Hosting** conformance ([05](05-conformance-and-marks.md)); two OFCO on the roster; support at Premium or above; a DR test in the trailing twelve months; a client can export the backup set and leave within thirty days | a hosting audit every year against the [hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard) |
| **Support** | the partner sells support on deployments it did not necessarily implement | the support desk audited against the standard; a maintainer-escalation record; severities mapped to the platform's classes | the desk audit, and the ticket record's classes and remedies |
| **Training** (Authorised Training Partner) | the partner teaches the program's courses | at least one OFCT on the roster; the courseware licence; a public course page; student references from the first two deliveries; exams delivered through the program's platform | student evaluations and a delivery observed in the first year |
| **Technology** | the partner ships an add-on the core does not | the add-on listed as OpenFactory Compatible on the current and previous minor; a support commitment (critical fixes within two business days, others within ten) | the conformance listing, per release |

## What a partner gets

| benefit | Registered | Certified | Premier |
|---|---|---|---|
| listing in the public partner directory on openfactory.digital, by country and specialisation | name only | ● | ● first, with a profile page |
| the marks, under the trademark licence | Powered by | Certified Partner | Premier Partner |
| leads from the project's contact address and the directory, routed by region and specialisation, in rotation | – | ● | ● first in rotation |
| exam vouchers per year | – | 3 | 8 |
| training discount on the program's public courses | – | 20% | 40% |
| release candidates two weeks before the release, with the behaviour-change list | – | ● | ● |
| a maintainer escalation channel for defects found in the field, with a target first response | – | 5 business days | 2 business days |
| a seat on the roadmap council (quarterly; advisory; the technical decisions stay with the maintainers) | – | – | ● |
| co-marketing: a case study reviewed and published by the project; joint webinars | – | on request | ● twice a year |
| the partner's certified people listed on the verification page with the partner's name | – | ● | ● |

## What a partner owes

1. **The method.** Every implementation follows the [delivery method](01-delivery-method.md) on
   the profile it claims, and the evidence table can be produced on request. The program audits
   one deployment per partner per year, chosen by the program.
2. **Honesty about status.** What the platform does not do ([STATUS](../STATUS.md)) is told to
   the client before the design record is signed. A partner found selling a feature the status
   page says is not built loses the tier on the first finding.
3. **Upstream first.** A defect found in the field is reported upstream with the journal
   excerpt and the version. A fix a partner writes is proposed upstream before it is shipped to
   a second client. A partner may carry a private patch for one client while the upstream
   pull request is open; it may not maintain a divergent fork and call it OpenFactory
   ([05](05-conformance-and-marks.md)).
4. **The client's data.** A data processing agreement with every client; the credential
   boundary respected; `forget-conversations` honoured on request; the backup set exportable.
5. **The people.** Certified people named on the roster, kept current, and never shared between
   partners.
6. **The marks.** Used as the trademark licence says, and removed within thirty days of losing
   the tier.
7. **The fee.** Paid annually in advance; not refundable on revocation.
8. **The report.** A short annual report to the program: deployments in operation by profile,
   certified people, upstream contributions, support tickets by class. Aggregates are published
   by the program; nothing per client is.

## How a partner is verified

- **Application.** The [form](templates/09-partner-application.md): company, roster with
  credential numbers, the referenceable deployments with client attestations, the support tier,
  the specialisations sought, the signed agreement. Reviewed within fifteen business days; the
  program may ask to see the evidence table of one deployment before listing.
- **Annual renewal.** The report above; the roster re-verified against the credential registry;
  the deployment count re-attested; the fee. A Premier partner's support desk and one hosting
  deployment are audited in the renewal month.
- **Continuous.** Credentials expire on their own dates; a roster falling below the count starts
  the ninety-day clock automatically. A complaint from a client is investigated within thirty
  days and its outcome recorded.
- **Revocation.** For a breach of the agreement, the trademark licence or the code of conduct:
  written notice, thirty days to cure where a cure is possible, then removal from the list and
  the marks withdrawn. Misrepresenting the platform's capabilities, sharing rostered people, or
  misusing the marks after notice have no cure period. The list of revoked partners is public
  for one year.

## Who this is for, in plain terms

- **A two-person consultancy** registers for free, certifies both people (OFCO and OFCI), delivers
  one Standard-profile implementation with the method, gets the client's attestation, adds a
  third credential, and becomes a Certified Partner for USD 1,250 a year in a purchasing-power
  economy. The directory and the lead rotation then work for it.
- **A regional systems integrator** with a platform practice puts six people through the
  ladder, implements three deployments including one Enterprise, stands up a support desk to
  the standard, contributes an adapter for the tracker its clients use, and becomes a Premier
  Partner with the Technology and Support specialisations.
- **A hosting company** certifies its operators, passes the hosting conformance for its service,
  and holds the Managed Hosting specialisation, which is the only way to call a hosted service
  "OpenFactory Certified Hosting".
- **A training company** puts an instructor through OFCT, licenses the courseware, and becomes
  an Authorised Training Partner, delivering the program's courses and examinations in its
  region and language.
