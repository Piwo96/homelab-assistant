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

When creating a new skill, check if a global `/skill-creator` skill exists and use it. The skill-creator provides structured guidance for authoring skills following best practices.

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

### When something breaks:
1. Read error message and stack trace
2. Fix the issue and test again
3. Update the relevant skill with what you learned (API limits, edge cases, better approaches)
4. System is now stronger

**For coding errors:** Use the global skill `/error-handling-patterns` for guidance on robust error handling, retry patterns, circuit breakers, and graceful degradation. This skill covers best practices across TypeScript, Python, Rust, and Go.

### When new functionality is needed:
1. User requests a capability not yet covered by the skill
2. If it fits thematically: extend the existing skill (API endpoints, scripts, documentation)
3. If it doesn't fit: create a new skill using `/skill-creator`
4. Test the new functionality
5. System now handles more scenarios

**Decision guide:** Follow single responsibility principle - each skill should do one thing well. If the new functionality would dilute the skill's focus or conflict with its naming, create a separate skill.

Skills are living documents. When you discover constraints, better approaches, common errors, or **new capabilities**: **update the skill** (ask first unless explicitly told to modify freely).

## Sub-Agents

Sub-Agents are specialized background workers that handle specific tasks autonomously. Unlike skills (which are instructions you follow), sub-agents are independent processes you spawn.

### Concept

| Aspect | Skills | Sub-Agents |
|--------|--------|------------|
| What | Instructions (Markdown SOPs) | Autonomous workers |
| How | You read and follow them | You spawn them via Task tool |
| When | Before doing work | After doing work (background) |
| Purpose | Guide your actions | Offload parallel tasks |

### Available Sub-Agents

| Agent | Purpose | Can Edit | Cannot Edit |
|-------|---------|----------|-------------|
| `code-reviewer` | Reviews code quality, security, best practices | Scripts (`.py`, `.sh`, `.ts`...) | Markdown (`.md`) |
| `skill-documenter` | Documents learnings into skill files | Markdown (`.md`) | Scripts |

### Storage Locations

- **Global agents (Claude)**: `~/.claude/agents/` - Available across all projects
- **Global agents (Gemini)**: `~/.gemini/antigravity/agents/` - Available across all projects
- **Project agents**: `.claude/agents/` - Project-specific agents

### Self-Annealing Workflow with Sub-Agents

```
You complete a task
        │
        ├─► Code written?
        │   └─► Spawn: code-reviewer (background)
        │       → Reviews scripts, fixes HIGH/CRITICAL issues
        │
        └─► Error resolved? New pattern discovered?
            └─► Spawn: skill-documenter (background)
                → Documents learning in relevant skill MD
```

### Usage

Spawn sub-agents as background tasks using the Task tool:

```
# After writing code
Task:
  subagent_type: code-reviewer
  run_in_background: true
  prompt: "Review the code I created: [file paths]"

# After self-annealing (error resolved, new pattern found)
Task:
  subagent_type: skill-documenter
  run_in_background: true
  prompt: "Document this learning: [what was learned]"
```

### When to Spawn Sub-Agents

**code-reviewer**: After any code creation or modification
- New scripts added
- Existing code changed
- Bug fixes implemented

**skill-documenter**: After any learning event
- Error was encountered and resolved
- API limit or constraint discovered
- Better approach found through trial
- Edge case handled

## Operating Principles

1. **Skills first**: Before manual work, check `~/.claude/skills/` and `.claude/skills/`
2. **Self-improve on errors**: Fix → Test → Update skill → System is stronger
3. **Prefer determinism**: Complex logic belongs in code/scripts, not ad-hoc decisions
4. **Progressive disclosure**: Load skill resources on-demand, not all upfront

## Summary

You sit between user intent (skills/directives) and deterministic execution (code/scripts). Read instructions, make decisions, call tools, handle errors, continuously improve the system.

Be pragmatic. Be reliable. Self-anneal.
