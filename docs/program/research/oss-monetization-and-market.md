# Market references: open-source monetization, the coding-agent market, services benchmarks

Research notes compiled on 2026-09-21 as input to the OpenFactory program and to partner
pricing. Each figure cites its source with a confidence mark: **[verified primary]**,
**[secondary]** (a summary of a filing or page that could not be opened directly), or
**[estimate]**. Currency is USD unless stated. These notes are reference material, not program
rules.

---

## 1. Open-source business models: how the revenue actually splits

| Model | Example | Scale (latest) | What the split looks like | Source |
|---|---|---|---|---|
| Pure support subscription | Red Hat (FY2019, pre-IBM) | $3.4B | ~87.7% subscriptions, ~12.3% training + services ($413M) | [Red Hat FY19](https://www.redhat.com/en/about/press-releases/red-hat-reports-fourth-quarter-and-fiscal-year-2019-results) [secondary] |
| Open core, self-managed heavy | GitLab (FY2026) | $955.2M (+26%) | ~90.5% subscription; SaaS ≈ 32% of total growing 38% vs ~20% for self-managed | [GitLab 10-K FY26](https://www.sec.gov/Archives/edgar/data/1653482/000162828026018731/gtlb-20260131.htm) [secondary] |
| Open core, cloud tipping point | Elastic (FY2026) | $1.739B (+17%) | Elastic Cloud ≈ 48–49% of revenue, growing 20–22% vs 17% overall | [Elastic Q4 FY26](https://www.businesswire.com/news/home/20260527847546/en/Elastic-Reports-Fourth-Quarter-and-Fiscal-2026-Financial-Results) [secondary] |
| Open core observability | Grafana Labs | $400M ARR (Sep-25) | Cloud grows ~2x faster than self-managed | [Grafana press](https://grafana.com/press/2025/09/30/grafana-labs-surpasses-400m-arr-and-7000-customers-gains-new-investors-to-accelerate-global-expansion/) [estimate] |
| Fair-code automation | n8n | $100M ARR (Apr-26) | Cloud tiers $24 / $60 / $800 per month; 1.7M monthly self-hosted builders as the funnel | [Sacra](https://sacra.com/c/n8n/) [secondary] |
| Open core, buyer-based | Mattermost | $33.1M (2024, est.) | Developer features free; paid features aimed at IT/security buyers | [Handbook](https://handbook.mattermost.com/company/about-mattermost/business-model) [estimate] |
| Source-available + cloud | Camunda | ~$200M ARR (Aug-26) | Ten years to the first $100M, two years to the next | [Camunda PR](https://camunda.com/press-releases/camunda-closing-in-on-200m-in-arr-doubling-revenue-in-record-time/) |
| Consumption cloud, no foundation | Temporal | Run-rate >$250M (Aug-26, third-party) | Actions-based pricing $50/M list, blended ≈ $11/M; support priced at 5–10% of usage | [Temporal pricing](https://docs.temporal.io/cloud/pricing), [teardown](https://dev.to/beton/temporal-pricing-teardown-2026-2j11) [estimate] |
| Managed hosting of OSS | Supabase | ~$170M ARR (May-26) | Self-host free; essentially all revenue is cloud | [Sacra](https://sacra.com/research/supabase-170m-year-growing-221-yoy/) [estimate] |
| Managed hosting of OSS | Discourse | ~$15M (Aug-25) | Starter $20, Pro $100, Business $500/mo, Enterprise custom | [Discourse pricing](https://www.discourse.org/pricing) |
| Non-profit + hosting | Ghost | ~$7.5M; 24k paying customers | $36M cumulative hosting revenue | [Ghost 6.0](https://ghost.org/changelog/6/) [secondary] |
| Bootstrapped hosted OSS | Plausible | $3.1M ARR (2024 est.); 8 staff | 100% hosted subscriptions; self-host as marketing | [Plausible blog](https://plausible.io/blog/open-source-saas) |
| Partner/implementer ecosystem | Odoo | €650M billings 2025, ARR +42% | Partners earn 10/15/20% commission on Enterprise subscriptions; Odoo sells subscriptions, partners sell implementation | [Odoo results](https://www.odoo.com/blog/odoo-news-5/odoo-unveils-its-results-and-ambitious-projects-at-odoo-experience-2025-1857) |
| Platform + partner ecosystem | Acquia (Drupal) | $200–350M (estimates) | May 2026 pledge: 2% of partner revenue to the Drupal project | [BriefGlance](https://briefglance.com/articles/acquias-fair-trade-plan-to-fix-open-sources-funding-problem) [estimate] |
| Marketplace fee | Adobe Commerce Marketplace | n/a | 85/15 split on extensions | [Adobe dev docs](https://developer.adobe.com/commerce/marketplace/guides/sellers/revenue-share) [verified] |
| Foundation | Linux Foundation (2025) | ~$311M | Memberships $133M (43%), project services $84M (27%), events $59M (19%), training & certification ~$30M (~10%) | [LF 2025 report](https://www.linuxfoundation.org/hubfs/Publications/2025%20Linux%20Foundation%20Annual%20Report_121825a_lr.pdf) |

**Odoo's partner share could not be verified.** The only sourced statement is that new sales were split roughly evenly between direct and indirect channels (undated, via Wikipedia). Commission structure and tier thresholds (10 / 75 / 300 new users, 1 / 3 / 6 certified staff, 70% / 80% retention) are verified through secondary sources.

**Patterns:**
1. Self-managed still dominates revenue at infrastructure-adjacent OSS vendors (GitLab ~68% self-managed, Elastic ~52%). "Runs on the client's machines" is not a handicap.
2. Cloud grows faster everywhere. Private cloud add-ons are the right hedge.
3. Training and certification is ~10% of revenue at the LF and ~12% at Red Hat — a margin-positive channel builder, not a primary line.
4. Partner-fee norms: 15% marketplace take, 10–20% commission on subscriptions, 2% of partner revenue back to the project.

---

## 2. The AI coding-agent and autonomous engineering market (2026)

| Vendor / product | Entry | Team / Business | Enterprise | Unit of consumption | Source |
|---|---|---|---|---|---|
| **Cognition Devin** | Core $20/mo + $2.25/ACU | Team $500/mo incl. 250 ACU | Custom; VPC, SSO, ACU commitments | ACU ≈ 15 min of agent work | [Devin pricing](https://devin.ai/pricing), [Lindy](https://www.lindy.ai/blog/devin-pricing) |
| **GitHub Copilot** | Free / Pro $10 / Pro+ $39 | Business $19/user | Enterprise $39/user | Since Jun-2026 "AI credits" billed per token at model API rates; seat includes $19 / $39 of credits | [GitHub blog](https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/) |
| **Cursor** | Pro $20 / Ultra $200 | Teams $40, Premium $120 | Custom pooled usage | Seat includes usage; overage on demand | [Cursor docs](https://cursor.com/docs/account/teams/pricing) |
| **Anthropic Claude Code** | Pro $20 / Max $100–200 | Team $20–25, Premium $100–125 | ≈ $20/seat + usage at API rates; observed $60–250/active user/mo | Tokens | [Anthropic pricing](https://www.anthropic.com/pricing) |
| **OpenAI Codex (cloud)** | Plus $20, Pro $100 / $200 | Business per seat | Custom credit pool | Token credits; typical $100–200/dev/mo | [Codex pricing](https://developers.openai.com/codex/pricing) |
| **Google Jules** | Free 15 tasks/day | AI Pro $19.99: 100 tasks/day | AI Ultra $124.99: 300 tasks/day | **Tasks per day** | [HackUp](https://hackup.ai/ai-plans/jules/) |
| **Sourcegraph Amp** | PAYG, zero markup | same | +50% markup; $1,000 entry | Pass-through tokens | [G2](https://www.g2.com/products/sourcegraph-sourcegraph/pricing) |
| **Factory.ai** | Pro $20 / Plus $100 / Max $200 | Custom | Custom: SSO, ZDR, on-prem, SLA; $1.5B valuation (Apr-26) | Credits | [EnterpriseDNA](https://enterprisedna.co/resources/news/factory-ai-series-c-enterprise-coding-agents-2026/) |
| **All Hands / OpenHands** | OSS MIT, BYO key | BYOK or PAYG | Self-hosted, SSO, SLA; quote | Tokens | [OpenHands pricing](https://www.openhands.dev/pricing) |
| **Augment Code** | Indie $20 | Standard $60, Max $200 | Credit-based | Credits per action class | [Augment blog](https://www.augmentcode.com/blog/our-new-credit-based-plans-are-now-live) |
| **Qodo** | — | $30/mo base + $0.012/credit (~$1.70/review) | ≈ $45/user/mo | Credits per review | [Qodo docs](https://docs.qodo.ai/pricing-and-usage) |
| **Zencoder** | Free BYOK | $45 / $95 / $195 per user | Custom | Credits | [Zencoder pricing](https://zencoder.ai/pricing) |
| **Blitzy** | none | none | Enterprise-only, annual contracts scaled to codebase size; $1.4B valuation (May-26) | Contract | [BusinessWire](https://www.businesswire.com/news/home/20260505342338/en/Blitzy-Raises-$200-Million-at-$1.4-Billion-Valuation-to-Advance-Autonomous-Software-Development-for-the-Enterprise) |
| **Sweep** | $10 / $20 / $60 | Teams from $480/mo | — | LLM cost + 5% | [Sweep pricing](https://sweep.dev/pricing) |
| **Kilo / Cline / Roo** | OSS, BYOK | $15–20/user | Custom | Pass-through | [Kilo vs Cline](https://kilo.ai/kilo-code/vs/cline) |

**Scale signals.** Cognition: $73M ARR (Jun-25) → $492M (May-26) → reportedly >$900M annualized (Sep-26); Blitzy and Factory valuations show a distinct enterprise-only "autonomous factory" category priced on annual contracts, not seats. [Dealroom](https://app.dealroom.co/news/note/cognition-reportedly-reaches-900m-annualised-revenue-targets-1-5b-by-end-2026).

**The pricing pattern.**
1. Hybrid platform + consumption is the norm since 2026: seat or platform fee plus metered credits at model API rates. Sticker price is a floor; production developers spend 5–20x the entry price.
2. Three consumption units exist: tokens/credits, agent-time (Devin ACU), tasks (Jules, Qodo). **Nobody major prices per merged pull request**, which leaves an opening for an outcome-priced offering.
3. Enterprise packaging = custom annual contract with VPC/on-prem, SSO/SCIM, audit logs, zero data retention, dedicated compute, SLA support, committed consumption pool with overage caps.
4. Public per-task economics: small/medium agent tasks $0.03–$2.60; merged feature ~$12 on Claude Code, $12–17 on Copilot, ~$29 on OpenCode ([Insight](https://blog.insight-services-apac.dev/2026/07/06/cost-to-a-merged-feature)); AI code review $15–25/PR at the high end ([Codacy](https://blog.codacy.com/ai-code-review-cost-per-pull-request-what-engineering-teams-actually-pay-in-2026)); Devin 1–2 hour ticket ≈ $8–18. OpenFactory's own published figures: $0.65 for one ticket on a fresh installation, and medians of $7.47 (map injected) vs $11.70 (control) on one production codebase, n = 8 ([STATUS](../../STATUS.md), [knowledge-layer](../../knowledge-layer.md)).

Implication: a fully autonomous ticket-to-PR run with an independent reviewer plausibly costs $5–60 in model and compute today; a per-merged-PR price of $50–150, or a platform fee plus metered ticket credits, sits above cost and well below a human hour in the US/EU.

---

## 3. Services, hosting and support benchmarks

### 3.1 Labour rates

| Role / market | Rate | Source |
|---|---|---|
| Brazil, senior DevOps, CLT median | ≈ R$12,050/month | [Glassdoor BR](https://www.glassdoor.com.br/Sal%C3%A1rios/devops-senior-sal%C3%A1rio-SRCH_KO0,13.htm) |
| Brazil, senior engineer, PJ monthly | R$12k–21k/month | [Tabnews/Revin](https://www.tabnews.com.br/revinsoftware/quanto-custa-um-squad-de-desenvolvimento-em-2026) |
| Brazil, consultancy hora/homem | R$180–280/h senior; R$120–180/h pleno → R$1,450–2,250/day | [Nextage](https://nextage.com.br/blog/quanto-custa-um-squad-de-desenvolvimento-guia-para-ctos/) |
| Brazil, senior AI engineer PJ | R$25k–45k/month | [Exame](https://exame.com/inteligencia-artificial/salario-de-engenheiro-de-ia-no-brasil-em-2026-quanto-ganha-e-o-que-faz-quem-trabalha-com-inteligencia-artificial-estao-usando-inteligencia-artificial/) |
| Brazil, squad as a service (5 people) | R$57k–105k/month | [Revin](https://revin.com.br/pt/blog/squad-como-servico) |
| US, DevOps contractor | $80–200/h; senior ≈ $165/h → $1,300–1,600/day | [devopssalary.com](https://devopssalary.com/contract) |
| UK, senior platform contract median | £525/day | [ITJobsWatch](https://www.itjobswatch.co.uk/contracts/uk/senior%20platform%20engineer.do?p=6) |
| EU, freelance AI engineer | $90–270/h; $670–1,880/day | [Nicola Lazzari](https://nicolalazzari.ai/ai-consultant-europe) |

A senior Brazilian engineer billed at R$2,000/day ≈ US$370/day is roughly a quarter of a US senior contractor's day.

### 3.2 Managed service retainers

| Scope | Monthly | Source |
|---|---|---|
| Early-stage (10-person team, AWS, CI/CD, monitoring) | $3,000–5,500 | [CloudHouse](https://cloudhousetechnologies.com/blog/devops-support-cost-pricing-2026) |
| Small/mid DevOps retainer | $3,500–8,000 (lean $5k–15k) | [SquareOps](https://squareops.com/blog/devops-consulting-services-cost-pricing-guide-2026/) |
| Growth SaaS, Kubernetes, 24/7 | $8,000–18,000 | [CloudHouse](https://cloudhousetechnologies.com/blog/devops-support-cost-pricing-2026) |
| Boutique retainer with on-call | $8,000–30,000 | [Flamingo](https://www.flamingo.run/blog/msp-pricing-models) |
| Fixed-price packages seen | audit $1,900; cloud launch $5,900; SOC2-ready infra $6,900 | [Tasrie](https://tasrieit.com/blog/how-much-does-devops-consulting-cost-2026-pricing-guide) |

### 3.3 Support tiers and price ratios

| Vendor | Tier ladder | Ratio | Source |
|---|---|---|---|
| Red Hat RHEL (per server/yr) | Self-support $383.90 → Standard $878.90 (business hours, Sev1 1 business hour) → Premium $1,428.90 (24x7 Sev1/2 1h) | Premium ≈ 1.6x Standard | [Red Hat SLA](https://access.redhat.com/support/offerings/production/sla) |
| Canonical Ubuntu Pro (per server/yr) | Pro $500 → +Infra 24x7 $1,775 → +Full 24x7 $3,400; weekday = 50% of 24x7 | 24x7 ≈ 6.8x base | [ubuntu.com/pricing/pro](https://ubuntu.com/pricing/pro) [verified] |
| SUSE SLES | Standard $749 → Priority $1,199 | ≈ 1.6x | [SUSE shop](https://www.suse.com/shop/server/) |
| SAP / Oracle maintenance | 22% of licence value per year | classic benchmark | — |
| Temporal Cloud support | Essentials max($100, 5% of usage), P0 1 business day; Business max($500, 10%), P0 2 business hours | 5–10% of consumption | [Temporal pricing](https://temporal.io/pricing) |
| Google Cloud Enhanced | min $15k/mo or 10% of spend; P1 15 min | % of spend with a floor | [Google Cloud](https://cloud.google.com/support/premium) |
| Azure | Standard $100/mo, ProDirect $1,000/mo | flat | [US Cloud](https://www.uscloud.com/blog/how-much-is-microsoft-azure-enterprise-support/) |

Typical ladder: Standard (8x5, P1 4h), Premium (24x7 P1 1h, named contact), Enterprise (24x7 P1 30–60 min, quarterly reviews); Premium at 1.6–2x Standard, Enterprise at 3x+.

### 3.4 Training and certification pricing

| Item | Price | Source |
|---|---|---|
| LF CKA exam | $445 incl. one retake | [ckaexam](https://ckaexam.com/blog/cka-certification-cost) |
| Red Hat RHCSA exam | $500 | [passitexams](https://passitexams.com/articles/rhcsa-certification-cost/) |
| AWS exams | $100 / $150 / $300 | [StudyTech](https://studytech.ai/blog/aws-exam-fees-2026-every-certification) |
| Google Cloud exams | $99 / $125 / $200 | [certempire](https://certempire.com/gcp-certification-cost/) |
| HashiCorp Terraform Associate | $70.50 | [TrueCert](https://truecert.co/blog/terraform-certification-cost-2026/) |
| Red Hat RH124, 5-day public | ≈ €3,300 + VAT per seat | [bilginc](https://bilginc.com/en/training/red-hat-system-administration-i-rh124-1093-training/) |
| Red Hat Learning Subscription | ≈ $5,500–7,500 per person/yr | [pcxio](https://pcxio.com/what-does-red-hat-certification-cost-the-complete-2026-price-guide/) |
| LF LFS258 self-paced | $299 | [LF training](https://training.linuxfoundation.org/training/kubernetes-fundamentals/) |
| Boutique 5-day Kubernetes workshop | $950–1,450 per seat | [SuperOrbital](https://discuss.kubernetes.io/t/core-kubernetes-workshop-may-10-14/15412) |

Private on-site training is not publicly priced by Red Hat; practice is 1.5–3x a senior day rate per instructor-day plus per-seat materials (a practitioner heuristic).

### 3.5 Partner economics

| Mechanism | Benchmark | Source |
|---|---|---|
| Referral fee | 5–20% of first-year ACV; 10–25% common | [Magentrix](https://www.magentrix.com/blog/partner-compensation-commission-structures) |
| Resell margin | 15–30% typical; 25–40% with volume | [Magentrix](https://www.magentrix.com/blog/partner-compensation-commission-structures) |
| SaaS affiliate recurring | 20–30% | [Post Affiliate Pro](https://www.postaffiliatepro.com/blog/saas-affiliate-commission-rates/) |
| Odoo partner commission | 10 / 15 / 20% | [ERP Research](https://www.erpresearch.com/en-us/odoo-partners) |
| Marketplace take | Adobe Commerce 15% | [Adobe](https://developer.adobe.com/commerce/marketplace/guides/sellers/revenue-share) |
| Partner give-back to project | Acquia 2% of partner revenue | [BriefGlance](https://briefglance.com/articles/acquias-fair-trade-plan-to-fix-open-sources-funding-problem) |

### 3.6 Brazil-specific structure

- **MEI**: ceiling R$81,000/yr; software development is not an allowed MEI activity, so engineers contract through an SLU/LTDA under Simples. [meucontadoronline](https://www.meucontadoronline.com.br/blog/desenvolvedor-pode-ser-mei/)
- **Simples Nacional**: ceiling R$4.8M/yr. IT consulting is Anexo V (15.5–30.5%) unless the **Fator R** (payroll ≥ 28% of revenue) moves it to Anexo III. This pushes consultancies to sell labour (alocação, hora/homem, squad) rather than licence-like revenue. [Contabilidade.com](https://contabilidade.com/blog/fator-r-no-simples-nacional-2026-como-calcular-exemplos-praticos-e-quando-servicos-migram-do-anexo-v-para-o-iii/)
- **Lei do Bem (Lei 11.196/2005)**: Lucro Real companies only; additional exclusion of 60–100% of R&D spend from the IRPJ/CSLL base; annual reporting to MCTI. Relevant once a company outgrows Simples. [ABGI](https://abgi-brasil.com/lei-do-bem-inovacao/)
- **How Brazilian consultancies price**: hora/homem R$120–280/h; monthly alocação R$12k–21k senior; squad R$57k–105k/mo; retainers with hour banks (banco de horas) are common; fixed-price is less common for platform work.

---

## 4. Foundation economics

| Foundation / structure | Type | Money and control | Source |
|---|---|---|---|
| Linux Foundation | US 501(c)(6) | $311M (2025); projects assign trademarks to LF; fiscal-sponsorship fee 9% of the first $1M/yr and 6% above | [LF trademarks](https://www.linuxfoundation.org/blog/blog/open-source-communities-and-trademarks-a-reprise) |
| CNCF / Kubernetes | LF directed fund | Platinum $350k, Gold $100k, Silver $10k–100k by headcount; conformance self-tested and submitted on GitHub | [CNCF join](https://www.cncf.io/about/join/) |
| OpenTofu | LF → CNCF Sandbox | Pledges: env0, Spacelift, Scalr, Harness fund 18 FTE for 5 years | [LF PR](https://www.linuxfoundation.org/press/announcing-opentofu) |
| Valkey | LF project | Member-funded, no single vendor | [LF PR](https://www.linuxfoundation.org/press/linux-foundation-launches-open-source-valkey-community) |
| Temporal | No foundation | Company owns trademark and cloud | [Contrary](https://research.contrary.com/company/temporal-technologies) |
| Odoo SA vs OCA | Belgian company + Swiss non-profit | Odoo SA owns the mark and Enterprise; OCA hosts community modules, €60/yr membership, ~10 staff | [OCA FAQ](https://www.odoo-community.org/resources/faq) |
| TYPO3 Association vs TYPO3 GmbH | Swiss association owns 100% of a German GmbH | Association ~€650k/yr into core; GmbH sells services, ELTS, certification and returns profit | [TYPO3 structure](https://typo3.org/company/structure-leadership) |
| Nextcloud GmbH | Company only | Profitable, independent; no foundation | [Nextcloud blog](https://nextcloud.com/blog/nextcloud-doubles-order-intake-and-customer-base-remains-profitable-and-independent/) |
| Django Software Foundation | US 501(c)(3) | ~$200–300k/yr; owns the mark | [DSF 2024](https://www.djangoproject.com/foundation/reports/2024/) |
| Python Software Foundation | US 501(c)(3) | FY2024 revenue $4.1M; PyCon is the main source | [PSF](https://pyfound.blogspot.com/2025/10/connecting-the-dots.html) |
| Plone Foundation | US 501(c)(3) | Small; primary historical expense = trademark registration | [Plone finance](https://plone.org/foundation/finance) |

### What a vendor keeps vs gives up

| Structure | Trademark | Cert/conformance revenue | Training | Cloud/paid add-ons | Governance cost |
|---|---|---|---|---|---|
| Company-owned (Temporal, Nextcloud, Odoo SA) | Company | Company | Company | Company | None; single-vendor objections |
| LF/CNCF hosted | Assigned to LF | LF | LF runs official training; partners deliver | Company keeps its products, not the mark | Dues + 9%/6% fiscal fee |
| Company + own foundation (TYPO3 model) | Foundation | Foundation or its company | Shared | Company | Foundation running cost |
| Fiscal host (SFC 10%; OSC 10% + ~3%; LF 9%/6%) | Project retains | Project | Project | Company | Lowest overhead |

### Minimum viable foundation for a one-company project

| Option | Setup cost | Ongoing | Fit |
|---|---|---|---|
| Dutch stichting | Notary €500–1,500 + KVK €75; no minimum capital | Annual accounts | Cheap, credible EU vehicle that can own marks and run conformance. [Business.gov.nl](https://business.gov.nl/running-your-business/legal-forms-and-governance/foundation/) |
| US 501(c)(6) | Incorporation ~$100–500 + IRS Form 1024 $600 + legal | Form 990 | Best if US enterprise buyers and vendor dues are the target. [Baker Tilly](https://www.bakertilly.com/insights/tax-exempt-organizations-via-irs-form-1024) |
| Open Source Collective | Free | 10% + ~3% processing | Simplest for community funds; weaker for trademark holding. [OSC](https://docs.oscollective.org/how-it-works/fees) |
| Software Freedom Conservancy | Selective | 10% | Can hold trademarks; slow intake. [SFC](https://sfconservancy.org/projects/apply/) |
| LF / CNCF Sandbox | Membership + application; trademark assignment | Dues; 9%/6% | Only once ≥3 independent vendors want in; premature for one company |

---

## 5. Key uncertainties

Odoo's share through partners; Grafana, Supabase, Automattic, Mattermost, Nextcloud and Acquia revenues (third-party estimates); Elastic's full-year cloud share (inferred from quarters); Claude Team Premium seat price (sources differ); CNCF conformance and training-partner fees; private on-site training day pricing (heuristic).
