"""Template-driven Clinical Study Report (CSR / CIR) generator.

Pipeline: ingest study sources (Protocol, SAP, MOP, TFLs) -> vector RAG index
(LanceDB vector + full-text search, RRF fusion) -> per-section generation with
Claude on Bedrock, grounded citations, numeric verification -> template-preserving
.docx assembly with Word-comment traceability.
"""

__version__ = "0.1.0"
