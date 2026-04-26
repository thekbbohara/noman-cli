# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- TUI diff preview mode
- Model switching in TUI
- Session persistence with active session tracking
- Skill management commands
- Emergency stop functionality
- Stats command for execution tracking

### Changed
- Updated Textual import paths for compatibility
- Improved context management with skeleton maps

### Fixed
- Context bundle token budget calculation
- Session active state tracking
- Tool bus error handling

## [0.1.0] — 2026-04-22

### Added
- Initial release
- Model-agnostic adapter system (OpenAI, Anthropic)
- Textual-based TUI with REPL mode
- SQLite-backed tiered memory (episodic, semantic, procedural)
- Context management with skeleton maps and centrality scoring
- 35+ tools (file ops, git, search, docker, etc.)
- Filesystem and network sandboxing
- Self-improvement system (trace critic, meta-agent, rollback)
- Comprehensive test suite (274 tests)
- Architecture documentation
