"""
Hermes Agent — complete tools and features catalog.

This module provides a comprehensive inventory of all tools, features,
and capabilities available to the Hermes agent. It is designed to be
queryable programmatically and displayable in the TUI or CLI output.

Categories covered:
- Browser automation
- Terminal execution
- File management
- Session & memory
- Skill management
- Messaging
- Code analysis (jcodemunch)
- Database (MySQL)
- Image generation
- Task planning
- Delegation
- Process management
- MCP servers
- Skills library
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ToolCategory = Literal[
    "browser",
    "terminal",
    "file",
    "session",
    "skill",
    "messaging",
    "code-analysis",
    "database",
    "image",
    "planning",
    "delegation",
    "process",
    "mcp",
    "skills-library",
]


@dataclass
class ToolDef:
    """Single tool definition."""

    name: str
    category: ToolCategory
    description: str
    params: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class SkillDef:
    """Single skill definition."""

    name: str
    category: str
    description: str
    file_path: str = ""
    setup_needed: bool = False
    missing_env: list[str] = field(default_factory=list)
    missing_cmds: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalog — all tools available to Hermes
# ---------------------------------------------------------------------------

TOOLS: list[ToolDef] = [
    # --- Browser (10 tools) ---
    ToolDef("browser_navigate", "browser", "Navigate to a URL. Initializes session and loads the page.", ["url"]),
    ToolDef("browser_snapshot", "browser", "Get text-based snapshot of the page's accessibility tree. Returns interactive elements with ref IDs.", ["full"]),
    ToolDef("browser_click", "browser", "Click on an element identified by ref ID from the snapshot.", ["ref"]),
    ToolDef("browser_type", "browser", "Type text into an input field identified by ref ID.", ["ref", "text"]),
    ToolDef("browser_press", "browser", "Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.).", ["key"]),
    ToolDef("browser_scroll", "browser", "Scroll the page up or down to reveal more content.", ["direction"]),
    ToolDef("browser_console", "browser", "Get browser console output and JS errors. Supports JS evaluation in page context.", ["expression", "clear"]),
    ToolDef("browser_get_images", "browser", "Get a list of all images on the current page with URLs and alt text.", []),
    ToolDef("browser_vision", "browser", "Take a screenshot and analyze it with vision AI. For CAPTCHAs, visual challenges, complex layouts.", ["question", "annotate"]),
    ToolDef("browser_back", "browser", "Navigate back to the previous page in browser history.", []),

    # --- Terminal (1 tool) ---
    ToolDef("terminal", "terminal", "Execute shell commands. Supports foreground, background, PTY, notify.", ["command", "background", "timeout", "workdir", "pty", "notify_on_complete"]),

    # --- File (4 tools) ---
    ToolDef("read_file", "file", "Read a text file with line numbers and pagination.", ["path", "offset", "limit"]),
    ToolDef("write_file", "file", "Write content to a file. Creates parent directories. Overwrites entirely.", ["path", "content"]),
    ToolDef("patch", "file", "Targeted find-and-replace with 9 fuzzy matching strategies. Returns diff.", ["mode", "path", "old_string", "new_string", "replace_all"]),
    ToolDef("search_files", "file", "Search file contents or find files by name using Ripgrep.", ["pattern", "target", "path", "file_glob", "limit", "offset", "output_mode"]),

    # --- Session (2 tools) ---
    ToolDef("session_search", "session", "Search long-term memory of past conversations. Keyword search or browse recent sessions.", ["query", "role_filter", "limit"]),
    ToolDef("memory", "session", "Save durable facts to persistent memory across sessions.", ["action", "target", "content", "old_text"]),

    # --- Skill (3 tools) ---
    ToolDef("skill_view", "skill", "Load a skill's full content. Supports linked references/templates/scripts.", ["name", "file_path"]),
    ToolDef("skill_manage", "skill", "Create, update, delete, patch skills. Skills are procedural memory.", ["action", "name", "content", "old_string", "new_string", "category", "file_path", "file_content"]),
    ToolDef("skills_list", "skill", "List available skills. Optional category filter.", ["category"]),

    # --- Messaging (2 tools) ---
    ToolDef("send_message", "messaging", "Send messages to messaging platforms. List targets or send directly.", ["action", "target", "message"]),
    ToolDef("text_to_speech", "messaging", "Convert text to speech audio. Returns voice message path for Telegram/Discord/WhatsApp.", ["text", "output_path"]),

    # --- Code Analysis (jcodemunch — 45 tools) ---
    ToolDef("mcp_jcodemunch_search_symbols", "code-analysis", "Search for symbols matching a query across indexed repos. BM25 + semantic search.", ["repo", "query"]),
    ToolDef("mcp_jcodemunch_get_symbol_source", "code-analysis", "Get full source of one or many symbols.", ["repo", "symbol_id", "symbol_ids"]),
    ToolDef("mcp_jcodemunch_find_references", "code-analysis", "Find all files that import or reference an identifier.", ["repo", "identifier", "identifiers"]),
    ToolDef("mcp_jcodemunch_get_blast_radius", "code-analysis", "Find all files affected by changing a symbol. Impact analysis with depth scoring.", ["repo", "symbol", "depth", "cross_repo"]),
    ToolDef("mcp_jcodemunch_get_impact_preview", "code-analysis", "Show what breaks if a symbol is removed or renamed. Call-chain paths.", ["repo", "symbol_id"]),
    ToolDef("mcp_jcodemunch_check_rename_safe", "code-analysis", "Check whether renaming a symbol would cause name collisions.", ["repo", "symbol_id", "new_name"]),
    ToolDef("mcp_jcodemunch_plan_refactoring", "code-analysis", "Generate edit-ready refactoring instructions for rename/move/extract/signature.", ["repo", "symbol", "refactor_type", "new_name", "new_file", "new_signature"]),
    ToolDef("mcp_jcodemunch_get_call_hierarchy", "code-analysis", "Return incoming callers and outgoing callees for a symbol, N levels deep.", ["repo", "symbol_id", "direction", "depth"]),
    ToolDef("mcp_jcodemunch_get_symbol_complexity", "code-analysis", "Return cyclomatic complexity, nesting depth, and parameter count for a symbol.", ["repo", "symbol_id"]),
    ToolDef("mcp_jcodemunch_get_hotspots", "code-analysis", "Return top-N highest-risk symbols ranked by hotspot score (complexity x log(churn)).", ["repo", "top_n", "days", "min_complexity"]),
    ToolDef("mcp_jcodemunch_find_dead_code", "code-analysis", "Find dead code — files and symbols with zero importers and no entry-point role.", ["repo", "granularity", "min_confidence", "include_tests"]),
    ToolDef("mcp_jcodemunch_get_dead_code_v2", "code-analysis", "Find likely-dead functions using three independent evidence signals.", ["repo", "min_confidence", "include_tests"]),
    ToolDef("mcp_jcodemunch_get_dependency_cycles", "code-analysis", "Detect circular import chains. Returns strongly-connected components.", ["repo"]),
    ToolDef("mcp_jcodemunch_get_dependency_graph", "code-analysis", "Get file-level dependency graph with import relationships up to 3 hops.", ["repo", "file", "direction", "depth", "cross_repo"]),
    ToolDef("mcp_jcodemunch_get_file_content", "code-analysis", "Get cached source for a file, optionally sliced to a line range.", ["repo", "file_path", "start_line", "end_line"]),
    ToolDef("mcp_jcodemunch_get_file_outline", "code-analysis", "Get all symbols in a file with full signatures and summaries.", ["repo", "file_path", "file_paths"]),
    ToolDef("mcp_jcodemunch_get_repo_health", "code-analysis", "One-call triage snapshot: symbol counts, dead code %, complexity, hotspots, cycles.", ["repo", "days"]),
    ToolDef("mcp_jcodemunch_index_folder", "code-analysis", "Index a local folder containing source code for semantic search.", ["path", "use_ai_summaries", "extra_ignore_patterns", "incremental"]),
    ToolDef("mcp_jcodemunch_index_repo", "code-analysis", "Index a GitHub repository's source code.", ["url", "use_ai_summaries", "extra_ignore_patterns", "incremental"]),
    ToolDef("mcp_jcodemunch_list_repos", "code-analysis", "List all indexed repositories.", []),
    ToolDef("mcp_jcodemunch_get_class_hierarchy", "code-analysis", "Get full inheritance hierarchy for a class (ancestors + descendants).", ["repo", "class_name"]),
    ToolDef("mcp_jcodemunch_get_symbol_provenance", "code-analysis", "Trace authorship lineage and evolution narrative of a symbol through git history.", ["repo", "symbol", "max_commits"]),
    ToolDef("mcp_jcodemunch_get_coupling_metrics", "code-analysis", "Return afferent/efferent coupling and instability score for a module.", ["repo", "module_path"]),
    ToolDef("mcp_jcodemunch_get_tectonic_map", "code-analysis", "Discover logical module topology via structural, behavioral, temporal coupling signals.", ["repo", "days", "min_plate_size"]),
    ToolDef("mcp_jcodemunch_search_ast", "code-analysis", "Cross-language AST pattern matching for anti-patterns and custom queries.", ["repo", "pattern", "category", "language", "file_pattern", "max_results"]),
    ToolDef("mcp_jcodemunch_winnow_symbols", "code-analysis", "Multi-axis constraint query against the index. Filter + rank in one call.", ["repo", "criteria", "rank_by", "order", "max_results"]),
    ToolDef("mcp_jcodemunch_get_pr_risk_profile", "code-analysis", "Unified risk assessment for PR changes between two git refs. Fuses blast radius, complexity, churn, test gaps.", ["repo", "base_ref", "head_ref", "days"]),
    ToolDef("mcp_jcodemunch_get_churn_rate", "code-analysis", "Return git churn metrics for a file or symbol: commit count, authors, first/last modified.", ["repo", "target", "days"]),
    ToolDef("mcp_jcodemunch_get_project_intel", "code-analysis", "Auto-discover non-code knowledge files and cross-reference to code symbols.", ["repo", "category"]),
    ToolDef("mcp_jcodemunch_get_related_symbols", "code-analysis", "Find symbols related to a given symbol using heuristic clustering (co-location, shared imports).", ["repo", "symbol_id", "max_results"]),
    ToolDef("mcp_jcodemunch_get_ranked_context", "code-analysis", "Assemble best-fit context for a query within a token budget. BM25 + PageRank ranking.", ["repo", "query", "token_budget", "strategy"]),
    ToolDef("mcp_jcodemunch_get_context_bundle", "code-analysis", "Get full source + imports for one or more symbols in one call. Deduplicated.", ["repo", "symbol_id", "symbol_ids", "token_budget"]),
    ToolDef("mcp_jcodemunch_get_symbol_diff", "code-analysis", "Diff symbol sets between two indexed snapshots (branch comparison).", ["repo_a", "repo_b"]),
    ToolDef("mcp_jcodemunch_get_untested_symbols", "code-analysis", "Find functions/methods with no evidence of being exercised by any test file.", ["repo", "file_pattern", "min_confidence", "max_results"]),
    ToolDef("mcp_jcodemunch_get_extraction_candidates", "code-analysis", "Identify functions good candidates for extraction to a shared module.", ["repo", "file_path", "min_complexity", "min_callers"]),
    ToolDef("mcp_jcodemunch_get_layer_violations", "code-analysis", "Check whether imports respect declared architectural layer boundaries.", ["repo", "rules"]),
    ToolDef("mcp_jcodemunch_get_cross_repo_map", "code-analysis", "Return which indexed repos depend on which other indexed repos at the package level.", ["repo"]),
    ToolDef("mcp_jcodemunch_get_watch_status", "code-analysis", "Report watch-all daemon coverage: every indexed repo's staleness status.", []),
    ToolDef("mcp_jcodemunch_render_diagram", "code-analysis", "Render graph-producing tool output as rich, annotated Mermaid markup.", ["source", "theme", "max_nodes"]),
    ToolDef("mcp_jcodemunch_check_embedding_drift", "code-analysis", "Pin canary vectors against the embedding provider. Report cosine drift.", ["capture", "force", "threshold"]),
    ToolDef("mcp_jcodemunch_embed_repo", "code-analysis", "Precompute and cache symbol embeddings for semantic search.", ["repo", "batch_size", "force"]),
    ToolDef("mcp_jcodemunch_get_session_context", "code-analysis", "Get current session context — files accessed, searches, edits.", ["max_files", "max_queries"]),
    ToolDef("mcp_jcodemunch_get_session_snapshot", "code-analysis", "Get compact session snapshot for context continuity.", ["max_files", "max_searches", "max_edits"]),
    ToolDef("mcp_jcodemunch_get_session_stats", "code-analysis", "Get token savings stats for the current MCP session.", []),
    ToolDef("mcp_jcodemunch_register_edit", "code-analysis", "Register file edits to invalidate BM25 cache and search result cache.", ["repo", "file_paths", "reindex"]),
    ToolDef("mcp_jcodemunch_invalidate_cache", "code-analysis", "Delete the index and cached files for a repository. Forces full re-index.", ["repo"]),
    ToolDef("mcp_jcodemunch_resolve_repo", "code-analysis", "Resolve a filesystem path to its indexed repo identifier.", ["path"]),
    ToolDef("mcp_jcodemunch_get_repo_outline", "code-analysis", "Get a high-level overview of an indexed repository: directories, file counts, language breakdown.", ["repo"]),
    ToolDef("mcp_jcodemunch_get_file_tree", "code-analysis", "Get the file tree of an indexed repository, optionally filtered by path prefix.", ["repo", "path_prefix", "include_summaries", "max_files"]),
    ToolDef("mcp_jcodemunch_summarize_repo", "code-analysis", "Re-run AI summarization on all symbols in an existing index.", ["repo", "force"]),
    ToolDef("mcp_jcodemunch_check_references", "code-analysis", "Check if an identifier is referenced anywhere. Combines find_references + search_text.", ["repo", "identifier", "identifiers"]),
    ToolDef("mcp_jcodemunch_get_symbol_importance", "code-analysis", "Return the most architecturally important symbols, ranked by PageRank or in-degree centrality.", ["repo", "top_n", "algorithm", "scope"]),
    ToolDef("mcp_jcodemunch_get_suggest_queries", "code-analysis", "Suggest search queries, entry-point files, and index stats for unfamiliar repos.", ["repo"]),
    ToolDef("mcp_jcodemunch_tune_weights", "code-analysis", "Learn per-repo retrieval weights from the ranking ledger. Optimize BM25 + semantic fusion.", ["repo", "dry_run", "min_events", "explain"]),
    ToolDef("mcp_jcodemunch_audit_agent_config", "code-analysis", "Audit agent configuration files for token waste, stale refs, dead paths, bloat.", ["repo", "project_path"]),
    ToolDef("mcp_jcodemunch_analyze_perf", "code-analysis", "Per-tool latency telemetry: p50/p95/max, error rate, cache hit-rate, ledger summary.", ["window", "top", "tool", "compare_release", "ledger"]),
    ToolDef("mcp_jcodemunch_plan_turn", "code-analysis", "Plan the next turn by analyzing query against the codebase. Returns recommended symbols.", ["repo", "query", "max_recommended", "model"]),
    ToolDef("mcp_jcodemunch_get_signal_chains", "code-analysis", "Discover how external signals (HTTP, CLI, tasks, events) propagate through the codebase via call graph.", ["repo", "symbol", "kind", "max_depth", "include_tests"]),
    ToolDef("mcp_jcodemunch_get_changed_symbols", "code-analysis", "Map a git diff to affected symbols: added, removed, modified, renamed.", ["repo", "since_sha", "until_sha", "include_blast_radius"]),
    ToolDef("mcp_jcodemunch_get_prompt", "mcp", "Get a prompt by name from jcodemunch MCP server.", ["name", "arguments"]),
    ToolDef("mcp_jcodemunch_list_prompts", "mcp", "List available prompts from jcodemunch MCP server.", []),
    ToolDef("mcp_jcodemunch_list_resources", "mcp", "List available resources from jcodemunch MCP server.", []),
    ToolDef("mcp_jcodemunch_read_resource", "mcp", "Read a resource by URI from jcodemunch MCP server.", ["uri"]),
    ToolDef("mcp_jcodemunch_get_tectonic_map", "mcp", "Discover logical module topology via coupling signals.", ["repo", "days", "min_plate_size"]),
    ToolDef("mcp_jcodemunch_get_signal_chains", "mcp", "Discover how external signals propagate through the codebase via call graph.", ["repo", "symbol", "kind", "max_depth"]),

    # --- Database (MySQL — 5 tools) ---
    ToolDef("mcp_mysql_mysql_query", "database", "Run SQL queries against MySQL database (READ-ONLY).", ["sql"]),
    ToolDef("mcp_mysql_list_resources", "database", "List available resources from MySQL MCP server.", []),
    ToolDef("mcp_mysql_read_resource", "database", "Read a resource by URI from MySQL MCP server.", ["uri"]),
    ToolDef("mcp_mysql_list_prompts", "database", "List available prompts from MySQL MCP server.", []),
    ToolDef("mcp_mysql_get_prompt", "database", "Get a prompt by name from MySQL MCP server.", ["name", "arguments"]),

    # --- Image (1 tool) ---
    ToolDef("image_generate", "image", "Generate high-quality images from text prompts. Returns URL or file path.", ["prompt", "aspect_ratio"]),

    # --- Planning (2 tools) ---
    ToolDef("todo", "planning", "Manage task list for the session. Create/update items with status.", ["todos", "merge"]),
    ToolDef("clarify", "planning", "Ask the user a question before proceeding. Multiple choice or open-ended.", ["question", "choices"]),

    # --- Delegation (1 tool) ---
    ToolDef("delegate_task", "delegation", "Spawn subagents to work on tasks in isolated contexts. Parallel or goal-based.", ["goal", "context", "toolsets", "role", "acp_command"]),

    # --- Process (1 tool) ---
    ToolDef("process", "process", "Manage background processes: list, poll, log, wait, kill, write, submit, close.", ["action", "session_id", "data", "timeout"]),

    # --- Cron (1 tool) ---
    ToolDef("cronjob", "planning", "Manage scheduled cron jobs. Create, list, update, pause, resume, remove, run.", ["action", "job_id", "prompt", "schedule"]),

    # --- Model/Config (2 tools) ---
    ToolDef("announce_model", "mcp", "Agent self-reports its active model identifier. Resolves to a tier for tool access.", ["model"]),
    ToolDef("set_tool_tier", "mcp", "Explicit tier override for the current session. Narrows or widens tool list.", ["tier"]),
]


# ---------------------------------------------------------------------------
# Skills library inventory
# ---------------------------------------------------------------------------

SKILLS: list[SkillDef] = [
    # DevOps (7 skills)
    SkillDef("mydumper-myloader-restore", "devops", "Restore MySQL databases from mydumper backups using myloader."),
    SkillDef("mysql-lock-debugging", "devops", "Diagnose and fix MySQL lock timeouts and deadlocks in scripts."),
    SkillDef("mysqlsh-dump-backup", "devops", "Use mysqlsh dump instead of mydumper for MySQL backups."),
    SkillDef("scrape-debug-logging", "devops", "Structured debug logging for Node.js scraping/automation."),
    SkillDef("tms-websocket-dynamic-subscription", "devops", "Connecting to TMS Nepal WebSocket with dynamic config."),
    SkillDef("webhook-subscriptions", "devops", "Create and manage webhook subscriptions for event-driven workflows."),
    SkillDef("mysql-per-row-trigger-to-batch", "devops", "Replace per-row MySQL triggers with batch operations."),
    SkillDef("tms-cookie-persistence", "devops", "Cookie persistence and SPA login handling for TMS."),

    # Gaming (2 skills)
    SkillDef("minecraft-modpack-server", "gaming", "Set up a modded Minecraft server from CurseForge/Modrinth."),
    SkillDef("pokemon-player", "gaming", "Play Pokemon games autonomously via headless emulation."),

    # Media (5 skills)
    SkillDef("gif-search", "media", "Search and download GIFs from Tenor using curl."),
    SkillDef("heartmula", "media", "Set up and run HeartMuLa, the open-source music generation model."),
    SkillDef("songsee", "media", "Generate spectrograms and audio feature visualizations."),
    SkillDef("spotify", "media", "Control Spotify — play, search, manage playlists."),
    SkillDef("youtube-content", "media", "Fetch YouTube video transcripts and transform them."),

    # Email (1 skill)
    SkillDef("himalaya", "email", "CLI to manage emails via IMAP/SMTP."),

    # Social (2 skills)
    SkillDef("xitter", "social-media", "Interact with X/Twitter via x-cli terminal client."),
    SkillDef("xurl", "social-media", "Interact with X/Twitter via xurl, the official X API CLI."),

    # Research (4 skills)
    SkillDef("arxiv", "research", "Search and retrieve academic papers from arXiv."),
    SkillDef("blogwatcher", "research", "Monitor blogs and RSS/Atom feeds for updates."),
    SkillDef("llm-wiki", "research", "Karpathy's LLM Wiki — build and maintain persistent knowledge."),
    SkillDef("polymarket", "research", "Query Polymarket prediction market data."),

    # MLOps — Cloud (1 skill)
    SkillDef("modal-serverless-gpu", "mlops/cloud", "Serverless GPU cloud platform for ML workloads."),

    # MLOps — Evaluation (2 skills)
    SkillDef("evaluating-llms-harness", "mlops/evaluation", "Evaluates LLMs across 60+ academic benchmarks (MMLU, HumanEval, etc.)."),
    SkillDef("weights-and-biases", "mlops/evaluation", "Track ML experiments with automatic logging and visualization."),

    # MLOps — Inference (6 skills)
    SkillDef("gguf-quantization", "mlops/inference", "GGUF format and llama.cpp quantization for efficient CPU inference."),
    SkillDef("guidance", "mlops/inference", "Control LLM output with regex and grammars, guarantee valid structure."),
    SkillDef("llama-cpp", "mlops/inference", "llama.cpp local GGUF inference + HuggingFace Hub model discovery."),
    SkillDef("obliteratus", "mlops/inference", "Remove refusal behaviors from open-weight LLMs using OBLITERATUS."),
    SkillDef("outlines", "mlops/inference", "Guarantee valid JSON/XML/code structure during generation."),
    SkillDef("serving-llms-vllm", "mlops/inference", "Serves LLMs with high throughput using vLLM's PagedAttention."),

    # MLOps — Models (5 skills)
    SkillDef("audiocraft-audio-generation", "mlops/models", "PyTorch library for audio generation including text-to-music."),
    SkillDef("clip", "mlops/models", "OpenAI's model connecting vision and language. Zero-shot transfer."),
    SkillDef("segment-anything-model", "mlops/models", "Foundation model for image segmentation with zero-shot transfer."),
    SkillDef("stable-diffusion-image-generation", "mlops/models", "Text-to-image generation with Stable Diffusion."),
    SkillDef("whisper", "mlops/models", "OpenAI's general-purpose speech recognition model."),

    # MLOps — Research (1 skill)
    SkillDef("dspy", "mlops/research", "Build complex AI systems with declarative programming, optimization."),

    # MLOps — Training (5 skills)
    SkillDef("axolotl", "mlops/training", "Expert guidance for fine-tuning LLMs with Axolotl — YAML config."),
    SkillDef("fine-tuning-with-trl", "mlops/training", "Fine-tune LLMs using reinforcement learning with TRL — SFT/DPO/PPO."),
    SkillDef("grpo-rl-training", "mlops/training", "Expert guidance for GRPO/RL fine-tuning with TRL for reasoning."),
    SkillDef("peft-fine-tuning", "mlops/training", "Parameter-efficient fine-tuning for LLMs using LoRA, QLoRA."),
    SkillDef("pytorch-fsdp", "mlops/training", "Expert guidance for Fully Sharded Data Parallel training."),
    SkillDef("unsloth", "mlops/training", "Expert guidance for fast fine-tuning with Unsloth — 2-5x speedup."),

    # Creative (12 skills)
    SkillDef("architecture-diagram", "creative", "Generate dark-themed SVG diagrams of software systems and architectures."),
    SkillDef("ascii-art", "creative", "Generate ASCII art using pyfiglet (571 fonts), cowsay, boxy."),
    SkillDef("ascii-video", "creative", "Production pipeline for ASCII art video — any format."),
    SkillDef("baoyu-comic", "creative", "Knowledge comic creator supporting multiple art styles."),
    SkillDef("baoyu-infographic", "creative", "Generate professional infographics with 21 layout types."),
    SkillDef("design-md", "creative", "Author, validate, diff, and export DESIGN.md files to Google Docs."),
    SkillDef("excalidraw", "creative", "Create hand-drawn style diagrams using Excalidraw JSON format."),
    SkillDef("ideation", "creative", "Generate project ideas through creative constraints."),
    SkillDef("manim-video", "creative", "Production pipeline for mathematical and technical animations."),
    SkillDef("p5js", "creative", "Production pipeline for interactive and generative visualizations."),
    SkillDef("pixel-art", "creative", "Convert images into retro pixel art with hardware-accurate palettes."),
    SkillDef("popular-web-designs", "creative", "54 production-quality design systems extracted from real websites."),
    SkillDef("songwriting-and-ai-music", "creative", "Songwriting craft, AI music generation prompts (Suno focused)."),

    # Note-taking (1 skill)
    SkillDef("obsidian", "note-taking", "Read, search, and create notes in the Obsidian vault."),

    # Productivity (6 skills)
    SkillDef("maps", "productivity", "Location intelligence — geocode a place, reverse-geocode, directions."),
    SkillDef("nano-pdf", "productivity", "Edit PDFs with natural-language instructions using the nanoPDF API."),
    SkillDef("notion", "productivity", "Notion API for creating and managing pages, databases, and content."),
    SkillDef("ocr-and-documents", "productivity", "Extract text from PDFs and scanned documents."),
    SkillDef("powerpoint", "productivity", "PowerPoint generation and manipulation via pptx API."),
    SkillDef("google-workspace", "productivity", "Gmail, Calendar, Drive, Contacts, Sheets, and Docs integration."),
    SkillDef("linear", "productivity", "Manage Linear issues, projects, and teams via the GraphQL API."),

    # Leisure (1 skill)
    SkillDef("find-nearby", "leisure", "Find nearby places (restaurants, cafes, bars, pharmacies, etc.)."),

    # GitHub (5 skills)
    SkillDef("github-auth", "github", "Set up GitHub authentication for the agent using git."),
    SkillDef("github-code-review", "github", "Review code by analyzing git diffs, leaving inline comments."),
    SkillDef("github-issues", "github", "Create, manage, triage, and close GitHub issues."),
    SkillDef("github-pr-workflow", "github", "Full pull request lifecycle — branches, commits, PRs, reviews."),
    SkillDef("github-repo-management", "github", "Clone, create, fork, configure, and manage GitHub repositories."),
    SkillDef("codebase-inspection", "github", "Inspect and analyze codebases using pygount for LOC counts."),

    # Software Development (11 skills)
    SkillDef("audit-then-build", "software-development", "Systematic approach for auditing partially-complete projects."),
    SkillDef("bridging-architecture-analysis", "software-development", "Analyze high-betweenness centrality nodes in a graphify-based graph."),
    SkillDef("build-out-incomplete-project", "software-development", "Systematic approach for completing an incomplete project from scratch."),
    SkillDef("code-reviewer", "software-development", "Code review automation for TypeScript, JavaScript, Python."),
    SkillDef("plan", "software-development", "Plan mode for Hermes — inspect context, write a markdown plan."),
    SkillDef("requesting-code-review", "software-development", "Pre-commit verification pipeline — static security scan, tests."),
    SkillDef("senior-qa", "software-development", "Generates unit tests, integration tests, and E2E tests for web apps."),
    SkillDef("subagent-driven-development", "software-development", "Use when implementing plans with independent subtasks."),
    SkillDef("systematic-debugging", "software-development", "Use when encountering any bug, test failure, or unexpected behavior."),
    SkillDef("test-driven-development", "software-development", "Write tests before implementing features/bugfixes."),
    SkillDef("testing-external-db-dependencies", "software-development", "Testing patterns for modules with external database dependencies."),
    SkillDef("textual-richlog-export", "software-development", "How to export content from Textual's RichLog widget."),
    SkillDef("textual-session-persistence", "software-development", "Fix session persistence in Textual TUI apps."),
    SkillDef("textual-tui-quirks", "software-development", "Textual version-specific import paths, widget quirks, and gotchas."),
    SkillDef("writing-plans", "software-development", "Use when you have a spec or requirements for a multi-step implementation."),

    # MCP (2 skills)
    SkillDef("mcporter", "mcp", "CLI to list, configure, auth, and call MCP servers."),
    SkillDef("native-mcp", "mcp", "Built-in MCP client that connects to MCP servers automatically."),

    # Superproject (2 skills)
    SkillDef("ralph-loop-remediation", "superproject", "Iterative fix loop using PRD-driven stories — one story per iteration."),
    SkillDef("superproject", "superproject", "Transform any repo into a production-grade superproject."),

    # Agent Orchestration (5 skills)
    SkillDef("brainstorming", "brainstorming", "Use before any creative work — structured brainstorming."),
    SkillDef("autonomous-ai-agents", "automated-ai-agents", "Spawn and orchestrate autonomous AI coding agents and multi-agent workflows."),
    SkillDef("claude-code", "automated-ai-agents", "Delegate coding tasks to Claude Code (Anthropic's CLI agent)."),
    SkillDef("codex", "automated-ai-agents", "Delegate coding tasks to OpenAI Codex CLI agent."),
    SkillDef("hermes-agent", "automated-ai-agents", "Complete guide to using and extending Hermes Agent."),
    SkillDef("opencode", "automated-ai-agents", "Delegate coding tasks to OpenCode CLI agent."),
    SkillDef("dispatching-parallel-agents", "dispatching-parallel-agents", "Facing 2+ independent tasks that can be worked on in parallel."),

    # Other (7 skills)
    SkillDef("dogfood", "dogfood", "Systematic exploratory QA testing of web applications."),
    SkillDef("executing-plans", "executing-plans", "Use when you have a written implementation plan to execute."),
    SkillDef("finishing-a-development-branch", "finishing-a-development-branch", "When implementation is complete and all tests pass."),
    SkillDef("receiving-code-review", "receiving-code-review", "Use when receiving code review feedback, before implementation."),
    SkillDef("godmode", "red-teaming", "Jailbreak API-served LLMs using G0DM0D3 techniques."),
    SkillDef("using-git-worktrees", "using-git-worktrees", "Use when starting feature work that needs isolation from main."),
    SkillDef("using-superpowers", "using-superpowers", "Use when starting any conversation — establishes how to work together."),
    SkillDef("verification-before-completion", "verification-before-completion", "Verify work before claiming it passes — quality gates."),
    SkillDef("writing-skills", "writing-skills", "Creating and editing skills — format, structure, and best practices."),
    SkillDef("test-entity-splitting", "test-entity-splitting", "When test setup creates multiple entities with proportional splits."),
    SkillDef("acecapital-testing", "acecapital-testing", "Write and run tests for AceCapital Nepal stock trading platform."),
    SkillDef("jupyter-live-kernel", "data-science", "Use a live Jupyter kernel for stateful, iterative Python exploration."),
]


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

TOTAL_TOOLS = len(TOOLS)
TOTAL_SKILLS = len(SKILLS)


def get_tools_by_category() -> dict[str, list[ToolDef]]:
    """Group all tools by category."""
    groups: dict[str, list[ToolDef]] = {}
    for tool in TOOLS:
        groups.setdefault(tool.category, []).append(tool)
    return dict(sorted(groups.items()))


def get_skills_by_category() -> dict[str, list[SkillDef]]:
    """Group all skills by category."""
    groups: dict[str, list[SkillDef]] = {}
    for skill in SKILLS:
        groups.setdefault(skill.category, []).append(skill)
    return dict(sorted(groups.items()))


def get_tool_count() -> dict[str, dict[str, int]]:
    """Return count of tools and skills per category."""
    tool_counts: dict[str, int] = {}
    for tool in TOOLS:
        tool_counts[tool.category] = tool_counts.get(tool.category, 0) + 1
    skill_counts: dict[str, int] = {}
    for skill in SKILLS:
        skill_counts[skill.category] = skill_counts.get(skill.category, 0) + 1
    return {"tools_by_category": tool_counts, "skills_by_category": skill_counts}


def format_tools_table(tools: list[ToolDef]) -> str:
    """Format tools as a terminal-friendly table."""
    lines = []
    lines.append(f"{'TOOL':<45} {'CATEGORY':<20} {'PARAMS':<25}")
    lines.append("-" * 95)
    for t in tools:
        params_str = ", ".join(t.params) if t.params else "—"
        lines.append(f"{t.name:<45} {t.category:<20} {params_str:<25}")
    return "\n".join(lines)


def format_skills_table(skills: list[SkillDef]) -> str:
    """Format skills as a terminal-friendly table."""
    lines = []
    lines.append(f"{'SKILL':<40} {'CATEGORY':<25} {'DESCRIPTION'}")
    lines.append("-" * 100)
    for s in skills:
        desc = s.description[:60] + "..." if len(s.description) > 60 else s.description
        lines.append(f"{s.name:<40} {s.category:<25} {desc}")
    return "\n".join(lines)
