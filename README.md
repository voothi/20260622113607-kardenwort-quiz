# Kardenwort TSV Quiz

[![Version](https://img.shields.io/badge/version-v1.0.0-green)](https://github.com/voothi/20260622113607-kardenwort-quiz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, terminal-based vocabulary study quiz utility for Windows. Designed to study TSV (Tab-Separated Values) flashcards using the Leitner system for spaced repetition, it creates an efficient learning workflow seamlessly integrated into your right-click "Send to" menu.

## Table of Contents
- [Description](#description)
- [Features](#features)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Usage](#usage)
- [Kardenwort Ecosystem](#kardenwort-ecosystem)
- [License](#license)

---

## Description
The Kardenwort TSV Quiz is a flashcard study tool written in Lua that helps you memorize vocabulary from TSV files. It utilizes a configurable spaced-repetition Leitner box system and offers a highly customizable study experience directly from the command line, with options for flashcard modes, diff highlighting, and penalty settings. 

[Return to Top](#kardenwort-tsv-quiz)

## Features
- **Leitner System**: Spaced repetition with customizable intervals for each box level.
- **Diff Highlighting**: Highlights exact capitalization errors in your answers and optionally ignores punctuation for a smoother study experience.
- **Multi-File Support**: Pass multiple TSV files at once to consolidate all vocabulary into a single quiz session.
- **Flexible Ordering**: Sort due reviews and new cards by due date, added order, or randomly.
- **Flashcard Mode**: Clear terminal screen stages for front and back viewing.
- **Context Masking**: Option to use underscores matching the exact length of the target word for better hints.
- **Easy Windows Integration**: An automatic shortcut installer (`install.py`) to add the quiz to your Windows "Send to" right-click menu.

[Return to Top](#kardenwort-tsv-quiz)

## Project Structure
```text
20260622113607-kardenwort-quiz/
├── config.ini               # Active settings (intervals, sort orders, penalties)
├── .gitignore               # Excludes git caches and local configurations
├── install.py               # Windows SendTo Shortcut Installer
├── LICENSE.txt              # MIT License
├── README.md                # Premium documentation
├── tsv_quiz.lua             # Core Lua script handling the spaced repetition and quiz logic
└── tests/                   # Automated unit test suite
```

[Return to Top](#kardenwort-tsv-quiz)

## Configuration

Configuring the utility is simple via the `config.ini` file located at the root of the project.

### Default `config.ini`
```ini
[Leitner]
# Repetition intervals for each box level (m = minutes, h = hours, d = days)
# The number of entries here dynamically defines the number of boxes.
intervals = 5m, 1h, 1d, 3d, 7d

# Max new cards introduced per quiz session.
# Set to -1 to disable the limit and load all new cards.
new_cards_per_day = 20

# Study ahead when no cards are due (true/false)
# - false: If no cards are due, print a summary and exit (default).
# - true: If no cards are due, let the user study cards ahead of schedule.
study_ahead = false

# Penalty for incorrect answers (reset / decrease)
# - reset: Drop progress all the way back to Box 1 (default).
# - decrease: Drop progress down by one box level.
incorrect_penalty = reset

# Serving order of new cards vs. due reviews (review_first / new_first / mix)
new_review_order = review_first

# Sort order for due reviews (due_date / order_added / random)
review_sort_order = due_date

# Sort order for new cards (order_added / random)
new_sort_order = order_added

# Enable flashcard mode (true/false)
single_card_mode = true

# Mask context with underscores matching the exact length of the target word/phrase (true/false)
exact_length_mask = true

# Use strict case-sensitive matching for the diff display (true/false)
case_sensitive_diff = true

# Ignore punctuation marks when validating answers and generating diffs (true/false)
ignore_punctuation = true
```

[Return to Top](#kardenwort-tsv-quiz)

## Usage

### 1. Installation
Run the Python installer to automatically create a right-click shortcut in Windows:
```powershell
python install.py
```

### 2. Studying from the Context Menu
1. Locate your vocabulary `.tsv` file in Windows Explorer.
2. Right-click the file → **Send to** → **Kardenwort TSV Quiz**.

### 3. Command Line Execution
Alternatively, you can run the script manually against a TSV file:
```powershell
lua tsv_quiz.lua path/to/your/vocabulary.tsv
```

You can also pass multiple files at once to consolidate all vocabulary into a single quiz session:
```powershell
lua tsv_quiz.lua vocab1.tsv vocab2.tsv
```

[Return to Top](#kardenwort-tsv-quiz)

## Kardenwort Ecosystem
This utility is part of the Zettelkasten and **[Kardenwort](https://github.com/kardenwort)** productivity toolset, designed to maximize development velocity, maintain traceability, and integrate AI agent logs with Obsidian Vault note graphs.

[Return to Top](#kardenwort-tsv-quiz)

- **Project Anchor ZID**: `20260622113607`

[Return to Top](#kardenwort-tsv-quiz)

## License
MIT License. See LICENSE.txt file for details.
