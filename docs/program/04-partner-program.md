# Partner program

The OpenFactory Partner Program recognises companies that implement, host, support, teach or
extend OpenFactory for customers. Partners are listed in the public directory at
openfactory.digital and may use the partner marks under the
[trademark policy](05-conformance-and-marks.md). The terms "OpenFactory Certified Partner" and
"OpenFactory Premier Partner" are reserved for companies on that list.

The program is administered by the project's steward and transfers to the neutral holder
described in [07-sustainability.md](07-sustainability.md). All requirements apply equally to
every applicant, including companies affiliated with the steward.

## Tiers

| | Registered | Certified Partner | Premier Partner |
|---|---|---|---|
| Eligibility | Any company that registers and accepts the code of conduct | A company that has delivered at least one certified implementation | A company with an established OpenFactory practice, a support desk and an upstream contribution record |
| Certified staff on the roster | None | 3, including at least one OFCI and one OFCO; the third holds any certification above OFCA | 6, including at least two OFCI, two OFCO and one OFCSA, plus one OFCPO or OFCT |
| Referenceable deployments | None | 1, attested at Standard profile or above, with the method's evidence available | 3, at least one at Enterprise profile, across at least two customer organisations |
| Support | – | A named first line and a tier from the [standard](06-support-and-maintenance-standard.md) | A support desk audited against the standard, Premium tier or above |
| Upstream contribution | – | Field defects reported with journal excerpts | One of: an add-on listed as OpenFactory Compatible; twelve merged pull requests in the trailing twelve months; one sponsored maintainer-day per month |
| Agreement | Code of conduct | Partner agreement and trademark licence | Partner agreement, trademark licence and Premier addendum (audit, roadmap council) |
| Annual fee (proposed) | None | USD 2,500 | USD 10,000 |
| Reduced fee (lower-middle and upper-middle income economies) | None | USD 1,250 | USD 5,000 |
| Marks | "Powered by OpenFactory" | "OpenFactory Certified Partner" | "OpenFactory Premier Partner" |

Headcounts follow common practice (see [research](research/partner-and-certification-programs.md),
section 1.3): three certified engineers is the usual floor for a services designation. Fees are
within the range charged by comparable SMB-oriented programs.

### Roster rules

- Each certified person is listed with their certificate number.
- A person may appear on one partner's roster at a time.
- The partner notifies the program within 30 days when a rostered person leaves, and has 90 days
  to restore the required headcount before the tier is reviewed.

### Referenceable deployments

A deployment is referenceable when the customer has signed the
[client attestation](templates/08-client-attestation.md). The attestation confirms that the
implementation followed the method, that the profile claimed is in place, and that the program
may contact the customer to verify. The program does not publish attestations.

## Specialisations

Certified and Premier partners may hold one or more specialisations. Specialisations appear in
the directory.

| specialisation | scope | additional requirements | audit |
|---|---|---|---|
| Implementation | Delivery of the method from assessment to go-live | None beyond the tier (held by every Certified Partner) | Evidence review of one deployment per year |
| Managed Hosting | Operating deployments for customers as a service | The service holds OpenFactory Certified Hosting ([05](05-conformance-and-marks.md)); two OFCO on the roster; Premium support or above; a DR test in the trailing twelve months; customer data exportable within 30 days | Annual hosting audit against the [hosting standard](06-support-and-maintenance-standard.md#the-hosting-standard) |
| Support | Support contracts on deployments the partner may not have implemented | Support desk audited against the standard; maintainer-escalation record; severities mapped to the platform's failure classes | Desk audit; ticket record review |
| Training (Authorised Training Partner) | Delivery of the program's courses and exams | At least one OFCT on the roster; courseware licence; public course page; participant references from the first two deliveries; exams delivered through the program's platform | Participant evaluations; one observed delivery in the first year |
| Technology | An add-on package the core does not ship | The add-on listed as OpenFactory Compatible on the current and previous minor release; a support commitment (critical fixes within two business days, others within ten) | Conformance listing per release |

## Benefits

| benefit | Registered | Certified | Premier |
|---|---|---|---|
| Directory listing by country and specialisation | Name only | Yes | Yes, listed first, with a profile page |
| Partner marks under the trademark licence | Powered by | Certified Partner | Premier Partner |
| Leads from the project's contact address and directory, routed by region and specialisation in rotation | – | Yes | Yes, first in rotation |
| Exam vouchers per year | – | 3 | 8 |
| Discount on the program's public courses | – | 20% | 40% |
| Release candidates two weeks before release, with the behaviour-change list | – | Yes | Yes |
| Maintainer escalation channel for field defects, target first response | – | 5 business days | 2 business days |
| Roadmap council seat (quarterly, advisory) | – | – | Yes |
| Co-marketing: reviewed case studies, joint webinars | – | On request | Twice a year |
| Certified staff listed on the verification page with the partner's name | – | Yes | Yes |

## Obligations

1. **Method.** Every implementation described as certified follows the
   [delivery method](01-delivery-method.md) at the claimed profile. The evidence listed in the
   method is available on request. The program audits one deployment per partner per year.
2. **Accuracy.** Customers are told before the design record is signed what the platform does
   not do, as published in [STATUS.md](../STATUS.md). Selling a capability the status page lists
   as not built results in loss of tier on the first finding.
3. **Upstream first.** Field defects are reported upstream with journal excerpts and version.
   Fixes are proposed upstream before being shipped to a second customer. A partner may carry a
   private patch for one customer while the upstream pull request is open. A partner may not
   maintain a divergent fork under the OpenFactory name ([05](05-conformance-and-marks.md)).
4. **Customer data.** A data processing agreement with every customer. The credential boundary
   respected. `forget-conversations` honoured on request. The backup set exportable.
5. **Roster.** Certified staff named, kept current, and not shared between partners.
6. **Marks.** Used as the trademark licence specifies. Removed within 30 days of losing the tier.
7. **Fee.** Paid annually in advance. Not refundable on revocation.
8. **Annual report.** Deployments in operation by profile, certified staff, upstream
   contributions, support tickets by class. The program publishes aggregates only.

## Application and verification

**Application.** Submit the [partner application](templates/09-partner-application.md): company
details, roster with certificate numbers, referenceable deployments with client attestations,
support tier, specialisations requested, signed agreement. The program reviews within fifteen
business days and may request the evidence for one deployment before listing.

**Annual renewal.** The annual report, roster re-verified against the certificate registry,
deployment count re-attested, fee paid. Premier partners' support desks and one hosting
deployment are audited during the renewal month.

**Continuous.** Certifications expire on their own dates. A roster that falls below the required
headcount starts the 90-day clock. Customer complaints are investigated within 30 days and the
outcome recorded.

**Revocation.** For breach of the agreement, the trademark licence or the code of conduct: written
notice, 30 days to cure where possible, then removal from the directory and withdrawal of the
marks. No cure period for misrepresenting platform capabilities, sharing rostered staff, or
using the marks after notice. Revoked partners are listed for one year.

## Examples

- A two-person consultancy registers free, certifies both people (OFCO and OFCI), delivers one
  Standard-profile implementation with a client attestation, adds a third certification and
  applies as a Certified Partner.
- A regional systems integrator certifies six people, delivers three deployments including one
  Enterprise, stands up a support desk to the standard, contributes a tracker adapter, and
  applies as a Premier Partner with the Technology and Support specialisations.
- A hosting company certifies its operators, passes hosting conformance for its service, and
  holds the Managed Hosting specialisation, which is required to use the name "OpenFactory
  Certified Hosting".
- A training company puts an instructor through OFCT, licenses the courseware, and becomes an
  Authorised Training Partner.
