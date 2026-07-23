# BookRAG for Civilization-Critical Industries / 文明基盤産業向け BookRAG

This document defines the strategic industrial role of EVSUI's `multi_format_bookrag` mode. Its scope is not limited to factories or “heavy industry.” It covers the systems that determine how civilization allocates capital, protects life, produces food and energy, transforms materials, computes and communicates, moves people and goods, governs risk, and responds to planetary change.

本書は、EVSUI の `multi_format_bookrag` モードが担う戦略的な産業上の役割を定義します。対象は工場や「重工業」だけではありません。資本配分、生命保護、食料・エネルギー生産、素材転換、計算・通信、人流・物流、リスク統治、地球規模変化への対応を支える文明基盤全体です。

## English

### Strategic Thesis

BookRAG should not be sold as another chatbot for documents. Its strongest role is an evidence layer for decisions inside civilization-critical systems.

These systems share four characteristics:

- A decision can affect many people, large amounts of capital, critical assets, or the environment.
- The governing evidence is distributed across long, structured, versioned documents.
- Definitions, exceptions, tables, warnings, assumptions, and document applicability matter as much as semantic similarity.
- A qualified person or governed institution remains accountable for the final decision.

The strategic question is therefore not:

```text
Which industries have many PDFs?
```

It is:

```text
Where does slow, fragmented, or context-free evidence retrieval
create systemic risk, delay essential work, waste scarce expertise,
or weaken society's ability to invest, build, heal, feed, and adapt?
```

BookRAG is useful when it shortens the path from a question to reviewable source evidence. It is not a substitute for professional judgment, scientific validation, engineering calculation, real-time control, or a system of record.

### The Ten Civilization-Scale Systems

| Civilization-scale system | Industries and institutions | Decisions shaped by documents | Why the system matters globally |
|---|---|---|---|
| Capital and trust | Banking, central banking, capital markets, insurance, payments, clearing, audit, financial regulation | Credit, investment, capital, liquidity, coverage, conduct, model risk, recovery, and regulatory evidence | Determines which companies, infrastructure, technologies, and countries can finance growth and absorb shocks |
| Health and life | Healthcare, public health, pharmaceuticals, biotechnology, diagnostics, medical devices, research institutes | Clinical governance, research, safety, benefit-risk, quality, validation, regulatory, and emergency-health evidence | Determines survival, healthy life expectancy, epidemic resilience, and the pace at which biological science becomes trusted care |
| Food, agriculture, and water | Farming, agricultural inputs, food processing, fisheries, water utilities, irrigation, veterinary and biosecurity agencies | Crop and animal health, food safety, water quality, resource allocation, traceability, incident, and regulatory evidence | Determines whether populations can eat, drink, and withstand climate, disease, and supply shocks |
| Energy | Electric grids, nuclear, renewables, storage, oil, gas, LNG, hydrogen, fusion, and energy regulation | Operating limits, outage work, asset integrity, safety, market rules, project approval, and incident evidence | Every digital, industrial, medical, transport, and household system depends on reliable and affordable energy |
| Materials and the physical economy | Mining, critical minerals, chemicals, steel, nonferrous metals, cement, glass, pulp, recycling, and waste | Resource assessment, process safety, quality, environmental permits, changes, shutdowns, and supplier evidence | Converts planetary resources into the materials required for cities, energy transition, defense, transport, and technology |
| Compute and communication | Semiconductors, AI infrastructure, cloud, data centers, telecom, cybersecurity, quantum and photonics | Process and product changes, qualification, reliability, security, capacity, service continuity, and supplier evidence | Controls the world's ability to calculate, coordinate, communicate, automate, and create new knowledge |
| Production and mobility | Advanced manufacturing, robotics, automotive, batteries, aerospace, space, shipbuilding, rail, ports, logistics | Requirements, design verification, configuration, maintenance, quality, certification, and operational evidence | Turns science and capital into physical capability and connects global production, trade, and movement |
| Built environment and human capability | Construction, civil engineering, housing, cities, universities, vocational education, research and accreditation institutions | Building and infrastructure assurance, codes, project change, research governance, accreditation, technical qualification, and knowledge-transfer evidence | Shapes where people live and work, the safety and carbon footprint of cities, and whether societies can reproduce scarce expertise |
| Security, governance, and standards | Government, regulators, standards bodies, emergency services, defense, civil protection, and courts | Policy, legal authority, standards, procurement, assurance, readiness, investigation, and public accountability | Establishes the rules, legitimacy, security, and coordinated response on which every other system relies |
| Climate, environment, and resilience | Climate science, meteorology, environmental agencies, carbon markets, adaptation programs, disaster risk and insurers | Environmental assessment, emissions, adaptation, hazards, resilience investment, recovery, and loss evidence | Determines whether economic and social systems can remain viable under planetary constraints and extreme events |

These systems are interdependent. A semiconductor fab depends on finance, water, power, chemicals, logistics, telecommunications, skilled labor, and public authority. A hospital depends on all of those plus pharmaceutical and medical-device supply chains. Strategic BookRAG applications should therefore preserve document boundaries while allowing a host application to coordinate evidence across systems.

### Where BookRAG Has Strategic Leverage

A candidate use case should be scored on six dimensions:

| Dimension | Strategic question |
|---|---|
| Consequence | What happens if relevant evidence is missed, obsolete, or stripped of context? |
| Evidence complexity | Are decisions governed by long documents, nested sections, tables, figures, definitions, exceptions, and revisions? |
| Expert scarcity | Are highly trained people spending time searching and reconstructing evidence instead of deciding or designing? |
| Recurrence | Does the evidence task repeat across assets, cases, products, reporting periods, projects, or regulatory cycles? |
| Traceability | Must another person, auditor, regulator, scientist, engineer, or court return to the original source? |
| Integration feasibility | Can authoritative identity, applicability, permissions, lifecycle state, and approval data be supplied by existing systems? |

The strongest opportunities score high on all six. A large document collection alone is not a market.

### Current EVSUI Capability

Current processing:

```text
documents
  -> Unstructured parsing and optional enrichments
  -> document catalog (bdoc)
  -> source blocks (bblk)
  -> section/tree nodes (bnode)
  -> optional raw audit rows and document-scoped entity metadata
  -> governed document relationships (bdrel)
  -> vector index over bnode.content
```

Current retrieval:

```text
question
  -> semantic similarity search over bnode.content
  -> matched nodes
  -> ancestor section chain + page/source-block reconstruction
  -> optional table/image/entity context and document-relation labels
  -> structured evidence packages
  -> qualified reviewer or governed downstream application
```

Current BookRAG enriches a semantic-search result with document structure and provenance. It does not automatically traverse an enterprise graph, retrieve every affected document, resolve entities across documents, reconcile revisions, run domain calculations, detect contradictions, or verify that every generated claim is supported.

### Six Strategic Missions

#### Mission 1: Govern Capital and Systemic Risk

**Actors:** commercial and central banks, securities firms, exchanges, clearing and payment operators, asset managers, insurers, rating agencies, auditors, supervisors, and financial ministries.

**Evidence:** prudential rules, supervisory notices, internal policies, credit papers, covenants, issuer disclosures, prospectuses, research, model methodology and validation, product terms, claims, recovery plans, and operational-incident reports.

**BookRAG output:** a review packet containing the relevant disclosure, definition, exception, assumption, limit, control, or finding with entity, period, document, section, page, table, and issue/update context.

**High-value workflows:**

- Credit committee and project-finance evidence preparation
- Investment and issuer research over recurring disclosures
- Regulatory-change and policy/control review
- Model-risk and model-change evidence
- Insurance underwriting, wording, and claims review
- Payment, clearing, cyber, fraud operations, and resilience investigations
- Climate and nature-risk disclosure evidence

**Business measures:** time to evidence, analyst throughput, evidence acceptance, missed-material-evidence rate, review findings, committee-cycle time, and repeated search effort.

**Boundary:** BookRAG does not calculate exposure, capital, liquidity, valuation, expected loss, reserves, suitability, fraud, coverage, or market risk. It does not approve credit, execute a transaction, settle a claim, determine compliance, or provide investment advice.

#### Mission 2: Protect Human Life and Advance Biology

**Actors:** hospitals, public-health agencies, pharmaceutical and biotechnology companies, diagnostics and medical-device makers, research institutes, laboratories, contract research organizations, and regulators.

**Evidence:** clinical guidelines, care pathways, formularies, device instructions, research protocols, preclinical and clinical reports, investigator brochures, safety narratives and aggregate reports, labels, risk-management plans, CMC, validation, specifications, deviations, CAPA, QMS records, submissions, and public-health guidance.

**BookRAG output:** attributable recommendations, populations, methods, endpoints, findings, limitations, contraindications, specifications, and commitments with study/product/document identity, section, page, table/source block, and update context.

**High-value workflows:**

- Clinical-guideline and care-policy governance
- Research and translational-science evidence review
- Clinical-development and study-review preparation
- Pharmacovigilance and medical-safety evidence assembly
- Regulatory submission and commitment review
- Deviation, CAPA, validation, and inspection preparation
- Patient-safety and public-health incident review

**Business measures:** review preparation time, source-locator accuracy, evidence acceptance, missed-material-evidence rate, second-person review time, rework, and inspection or submission findings.

**Boundary:** BookRAG does not diagnose, recommend treatment, determine patient applicability, assess causality, calculate dose, evaluate benefit-risk, detect a safety signal, release product, establish GxP compliance, or make a regulatory decision.

#### Mission 3: Secure Food, Water, and Biological Resilience

**Actors:** agricultural producers, seed and crop-science companies, fertilizer and animal-health companies, food manufacturers, fisheries, water utilities, laboratories, public-health and biosecurity agencies, and development institutions.

**Evidence:** agronomic protocols, seed and input specifications, veterinary guidance, disease and pest reports, food-safety plans, HACCP records, water-treatment procedures, laboratory methods, quality results, permits, environmental studies, recall reports, drought plans, and emergency guidance.

**BookRAG output:** source-grounded evidence for a disease, contamination, treatment, process, water-quality, recall, drought, or biosecurity review, preserving geography, species or population, product, method, limit, date, and regulatory context.

**High-value workflows:**

- Crop, livestock, and aquaculture disease evidence
- Food-safety deviation and recall investigation
- Water-quality and treatment-procedure review
- Drought, irrigation, and watershed planning evidence
- Agricultural-input and supplier qualification
- Biosecurity and zoonotic-event preparedness

**Business measures:** incident triage time, recall or corrective-action cycle, evidence completeness findings, water-quality review time, expert workload, and recurrence.

**Boundary:** BookRAG does not diagnose a field or population condition, optimize irrigation, forecast yield, control treatment, certify food or water safety, or replace laboratory, geospatial, sensor, and epidemiological analysis.

#### Mission 4: Keep Energy and Material Systems Safe

**Actors:** grid, nuclear, renewable, storage, oil, gas, LNG, hydrogen, mining, chemical, steel, cement, materials, recycling, and environmental organizations.

**Evidence:** operating and maintenance procedures, safety cases, process-safety information, operating envelopes, OEM bulletins, inspection and integrity reports, outage and turnaround packages, MOC, mine and geotechnical reports, quality specifications, permits, incident reports, and regulatory commitments.

**BookRAG output:** an evidence package for an asset condition, work order, change, deviation, outage, project, or event with section, page, source block, table/image context, and known update or supplement relationships.

**High-value workflows:**

- Operating-limit and controlled-procedure review
- Outage, shutdown, and turnaround preparation
- Asset-integrity and inspection evidence
- Process-safety and management-of-change review
- Failure, event, and root-cause investigation
- Critical-mineral and energy-project technical review
- Environmental-permit and transition-project evidence

**Business measures:** search time, review-cycle time, wrong-procedure selections, missed-impact findings, repeat events, outage preparation effort, and regulator/auditor evidence acceptance.

**Boundary:** BookRAG does not determine operability, control a plant, interpret P&IDs as a complete engineering graph, calculate process safety, prove change-impact completeness, approve a mine or energy project, or replace real-time operational systems.

#### Mission 5: Preserve Compute, Production, and Supply-Chain Sovereignty

**Actors:** semiconductor fabs, equipment makers, AI and cloud infrastructure, telecom, quantum and photonics programs, advanced manufacturers, robotics, batteries, automotive, aerospace, space, shipbuilding, construction and civil engineering, rail, ports, and strategic suppliers.

**Evidence:** requirements, process and product specifications, tool manuals, control plans, FMEA, qualification and validation reports, engineering changes, supplier notices, interface documents, certification evidence, service bulletins, field reports, cybersecurity procedures, and capacity or continuity plans.

**BookRAG output:** candidate evidence for an excursion, design or process change, requirement, qualification, anomaly, supplier issue, maintenance event, or service disruption with configuration/document context and exact source locators.

**High-value workflows:**

- Semiconductor yield-excursion and tool/process change review
- AI infrastructure, data-center, and telecom continuity evidence
- Product and supplier change-impact preparation
- Requirement-to-test and certification evidence preparation
- Warranty, field-failure, and anomaly investigation
- Maintenance and service-bulletin review
- Building, infrastructure, and major-project assurance evidence
- Standards-based technical training and workforce-qualification evidence
- Strategic supplier and technology due diligence
- Expert knowledge continuity across long programs

**Business measures:** investigation time, qualification-cycle time, unresolved requirements, supplier-review time, downtime, rework, field-event recurrence, and expert interruption load.

**Boundary:** BookRAG does not analyze wafer maps, telemetry, CAD, source code, network traffic, or causal process relationships; establish configuration effectivity; guarantee requirement coverage; approve a design; or operate digital or physical infrastructure.

#### Mission 6: Strengthen Planetary Governance and Resilience

**Actors:** governments, regulators, standards bodies, cities, emergency services, defense and civil-protection organizations, climate and meteorological agencies, multilateral institutions, infrastructure operators, and insurers.

**Evidence:** laws, regulations, standards, public policy, procurement and assurance documents, hazard and climate assessments, emergency plans, mutual-aid procedures, resilience strategies, environmental impact studies, after-action reports, recovery plans, and public inquiries.

**BookRAG output:** traceable policy, authority, obligation, hazard, assumption, preparedness, and recovery evidence for a reviewer, planner, investigator, or governed public workflow.

**High-value workflows:**

- Regulatory and standards evidence services
- Critical-infrastructure assurance and dependency review
- Disaster preparedness and after-action evidence
- Climate adaptation and resilience-investment review
- Environmental assessment and public-accountability evidence
- Strategic procurement and industrial-policy review
- Defense, civil-protection, and continuity planning support

**Business measures:** policy-review time, response-plan preparation, unresolved control or dependency findings, evidence reuse, auditability, public-inquiry preparation, and recovery learning.

**Boundary:** BookRAG does not create legal authority, predict disasters, command emergency response, classify security threats, determine environmental approval, allocate public resources, or replace democratic and accountable decision processes.

### Cross-System Workflows

| Workflow | Reusable BookRAG role | Systems commonly required around BookRAG |
|---|---|---|
| Change-impact review | Retrieve requirements, policies, procedures, warnings, tests, commitments, and prior changes for human review | PLM, configuration, policy, QMS, regulatory, asset, and workflow systems |
| Incident and investigation evidence | Assemble prior findings, applicable limits, procedures, reports, and corrective actions | Case management, EAM/CMMS, QMS, safety, claims, clinical, cyber, or event systems |
| Controlled procedure access | Return the relevant procedure with prerequisites, cautions, scope, and source | DMS plus identity, asset/product/patient applicability, revision, and authorization |
| Verification and assurance | Provide requirement, test, analysis, control, and certification evidence candidates | Requirements, test, model, validation, audit, and certification systems |
| Regulatory evidence | Retrieve rules, definitions, obligations, exceptions, submissions, commitments, and internal controls | Regulatory inventory, GRC, RIM, policy, legal, and approval systems |
| Technical and institutional due diligence | Triage reports, disclosures, specifications, permits, contracts, and supplier evidence | Data room, project, finance, legal, supply-chain, and specialist-review workflows |
| Knowledge continuity | Recover documented rationale, exception, lesson, and prior resolution with provenance | Knowledge governance, training, document ownership, and expert review |

### Strategic Market Entry

#### Wave 1: Evidence products that fit the current implementation

Enter through bounded, human-reviewed workflows where document structure and provenance create immediate value:

1. Financial, credit, risk, and regulatory evidence preparation
2. Life-science quality, regulatory, safety, and validation review
3. Energy and industrial procedure, maintenance, and incident evidence
4. Semiconductor and advanced-manufacturing investigation and change-review preparation
5. Requirements, certification, and supplier-document evidence
6. Food, water, environmental, and public-safety investigation packets

The sellable unit is not “chat with all enterprise knowledge.” It is a reviewable evidence package for one defined decision workflow.

#### Wave 2: Integrated decision-support workflows

Add value by connecting authoritative identifiers and lifecycle states:

- Customer, legal entity, exposure, position, product, jurisdiction, and reporting period
- Patient or population, study, site, indication, product version, and approved label
- Field, species, batch, watershed, geography, method, and regulatory limit
- Asset, tag, configuration, material, process step, supplier, and revision
- Requirement, hazard, control, test, finding, corrective action, and approval state

At this stage, BookRAG remains the document evidence layer. The host application supplies identity, permissions, applicability, workflow, deterministic rules, and decisions.

#### Wave 3: Claims the current product must not make

- Autonomous financial, legal, clinical, scientific, engineering, safety, military, or public-policy decisions
- Real-time process, grid, traffic, treatment, trading, payment, or emergency control
- Prediction from market, patient, sensor, telemetry, weather, geospatial, or time-series data
- Guaranteed completeness of compliance, change impact, requirements, or dependency analysis
- Automatic engineering, financial, clinical, climate, or risk calculations
- A self-maintaining cross-enterprise knowledge graph

### Relationship to Systems of Record

```text
controlled document and records management
banking / risk / finance / trading / payment / insurance / regulatory reporting
EHR / clinical knowledge / CTMS / eTMF / safety / RIM / QMS / LIMS
agriculture / laboratory / food safety / water / geospatial systems
PLM / requirements / configuration / supplier management
EAM / CMMS / work management / MES / historian
legal / GRC / policy / emergency and case management
        |
        | approved documents + authoritative identity and applicability
        v
BookRAG document evidence layer
        |
        | structured evidence packages
        v
qualified analyst, clinician, scientist, engineer, operator,
investigator, regulator, or governed workflow
```

BookRAG should complement these systems, not replace them. The host application must provide access control, identity, jurisdiction, asset/product/population applicability, version effectivity, workflow state, and approval authority.

### Production Doctrine

Before production use:

- Evaluate recall for material evidence, not only precision on easy questions.
- Verify section hierarchy, page ranges, tables, image context, and source locators.
- Test obsolete, conflicting, missing, restricted, and low-quality evidence.
- Obtain applicability and lifecycle state from authoritative systems.
- Measure reviewer acceptance and rejection reasons.
- Enforce role-based access, confidentiality, privacy, consent, de-identification, bank secrecy, export control, retention, legal hold, and audit requirements.
- Measure total parsing, embedding, storage, integration, and review cost per completed business task.
- Track time to evidence, review throughput, rework, missed findings, repeat incidents, and decision-cycle time.

Section construction uses Unstructured structure metadata where available and a Japanese-oriented local fallback profile. Non-Japanese, scanned, handwritten, highly graphical, formula-heavy, and drawing-centric documents require representative evaluation.

### When Not To Use BookRAG

Use plain `Multi Format` or a different system when:

- The content is short, flat, and low risk.
- FAQ or ordinary semantic search meets the business metric.
- The primary evidence is structured transactions, time series, telemetry, imagery, CAD, GIS, omics, source code, or live state rather than documents.
- The task requires deterministic calculation, real-time action, or guaranteed graph completeness.
- Approved identity, version, access, and applicability cannot be maintained.
- No qualified person or governed application will review the retrieved evidence.

### Product Positioning

- `Multi Format`: ordinary document search and low-risk grounded Q&A.
- `Multi-Format BookRAG`: semantic retrieval plus document identity, section hierarchy, pages, source elements, and optional table/image/entity context.
- Integrated BookRAG application: a bounded evidence workflow connected to authoritative domain systems.

In one sentence:

> BookRAG is for decisions where evidence is expensive to find, context is dangerous to lose, and responsibility cannot be delegated to a language model.

## 日本語

### 戦略的な位置づけ

BookRAG は「文書と会話するチャットボット」として売るべきではありません。最も強い役割は、文明基盤システムにおける意思決定のためのエビデンス層です。

文明基盤システムには共通点があります。

- 判断が多数の人命、巨額資本、重要設備、環境に影響する。
- 根拠が長大で構造化され、版管理された文書に分散している。
- 意味の類似だけでなく、定義、例外、表、警告、前提、適用性が重要である。
- 最終判断の責任を、有資格者または統治された機関が負う。

問うべきなのは「PDF が多い産業はどこか」ではありません。

```text
根拠の探索が遅い、分断されている、文脈を失っていることが、
どこでシステミックリスク、重要業務の遅延、希少専門家の浪費を生み、
社会の投資・建設・治療・食料供給・適応能力を弱めているか。
```

BookRAG は、質問から確認可能な原典までの時間を短縮するときに価値を持ちます。専門判断、科学的検証、技術計算、リアルタイム制御、正式な記録システムを置き換えません。

### 十の文明基盤システム

| 文明基盤システム | 産業・機関 | 文書が支える判断 | 地球規模で重要な理由 |
|---|---|---|---|
| 資本と信頼 | 銀行、中央銀行、資本市場、保険、決済、清算、監査、金融規制 | 与信、投資、資本、流動性、補償、コンダクト、モデルリスク、再建・規制根拠 | 企業、インフラ、技術、国家が成長を資金調達し、ショックを吸収できるかを決める |
| 健康と生命 | 医療、公衆衛生、製薬、バイオ、診断、医療機器、研究機関 | 臨床ガバナンス、研究、安全性、ベネフィット・リスク、品質、申請、緊急医療根拠 | 生存、健康寿命、感染症への強靭性、生物科学を信頼できる医療へ転換する速度を決める |
| 食料・農業・水 | 農業、農業資材、食品、水産、水道、灌漑、獣医・防疫機関 | 作物・家畜衛生、食品安全、水質、資源配分、追跡、事故、規制根拠 | 気候、疾病、供給ショック下でも人々が食べ、飲めるかを決める |
| エネルギー | 電力網、原子力、再エネ、蓄電、石油、ガス、LNG、水素、核融合、規制 | 運転限界、停止工事、健全性、安全、市場規則、事業承認、事故根拠 | デジタル、産業、医療、交通、家庭の全システムが安定し手頃なエネルギーに依存する |
| 素材と物理経済 | 鉱業、重要鉱物、化学、鉄鋼、非鉄、セメント、ガラス、紙、リサイクル、廃棄物 | 資源評価、安全、品質、環境許可、変更、定修、サプライヤー根拠 | 地球資源を都市、脱炭素、防衛、交通、技術に必要な素材へ転換する |
| 算力と通信 | 半導体、AI 基盤、クラウド、データセンター、通信、サイバー、量子、フォトニクス | 工程・製品変更、認定、信頼性、セキュリティ、容量、継続性、供給根拠 | 世界の計算、連携、通信、自動化、知識創造能力を決める |
| 生産と移動 | 先端製造、ロボット、自動車、電池、航空宇宙、宇宙、造船、鉄道、港湾、物流 | 要求、設計検証、構成、保全、品質、認証、運用根拠 | 科学と資本を物理能力へ変換し、世界の生産、貿易、人流・物流を接続する |
| 建築環境と人材能力 | 建設、土木、住宅、都市、大学、職業教育、研究・認定機関 | 建築・インフラ保証、法規、事業変更、研究統治、認定、技術資格、知識継承根拠 | 人々が暮らし働く環境、都市の安全性と炭素負荷、希少専門性を社会が再生産できるかを決める |
| 安全保障・統治・標準 | 政府、規制機関、標準化、緊急サービス、防衛、民間防護、司法 | 政策、法的権限、標準、調達、保証、即応、調査、説明責任 | 他の全システムを支えるルール、正統性、安全、協調対応を形成する |
| 気候・環境・レジリエンス | 気候科学、気象、環境行政、炭素市場、適応、防災、保険 | 環境評価、排出、適応、ハザード、投資、復旧、損失根拠 | 地球の制約と極端現象の中で経済・社会システムが存続できるかを決める |

これらは相互依存します。半導体工場は金融、水、電力、化学、物流、通信、人材、行政に依存し、病院はさらに医薬品・医療機器供給網に依存します。BookRAG は文書境界を保持し、外部アプリケーションが複数システムの根拠を統合できるようにする必要があります。

### 戦略的レバレッジの評価

| 評価軸 | 戦略的な問い |
|---|---|
| 影響 | 根拠の見落とし、旧版、文脈欠落が何を引き起こすか |
| 根拠の複雑性 | 長文、章、表、図、定義、例外、改訂に支配されるか |
| 専門家の希少性 | 高度人材が判断・設計ではなく検索に時間を使っているか |
| 反復性 | 設備、案件、製品、報告期、プロジェクト、規制周期で繰り返すか |
| 追跡性 | 監査人、規制者、科学者、技術者、裁判所が原典へ戻る必要があるか |
| 統合可能性 | 正式 ID、適用性、権限、状態、承認を既存システムから提供できるか |

文書量が多いだけでは市場になりません。六軸すべてが高い用途が戦略的な市場です。

### 現行 EVSUI の能力

```text
文書
  -> Unstructured 解析と任意 enrichment
  -> 文書台帳 (bdoc)
  -> 元ブロック (bblk)
  -> 章・ツリーノード (bnode)
  -> 任意の raw 監査行と文書内エンティティ
  -> 管理された文書関係 (bdrel)
  -> bnode.content のベクトル索引
```

```text
質問
  -> bnode.content の意味類似検索
  -> ヒットしたノード
  -> 上位章、ページ、元ブロックの再構成
  -> 任意の表・画像・エンティティ文脈と文書関係ラベル
  -> 構造化エビデンスパッケージ
  -> 有資格者または統治された外部アプリケーション
```

現行 BookRAG は検索結果に文書構造と出典を付加します。企業グラフの自動探索、影響文書の網羅取得、文書横断の名寄せ、改訂照合、専門計算、矛盾検出、生成主張の自動根拠検証は行いません。

### 六つの戦略ミッション

#### 1. 資本とシステミックリスクを統治する

銀行、中央銀行、証券、取引所、清算・決済、資産運用、保険、格付、監査、監督機関を対象に、健全性規制、方針、与信稟議、コベナンツ、発行体開示、目論見書、調査、モデル文書、商品約款、保険金、再建計画、業務事故から、法人・期間・章・ページ・表・更新関係付きの根拠を返します。

主要業務は、与信委員会、プロジェクトファイナンス、投資調査、規制変更、方針・統制、モデルリスク、保険引受・保険金、決済・サイバー・オペレーショナルレジリエンス、気候・自然リスク開示です。

BookRAG はエクスポージャー、資本、流動性、評価、期待損失、準備金、適合性、不正、補償、マーケットリスクを計算せず、与信、取引、決済、保険金、適合性、投資判断を行いません。

#### 2. 人命を守り、生物科学を前進させる

病院、公衆衛生、製薬、バイオ、診断、医療機器、研究機関、研究所、CRO、規制機関を対象に、診療ガイドライン、ケアパス、研究計画、非臨床・臨床報告、安全性報告、添付文書、リスク管理、CMC、バリデーション、仕様、逸脱、CAPA、QMS、申請資料から、対象集団・試験・製品・章・ページ・表付きの根拠を返します。

主要業務は、ガイドライン統治、研究審査、臨床開発、薬物警戒、メディカルセーフティ、申請・コミットメント、逸脱・CAPA、バリデーション、査察、患者安全、公衆衛生事象です。

BookRAG は診断、治療推奨、患者適用性、因果関係、用量、ベネフィット・リスク、安全性シグナル、製品出荷、GxP 適合、規制判断を行いません。

#### 3. 食料・水・生物学的レジリエンスを確保する

農業、種苗、農業資材、動物薬、食品、水産、水道、研究所、防疫、公衆衛生、開発機関を対象に、栽培・獣医手順、疾病・害虫報告、HACCP、水処理、試験法、品質結果、許可、環境調査、回収、干ばつ計画、防疫指針から、地域・種・製品・方法・限度・日付・規制文脈付きの根拠を返します。

主要業務は、作物・家畜・水産疾病、食品安全・回収、水質・処理手順、干ばつ・灌漑、農業資材・サプライヤー審査、防疫・人獣共通感染症準備です。

BookRAG は圃場・集団の診断、灌漑最適化、収量予測、処理制御、食品・水の安全認証を行わず、研究所、地理空間、センサー、疫学解析を置き換えません。

#### 4. エネルギーと素材システムを安全に維持する

電力、原子力、再エネ、蓄電、石油、ガス、LNG、水素、鉱業、化学、鉄鋼、セメント、素材、リサイクルを対象に、運転・保全手順、安全解析、運転限界、OEM 通知、検査、停止工事、MOC、地質・地盤、品質、許認可、事故報告から、設備・変更・事象に関する章・ページ・表・画像・更新関係付きの根拠を返します。

主要業務は、運転限界、受控手順、停止工事、健全性、プロセス安全、変更管理、事故・原因調査、重要鉱物・エネルギー事業審査、環境許可です。

BookRAG は運転可否、プラント制御、P&ID の完全グラフ化、安全計算、影響網羅性、鉱山・エネルギー事業承認を行いません。

#### 5. 算力・生産・サプライチェーン主権を守る

半導体、製造装置、AI・クラウド、データセンター、通信、量子、フォトニクス、先端製造、ロボット、電池、自動車、航空宇宙、宇宙、造船、建設・土木、鉄道、港湾、戦略サプライヤーを対象に、要求、仕様、装置資料、FMEA、認定、検証、変更、サプライヤー通知、インターフェース、認証、サービス通知、現場報告、サイバー手順から、異常・変更・要求・供給問題の根拠を返します。

主要業務は、半導体異常・工程変更、AI 基盤・通信継続性、製品・サプライヤー変更、要求・試験・認証、保証・市場不具合、保全、建築・インフラ・大型事業保証、標準に基づく技術教育・資格根拠、技術 DD、長期プログラムの知識継承です。

BookRAG はウェハマップ、テレメトリ、CAD、コード、通信トラフィック、因果工程を解析せず、構成発効、要求カバレッジ、設計承認、インフラ運用を行いません。

#### 6. 地球規模の統治とレジリエンスを強化する

政府、規制機関、標準化、都市、緊急サービス、防衛・民間防護、気候・気象、国際機関、インフラ、保険を対象に、法令、標準、政策、調達、保証、気候・ハザード評価、緊急計画、相互支援、適応、環境影響、事後検証、復旧、公的調査から追跡可能な根拠を返します。

主要業務は、規制・標準、重要インフラ保証、防災・事後検証、気候適応投資、環境評価、産業政策・戦略調達、防衛・民間防護・事業継続です。

BookRAG は法的権限を創設せず、災害を予測せず、緊急対応を指揮せず、脅威分類、環境承認、公共資源配分、民主的意思決定を代替しません。

### 産業横断ワークフロー

| 業務 | BookRAG の共通役割 | 周辺に必要なシステム |
|---|---|---|
| 変更影響審査 | 要求、方針、手順、警告、試験、コミットメント、過去変更を審査候補として返す | PLM、構成、方針、QMS、規制、設備、ワークフロー |
| 事故・調査 | 過去所見、限度、手順、報告、是正措置を集約する | 案件管理、EAM、QMS、安全、保険金、臨床、サイバー、事故システム |
| 受控手順検索 | 前提、注意、適用範囲、原典付きの手順を返す | DMS、本人・設備・製品・患者適用性、版、権限 |
| 検証・保証 | 要求、試験、解析、統制、認証の根拠候補を提供する | 要求、試験、モデル、バリデーション、監査、認証 |
| 規制エビデンス | 規則、定義、義務、例外、申請、コミットメント、統制を返す | 規制台帳、GRC、RIM、方針、法務、承認 |
| 技術・制度 DD | 報告、開示、仕様、許可、契約、サプライヤー根拠を一次選別する | データルーム、事業、金融、法務、供給網、専門家審査 |
| 知識継承 | 判断理由、例外、教訓、過去解決を出典付きで再利用する | 知識統治、教育、文書責任者、専門家審査 |

### 戦略的な市場参入

#### Wave 1: 現行実装に適合するエビデンス製品

1. 金融・与信・リスク・規制エビデンス
2. 生命科学の品質・薬事・安全性・バリデーション審査
3. エネルギー・産業設備の手順・保全・事故根拠
4. 半導体・先端製造の異常・変更審査
5. 要求・認証・サプライヤー文書根拠
6. 食品・水・環境・公共安全の調査パッケージ

販売単位は「全社知識とのチャット」ではなく、一つの定義された意思決定業務に対する審査可能なエビデンスパッケージです。

#### Wave 2: 正式システムと統合した意思決定支援

- 顧客、法人、エクスポージャー、ポジション、商品、法域、報告期
- 患者・対象集団、試験、施設、適応、製品版、承認済み表示
- 圃場、種、ロット、流域、地域、方法、規制限度
- 設備、タグ、構成、材料、工程、サプライヤー、改訂
- 要求、危険、統制、試験、所見、是正、承認状態

BookRAG は文書エビデンス層に留まり、外部アプリケーションが ID、権限、適用性、業務フロー、決定論的ルール、最終判断を提供します。

#### Wave 3: 現行製品が主張しない能力

- 自律的な金融、法務、臨床、科学、技術、安全保障、政策判断
- 工程、電力網、交通、治療、取引、決済、緊急対応のリアルタイム制御
- 市場、患者、センサー、テレメトリ、気象、地理空間、時系列からの予測
- 適合性、変更影響、要求、依存関係の完全性保証
- 技術、金融、臨床、気候、リスクの自動計算
- 自律更新される企業横断知識グラフ

### 正式システムとの関係

```text
受控文書・記録管理
銀行 / リスク / 財務 / 取引 / 決済 / 保険 / 規制報告
電子カルテ / 臨床知識 / CTMS / eTMF / 安全性 / RIM / QMS / LIMS
農業 / 研究所 / 食品安全 / 水道 / 地理空間
PLM / 要求 / 構成 / サプライヤー管理
EAM / CMMS / 作業管理 / MES / ヒストリアン
法務 / GRC / 方針 / 緊急・案件管理
        |
        | 承認済み文書 + 正式 ID・適用性
        v
BookRAG 文書エビデンス層
        |
        | 構造化エビデンスパッケージ
        v
有資格アナリスト、臨床家、科学者、技術者、運転員、
調査者、規制者、統治された業務フロー
```

BookRAG は正式システムを補完し、置き換えません。外部アプリケーションが権限、ID、法域、設備・製品・対象集団の適用性、版の発効、業務状態、承認権限を提供します。

### 本番原則

- 簡単な質問の precision だけでなく、重要根拠の recall を評価する。
- 章、ページ、表、画像文脈、元要素の正確性を検証する。
- 旧版、矛盾、不足、権限制限、低品質文書での失敗動作を確認する。
- 適用性とライフサイクル状態は正式システムから取得する。
- 専門家による根拠採用率と却下理由を測定する。
- 権限、機密、プライバシー、同意、匿名化、銀行秘密、輸出管理、保存、リーガルホールド、監査要件を実装する。
- 1 業務当たりの解析、埋め込み、保存、統合、審査コストを測る。
- 根拠発見時間、審査処理量、手戻り、見落とし、事故再発、判断期間を追跡する。

章構築は Unstructured の構造情報を優先し、ローカルのフォールバックは日本語向けです。日本語以外、スキャン、手書き、図表・数式・図面中心の文書は代表資料で評価する必要があります。

### BookRAG を使わない場面

- 短く平坦で低リスクなコンテンツ。
- FAQ や通常の意味検索で業務指標を満たせる場合。
- 主な根拠が文書ではなく、取引、時系列、テレメトリ、画像、CAD、GIS、オミクス、コード、ライブ状態である場合。
- 決定論的計算、リアルタイム動作、完全なグラフが必要な場合。
- 承認済み ID、版、権限、適用性を維持できない場合。
- 有資格者または統治されたアプリケーションが根拠を審査しない場合。

### 製品ポジショニング

- `Multi Format`: 一般文書検索と低リスクな grounded Q&A。
- `Multi-Format BookRAG`: 意味検索に文書 ID、章階層、ページ、元要素、任意の表・画像・エンティティ文脈を加える。
- 統合 BookRAG アプリケーション: 正式な業務システムと接続された、範囲の明確なエビデンス業務。

一文で表すと:

> BookRAG は、根拠を探すコストが高く、文脈を失うことが危険で、責任を言語モデルへ委譲できない意思決定のためにある。
