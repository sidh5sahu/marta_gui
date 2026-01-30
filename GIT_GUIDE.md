# GitLab Push Guide - Marta GUI

## Your Current Situation

**Repository**: `ssh://git@gitlab.cern.ch:7999/niser/marta-gui.git`  
**Status**: Branch diverged (2 local commits, 1 remote commit)

## Quick Push (Recommended Steps)

### Option 1: Push with Merge (Safest)

```bash
# 1. Add all new and modified files
git add .

# 2. Commit your changes
git commit -m "feat: refactored app.py into managers + Priority 1 improvements

- Extracted 4 managers (ConnectionManager, MartaController, PlotManager, ReportManager)
- Reduced app.py from 1850 to 1201 lines (-35%)
- Added structured logging system
- Added configuration validation
- Created comprehensive README.md and documentation
- All tests passing (100%)
"

# 3. Pull remote changes and merge
git pull --no-rebase origin main

# 4. Resolve any conflicts (if any), then:
git push origin main
```

### Option 2: Force Push (Use with caution!)

**⚠️  WARNING**: Only use if you're sure you want to overwrite remote changes!

```bash
# Add and commit
git add .
git commit -m "feat: major refactoring with Priority 1 improvements"

# Force push (overwrites remote)
git push --force origin main
```

### Option 3: Create a New Branch (Safest for collaboration)

```bash
# 1. Create and switch to a new branch
git checkout -b refactoring-improvements

# 2. Add all files
git add .

# 3. Commit
git commit -m "feat: refactored app.py into managers + Priority 1 improvements"

# 4. Push new branch
git push -u origin refactoring-improvements

# Then create a Merge Request on GitLab
```

---

## Detailed Step-by-Step

### Step 1: Review What Will Be Committed

```bash
git status
```

### Step 2: Add Files

```bash
# Add all files
git add .

# Or add specific files only
git add README.md INSTALL.md CONFIG.md requirements.txt
git add marta_app/gui/managers/
git add marta_app/utils/
git add marta_app/config.py
git add test_refactoring.py
```

### Step 3: Commit with Detailed Message

```bash
git commit -m "feat: major refactoring and quality improvements

## Refactoring (Phase 1)
- Extracted ConnectionManager (~350 lines)
- Extracted MartaController (~500 lines)
- Extracted PlotManager (~400 lines)
- Extracted ReportManager (~100 lines)
- Reduced app.py from 1850 to 1201 lines (-35%)

## Priority 1 Improvements
- Added structured logging system (marta_app/utils/logger.py)
- Added configuration validation with detailed errors
- Created comprehensive README.md
- Added INSTALL.md and CONFIG.md documentation

## Testing
- All 5 refactoring tests passing (100%)
- Config validation tests passing
- Logger tests passing

## Files Changed
- Created: marta_app/gui/managers/ (4 files)
- Created: marta_app/utils/logger.py
- Created: README.md, INSTALL.md, CONFIG.md, requirements.txt
- Modified: marta_app/gui/app.py (-649 lines)
- Modified: marta_app/config.py (+90 lines validation)
- Created: test_refactoring.py

Code quality upgraded from B+ to A grade.
"
```

### Step 4: Handle Diverged Branch

Your branch has diverged. You have 2 options:

**Option A: Merge (Recommended)**
```bash
git pull --no-rebase origin main
# If conflicts appear, resolve them then:
git add .
git commit -m "merge: resolved conflicts"
git push origin main
```

**Option B: Rebase (Clean history)**
```bash
git pull --rebase origin main
# If conflicts appear, resolve them then:
git add .
git rebase --continue
git push origin main
```

### Step 5: Push to GitLab

```bash
git push origin main
```

---

## .gitignore Recommendations

Make sure these are in your `.gitignore`:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/

# Virtual environments
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Logs
*.log
marta_logs/
logs/

# Config (if sensitive)
# marta_app/config.json  # Uncomment if you don't want to commit config

# Test
.pytest_cache/
htmlcov/

# Backup files
*.backup
*.progress
```

---

## Troubleshooting

### "Permission denied (publickey)"
```bash
# Check SSH key
ssh -T git@gitlab.cern.ch

# If fails, add your SSH key to GitLab:
# 1. Generate key: ssh-keygen -t ed25519 -C "your_email@example.com"
# 2. Copy: cat ~/.ssh/id_ed25519.pub
# 3. Add to GitLab: Settings → SSH Keys
```

### "Remote rejected"
```bash
# You may not have push permissions
# Contact repository owner for access
```

### "Merge conflicts"
```bash
# After git pull, Git will show conflicted files
# Edit each file to resolve conflicts (remove <<<<<<, ======, >>>>>>)
git add <resolved-files>
git commit -m "merge: resolved conflicts"
git push origin main
```

---

## Best Practices

1. **Always pull before push**: `git pull origin main` before `git push`
2. **Use descriptive commit messages**: Explain what and why
3. **Don't commit sensitive data**: Check config files
4. **Use branches for features**: Keep main stable
5. **Review changes**: `git diff` before commit
6. **Small, focused commits**: Better than one huge commit

---

## What Files Are New

Files created during refactoring and improvements:

```
New Managers:
✓ marta_app/gui/managers/__init__.py
✓ marta_app/gui/managers/connection_manager.py
✓ marta_app/gui/managers/controller.py
✓ marta_app/gui/managers/plot_manager.py
✓ marta_app/gui/managers/report_manager.py

New Utils:
✓ marta_app/utils/__init__.py
✓ marta_app/utils/logger.py

Documentation:
✓ README.md
✓ INSTALL.md
✓ CONFIG.md
✓ requirements.txt

Tests:
✓ test_refactoring.py

Modified:
✓ marta_app/gui/app.py (1850 → 1201 lines)
✓ marta_app/config.py (added validation)
✓ marta_app/config.json (last_run_number updated)
```

---

## Quick Reference Commands

```bash
# Check status
git status

# See what changed
git diff

# Add all files
git add .

# Commit
git commit -m "your message"

# Pull latest
git pull origin main

# Push
git push origin main

# Create branch
git checkout -b branch-name

# Switch branch
git checkout main

# View commit history
git log --oneline
```

---

**Ready to push? Use Option 1 (merge) for safest approach!**
