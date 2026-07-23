# BookRAG Industrial Use Cases: Concrete Decision Workflows / BookRAG 産業ユースケース：具体的な意思決定業務

This document describes specific workflows that can be evaluated against the current EVSUI `multi_format_bookrag` implementation. It does not assume that BookRAG can perform graph traversal, automatic cross-document comparison, domain calculations, or autonomous decisions.

本書は、現行 EVSUI `multi_format_bookrag` 実装に対して評価可能な、具体的な業務フローを定義します。グラフ探索、文書横断の自動比較、専門計算、自律判断が実装済みであるとは仮定しません。

## English

### What the Current Product Actually Returns

Current retrieval starts with semantic similarity search over `bnode.content`. For each matched node, EVSUI can return:

- Document identity and filename
- Matched node content
- Ancestor section path
- Page range and source element
- Source text, table HTML, or image context when parsing produced it
- Document-scoped entity and relation metadata when available
- Governed document-relation labels such as `updates`, `summary_of`, or `supplement_to`

The result is a set of evidence candidates for a person or downstream application. A document-relation label adds context to a matched document; it does not automatically retrieve the related document. Entity normalization is document-scoped.

### How to Prioritize a Use Case

Score each proposed workflow from 1 to 5 on:

| Factor | Question |
|---|---|
| Frequency | How often does the same evidence task occur? |
| Consequence | What is the cost of missing or misreading evidence? |
| Document dependence | Is the decision materially governed by long, structured documents? |
| Traceability | Must a reviewer return to the exact section, page, table, or source element? |
| Current-fit | Can the first useful version work with semantic retrieval plus evidence reconstruction? |
| Integration burden | How many authoritative systems are required before the result is usable? Lower burden receives a higher score. |

Start with cases that score high on the first five factors and do not require real-time or highly integrated data for the first pilot.

### Use-Case Portfolio

| ID | Specific workflow | Primary user | Initial delivery priority |
|---|---|---|---|
| FIN-01 | Annual project-finance credit review | Credit analyst and credit committee secretary | A |
| FIN-02 | Regulatory change evidence review | Compliance and policy owner | A |
| FIN-03 | Industrial property and business-interruption claim review | Claims adjuster and coverage counsel | A |
| MED-01 | Medical-device safety notice and local-procedure review | Clinical engineering and patient-safety team | B |
| LIFE-01 | Pharmaceutical batch deviation and CAPA evidence | Quality investigator and qualified reviewer | A |
| LIFE-02 | Clinical-trial safety review preparation | Medical monitor and pharmacovigilance reviewer | B |
| FOOD-01 | Food contamination and recall investigation | Food-safety and quality team | B |
| WATER-01 | Drinking-water limit excursion review | Water-quality manager and laboratory reviewer | B |
| ENERGY-01 | Power-transformer outage work-package preparation | Maintenance and outage engineer | A |
| CHEM-01 | Chemical-plant management-of-change review | Process-safety and operations engineer | A |
| SEMI-01 | Semiconductor yield-excursion evidence collection | Process and equipment engineer | A |
| AERO-01 | Aerospace requirement-change verification evidence | Systems and verification engineer | B |
| SUPPLY-01 | Critical supplier material or process change review | Supplier-quality and product engineer | B |
| CLIMATE-01 | Flood-resilience investment evidence preparation | Infrastructure planner and risk reviewer | B |

Priority A means a bounded pilot can use the current evidence-package model. Priority B means the document evidence is useful, but authoritative applicability or structured data integration is required before operational use.

## Concrete Use Cases

### FIN-01: Annual Project-Finance Credit Review

**Trigger:** A bank performs the annual review of financing for a power plant, LNG terminal, semiconductor fab, mine, data center, or transport project.

**Users:** Credit analyst, sector specialist, covenant-monitoring team, credit committee secretary.

**Documents:**

- Original credit memorandum and approval conditions
- Loan agreement and covenant definitions
- Latest audited financial statements and quarterly reports
- Independent engineer and environmental reports
- Rating or market reports
- Prior annual-review papers and waiver decisions

**Representative questions:**

- Where is the debt-service coverage covenant defined, including exclusions and cure provisions?
- Which passages explain the latest construction delay or cost overrun?
- What operating, regulatory, supply, or environmental risks changed since the prior review?
- Which current report updates or supplements the original technical assumptions?

**BookRAG output:** Evidence candidates containing the relevant covenant, definition, risk statement, management explanation, technical finding, section path, page, table/source block, and document relationship.

**Required outside BookRAG:** Borrower and facility identity, current exposure, covenant calculations, financial spreading, market data, approval state, and access rights from credit and risk systems.

**Pilot measures:** Median time to assemble committee evidence; reviewer acceptance rate; unsupported or wrongly scoped evidence; missed material evidence found during second review.

**Not a BookRAG decision:** Credit rating, covenant compliance calculation, expected loss, pricing, approval, or investment recommendation.

### FIN-02: Regulatory Change Evidence Review

**Trigger:** A regulator publishes a new or revised rule on capital, liquidity, operational resilience, consumer protection, model risk, payments, insurance, or disclosure.

**Users:** Regulatory change team, compliance officer, policy owner, control owner, internal audit.

**Documents:**

- New rule, consultation, final guidance, and implementation date
- Superseded rule and regulatory FAQs
- Internal policy and standard
- Control descriptions and operating procedures
- Prior legal or compliance interpretations
- Audit and examination findings

**Representative questions:**

- Which clauses introduce a new obligation, threshold, exception, or reporting date?
- Which internal policies currently address the same subject?
- What evidence should a control owner review before confirming implementation?

**BookRAG output:** Clause-level evidence from the new rule and candidate internal policy/control passages, with document version, section, page, and source element.

**Required outside BookRAG:** Regulatory inventory, legal-entity and jurisdiction scope, policy ownership, control mapping, implementation status, legal interpretation, and approval workflow.

**Pilot measures:** Time to prepare an initial impact-review pack; clause locator accuracy; percentage of evidence accepted by policy owners; false matches requiring removal.

**Not a BookRAG decision:** Legal interpretation, applicability determination, control sufficiency, or compliance certification.

### FIN-03: Industrial Property and Business-Interruption Claim Review

**Trigger:** A fire, flood, machinery breakdown, cyber event, or supply interruption causes an industrial insurance claim.

**Users:** Claims adjuster, coverage counsel, forensic accountant, engineer, reinsurance reviewer.

**Documents:**

- Policy wording, schedule, endorsements, exclusions, and sublimits
- Engineering survey and risk-improvement recommendations
- Incident and root-cause reports
- Repair estimates and equipment manuals
- Business-interruption submissions
- Adjuster, expert, and prior-claim reports

**Representative questions:**

- Which endorsement defines coverage for this equipment and cause of loss?
- What exclusions, waiting periods, deductibles, or sublimits require review?
- Which incident findings support or conflict with the claimed event description?

**BookRAG output:** Coverage and incident evidence candidates with clause hierarchy, definitions, pages, source blocks, and relationships between policy, endorsement, and report documents.

**Required outside BookRAG:** Insured object identity, policy period, loss dates, financial calculations, reserves, fraud controls, legal privilege, and claim authority.

**Pilot measures:** Time to prepare the coverage issue list; percentage of cited clauses accepted by counsel; missing endorsement findings; repeated search effort.

**Not a BookRAG decision:** Coverage determination, causation, loss valuation, reserve, liability, fraud finding, or payment.

### MED-01: Medical-Device Safety Notice and Local-Procedure Review

**Trigger:** A manufacturer or regulator issues a field-safety notice, correction, contraindication, or software update for a medical device.

**Users:** Clinical engineering, biomedical engineering, patient safety, infection control, procurement, clinical governance.

**Documents:**

- Manufacturer safety notice and updated instructions for use
- Previous instructions and service bulletins
- Local operating, cleaning, maintenance, and escalation procedures
- Device committee decisions and training material
- Incident or near-miss reports

**Representative questions:**

- Which device models, software versions, accessories, and use conditions are named?
- What new warning, contraindication, maintenance step, or deadline is stated?
- Which passages in local procedures discuss the same operation?

**BookRAG output:** Notice and procedure evidence candidates with model/version text, warning context, section, page, and known update relationships.

**Required outside BookRAG:** Installed-device inventory, software version, location, patient exposure, recall status, maintenance records, clinical approval, and task assignment.

**Pilot measures:** Time to prepare the affected-procedure review; correct source/model/version extraction by reviewers; missed relevant procedure passages.

**Not a BookRAG decision:** Whether a device is safe for a patient, whether to stop use, clinical risk classification, recall closure, or maintenance authorization.

### LIFE-01: Pharmaceutical Batch Deviation and CAPA Evidence

**Trigger:** A batch result, environmental-monitoring result, process step, or equipment event deviates from an approved requirement.

**Users:** Deviation investigator, manufacturing science, laboratory, quality assurance, qualified reviewer.

**Documents:**

- Approved SOP and batch instruction
- Product and process specifications
- Analytical method and validation report
- Equipment qualification and maintenance report
- Deviation, nonconformance, CAPA, and change-control history
- Regulatory commitments and relevant inspection findings

**Representative questions:**

- What approved requirement and acceptance criterion applied at the event time?
- Which prior deviations involved the same step, equipment, method, or failure mode?
- Which validation limitation or change-control condition requires review?

**BookRAG output:** Source-attributable requirement, method, validation, and prior-investigation evidence with document, section, page, table, and source element.

**Required outside BookRAG:** Batch, lot, equipment, method, product version, effective-document date, laboratory data, electronic signatures, workflow status, and quality authority.

**Pilot measures:** Evidence-collection time; reviewer acceptance; obsolete-document retrieval rate; second-person review findings; repeated evidence collection.

**Not a BookRAG decision:** Root cause, product impact, patient risk, CAPA adequacy, batch disposition, release, or GxP compliance.

### LIFE-02: Clinical-Trial Safety Review Preparation

**Trigger:** A medical monitor or safety committee reviews a serious adverse event, an aggregate trend, or a scheduled safety report.

**Users:** Medical monitor, pharmacovigilance physician, clinical scientist, data-safety committee support, regulatory writer.

**Documents:**

- Protocol and amendments
- Investigator brochure and reference safety information
- Statistical analysis plan
- Clinical study report sections
- Safety narratives and aggregate safety reports
- Risk-management plan and product label

**Representative questions:**

- How is the event defined, collected, graded, and analyzed in the current protocol?
- Which known risks and expected events are described in the current reference safety information?
- Which study population, dose, cohort, endpoint, and reporting period apply to the cited result?

**BookRAG output:** Protocol, safety, population, method, and result evidence candidates with study/document identity, section, page, table, and amendment relationship.

**Required outside BookRAG:** Subject-level data, coding, exposure, randomization, current clinical state, statistical analysis, approved reference version, unblinding controls, and decision authority.

**Pilot measures:** Time to prepare source evidence; amendment/version errors; accepted citations; missing relevant safety sections found by medical review.

**Not a BookRAG decision:** Causality, expectedness, signal detection, benefit-risk, dose modification, patient care, or regulatory reporting decision.

### FOOD-01: Food Contamination and Recall Investigation

**Trigger:** A pathogen, allergen, chemical, foreign-material, or labeling issue is detected in a product or facility.

**Users:** Food-safety manager, quality team, laboratory reviewer, recall coordinator, regulatory affairs.

**Documents:**

- HACCP or food-safety plan
- Product, allergen, sanitation, and release specifications
- Sampling and laboratory methods
- Supplier certificates and audits
- Deviation, complaint, recall, and corrective-action reports
- Regulatory guidance and customer requirements

**Representative questions:**

- Which control point, limit, sampling rule, or release criterion applied?
- Which prior incidents involved the same ingredient, line, supplier, or organism?
- What notification, hold, investigation, or documentation steps are stated?

**BookRAG output:** Procedure, limit, method, supplier, and prior-incident evidence with section, page, table, and source provenance.

**Required outside BookRAG:** Lot genealogy, inventory, shipment, supplier-lot linkage, laboratory results, jurisdiction, customer list, case workflow, and recall authority.

**Pilot measures:** Time to assemble the investigation pack; accepted evidence; obsolete specification rate; missing procedure or supplier-document findings.

**Not a BookRAG decision:** Contamination source, affected-lot scope, health risk, product release, recall classification, or public notification.

### WATER-01: Drinking-Water Limit Excursion Review

**Trigger:** A laboratory or online measurement exceeds an operating, internal, or regulatory threshold.

**Users:** Water-quality manager, treatment engineer, laboratory, regulatory liaison, incident manager.

**Documents:**

- Permit and drinking-water standard
- Sampling plan and analytical method
- Treatment and abnormal-operation procedures
- Instrument manuals and calibration instructions
- Prior excursion, corrective-action, and regulator reports
- Emergency and public-notification procedures

**Representative questions:**

- Which limit, averaging period, confirmation sample, and reporting rule apply?
- What procedure governs this treatment unit and measurement method?
- Which prior excursions describe similar conditions and corrective actions?

**BookRAG output:** Limit, method, procedure, and prior-event evidence with jurisdiction/document identity, section, page, table, and source block.

**Required outside BookRAG:** Current laboratory and sensor data, sampling location, asset state, distribution model, affected population, permit scope, incident workflow, and regulatory authority.

**Pilot measures:** Evidence-pack preparation time; correct rule/method locator rate; obsolete procedure findings; reviewer rejection reasons.

**Not a BookRAG decision:** Water safety, affected population, treatment adjustment, cause, compliance status, or public notification.

### ENERGY-01: Power-Transformer Outage Work-Package Preparation

**Trigger:** A utility plans an outage after inspection findings, dissolved-gas results, relay events, overheating, leakage, or an OEM notice.

**Users:** Maintenance engineer, asset manager, outage planner, protection engineer, safety reviewer.

**Documents:**

- Transformer and accessory manuals
- OEM service bulletins
- Inspection, oil-analysis, and condition-assessment reports
- Prior maintenance and outage reports
- Approved maintenance, isolation, test, and return-to-service procedures
- Safety and environmental requirements

**Representative questions:**

- Which inspection finding or OEM bulletin recommends this work?
- What prerequisites, cautions, test limits, and return-to-service steps require review?
- Which current document supersedes or supplements the previous instruction?

**BookRAG output:** Candidate work-scope, warning, limit, inspection, and prior-maintenance evidence with document relationships, sections, pages, tables, and image context.

**Required outside BookRAG:** Asset tag, model and serial number, configuration, live condition data, work history, spares, outage schedule, switching order, permit, and authorization.

**Pilot measures:** Engineer search time; accepted evidence; wrong-model or obsolete-manual retrieval; work-package review comments caused by missing documents.

**Not a BookRAG decision:** Operability, outage necessity, switching, isolation, work scope approval, test acceptance, or return to service.

### CHEM-01: Chemical-Plant Management-of-Change Review

**Trigger:** A plant proposes changing equipment material, catalyst, raw material, control setting, operating temperature, relief configuration, or procedure.

**Users:** Process engineer, operations, process safety, mechanical integrity, environmental, MOC coordinator.

**Documents:**

- Process-safety information and operating envelope
- Equipment datasheet and vendor manual
- Hazard analysis and prior MOC
- Operating, startup, shutdown, and emergency procedures
- Inspection and integrity reports
- SDS, environmental permit, incident, and corrective-action reports

**Representative questions:**

- Which operating limits, hazards, material-compatibility statements, and inspection assumptions relate to the proposed change?
- Which procedures and prior MOCs discuss the same equipment or condition?
- What permit, training, testing, or documentation commitments require review?

**BookRAG output:** Candidate limit, hazard, procedure, inspection, permit, and prior-change evidence with exact source context.

**Required outside BookRAG:** Equipment hierarchy, line and tag data, P&ID topology, process conditions, material properties, calculations, action owners, completeness checklist, and approvals.

**Pilot measures:** Initial evidence-gathering time; evidence accepted by discipline reviewers; missed-document findings; obsolete procedure or datasheet retrieval.

**Not a BookRAG decision:** Change-impact completeness, hazard adequacy, material compatibility, relief design, environmental compliance, or MOC approval.

### SEMI-01: Semiconductor Yield-Excursion Evidence Collection

**Trigger:** Yield or defect performance changes for a product, process step, chamber, tool family, material, or supplier lot.

**Users:** Process integration, module engineer, equipment engineer, yield team, product quality, supplier quality.

**Documents:**

- Process and equipment specifications
- Tool manual and troubleshooting guide
- Control plan and FMEA
- Qualification and validation report
- Engineering and supplier change notice
- Prior excursion, 8D, and corrective-action report

**Representative questions:**

- Which documented limits and failure modes relate to this defect signature or process step?
- What tool, material, or recipe-related changes were documented before the excursion?
- Which prior investigations used the same containment or verification method?

**BookRAG output:** Specification, failure-mode, troubleshooting, qualification, change, and prior-investigation evidence with process/tool/product document context.

**Required outside BookRAG:** Wafer maps, lot history, recipe values, sensor data, SPC, tool/chamber identity, material genealogy, experiment results, access control, and root-cause workflow.

**Pilot measures:** Time to collect document evidence; accepted references; wrong-product/tool evidence; repeated searches across engineering repositories.

**Not a BookRAG decision:** Root cause, containment, recipe change, disposition, causal relationship, or process release.

### AERO-01: Aerospace Requirement-Change Verification Evidence

**Trigger:** A system requirement, interface, design assumption, software/hardware baseline, or certification condition changes.

**Users:** Systems engineer, design authority, verification engineer, safety, quality, certification.

**Documents:**

- System and subsystem requirements
- Interface-control and design documents
- Safety assessment
- Verification plan, analysis, and test report
- Nonconformance and anomaly report
- Certification basis, means of compliance, and authority correspondence

**Representative questions:**

- Where is the changed requirement defined and what assumptions or exceptions surround it?
- Which analyses, tests, anomalies, and certification documents contain related evidence?
- Which document version was used for the cited verification result?

**BookRAG output:** Requirement and candidate verification/certification evidence with document identity, section, page, table, and known update relationships.

**Required outside BookRAG:** Authoritative requirement IDs, baseline and configuration effectivity, trace matrix, test status, safety classification, change workflow, export controls, and approval authority.

**Pilot measures:** Evidence-preparation time; accepted citations; wrong-baseline evidence; unresolved source-locator findings.

**Not a BookRAG decision:** Traceability completeness, interface consistency, verification closure, safety acceptance, design approval, or certification compliance.

### SUPPLY-01: Critical Supplier Material or Process Change Review

**Trigger:** A supplier changes a material, formulation, process, site, sub-tier supplier, equipment, specification, or inspection method.

**Users:** Supplier quality, product engineering, procurement, reliability, regulatory, manufacturing.

**Documents:**

- Supplier change notification
- Purchase and product specification
- Material certificate and test report
- PPAP, qualification, validation, or first-article package
- Supplier audit and corrective-action report
- Internal risk assessment and prior deviation

**Representative questions:**

- Which supplied characteristics, approved sources, tests, or process assumptions may be affected?
- What prior qualification or deviation evidence exists for the same material, site, or process?
- Which customer, regulatory, or certification commitments require specialist review?

**BookRAG output:** Candidate specification, qualification, audit, change, and commitment evidence with supplier/product/document provenance.

**Required outside BookRAG:** Supplier, part, BOM, approved-source, product, customer, site, lot, and configuration identity; purchase data; risk classification; workflow and approvals.

**Pilot measures:** Review-pack preparation time; evidence acceptance; missed specification findings; supplier-change cycle time attributable to document search.

**Not a BookRAG decision:** Affected-product completeness, equivalence, qualification sufficiency, supplier approval, deviation approval, or production use.

### CLIMATE-01: Flood-Resilience Investment Evidence Preparation

**Trigger:** A city, utility, port, insurer, or infrastructure fund evaluates a flood-defense, drainage, relocation, hardening, or recovery investment.

**Users:** Infrastructure planner, climate-risk analyst, engineer, insurer, finance team, public authority, reviewer.

**Documents:**

- Flood and climate-hazard assessment
- Asset vulnerability and consequence report
- Engineering option study
- Environmental and social impact assessment
- Land-use, building, water, and emergency policy
- Prior event, loss, recovery, and after-action report
- Funding, insurance, and regulatory criteria

**Representative questions:**

- Which assets, populations, return periods, scenarios, and assumptions are used?
- What limitations and uncertainty statements qualify the projected benefit?
- Which policy, permit, funding, insurance, or environmental criteria require evidence?

**BookRAG output:** Hazard, vulnerability, assumption, option, policy, and prior-event evidence with geography text, scenario, section, page, table, and source provenance.

**Required outside BookRAG:** Current geospatial layers, climate models, asset inventory, population data, engineering and economic calculations, project alternatives, legal authority, budget, and approval process.

**Pilot measures:** Time to prepare the decision evidence book; source/assumption locator accuracy; accepted evidence; gaps identified by technical reviewers.

**Not a BookRAG decision:** Flood prediction, design return period, benefit-cost calculation, environmental approval, insurance pricing, funding allocation, or project selection.

### Delivery Sequence

For a first commercial pilot:

1. Select one workflow, one reviewer group, and a bounded document set.
2. Define 30–100 real questions from completed cases.
3. Mark the source passages a qualified reviewer expects.
4. Measure retrieval recall, source-locator accuracy, evidence acceptance, and time saved.
5. Record failures caused by parsing, retrieval, missing metadata, obsolete documents, or absent integration.
6. Add external identity and workflow integration only after the evidence layer meets the agreed threshold.

Do not start with “chat across the enterprise.” Start with one recurring review packet whose inputs, reviewers, outputs, and acceptance criteria are known.

### Production Boundaries

- `Multi Format` is enough when ordinary chunks satisfy the retrieval target.
- BookRAG is appropriate when section, page, table/image context, document identity, or source reconstruction materially improves review.
- Current document relationships are context labels, not automatic retrieval paths.
- Current entities are document-scoped, not an enterprise master-data layer.
- Structured transactions, time series, telemetry, CAD, GIS, omics, images, and live state require other systems.
- Access control, privacy, consent, bank secrecy, export control, retention, legal hold, validation, and audit requirements belong to the production architecture.

## 日本語

### 現行製品が実際に返すもの

現行検索は `bnode.content` の意味類似検索から始まります。ヒットごとに、文書 ID、本文、上位章パス、ページ、元要素、取得できた表 HTML・画像文脈、文書内エンティティ、`updates`・`summary_of`・`supplement_to` などの文書関係ラベルを返せます。

これは人または外部アプリケーションが審査する根拠候補です。文書関係は追加情報であり、関連文書を自動検索する経路ではありません。エンティティの正規化も文書内に限定されます。

### 優先順位の付け方

各案件を、頻度、見落とし時の影響、長文書への依存、原典追跡の必要性、現行機能との適合、外部統合負荷の六項目で 1～5 点評価します。最初の五項目が高く、初期段階でリアルタイムデータや多数システムを必要としない案件から開始します。

### 用例一覧

| ID | 具体的業務 | 主な利用者 | 初期優先度 |
|---|---|---|---|
| FIN-01 | プロジェクトファイナンス年次与信レビュー | 与信アナリスト、与信委員会事務局 | A |
| FIN-02 | 金融規制変更の根拠レビュー | コンプライアンス、方針・統制責任者 | A |
| FIN-03 | 企業財産・利益保険の保険金審査 | 損害調査、カバレッジ法務 | A |
| MED-01 | 医療機器安全通知と院内手順のレビュー | 臨床工学、患者安全 | B |
| LIFE-01 | 医薬品バッチ逸脱・CAPA の根拠収集 | 品質調査、有資格審査者 | A |
| LIFE-02 | 臨床試験安全性レビュー準備 | メディカルモニター、薬物警戒 | B |
| FOOD-01 | 食品汚染・回収調査 | 食品安全、品質 | B |
| WATER-01 | 飲料水基準値逸脱レビュー | 水質責任者、研究所 | B |
| ENERGY-01 | 変圧器停止工事パッケージ準備 | 保全・停止工事技術者 | A |
| CHEM-01 | 化学プラント変更管理レビュー | プロセス安全、運転、技術 | A |
| SEMI-01 | 半導体歩留まり異常の文書根拠収集 | 工程・装置技術者 | A |
| AERO-01 | 航空宇宙要求変更の検証根拠 | システム・検証技術者 | B |
| SUPPLY-01 | 重要サプライヤー材料・工程変更 | サプライヤー品質、製品技術 | B |
| CLIMATE-01 | 洪水レジリエンス投資の根拠準備 | インフラ計画、リスク審査 | B |

A は現行のエビデンスパッケージで限定的な実証が可能です。B は文書検索に価値がありますが、正式な適用性データとの統合が業務利用の前提です。

## 具体的用例

### FIN-01: プロジェクトファイナンス年次与信レビュー

- **契機:** 発電所、LNG 基地、半導体工場、鉱山、データセンター、交通事業融資の年次レビュー。
- **文書:** 与信稟議、融資契約・コベナンツ、決算、独立技術者・環境報告、格付・市場資料、過去年次レビュー。
- **質問例:** DSCR 条項の定義・除外・治癒条項はどこか。最新の遅延・コスト超過を説明する根拠は何か。前回から変化した運転・規制・供給リスクは何か。
- **出力:** コベナンツ、定義、リスク説明、技術所見を章・ページ・表・文書関係付きで返す。
- **外部依存:** 与信先・融資 ID、エクスポージャー、財務分析、計算、市場データ、承認状態、権限。
- **評価:** 委員会資料の根拠収集時間、根拠採用率、誤スコープ、二次審査で発見された重要根拠。
- **非対象:** 格付、コベナンツ計算、期待損失、価格、与信承認、投資推奨。

### FIN-02: 金融規制変更レビュー

- **契機:** 資本、流動性、オペレーショナルレジリエンス、消費者保護、モデルリスク、決済、保険、開示規則の新設・改訂。
- **文書:** 新旧規則、FAQ、社内方針、統制記述、業務手順、過去の法務・コンプライアンス解釈、監査所見。
- **質問例:** 新しい義務、閾値、例外、期限はどこか。どの社内方針が同じ対象を扱うか。
- **出力:** 新規則の条項と関連する社内方針・統制の候補箇所を、版・章・ページ付きで返す。
- **外部依存:** 規制台帳、法人・法域、方針責任者、統制マッピング、導入状況、法的解釈、承認。
- **評価:** 初期影響パック作成時間、条項位置精度、方針責任者の採用率、誤一致。
- **非対象:** 法的解釈、適用性、統制十分性、適合性証明。

### FIN-03: 企業財産・利益保険の保険金審査

- **契機:** 火災、洪水、機械故障、サイバー、供給停止による産業保険事故。
- **文書:** 約款、明細、特約、免責、サブリミット、技術調査、事故・原因報告、修理見積、設備資料、利益損失請求、専門家報告。
- **質問例:** 対象設備・原因の補償を定義する特約はどこか。どの免責、待機期間、自己負担、限度額を確認すべきか。
- **出力:** 補償・事故根拠を条項階層、定義、ページ、元ブロック、文書関係付きで返す。
- **外部依存:** 保険対象 ID、保険期間、事故日、損害計算、準備金、不正管理、秘匿特権、決裁権限。
- **評価:** 争点一覧準備時間、法務による条項採用率、特約見落とし、重複検索工数。
- **非対象:** 補償判断、因果関係、損害評価、準備金、責任、不正、支払。

### MED-01: 医療機器安全通知と院内手順レビュー

- **契機:** メーカー・規制機関が安全通知、是正、禁忌、ソフトウェア更新を発行。
- **文書:** 安全通知、新旧使用説明、サービス通知、院内運用・洗浄・保全・エスカレーション手順、委員会決定、教育資料、インシデント。
- **質問例:** 対象モデル、版、アクセサリ、使用条件は何か。新しい警告、禁忌、保全、期限はどこか。
- **出力:** モデル・版の記述、警告文脈、院内手順候補を章・ページ・更新関係付きで返す。
- **外部依存:** 院内機器台帳、設置場所、ソフトウェア版、患者曝露、回収状態、保全記録、臨床承認、タスク管理。
- **評価:** 手順レビュー準備時間、モデル・版の正確性、関連手順の見落とし。
- **非対象:** 患者への安全性、使用停止、臨床リスク、回収完了、保全許可。

### LIFE-01: 医薬品バッチ逸脱・CAPA

- **契機:** バッチ、環境モニタリング、工程、設備が承認要件から逸脱。
- **文書:** SOP、製造指図、仕様、試験法、バリデーション、設備適格性・保全、逸脱、CAPA、変更管理、規制コミットメント。
- **質問例:** 事象時に適用された要件・合否基準は何か。同じ工程・設備・方法・故障モードの過去逸脱は何か。
- **出力:** 要件、方法、バリデーション、過去調査の根拠を文書・章・ページ・表付きで返す。
- **外部依存:** バッチ、設備、方法、製品版、発効日、試験データ、署名、業務状態、品質権限。
- **評価:** 根拠収集時間、採用率、旧版取得率、二者確認所見。
- **非対象:** 根本原因、製品影響、患者リスク、CAPA 十分性、バッチ処分・出荷、GxP 適合。

### LIFE-02: 臨床試験安全性レビュー

- **契機:** 重篤有害事象、集積傾向、定期安全性報告のレビュー。
- **文書:** プロトコル・改訂、治験薬概要書、参照安全性情報、統計解析計画、試験報告、安全性症例・集積報告、リスク管理、添付文書。
- **質問例:** 事象の定義、収集、重症度、解析方法は何か。既知・予期されるリスクはどこか。どの集団・用量・コホート・期間に属するか。
- **出力:** プロトコル、安全性、対象集団、方法、結果の根拠を試験 ID・章・ページ・表・改訂関係付きで返す。
- **外部依存:** 被験者データ、コーディング、曝露、割付、臨床状態、統計、参照版、盲検管理、決裁権限。
- **評価:** 根拠準備時間、改訂版誤り、採用引用、医学審査で判明した見落とし。
- **非対象:** 因果関係、予測性、シグナル、ベネフィット・リスク、用量変更、患者治療、報告判断。

### FOOD-01: 食品汚染・回収調査

- **契機:** 病原体、アレルゲン、化学物質、異物、表示問題を検出。
- **文書:** HACCP、製品・アレルゲン・衛生・出荷仕様、サンプリング・試験法、サプライヤー証明・監査、逸脱、苦情、回収、是正、規制・顧客要求。
- **質問例:** 適用された管理点、限度、サンプリング、出荷基準は何か。同じ原料・ライン・供給元・微生物の過去事例は何か。
- **出力:** 手順、限度、方法、サプライヤー、過去事例を章・ページ・表・出典付きで返す。
- **外部依存:** ロット系譜、在庫、出荷、供給ロット、試験結果、法域、顧客、案件管理、回収権限。
- **評価:** 調査パック作成時間、根拠採用率、旧版仕様、手順・供給文書の見落とし。
- **非対象:** 汚染源、対象ロット範囲、健康リスク、出荷、回収区分、公表。

### WATER-01: 飲料水基準値逸脱

- **契機:** 試験所またはオンライン測定が運用・社内・規制閾値を超過。
- **文書:** 許可・水質基準、採水計画、試験法、処理・異常運転手順、計器資料、過去逸脱・是正・規制報告、緊急・公表手順。
- **質問例:** 適用限度、平均期間、確認採水、報告規則は何か。この設備・測定法の手順はどこか。
- **出力:** 限度、方法、手順、過去事例を法域・文書・章・ページ・表付きで返す。
- **外部依存:** 現在の試験・センサーデータ、採水地点、設備状態、配水モデル、対象人口、許可範囲、事故業務。
- **評価:** 根拠パック時間、規則・方法位置精度、旧版手順、却下理由。
- **非対象:** 水の安全性、対象人口、処理調整、原因、適合性、公表。

### ENERGY-01: 変圧器停止工事パッケージ

- **契機:** 検査、油中ガス、リレー、過熱、漏油、OEM 通知を受けて停止工事を計画。
- **文書:** 本体・付属品資料、OEM 通知、検査・油分析・状態評価、過去保全・停止工事、保全・隔離・試験・復旧手順、安全・環境要件。
- **質問例:** どの所見・OEM 通知が作業を推奨するか。前提、注意、試験限度、復旧手順は何か。どの文書が旧指示を更新するか。
- **出力:** 作業範囲、警告、限度、検査、過去保全の候補根拠を章・ページ・表・画像・文書関係付きで返す。
- **外部依存:** 設備タグ、型式・製番、構成、状態データ、履歴、予備品、工程、開閉指令、許可、権限。
- **評価:** 技術者検索時間、採用率、誤型式・旧版資料、文書不足によるレビューコメント。
- **非対象:** 運転可否、停止要否、開閉・隔離、作業承認、試験合否、復旧。

### CHEM-01: 化学プラント変更管理

- **契機:** 材質、触媒、原料、制御設定、温度、リリーフ、手順を変更。
- **文書:** プロセス安全情報、運転限界、設備仕様、ベンダー資料、ハザード分析、過去 MOC、運転・起動・停止・緊急手順、検査、SDS、環境許可、事故・是正。
- **質問例:** 関連する限度、危険、材質適合、検査前提は何か。同じ設備・状態の過去 MOC は何か。
- **出力:** 限度、危険、手順、検査、許可、過去変更の候補根拠を正確な出典付きで返す。
- **外部依存:** 設備階層、タグ、P&ID、条件、物性、計算、責任者、完全性チェック、承認。
- **評価:** 初期収集時間、専門分野別採用率、文書見落とし、旧版手順・仕様。
- **非対象:** 影響網羅性、ハザード十分性、材質適合、安全計算、環境適合、MOC 承認。

### SEMI-01: 半導体歩留まり異常

- **契機:** 製品、工程、チャンバー、装置群、材料、供給ロットで歩留まり・欠陥が変化。
- **文書:** 工程・装置仕様、装置トラブル資料、管理計画、FMEA、認定・検証、技術・サプライヤー変更、過去異常・8D・是正。
- **質問例:** 欠陥・工程に関連する限度・故障モードは何か。異常前に装置・材料・レシピ変更が記録されたか。
- **出力:** 仕様、故障モード、トラブル、認定、変更、過去調査の根拠を工程・装置・製品文脈付きで返す。
- **外部依存:** ウェハマップ、ロット、レシピ、センサー、SPC、装置・チャンバー、材料系譜、実験、権限。
- **評価:** 文書根拠収集時間、採用率、誤製品・装置根拠、重複検索。
- **非対象:** 原因、封じ込め、レシピ変更、処分、因果、工程開放。

### AERO-01: 航空宇宙要求変更の検証根拠

- **契機:** システム要求、インターフェース、設計前提、HW/SW ベースライン、認証条件を変更。
- **文書:** システム・サブシステム要求、インターフェース・設計、安全評価、検証計画・解析・試験、不適合・異常、認証基準・適合手段・当局文書。
- **質問例:** 変更要求と前提・例外はどこか。関連する解析、試験、異常、認証根拠は何か。結果はどの版を使用したか。
- **出力:** 要求と検証・認証候補を文書 ID、章、ページ、表、更新関係付きで返す。
- **外部依存:** 正式要求 ID、ベースライン、構成発効、トレース、試験状態、安全分類、変更、輸出管理、承認。
- **評価:** 根拠準備時間、採用引用、誤ベースライン、出典位置の未解決。
- **非対象:** トレース完全性、インターフェース整合、検証完了、安全受容、設計承認、認証適合。

### SUPPLY-01: 重要サプライヤー材料・工程変更

- **契機:** 材料、配合、工程、工場、二次供給元、設備、仕様、検査法を変更。
- **文書:** 変更通知、購買・製品仕様、材料証明・試験、PPAP・認定・検証・初品、監査・是正、社内リスク・過去逸脱。
- **質問例:** どの特性、承認供給元、試験、工程前提が影響候補か。同じ材料・工場・工程の過去根拠は何か。
- **出力:** 仕様、認定、監査、変更、コミットメントの候補根拠を供給元・製品・文書出典付きで返す。
- **外部依存:** 供給元、部品、BOM、承認元、製品、顧客、工場、ロット、構成、購買、リスク、承認。
- **評価:** レビューパック準備時間、採用率、仕様見落とし、文書検索に起因する変更期間。
- **非対象:** 影響製品の網羅性、同等性、認定十分性、供給元・逸脱承認、製造使用。

### CLIMATE-01: 洪水レジリエンス投資

- **契機:** 都市、公益、港湾、保険、インフラ投資家が防潮・排水・移転・強靭化・復旧事業を検討。
- **文書:** 洪水・気候ハザード、設備脆弱性、技術案、環境・社会影響、土地利用・建築・水・緊急政策、過去災害・損害・復旧・事後検証、資金・保険・規制基準。
- **質問例:** 対象設備・人口、再現期間、シナリオ、前提は何か。便益を限定する不確実性は何か。どの政策・許可・資金・保険基準が必要か。
- **出力:** ハザード、脆弱性、前提、案、政策、過去事例を地域記述・シナリオ・章・ページ・表付きで返す。
- **外部依存:** GIS、気候モデル、設備台帳、人口、技術・経済計算、代替案、法的権限、予算、承認。
- **評価:** 意思決定資料準備時間、出典・前提位置精度、採用率、専門審査で判明した不足。
- **非対象:** 洪水予測、設計再現期間、費用便益、環境承認、保険料、資金配分、事業選定。

### 導入順序

1. 一つの業務、一つの審査者群、限定文書集合を選ぶ。
2. 完了案件から実質問 30～100 件を作る。
3. 有資格者が期待する原文箇所を正解として付ける。
4. Recall、出典位置精度、根拠採用率、時間短縮を測る。
5. 解析、検索、メタデータ、旧版、外部統合不足による失敗を分類する。
6. エビデンス層が合意基準を満たした後に ID・業務統合を追加する。

「全社知識と会話」から始めず、入力、審査者、出力、合否基準が明確な一つの反復レビューパックから始めます。

### 本番境界

- 通常チャンクで目標を満たす場合は `Multi Format` で十分。
- 章、ページ、表・画像、文書 ID、元要素が審査を改善する場合に BookRAG を使う。
- 文書関係は文脈ラベルであり、自動検索経路ではない。
- エンティティは文書内であり、企業マスターデータではない。
- 取引、時系列、テレメトリ、CAD、GIS、オミクス、画像、ライブ状態は別システムが必要。
- 権限、プライバシー、同意、銀行秘密、輸出管理、保存、リーガルホールド、バリデーション、監査は本番アーキテクチャで実装する。
