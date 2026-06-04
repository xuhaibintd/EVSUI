# BookRAG Pipeline: Data Structures and Processing Flow

This document describes the current `multi_format_bookrag` implementation in EVSUI. It focuses on the runtime data flow, persisted Teradata structures, and the node-tree construction algorithm used before VectorStore creation.

## 1. End-to-End Pipeline

```mermaid
flowchart LR
    DOC[Document files] --> MODE[Multi-Format BookRAG mode]
    MODE --> WF[Build Unstructured workflow definition]
    WF --> PART[Partitioner node<br/>auto / hi_res / vlm / fast]

    PART --> ENRICH{Optional enrichment nodes}
    ENRICH -->|Image Description| IMG_DESC[Image descriptions]
    ENRICH -->|Table to HTML| TABLE_HTML[Table HTML]
    ENRICH -->|Table Description| TABLE_DESC[Table descriptions]
    ENRICH -->|Generative OCR| GEN_OCR[OCR-enhanced text]
    ENRICH -->|NER| NER[Entity metadata]

    PART --> JOB[Unstructured on-demand job]
    IMG_DESC --> JOB
    TABLE_HTML --> JOB
    TABLE_DESC --> JOB
    GEN_OCR --> JOB
    NER --> JOB

    JOB --> RAW_JSON[Raw Unstructured output<br/>JSON elements]
    RAW_JSON --> RAW_STAGE[Raw stage file<br/>uploads/bookrag_raw_stage]
    RAW_STAGE --> RECON[Reconcile elements<br/>normalize parentage and metadata]

    RECON --> RAW_ROWS[Build raw rows]
    RECON --> BLOCKS[Build BookRAG blocks]
    BLOCKS --> NODES[Build document node tree]
    RECON --> ENTITY_GATE{Entity tables enabled?}
    ENTITY_GATE -->|Yes| GRAPH[Build entities, links, relations]
    ENTITY_GATE -->|No| SKIP_GRAPH[Skip entity graph]

    RAW_ROWS --> TD[(Teradata BookRAG tables)]
    BLOCKS --> TD
    NODES --> TD
    GRAPH --> TD

    TD --> VS[VectorStore source object<br/>*_bnode]
    VS --> RETRIEVAL[Retrieval over node content]
```

## 2. Persisted Data Model

```mermaid
erDiagram
    DOCUMENTS ||--o{ RAW : "doc_id"
    DOCUMENTS ||--o{ BLOCKS : "doc_id"
    DOCUMENTS ||--o{ NODES : "doc_id"
    DOCUMENTS ||--o{ ENTITIES : "doc_id"

    NODES ||--o{ ENTITY_LINKS : "node_id"
    NODES ||--o{ ENTITY_RELATIONS : "source_node_id"
    ENTITIES ||--o{ ENTITY_LINKS : "entity_id"
    ENTITIES ||--o{ ENTITY_RELATIONS : "from_entity_id"
    ENTITIES ||--o{ ENTITY_RELATIONS : "to_entity_id"

    DOCUMENTS {
        string doc_id PK
        string vector_store_name
        string workflow_id
        string workflow_name
        string job_id
        string processing_profile
        string source_file
        string filename
        string filetype
        int filesize_bytes
    }

    RAW {
        string id PK
        string doc_id FK
        string element_id
        int ordinal_raw
        string parent_id
        string type
        int page_number
        int category_depth
        string text
        string text_as_html
        string image_caption
        string image_context
    }

    BLOCKS {
        string doc_id FK
        string element_id
        string parent_id
        int category_depth
        int heading_level
        int page_number
        int ordinal
        string type
        string text
        string text_as_html
        string image_caption
        string image_context
    }

    NODES {
        string node_id PK
        string doc_id FK
        string source_element_id
        string parent_node_id
        string node_type
        int level
        int ordinal
        string title
        string content
        int page_start
        int page_end
        string path
        int is_leaf
    }

    ENTITIES {
        string entity_id PK
        string doc_id FK
        string canonical_name
        string display_name
        string entity_type
        int mention_count
        int node_count
    }

    ENTITY_LINKS {
        string link_id PK
        string entity_id FK
        string doc_id FK
        string node_id FK
        string section_node_id
        string source_field
        string mention_text
        int page_start
        int page_end
        string section_path
    }

    ENTITY_RELATIONS {
        string relation_id PK
        string doc_id FK
        string source_element_id
        string source_node_id FK
        string section_node_id
        string from_entity_id FK
        string from_entity_text
        string relationship
        string to_entity_id FK
        string to_entity_text
        string section_path
    }
```

## 3. Node-Tree Construction Algorithm

```mermaid
flowchart TD
    A[Reconciled Unstructured elements] --> B[Iterate elements in source order]
    B --> C[Read element fields and metadata<br/>element_id, parent_id, page_number,<br/>category_depth, text_as_html]

    C --> D{Classify block kind}
    D -->|Title or structural section signal| SEC[Section block]
    D -->|Table type or HTML table| TAB[Table block]
    D -->|Image, figure, or picture type| IMG[Image block]
    D -->|Other retained text| TXT[Text block]

    SEC --> LVL[Infer section level<br/>HTML heading, category_depth,<br/>Japanese section rules, numbered headings]
    LVL --> STACK[Update section stack]
    STACK --> SEC_NODE[Create section node<br/>is_leaf = 0]

    TAB --> LEAF_CONTENT[Build leaf content]
    TXT --> LEAF_CONTENT
    IMG --> IMG_CTX[Attach image caption/context<br/>from nearby compatible blocks]
    IMG_CTX --> LEAF_CONTENT

    LEAF_CONTENT --> LONG{Content exceeds<br/>embedding segment size?}
    LONG -->|No| LEAF_NODE[Create one leaf node<br/>is_leaf = 1]
    LONG -->|Yes| SEGMENT[Split into leaf segments<br/>384 token units, 48 overlap]
    SEGMENT --> LEAF_NODE

    SEC_NODE --> NODE_TABLE[(NODES table)]
    LEAF_NODE --> NODE_TABLE
    NODE_TABLE --> VECTOR[VectorStore retrieval source<br/>key_columns = node_id<br/>data_columns = content]
```

## 4. Runtime Object Flow

```mermaid
flowchart LR
    ELEM[Unstructured element] --> RAW[RAW row]
    ELEM --> BLK[BookRAG block]
    BLK --> NODE[BookRAG node]
    ELEM -->|optional entity metadata| ENT[Entity records]

    RAW --> RAW_TABLE[*_braw]
    BLK --> BLOCK_TABLE[*_bblk]
    NODE --> NODE_TABLE[*_bnode]
    ENT --> ENTITY_TABLES[*_bent / *_belnk / *_brel]

    NODE_TABLE --> VS_SRC[VectorStore object_names]
```

## 5. Table Naming Convention

For a vector store named `demo`, BookRAG table targets are generated from the `<vector_store_name>_bk` base name:

```text
demo_bk_bdoc   documents
demo_bk_braw   raw elements
demo_bk_bblk   normalized blocks
demo_bk_bnode  document tree nodes
demo_bk_bent   entities
demo_bk_belnk  entity mentions linked to nodes
demo_bk_brel   entity relations
```

The current BookRAG VectorStore source is the node table:

```text
object_names = <schema>.<vector_store_name>_bk_bnode
key_columns  = ["node_id"]
data_columns = ["content"]
```

Only nodes with retrievable `content` are useful for semantic retrieval. Section nodes preserve hierarchy and path context; leaf nodes carry the text, table, or image-derived content used by the VectorStore.
