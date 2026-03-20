# Capability Taxonomy

This document defines the initial capability taxonomy used to classify repositories into a fixed set of product capabilities.

## Principles
- Capabilities describe user-visible or system-level behavior, not implementation language.
- Classifiers must choose from this taxonomy only.
- When evidence is weak, the classifier may return a lower confidence result and mark it as needing manual review.

## Taxonomy

### `browser_automation`
- **Definition:** Automates browser actions such as opening pages, clicking, form filling, extraction, or end-to-end browsing workflows.
- **Common synonyms:** browser automation, web automation, web agent, browser agent, headless browser, Playwright automation, Selenium automation, web browsing.
- **Boundary notes:** Include repositories that directly control browser sessions. Exclude generic HTTP clients, browser extensions without automation, or simple crawlers that do not execute interactive browser workflows.

### `code_generation`
- **Definition:** Produces source code, patches, tests, or implementation artifacts from prompts, specs, or contextual inputs.
- **Common synonyms:** code generation, codegen, coding agent, AI coding, software generation.
- **Boundary notes:** Include systems whose core value is creating or modifying code. Exclude linters, static analyzers, or documentation-only generators unless code output is primary.

### `information_retrieval`
- **Definition:** Retrieves, ranks, or searches documents, snippets, or repository context for downstream answering or automation.
- **Common synonyms:** information retrieval, retrieval, semantic search, search, RAG, document retrieval.
- **Boundary notes:** Include search and retrieval systems even if paired with generation. Exclude generic dashboards or reports that merely display already-selected records.

### `summarization`
- **Definition:** Condenses repositories, documents, logs, or conversations into shorter natural language or structured summaries.
- **Common synonyms:** summarization, summary generation, repo summary, document summary.
- **Boundary notes:** Include dedicated summarizers and report generators. Exclude general-purpose chat tools unless summarization is explicitly a supported feature.

### `data_extraction`
- **Definition:** Extracts structured data from unstructured or semi-structured inputs such as HTML, PDFs, screenshots, logs, or free text.
- **Common synonyms:** data extraction, scraping, web scraping, parsing, structured extraction.
- **Boundary notes:** Include repositories focused on turning messy input into fields or records. Exclude pure transport clients or visualization tools.

### `workflow_orchestration`
- **Definition:** Coordinates multiple tools, steps, or agents into ordered execution pipelines.
- **Common synonyms:** workflow orchestration, orchestration, agent workflow, multi-step automation, task orchestration.
- **Boundary notes:** Include systems that manage sequencing, retries, delegation, or cross-tool execution. Exclude single-purpose scripts that perform only one isolated action.

## Manual Review Policy
If a matched capability has confidence below `0.60`, downstream reports should display **需要人工确认** to highlight that the result may be ambiguous and requires human validation.
