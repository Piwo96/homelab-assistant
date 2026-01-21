# Agent Instructions

> This file is mirrored across CLAUDE.md, AGENTS.md, and GEMINI.md so the same instructions load in any AI environment.

## Architecture

This system follows a 3-layer architecture that separates concerns:

**Layer 1: Directives (What to do)**
- Skills define workflows as Markdown SOPs
- Each skill contains: goals, inputs, tools, outputs, edge cases
- Natural language instructions, like you'd give a mid-level developer

**Layer 2: Orchestration (Decision making)**
- This is you. Your job: intelligent routing.
- Read skills, execute tools in the right order, handle errors
- You're the glue between intent and execution

**Layer 3: Execution (Doing the work)**
- Deterministic code and scripts
- API calls, data processing, file operations
- Reliable, testable, fast

**Why this works:** Errors compound. 90% accuracy per step = 59% success over 5 steps. The solution: push complexity into deterministic skills and code. You focus on decision-making.

## Skills

Skills are your instruction set. They live in these locations:

- **Global skills (Claude)**: `~/.claude/skills/` - Available across all projects
- **Global skills (Gemini)**: `~/.gemini/antigravity/skills/` - Available across all projects
- **Project skills**: `.claude/skills/` - Project-specific workflows

### Creating New Skills

When creating a new skill:

1. **Project skill**: Create in `.claude/skills/skill-name/`
2. **Global skill**: Create in the `chainmatics-skills` repository under `global-skills/skill-name/`, then run `/skill-sync` to install locally

Always ask the user whether the skill should be project-specific or global.

### Syncing Global Skills

This repository includes a project skill `/skill-sync` that synchronizes global skills to local directories. Use it to install or update skills selectively. The script pulls latest changes and lets you choose which skills to install.

### Using Skills

1. **Check for skills first**: Before doing a task manually, check if a skill exists
2. **Invoke via slash command**: `/skill-name` or describe the task naturally
3. **Follow the skill**: Read `SKILL.md`, then load additional resources as needed

### Skill Structure

```
skills/
└── skill-name/
    ├── SKILL.md           # Entry point (always read first)
    ├── PATTERNS.md        # Optional: patterns and mappings
    ├── BEST_PRACTICES.md  # Optional: guidelines
    └── scripts/           # Optional: utility scripts
```

## Self-Annealing

When something breaks:
1. Read error message and stack trace
2. Fix the issue and test again
3. Update the relevant skill with what you learned (API limits, edge cases, better approaches)
4. System is now stronger

**For coding errors:** Use the global skill `/error-handling-patterns` for guidance on robust error handling, retry patterns, circuit breakers, and graceful degradation. This skill covers best practices across TypeScript, Python, Rust, and Go.

Skills are living documents. When you discover constraints, better approaches, or common errors: **update the skill** (ask first unless explicitly told to modify freely).

## Operating Principles

1. **Skills first**: Before manual work, check `~/.claude/skills/` and `.claude/skills/`
2. **Self-improve on errors**: Fix → Test → Update skill → System is stronger
3. **Prefer determinism**: Complex logic belongs in code/scripts, not ad-hoc decisions
4. **Progressive disclosure**: Load skill resources on-demand, not all upfront

## Summary

You sit between user intent (skills/directives) and deterministic execution (code/scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
