# Troubleshooting - Self-Annealing

> Part of the [Self-Annealing skill](SKILL.md) - Read SKILL.md first for overview and setup.

Known issues and solutions for the self-annealing system.

## Git Issues

### Push rejected: no upstream branch

**Problem:** First push on a new branch fails with "no upstream branch" error.

**Solution:** The script automatically handles this by adding `-u origin <branch>`. If it still fails:
```bash
git push -u origin master
```

---

### Push rejected: remote has changes

**Problem:** Remote repository has commits not in local.

**Solution:** Pull first, then retry:
```bash
git_api.py pull
annealing_api.py anneal "your message"
```

---

### Authentication failed

**Problem:** Git push fails with authentication error.

**Solution:** Configure SSH key or Personal Access Token:
```bash
# SSH (recommended)
ssh-keygen -t ed25519 -C "your@email.com"
# Add to GitHub: Settings → SSH Keys

# Or HTTPS with token
git remote set-url origin https://<token>@github.com/user/repo.git
```

---

### Nothing to commit

**Problem:** `anneal` command says "No changes to commit".

**Solution:** Check status first:
```bash
git_api.py status

# If you expect changes, check if files are gitignored
git status --ignored
```

---

## Skill Issues

### Skill not found

**Problem:** `update-skill` or `create-skill` fails with "Skill not found".

**Solution:** Check available skills:
```bash
annealing_api.py list-skills

# Verify skill directory exists
ls -la .claude/skills/
```

---

### Edge Cases table not updated

**Problem:** Content added but not in the Edge Cases table.

**Solution:** Ensure the skill has an Edge Cases table with the correct header:
```markdown
## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
```

If missing, add manually or the content will be appended to the file.

---

## Error Store Issues

### Permission denied on errors.json

**Problem:** Cannot write to error store.

**Solution:** Check permissions:
```bash
chmod 644 .claude/skills/self-annealing/data/errors.json
chmod 755 .claude/skills/self-annealing/data/
```

---

### Corrupted errors.json

**Problem:** JSON parsing fails.

**Solution:** Reset the error store:
```bash
echo '{"errors": [], "patterns": []}' > .claude/skills/self-annealing/data/errors.json
```

---

## Environment Issues

### GIT_AUTHOR not set

**Problem:** Commits show wrong author.

**Solution:** Set in `.env`:
```bash
GIT_AUTHOR_NAME=Claude Self-Annealing
GIT_AUTHOR_EMAIL=claude@homelab-assistant
```

Or configure git globally:
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

---

### Module import error

**Problem:** `ModuleNotFoundError: No module named 'git_api'`

**Solution:** Run from correct directory or use full path:
```bash
python .claude/skills/self-annealing/scripts/annealing_api.py anneal "message"

# Or add to PYTHONPATH
export PYTHONPATH="$PYTHONPATH:.claude/skills/self-annealing/scripts"
```

---

## Common Mistakes

### Forgetting Conventional Commits format

**Wrong:**
```bash
annealing_api.py anneal "fixed the timeout bug"
```

**Right:**
```bash
annealing_api.py anneal "fix(agent): handle timeout in API calls"
```

---

### Not checking status before anneal

**Problem:** Accidentally committing unwanted files.

**Solution:** Always check first:
```bash
git_api.py status
git_api.py diff
# Then commit
annealing_api.py anneal "message"
```

---

### Using --no-push and forgetting to push later

**Problem:** Changes committed but never pushed to remote.

**Solution:** Set `AUTO_PUSH_ENABLED=true` in `.env` or remember to push:
```bash
git_api.py push
```

---

## Agent-Specific Issues

> **Note**: The following issues are specific to agent behavior and may belong in an agent-focused skill rather than the self-annealing skill.

### Acknowledgment + action verb misclassified as small talk

**Problem:** Short messages like "Okay schieß mal los" or "Ja mach mal" were treated as pure conversational acknowledgments, causing the agent to lose context and respond with generic greetings instead of following up on the previous conversation.

**Root Cause:** The conversational message detector matched "okay"/"ja" at the start and treated the entire message as small talk, ignoring that action verbs ("schieß", "mach") followed.

**Solution:** Check for action verbs BEFORE classifying as conversational. Messages containing action verbs like "schieß", "mach", "zeig", "los", "starte", "stopp" are NOT purely conversational - they're context-dependent requests that need chat history.

**Pattern:** Acknowledgment + Action Verb = Context-dependent request, not small talk

**Code location:** `agent/intent_classifier.py` - `_is_conversational_message()` function

**Implementation:**
```python
# Check for action verbs FIRST
ACTION_VERBS = ["schieß", "mach", "leg", "fang", "zeig", "erklär",
                "sag", "hilf", "starte", "stopp", "los", "weiter"]

has_action_verb = any(verb in message_lower for verb in ACTION_VERBS)
if has_action_verb:
    return False  # Not conversational - it's a request
```

**Key Learning:** In conversational AI, word order and context matter. A message starting with an acknowledgment doesn't mean it's not an action request. Check for intent signals (action verbs) across the entire message.

---

### Tool schema missing parameter guidance causes unbounded output

**Problem:** LLM tool-calling returned 99K+ characters of unfiltered data, overwhelming the response formatter. Model never passed camera filters or limits when calling events actions.

**Root Cause:** The tool schema's `args` field was defined as `additionalProperties: true` with no parameter documentation. Without parameter guidance in the schema, the LLM had no way to know that `camera`, `limit`, or `hours` parameters existed or how to use them.

**Solution:** Extract parameter definitions from Python argparse scripts and include them in tool descriptions. Three-step fix:

1. **Parse argparse from scripts** (`skill_loader.py`):
   ```python
   # Regex handles nested parentheses in help text
   # e.g., help="Last N hours (e.g., 24h, 1h)"
   pattern = r'add_argument\(["\']--?([a-zA-Z0-9_-]+)["\'][^)]*help=["\']([^"\']*(?:\([^()]*\)[^"\']*)*)["\']'
   ```

2. **Include parameters in action descriptions** (`tool_registry.py`):
   ```python
   description = f"{skill_name}/{action}: {help_text}"
   if params:
       param_list = ", ".join([f"--{name}: {help}" for name, help in params])
       description += f"\n\nParameters:\n{param_list}"
   ```

3. **Add default limits** to prevent unbounded queries:
   ```python
   if "--limit" not in args and action in ["events", "list"]:
       args.extend(["--limit", "20"])
   ```

**Key Regex Pattern:** `[^()]*(?:\([^()]*\)[^()]*)*` matches text with nested parentheses (crucial for argparse help strings with examples).

**Impact:** Reduced token usage from 99K to <5K chars per query. Model now correctly applies filters and limits.

**Code Locations:**
- `agent/skill_loader.py` - Parameter extraction regex
- `agent/tool_registry.py` - Tool schema generation with parameters

**Key Learning:** LLM tool schemas MUST include parameter guidance. `additionalProperties: true` is insufficient - the model needs explicit parameter names, types, and descriptions to use tools effectively. Extract from code when possible (argparse, decorators, type hints).

**Pattern:** No schema guidance → Model doesn't know parameters exist → Unbounded/unfiltered output

**Future:** This troubleshooting entry should be moved to an agent-focused skill (e.g., `/agent-tool-orchestration`) when such a skill is created.

---
