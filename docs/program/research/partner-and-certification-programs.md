# Market references: partner, certification and conformance programs

Research notes compiled on 2026-09-21 as input to the OpenFactory program. Each figure cites its
source; rows where the primary page could not be opened say so. These notes are reference
material, not program rules. Vendor products are named because they are the subject of the
survey; in OpenFactory a cloud is an add-on and a chat tool a connector, not part of the core
([ADR-0040](../../adr/0040-the-core-runs-on-the-clients-own-machines.md)).

Method: web search plus fetching of primary sources where reachable (github.com, gitlab.com,
eclipse.org, apache.org, hashicorp.com, ubuntu.com). Several vendor domains (redhat, odoo, cncf.io,
linuxfoundation.org, nextcloud, camunda, elastic, drupal.org, typo3.org, temporal.io) could not be
opened directly, so those facts come from search snippets of the primary page or secondary sources
and are marked. "Unverified" means no primary source could be opened.

---

## 1. Partner program structures

### 1.1 Comparison table

| Program | Tiers | Entry requirements (key numbers) | Fees | Verification / revocation | Sources |
|---|---|---|---|---|---|
| **Red Hat Partner Program** (Partner Connect, revamped 2024/25) | Ready → Advanced → Premier, global and uniform across routes | Tier = activity **points** accrued per calendar year (sales/marketing/technical/admin "modules") + minimum trained personnel. Personnel minima reported: Ready 2 Seller credentials / 0 Technical Seller / 0 Red Hat Certifications; Advanced 3 / 2 / 1; Premier 6 / 4 / 2 (from a 2025 program-update deck; point thresholds "up to 25,000" not confirmed) | None published (program is free; tier drives discounts/rebates) | Points recalculated each calendar year; tier badge issued via Credly | [FAQ](https://connect.redhat.com/en/programs/faq), [2026 blog](https://connect.redhat.com/en/blog/clear-path-to-partner-success-2026), [deck](https://www.scribd.com/document/865840710/Red-Hat-Partner-Program-updates) |
| **Odoo** | Learning Partner → Ready → Silver → Gold | Three metrics: new Enterprise users sold/yr, **certified resources**, customer retention. Ready: ≥10 new users, **1 certified**, 1 official training; Silver: ≥75 users, **3 certified**, 70% retention, 2 trainings; Gold: ≥300 users (older sources say 150), **6 certified**, 80% retention. Learning Partner: 0 certified | **Learning US$990/yr; Ready/Silver/Gold US$3,950/yr** (annual, non-refundable) | Commission on Enterprise licences 10% / 15% / 20%. Certifications are personal; partner must notify Odoo when certified staff join/leave. Agreement terminable on 30-day unremedied breach; post-termination partner must stop using the brand | [become-a-partner](https://www.odoo.com/become-a-partner), [agreement v19](https://www.odoo.com/documentation/19.0/legal/terms/partnership.html), [ERP Research](https://www.erpresearch.com/en-us/odoo-partners) |
| **Elastic** | Select → Premier → Elite (2023 relaunch) | Placement based on **certified engineers and delivered engagements**; monthly partner scorecard. Exact counts not public | Not published | Scorecard reviewed monthly | [Elastic blog](https://www.elastic.co/blog/elastic-partner-program-supporting-customers) |
| **GitLab** (handbook is public) | Open track; Select track (invite only); "Premier" is a label for top Select partners; plus PSP and MSP designations | Open: 2× Professional Sales Accreditation + 1× Solutions Architect Verified Associate; no revenue minimum. Select: **US$300K Net ARR OR PSP designation**, 4× sales accred., 2× SA Verified Associate, **1× GitLab Certified Services Engineer (PSE)**, joint business plan. **PSP: ≥3 PSEs** and avg 2 service-attach registrations/quarter. MSP: Select + PSP + 8×5 support | No fee | **PSP annual audit**: ≥8 service-attach / managed-service registrations with proof of execution in trailing 12 months | [Channel Program Guide](https://handbook.gitlab.com/handbook/resellers/channel-program-guide/), [MSP blog](https://about.gitlab.com/blog/introducing-the-gitlab-managed-service-provider-msp-partner-program/) |
| **HashiCorp Partner Network** | SI program: 3 tiers; Reseller: 2 tiers; plus **Competency** badges | Tier driven by counts of certifications (numbers gated) | Not published | Guide gated | [SI competency](https://www.hashicorp.com/en/systems-integrator-competency-program) |
| **Camunda** | Silver → Gold → Platinum | Camunda 8 Certified Professional exam **available only to Enterprise customers and partners**, US$200 per attempt. Per-tier counts not public | Not published | Not public | [become-a-partner](https://camunda.com/become-a-partner/), [certification](https://academy.camunda.com/page/certification) |
| **Mattermost** | Not tiered: Authorized Reseller, Value-Added Reseller (tier-1/2 support in local language), Deployment Solutions Partner | VAR: online training + local support process → discount; **≥2 years operating history** | None | — | [Handbook](https://handbook.mattermost.com/operations/sales/partner-programs) |
| **Nextcloud** (Sept 2025 guide) | Silver → Gold → Platinum, **by annual revenue commitment**: Silver <€100k, Gold up to €500k, Platinum >€500k | All tiers: portfolio access, engineer support, certifications | Not published | Not public | [Program page](https://nextcloud.com/channel-partner-program/) |
| **SUSE One** | Sapphire → Emerald → Diamond, plus specializations | Advancement = training + certification requirements | None stated | Annual | [SUSE partners](https://www.suse.com/partners/) |
| **Canonical** | Affiliate → Silver → Gold; tracks incl. Training | Qualitative | Not published | — | [canonical.com/partners](https://canonical.com/partners) |
| **Grafana Labs** | Tracks (Reseller, Consulting, MSP, Technology); Grafana Champions for individuals | Deal incentives, NFR keys, education | Not published | — | [Channel page](https://grafana.com/partnerships/channel/) |
| **Temporal** | No public tiers; partners page lists SIs, a "certified training partner", a "certified cloud partner"; **experts.temporal.io** directory | Apply by email | None public | — | [temporal.io/partners](https://temporal.io/partners) |
| **Drupal Certified Partner** (Drupal Association, 2024) | Bronze 150 → Silver 500 → Gold 1,000 → Platinum 2,500 → Diamond 5,000 → Top Tier 12,000 **contribution credits, trailing 12 months** | Min 150 credits/yr + annual survey + **annual financial contribution scaled to headcount, min US$1,000/yr** | Min US$1,000/yr | Credits computed continuously from drupal.org; tier moves automatically; 101 agencies (2025) | [Program page](https://new.drupal.org/association/become-a-drupal-certified-partner) |
| **Adobe Solution Partner (incl. Commerce)** | Community (free) → Bronze → Silver → Gold → Platinum | **Silver 30 certs / 10 deployments / 1 specialization; Gold 100 certs / 20 deployments / 5 specializations** | **Silver US$3,000; Gold US$15,000; Platinum US$25,000 / yr** | Annual program year | [Adobe benefits](https://partners.adobe.com/solution-partners/benefits.html) |
| **WordPress VIP agency partners** | Silver → Gold (limited) | Invitation on track record | Not published | — | [Service partners](https://wpvip.com/partners/service-partners/) |
| **TYPO3** | Association memberships Bronze/Silver/Gold/Platinum (€125–€13,750/yr) | **"TYPO3 Partner" title only via a commercial partnership with TYPO3 GmbH**; membership may not be presented as partnership | see left | Title-usage policy enforced | [Usage of Titles](https://docs.typo3.org/m/typo3/guide-policy/main/en-us/Association/UsageOfTitles.html) |

### 1.2 Foundation-run partner programs

**CNCF Kubernetes Certified Service Provider (KCSP).** ≥3 engineers who passed CKA; demonstrable community activity; a business model serving enterprise end users; must be a CNCF member (Silver minimum). Benefits: logo, listing on kubernetes.io and the CNCF landscape. Sources: [KCSP page](https://www.cncf.io/training/certification/kcsp/), [first KCSPs](https://www.linuxfoundation.org/press/press-release/cloud-native-computing-foundation-announces-first-kubernetes-certified-service-providers).

**CNCF Kubernetes Training Partner (KTP / KCNTP).** Be a KCSP first, resell the CKA exam, student references, a landing page, instructors pass the LF Authorized Instructor process. Sources: [KTP announcement](https://www.cncf.io/announcements/2018/05/02/cloud-native-computing-foundation-announces-new-partner-program-for-kubernetes-training-partners-ktp/), [Becoming a KCNTP](https://www.cncf.io/training/kubernetes-cloud-native-training-partners/becoming-a-kcntp/).

**Linux Foundation Authorized Training Partner (ATP).** Benchmarks for experience and quality; LF Authorized Instructors; application reviewed then a call with channel operations; customers get exam discounts. Fees gated. Source: [ATP page](https://training.linuxfoundation.org/about/training-partner-program/).

**Apache Software Foundation.** No "Apache X Certified" scheme; only "Powered by Apache X" with rules (link, full form, unmodified logo, attribution, no implied endorsement). Third parties may not use a mark in product or service branding. Sources: [Trademark policy](https://www.apache.org/foundation/marks/), [services policy](https://www.apache.org/foundation/marks/services).

**OpenInfra "OpenStack Powered".** Membership required; compliance with one of the two most recent Interop guidelines; results via RefStack; logo and Marketplace listing; a separate "OpenStack Expertise" logo for service firms. Sources: [OpenStack Powered](https://www.openstack.org/brand/openstack-powered/), [Interop process](https://docs.opendev.org/openinfra/interop/latest/process/2021A.html).

### 1.3 Patterns worth copying

1. **Certified-people counts as the tier gate** is near-universal: Odoo 1/3/6, KCSP 3 CKA, GitLab PSP 3 PSE, Adobe 30/100. Three certified engineers is the de-facto floor for a services designation.
2. **Named individuals hold certifications**; Odoo requires notification when a certified person leaves — a roster mechanic.
3. **Annual re-verification with objective evidence**: GitLab PSP audit, Drupal trailing-12-month credits, Red Hat calendar-year points, Odoo retention.
4. **Contribution as currency** (Drupal credits, KCSP community activity) fits a foundation-hosted project better than revenue quotas.
5. **Fees**: foundation programs charge through membership; vendor programs charge US$1k–25k/yr (Drupal min $1k, Odoo $3,950, Adobe $3k–25k, TYPO3 €2,750–13,750).
6. **Brand hygiene**: TYPO3 and ASF show why "Partner" wording must be reserved contractually.

---

## 2. Conformance programs

### 2.1 Certified Kubernetes (CNCF)

- **Run**: `sonobuoy run --mode=certified-conformance`; conformance = the e2e tests tagged `[Conformance]`.
- **Submit**: a pull request to `cncf/k8s-conformance` under `vX.Y/<product>/` with `PRODUCT.yaml` (vendor, name, version, URLs, product type, description, contact), `README.md` (reproduction instructions), `e2e.log`, `junit_01.xml`. One squashed commit.
- **Review**: a bot runs ~15 checks (URLs, all conformance tests present and passed, only required files, supported versions) and labels; staff then check membership or fee, a signed Participation Form, the product listed under qualifying offerings, and any combination name registered. ~3 business days.
- **Licence terms**: LF retains the marks; limited licence to use "Certified Kubernetes" per the branding guide only with qualifying offerings; results submitted within 90 days of first public use; end users must be able to reproduce; marketing states tested versions; marks removed within 30 days of expiry. Validity per version = later of 12 months after that minor release or 9 months after the next; certifiable window = current + 2 prior minors; a product stays certified if it recertifies at least annually.
- **Fees**: free for members, nonprofits and community distributions; commercial non-members pay an annual fee equal to joining.
- Sources: [instructions.md](https://github.com/cncf/k8s-conformance/blob/master/instructions.md), [reviewing.md](https://github.com/cncf/k8s-conformance/blob/master/reviewing.md), [terms](https://github.com/cncf/k8s-conformance/blob/master/terms-conditions/Certified_Kubernetes_Terms.md), [participation form](https://github.com/cncf/k8s-conformance/blob/master/participation-form/Certified_Kubernetes_Form.md).

### 2.2 Others

| Program | Test artefact | Submission / review | Mark & validity |
|---|---|---|---|
| OpenStack Powered / Interop | Unmodified Tempest must-pass tests via RefStack | Upload results; checked against one of two most-recent guidelines; membership required | Logo + Marketplace listing; re-test as guidelines roll |
| Jakarta EE / Java TCK | Full TCK run, 100% pass | Sign the Compatibility Trademark License Agreement, publish results publicly and keep them public while claiming compatibility | "Jakarta EE Compatible" per spec version. [Get listed](https://jakarta.ee/compatibility/get-listed/) |
| Docker Verified Publisher | No technical test; commercial vetting | Paid plans; free Docker-Sponsored OSS for OSI-licensed non-commercial projects | Badge, no rate limits. [DVP docs](https://docs.docker.com/docker-hub/repos/manage/trusted-content/dvp-program/) |
| Terraform Registry provider tiers | Official / Partner / Partner Premier / Community | Partner: join the Technology Partner Program; fix critical issues within 48h, others in 5 business days. Premier adds SBOM | Badge. [Partner Premier](https://www.hashicorp.com/en/blog/announcing-the-new-partner-premier-tier-for-the-terraform-registry) |

Takeaway: a conformance submission = machine-checkable artefacts in a public repository + a signed participation form + a membership or fee check + a human policy review; certification is per version with a forced annual refresh.

---

## 3. Individual certification design

| Credential | Format | Duration | Price (USD) | Pass mark | Proctoring | Validity | Retake |
|---|---|---|---|---|---|---|---|
| **CKA / CKAD** | Performance-based, live clusters, open docs | 2 h | $445 (incl. 1 free retake) | 66% | Online, PSI | 2 years | 1 free; 12 months to schedule |
| **CKS** | Performance-based; **prerequisite: valid CKA** | 2 h | $445 | 67% | PSI online | 2 years | 1 free |
| **OTCA / CBA / KCNA / KCSA** | Multiple choice | 90 min | $250 (1 free retake) | n/p | PSI online | 2–3 yrs | 1 free |
| **HashiCorp Terraform Associate** | 57 items | 1 h | $70.50 + tax | pass/fail | Online proctored | 2 years | Paid |
| **Red Hat RHCSA EX200** | 100% hands-on lab | 3 h | ~$500 | 210/300 | Centre, remote or kiosk | 3 years | Free 2nd attempt within 1 year on individual purchase |
| **Red Hat RHCE EX294** | Hands-on | 4 h | ~$500 | n/p | as above | 3 years | as above |
| **AWS SAA-C03** | 65 items | 130 min | $150 | 720/1000 | Pearson VUE or online | 3 years | 14-day wait |
| **Salesforce Administrator** | 60 items | 105 min | $200 | ~65–68% | Webassessor / Kryterion | Annual maintenance module | $100 |
| **Elastic Certified Engineer** | Performance-based on a live cluster | 3 h | $400 | n/p | Remote | 2 years | Paid |
| **Camunda Certified Professional** | 60 items | 90 min | $200 | 65% | Remote | 2 years | Paid; **partners and Enterprise customers only** |
| **Odoo Functional Certification** | 80–120 items, negative marking | 90 min | Free | 70% | Unproctored online | Per major version | Free |
| **Temporal** | No individual certification found (Sept 2026); free courses only | — | — | — | — | — | — |

Sources: [CKA FAQ](https://docs.linuxfoundation.org/tc-docs/certification/faq-cka-ckad-cks), [OTCA](https://training.linuxfoundation.org/certification/opentelemetry-certified-associate-otca/), [Red Hat renewal](https://www.redhat.com/en/services/certification/renewal), [AWS SAA-C03 guide](https://docs.aws.amazon.com/aws-certification/latest/solutions-architect-associate-03/solutions-architect-associate-03.html), [Elastic cert FAQ](https://www.elastic.co/training/certification/faq), [Camunda cert FAQs](https://academy.camunda.com/certification-faqs), [Odoo 19 cert](https://www.odoo.com/slides/odoo-19-functional-certification-502).

**What a credential unlocks**: KCSP needs 3× CKA; KTP adds authorized instructors; GitLab Select needs 1 PSE and PSP 3; Odoo tiers need 1/3/6; Adobe Silver needs 30. CKS is gated on a valid CKA.

**Digital badges**: CNCF/LF, Red Hat, Camunda, AWS and Salesforce issue through Credly; Open Badges standard; Accredible from ~US$1,500 setup and US$45/month. Sources: [Credly](https://info.credly.com/how-credly-works), [comparison](https://www.verifyed.io/blog/credly-vs-accredible).

Takeaways: performance-based exams are 2–3 h, $400–500, ~66–70% pass mark, 2–3-year validity, one free retake; multiple-choice exams are 60–105 min, $70–250. Prerequisite chaining and partner-only access are both used.

---

## 4. Trademark and foundation

### 4.1 Trademark policy models

- **Linux Foundation**: full mark form on first reference; nobody may describe a product or service as "certified" under an LF mark without having passed the compliance testing and holding written authorization. [LF trademark usage](https://www.linuxfoundation.org/legal/trademark-usage).
- **CNCF**: projects transfer trademark ownership to LF on entry; the Governing Board runs any brand-compliance program. Three distinct marks for three audiences: "Certified Kubernetes" (product), "Kubernetes Certified Service Provider" (company), "Certified Kubernetes Administrator" (person). [CNCF charter](https://github.com/cncf/foundation/blob/main/charter.md), [k8s logo guidelines](https://github.com/kubernetes/kubernetes/blob/master/logo/usage_guidelines.md).
- **ASF**: no certification marks; only "Powered by Apache X".
- **TYPO3**: the negative case — forbids "Gold Partner" wording derived from membership.

### 4.2 Foundation formation paths

| Path | Mechanics | Cost / fee model | Governance |
|---|---|---|---|
| **LF directed fund / sub-foundation** | Fund charter, Governing Board, technical charter, TSC; trademarks assigned to LF; LF membership prerequisite | LF core: Platinum $500k, Gold $100k, Silver $5k–20k by headcount. CNCF: Platinum $350k, Gold $100k, Silver banded. Agentic AI Foundation (Dec 2025): founding Platinum $350k | Board = funding; TSC/TOC = technical |
| **Apache Incubator** | Podling with mentors; graduation by vote; trademarks to ASF | No fees; no paid partner program | PMC per project |
| **Eclipse working group** | WG charter under Eclipse AISBL; classes Strategic / Enterprise / Participant / Committer / Guest | Eclipse membership required; Jakarta EE WG: Strategic €20k–260k by revenue; Participant €4k–15k; free below €1M revenue | Steering, Specification and Marketing committees |
| **The Commons Conservancy** (Dutch stichting) | A "Programme" under the foundation; holds assets and IP; no money handling | **Zero cost** | Programme statutes |
| **Open Source Collective** (fiscal host) | Money only, no IP | **10% of incoming funds** | None imposed |

Sources: [LF membership agreement](https://cdn.platform.linuxfoundation.org/agreements/tlf.pdf), [Jakarta EE charter](https://www.eclipse.org/collaborations/working-groups/jakarta-ee/charter/), [Eclipse fees](https://www.eclipse.org/membership/), [Commons Conservancy FAQ](https://commonsconservancy.org/faq/), [OSC fees](https://docs.oscollective.org/how-it-works/fees), [Apache graduation](https://incubator.apache.org/guides/graduation.html).

### 4.3 What revenue a foundation keeps

Linux Foundation 2024: **$292.2M** = membership dues and donations 43% ($125.1M), project support 25.1% ($73.6M), **events 18.6% ($54.5M)**, **training and certification 12.3% ($36.1M, up from $27.2M in 2023)**. Partner-program fees are folded into membership. Eclipse working groups must be self-funding; ASF keeps nothing from partners; the Drupal Association takes a minimum $1k/yr per certified partner plus contribution. [LF 2024 annual report](https://www.linuxfoundation.org/hubfs/Reports/2024%20Linux%20Foundation%20Annual%20Report_120524.pdf).

---

## 5. Explicitly unverified

Red Hat point thresholds; Nextcloud margin percentages; Elastic, Camunda and HashiCorp per-tier certified-staff counts; LF ATP fees and instructor details; Docker DVP prices; CNCF Silver dollar bands; TYPO3 Silver vs Gold prices; Odoo per-version recertification policy text; Drupal contribution bands above $1k.
