# Architecture Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SAS Field Lineage Tracker                     │
└─────────────────────────────────────────────────────────────────┘

                             ┌──────────┐
                             │ SAS Code │
                             └────┬─────┘
                                  │
                                  ▼
                         ┌────────────────┐
                         │   SAS Parser   │
                         │ (sas_parser.py)│
                         └────────┬───────┘
                                  │
                                  ▼
                         ┌────────────────┐
                         │   AST Builder  │
                         │ (field_ast.py) │
                         └────────┬───────┘
                                  │
                     ┌────────────┼────────────┐
                     │            │            │
                     ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │FieldNode │ │DataStep  │ │SASProgram│
              │          │ │Node      │ │          │
              └──────────┘ └──────────┘ └──────────┘
                     │            │            │
                     └────────────┼────────────┘
                                  │
                                  ▼
                         ┌────────────────┐
                         │LineageTracker  │
                         │  (tracker.py)  │
                         └────────┬───────┘
                                  │
                     ┌────────────┼────────────┐
                     │            │            │
                     ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │  Query   │ │  Browse  │ │Visualize │
              └──────────┘ └──────────┘ └──────────┘
                                  │
                     ┌────────────┼────────────┐
                     │                         │
                     ▼                         ▼
              ┌──────────┐              ┌──────────┐
              │Streamlit │              │   CLI    │
              │   Web    │              │Interface │
              │    UI    │              │          │
              └──────────┘              └──────────┘
                     │                         │
                     └────────────┬────────────┘
                                  │
                                  ▼
                            ┌──────────┐
                            │   User   │
                            └──────────┘
```

## Data Flow

```
1. Parse SAS Code
   ↓
2. Build AST (FieldNode tree)
   ↓
3. Create Lineage Graph (NetworkX)
   ↓
4. Query/Browse/Evaluate
   ↓
5. Display Results (Web UI or CLI)
```

## Component Interaction

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interfaces                          │
├──────────────────────┬──────────────────────────────────────┤
│  Streamlit Web App   │      CLI (sas_lineage.cli)           │
│  - Browse Tab        │      - Query command                 │
│  - Query Tab         │      - Browse command                │
│  - Evaluate Tab      │      - Graph export                  │
│  - Visualize Tab     │      - JSON output                   │
└──────────────────────┴──────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Core Logic Layer                         │
├──────────────────────┬──────────────────────────────────────┤
│  LineageTracker      │      FieldEvaluator                  │
│  - query_field()     │      - evaluate_field()              │
│  - browse_fields()   │      - load_data_from_csv()          │
│  - get_lineage_path()│      - evaluate_with_dataframe()     │
│  - export_graph_dot()│                                      │
└──────────────────────┴──────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     AST Layer                                │
├──────────────────────┬──────────────────────────────────────┤
│  FieldNode           │      SASProgram                      │
│  - name              │      - data_steps[]                  │
│  - dependencies[]    │      - all_fields{}                  │
│  - expression        │      - find_field()                  │
│  - operation         │      - get_all_fields()              │
└──────────────────────┴──────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Parser Layer                             │
├──────────────────────────────────────────────────────────────┤
│  SASParser                                                   │
│  - parse() → SASProgram                                      │
│  - _parse_data_step()                                        │
│  - _extract_field_references()                               │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Data Sources                             │
├──────────────────────────────────────────────────────────────┤
│  - SAS Code Files (.sas)                                     │
│  - CSV Files (for evaluation)                                │
│  - Excel Files (for evaluation)                              │
└──────────────────────────────────────────────────────────────┘
```

## Module Dependencies

```
sas_lineage/
│
├── parser/
│   └── SASParser ────────────┐
│                             │
├── ast/                      │
│   ├── FieldNode ←───────────┤
│   ├── DataStepNode ←────────┤
│   └── SASProgram ←──────────┘
│         │
│         └──→ lineage/
│                ├── LineageTracker (uses NetworkX)
│                └── FieldEvaluator (uses Pandas)
│                      │
│                      └──→ ui/
│                             ├── Streamlit App
│                             └── CLI Interface
```

## Key Technologies

```
Python 3.8+
    │
    ├── Streamlit ────→ Web Interface
    ├── NetworkX ─────→ Graph Operations
    ├── Pandas ───────→ Data Processing
    ├── OpenPyXL ─────→ Excel Support
    └── GraphViz ─────→ Visualization
```

## Feature Overview

```
┌───────────────────────────────────────────────────────────┐
│                    Core Features                           │
├───────────────────────────────────────────────────────────┤
│                                                            │
│  🌳 AST Representation        📊 Browse Functionality     │
│     • FieldNode tree              • Group by table        │
│     • Dependencies                • Statistics            │
│     • Metadata                    • Filter & search       │
│                                                            │
│  🔍 Query Functionality       🧮 Field Evaluation         │
│     • Search by name             • Manual entry           │
│     • Upstream/downstream        • CSV import             │
│     • Path finding               • Excel import           │
│                                                            │
│  📈 Visualization            💻 Dual Interface            │
│     • DOT export                 • Streamlit web app      │
│     • NetworkX graph             • Command-line tool      │
│     • GraphViz support           • API for integration    │
│                                                            │
└───────────────────────────────────────────────────────────┘
```

## Workflow Example

```
┌─────────┐
│ Upload  │   
│SAS File │   
└────┬────┘   
     │
     ▼
┌─────────────┐
│   Parse     │ ──→ Extract DATA steps, fields, expressions
└─────┬───────┘
      │
      ▼
┌─────────────┐
│Build AST    │ ──→ Create FieldNodes with dependencies
└─────┬───────┘
      │
      ▼
┌─────────────┐
│Create Graph │ ──→ Build NetworkX directed graph
└─────┬───────┘
      │
      ├──→ Query Tab ──→ Search for field ──→ Show lineage
      │
      ├──→ Browse Tab ──→ View all fields ──→ Group by table
      │
      ├──→ Evaluate Tab ──→ Upload CSV ──→ Calculate results
      │
      └──→ Visualize Tab ──→ Export DOT ──→ View graph
```
