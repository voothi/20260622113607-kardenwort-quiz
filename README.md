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
- **Command Mode (Vim-style)**: Fast command execution with single-key actions, toggleable answer/command modes with state saving, and separate configurations for keyboard arrow hints.
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

# Enable command mode (vim-style) (true/false)
command_mode = true

# Start in command mode (true/false)
start_in_command_mode = false

# Esc toggles modes (true/false)
command_mode_esc_toggles = true

# Save input on mode switch (true/false)
command_mode_save_input = false

# Save command input on mode switch (true/false)
command_mode_save_command = false

# Single-key commands (true/false)
command_mode_single_key = false

# Enable keyboard arrow hints in command mode (true, swap, false)
command_mode_arrow_hints = false

# Enable keyboard arrow hints in answer mode (true, swap, false)
answer_mode_arrow_hints = false

# Mask context with underscores matching the exact length of the target word/phrase (true/false)
exact_length_mask = true

# Use strict case-sensitive matching for the diff display (true/false)
case_sensitive_diff = true

# Ignore punctuation marks when validating answers and generating diffs (true/false)
ignore_punctuation = true

[fields]
# Ordered list of headers for headerless files. Empty lines (holes) are supported
# to correctly align columns when some headers are blank or unused.
Quotation
WordSource
WordSource2
WordSourceInflectedForm
WordSourceInflectedForm2
WordDestination
WordDestinationInflectedForm
WordSourceContext
SentenceSourceContextLeft
SentenceSource
SentenceSourceContextRight
SentenceDestinationContextLeft
SentenceDestination
SentenceDestinationContextRight
SentenceDestination2ContextLeft
SentenceDestination2
SentenceDestination2ContextRight
SentenceSourceWordlist
SentenceSourceCloze
SentenceSourceRewriteAISentenceSource
SentenceSourceRewriteAISentenceDestination
WordSourceMorphologyAI
Note
WordRussian
WordUkrainian
WordEnglish
WordGerman
WordSourceMorphemeFirst
WordSourceMorphemeFirstDefinition
WordSourceMorphemeSecond
WordSourceMorphemeSecondDefinition
WordSourceMorphemeThird
WordSourceMorphemeThirdDefinition
WordSourceMorphemeFourth
WordSourceMorphemeFourthDefinition
WordSourceMorphemeFifth
WordSourceMorphemeFifthDefinition
WordSourceIPA
WordSourceSynonymAI
WordSourceDefinitionAISentenceSource
WordSourceDefinitionAISentenceDestination
WordSourceDefinitionFirst
WordSourceDefinitionFirstClipping
WordSourceDefinitionSecond
WordDestinationDefinitionFirst
WordDestinationDefinitionSecond
WordSourceAudio
SentenceSourceIPA
SentenceSourceAudio
Image
WordSourceCloze
WordSourceContextAI
TextSource
TextDestination
TextSourceURL
SentenceEnglish
SentenceGerman
SentenceUkrainian
SentenceRussian
Source
SourceURL
SeparatorAudio
Source-en-GB
Source-en-US
Source-de-DE
Source-uk-UA
Source-ru-RU
Destination-en-GB
Destination-en-US
Destination-de-DE
Destination-uk-UA
Destination-ru-RU
Overlapping
ToggleAlwaysEmptyField
Note ID
am-all-morphs
am-all-morphs-count
am-unknown-morphs
am-unknown-morphs-count
am-highlighted
am-score
am-score-terms
am-study-morphs
SentenceSourceIndex
Deck
LeitnerBox
LeitnerDue

[fields_mapping.word]
# Mapping rules for single word cards
WordSourceInflectedForm = source_word
SentenceSource = source_sentence
SentenceSourceIndex = source_index
LeitnerBox = leitner_box
LeitnerDue = leitner_due

[fields_mapping.sentence]
# Mapping rules for sentence-level cards
WordSourceInflectedForm = source_word
SentenceSource = source_sentence
SentenceSourceIndex = source_index
LeitnerBox = leitner_box
LeitnerDue = leitner_due
```

### Dynamic Field Mapping
- **`[fields]`**: A list of fallback header names to assign to files that lack a header row. Empty lines (holes) within this list represent empty columns.
- **`[fields_mapping.word]` / `[fields_mapping.sentence]`**: Allows mapping arbitrary TSV headers to five target keys:
  - `source_word`: The vocabulary term.
  - `source_sentence`: The context sentence.
  - `source_index` (optional): Position index of the term.
  - `leitner_box`: Column name for the Leitner box level.
  - `leitner_due`: Column name for the Leitner due date timestamp.
- **Custom Leitner Columns**: If the mapped `leitner_box` or `leitner_due` columns are not found in the TSV file, they are automatically appended during the quiz run.


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

### 4. MPV Integration
The TSV Quiz features bidirectional integration with the MPV media player for context synchronization.

1. **Gating & Enabling**: Set `mpv_integration = true` in `config.ini` under the `[Leitner]` section.
2. **Forward Sync (Quiz ➔ MPV)**: Press `y` in command mode (or type `/y` or `/sync_forward`) to launch `mpv` with the corresponding video file and seek to the card's exact timestamp.
3. **Backward Sync (MPV ➔ Quiz)**: A backward trigger sends commands via named pipe to focus and jump to the card closest to the current video timestamp.

#### Configuration Options in `config.ini`:
- `mpv_integration`: Enable/disable integration features (`true`/`false`).
- `mpv_pipe_path`: The named pipe or socket path of the MPV IPC server (default: `\\.\pipe\mpv-socket`).
- `quiz_pipe_path`: The reverse listener named pipe or socket path (default: `\\.\pipe\kardenwort-quiz`).
- `python_cmd`: The python execution command or binary name/path (default: `python`).

[Return to Top](#kardenwort-tsv-quiz)

## Kardenwort Ecosystem
This utility is part of the Zettelkasten and **[Kardenwort](https://github.com/kardenwort)** productivity toolset, designed to maximize development velocity, maintain traceability, and integrate AI agent logs with Obsidian Vault note graphs.

[Return to Top](#kardenwort-tsv-quiz)

- **Project Anchor ZID**: `20260622113607`

[Return to Top](#kardenwort-tsv-quiz)

## License
MIT License. See LICENSE.txt file for details.
