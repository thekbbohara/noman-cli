# Design: Diff Preview + Code Navigation for Agent

**Date:** 2026-04-25

## Goal

Enable agent to make surgical code changes with visibility — agent can navigate codebase to find locations, see diff preview, and apply changes while user sees what changed.

## Core

### 1. Diff Preview
- `diff_preview(path, new_content)` — reads current file, returns unified diff format
- Shows line-by-line changes before applying

### 2. Edit Tool
- `edit_file(path, old_content, new_content)` — replaces content atomically
- Auto-applies after showing diff (user approved flow #2)

### 3. Navigation Tools (reuse existing)
- Extend `tools/__init__.py` with:
  - `find_definition(symbol)` — find where symbol is defined
  - `find_references(symbol)` — find where symbol is used
  - `search_symbols(query)` — search by name/signature

### 4. TUI Display
- Show colored diff after each edit (+green, -red)
- Integrates with existing TUI chat output

## Flow

1. Agent uses navigation to locate code (find_definition, find_references)
2. Agent calls edit_file with change
3. System shows diff preview, applies automatically
4. TUI displays colored diff in chat output

## Components

- `core/tools/__init__.py` — add `diff_preview`, `edit_file`, navigation tools
- `cli/tui.py` — render diff with colors in output

## Scope

Single session implementation — focus on agent making correct edits with visibility.

LSP for deep analysis (hover, go-to-def in-editor) — phase 2.