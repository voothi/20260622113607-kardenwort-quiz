import subprocess
import time
import sys
from pathlib import Path
import struct
import re
import pytest

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

def read_tsv_entry(path, word):
    """
    Helper to safely read a TSV file and return a card entry as a dictionary by matching the WordSource or Quotation.
    """
    with open(path, "r", encoding="utf-8", newline="\n") as f:
        lines = f.read().splitlines()
        
    if not lines:
        return None
    
    # Skip any comment lines at the beginning to find the header row
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        header_line_idx += 1
        
    if header_line_idx >= len(lines):
        return None
        
    headers = lines[header_line_idx].split("\t")
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if cols:
            word_source = cols[1] if len(cols) > 1 else ""
            quotation = cols[0] if len(cols) > 0 else ""
            if word_source == word or quotation == word:
                while len(cols) < len(headers):
                    cols.append("")
                return dict(zip(headers, cols))
            
    return None

def focus_single_card(quiz_env, tsv_name, target_word):
    """
    Modifies the TSV file in quiz_env so that only target_word is due/active (due=0),
    while all other cards are scheduled in the far future.
    """
    tsv_path = quiz_env / tsv_name
    lines = tsv_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
        
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    
    due_idx = headers.index("LeitnerDue") if "LeitnerDue" in headers else -1
    box_idx = headers.index("LeitnerBox") if "LeitnerBox" in headers else -1
    
    if due_idx == -1:
        headers.append("LeitnerDue")
        due_idx = len(headers) - 1
    if box_idx == -1:
        headers.append("LeitnerBox")
        box_idx = len(headers) - 1
        
    future_time = int(time.time()) + 100000
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
            
        word_source = cols[1] if len(cols) > 1 else ""
        quotation = cols[0] if len(cols) > 0 else ""
        
        if word_source == target_word or quotation == target_word:
            cols[box_idx] = "1"
            cols[due_idx] = "0"
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(future_time)
            
        new_lines.append("\t".join(cols))
        
    tsv_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")

def run_quiz(env_dir, args, inputs, env=None):
    cmd = ["lua", "tsv_quiz.lua"] + args
    
    # Run the process
    process = subprocess.Popen(
        cmd,
        cwd=env_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env
    )
    
    # Provide inputs and get output
    stdout, stderr = process.communicate(input="\n".join(inputs) + "\n", timeout=5)
    return process.returncode, stdout, stderr

def test_help_argument(quiz_env):
    """Test the basic CLI flag handling."""
    code, out, err = run_quiz(quiz_env, ["--help"], [])
    assert code == 0
    assert "Usage:" in out
    assert "lua tsv_quiz.lua [file.tsv]" in out

def test_single_file_quit(quiz_env):
    """Test that the user can start and quit the quiz gracefully."""
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    assert code == 0
    assert "Exiting quiz early" in out

def test_correct_answer_updates_box(quiz_env):
    """Test answering a card correctly updates its Leitner Box in the TSV."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["properly", "/q"])
    
    assert code == 0
    assert "Diff" in out
    
    # Verify the TSV was updated
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "2", f"Expected Box 2, got {entry['LeitnerBox']}"
    assert int(entry["LeitnerDue"]) > 0, "Expected LeitnerDue to be updated to a future timestamp"

def test_case_insensitivity_and_spacing(quiz_env):
    """Test the normalizer for user inputs with odd casing and spacing."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["  PROperly  ", "/q"])
    
    assert code == 0
    assert "Diff" in out
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry["LeitnerBox"] == "2"

def test_study_ahead(quiz_env):
    """Test the scheduling algorithm's behavior when no cards are currently due."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "study_ahead = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Put all cards in the far future
    future_time = int(time.time()) + 100000
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
        
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        cols[box_idx] = "1"
        cols[due_idx] = str(future_time)
        new_lines.append("\t".join(cols))
        
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    assert code == 0
    assert "Entering \"Study Ahead\" mode" in out
    assert "Question 1/" in out

def test_review_sort_order(quiz_env):
    """Test presentation order sort algorithms for due reviews."""
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
        
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
            
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source == "properly":
            cols[box_idx] = "1"
            cols[due_idx] = "1" # Box 1, due
        elif word_source == "meant":
            cols[box_idx] = "5"
            cols[due_idx] = "1" # Box 5, due
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(int(time.time()) + 100000) # not due
            
        new_lines.append("\t".join(cols))
        
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    assert code == 0
    
    # 'properly' is Box 1, should be sorted first (contains 'clear way to use it')
    clean_out = strip_ansi(out).replace("\n", " ")
    assert "clear way to use it" in clean_out
    assert "unified intelligence" not in clean_out

def test_incorrect_penalty_decrease(quiz_env):
    """Test answering a card incorrectly lowers its Leitner Box."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("incorrect_penalty = reset", "incorrect_penalty = decrease")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Mock card 'properly' in Box 3
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
        
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    
    box_idx = headers.index("LeitnerBox")
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source == "properly":
            cols[box_idx] = "3"
        new_lines.append("\t".join(cols))
        
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["wrong_answer", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    assert "wronganswer" in clean_out.replace("-", "")
    assert "properly" in clean_out.replace("-", "")
    
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry["LeitnerBox"] == "2", f"Expected Box 2, got {entry['LeitnerBox']}"

def test_utf8_masking_alignment(quiz_env):
    """Test exact length masking configuration with multibyte UTF-8 characters."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # We will use data.tsv which has 'Absätze' (7 characters, contains 'ä')
    focus_single_card(quiz_env, "data.tsv", "Absätze")
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    assert code == 0
    # Target word 'Absätze' has 7 characters, should be 7 underscores
    assert "_______" in out

def test_lua_lnk_resolution(quiz_env):
    """Test pure Lua .lnk parser universally via a mock binary payload."""
    lnk_path = quiz_env / "test.lnk"
    target_path = "20260604184114-microsoft-just-shocked-the.en.tsv"
    
    # Constructing the binary
    header = bytearray(76)
    header[0:4] = b"L\0\0\0"
    flags = 0x02 # Only HasLinkInfo
    struct.pack_into("<I", header, 20, flags)
    
    link_info_start = 76
    link_info_size = 28 + len(target_path) + 1
    link_info = bytearray(link_info_size)
    struct.pack_into("<I", link_info, 0, link_info_size)
    struct.pack_into("<I", link_info, 4, 28)
    struct.pack_into("<I", link_info, 8, 0x01)
    struct.pack_into("<I", link_info, 16, 28)
    
    link_info[28:28+len(target_path)] = target_path.encode('utf-8')
    link_info[28+len(target_path)] = 0
    
    with open(lnk_path, "wb") as f:
        f.write(header)
        f.write(link_info)
        
    code, out, err = run_quiz(quiz_env, ["test.lnk"], ["/q"])
    assert code == 0
    assert f"Loading: {target_path}" in out

def test_multi_file_loading(quiz_env):
    """Test passing multiple files correctly aggregates the queue."""
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv", "data.tsv"], ["/q"])
    
    assert code == 0
    assert "Loading: 20260604184114-microsoft-just-shocked-the.en.tsv" in out
    assert "Loading: data.tsv" in out
    assert "Queue Summary:" in out

def test_hints_display(quiz_env):
    """Test standard and advanced hints."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/h", "/h 2 1 1", "/q"])
    
    assert code == 0
    assert "💡 Hint:" in out
    assert "(length: 8)" in out

def test_single_card_mode(quiz_env):
    """Test flashcard mode toggling."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("single_card_mode = false", "single_card_mode = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["properly", "", "/q"])
    
    assert code == 0
    assert "\x1b[2J\x1b[H" in out
    assert "Press 'Enter' or 'Space' to continue, type '?' for help... " in out


def test_exact_length_masking(quiz_env):
    """Test exact length masking configuration."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    
    assert code == 0
    assert "________" in out

def test_empty_table_error(quiz_env):
    """Test handling of invalid or empty TSV gracefully."""
    # 1. Headerless file with one non-header line that has no valid vocabulary
    empty_tsv = quiz_env / "empty.tsv"
    with open(empty_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write("Header1\tHeader2\n")
    
    code, out, err = run_quiz(quiz_env, ["empty.tsv"], [])
    assert "Error loading" in out
    assert "No valid vocabulary entries could be loaded" in out
    assert "No vocabulary files could be loaded." in out

    # 2. File with valid headers but no data rows
    empty_headers_tsv = quiz_env / "empty_headers.tsv"
    with open(empty_headers_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write("WordSource\tSentenceSource\n")
        
    code, out, err = run_quiz(quiz_env, ["empty_headers.tsv"], [])
    assert "Error loading" in out
    assert "No vocabulary entries found (empty file or headers only)." in out
    assert "No vocabulary files could be loaded." in out

def test_invalid_extension_error(quiz_env):
    """Test handling of unsupported file types like .srt with friendly errors."""
    srt_file = quiz_env / "20260606211142-anthropic-just-warned-everyone.en.srt"
    with open(srt_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:04,000\nHello World\n")
    
    code, out, err = run_quiz(quiz_env, [str(srt_file)], [])
    assert "Error: " in out
    assert "appears to be a subtitle file (.srt)" in out
    assert "Please select a vocabulary TSV file instead." in out
    assert "Error loading" not in out
    assert "No vocabulary files could be loaded." not in out



def test_headerless_tsv_fallback(quiz_env):
    """Test automatic column layout mapping when the TSV has no header row."""
    headerless_tsv = quiz_env / "headerless.tsv"
    with open(headerless_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write("dog\tdog\t\t\tсобака\tI saw a dog.\t\t\t\t\t\tDeckA\t1\t0\n")
    
    code, out, err = run_quiz(quiz_env, ["headerless.tsv"], ["dog", "/q"])
    assert code == 0
    assert "Loading: headerless.tsv" in out
    assert "Diff" in out
    
    entry = read_tsv_entry(headerless_tsv, "dog")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"

def test_malformed_tsv_rows_skipped(quiz_env):
    """Test that rows missing key fields (word or sentence) are skipped without throwing errors."""
    malformed_tsv = quiz_env / "malformed.tsv"
    with open(malformed_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "\t\t\t\tяблоко\tI ate an apple today.\t\t\t\t\t\tDeckA\t1\t0\n" # Missing word
            "banana\tbanana\t\t\tбанан\t\t\t\t\t\t\tDeckA\t1\t0\n" # Missing sentence
            "cherry\tcherry\t\t\tвишня\tA sweet cherry.\t\t\t\t\t\tDeckA\t1\t0\n" # Valid entry
        )
    
    code, out, err = run_quiz(quiz_env, ["malformed.tsv"], ["cherry", "/q"])
    assert code == 0
    assert "Loading: malformed.tsv" in out
    assert "Queue Summary: 0 due reviews, 1 new cards selected." in out
    assert "Diff" in out

def test_scheduling_new_review_orders(quiz_env):
    """Test configurations for new_review_order sorting options."""
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = new_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
        
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source == "properly":
            cols[box_idx] = "1"
            cols[due_idx] = "0" # new card
        elif word_source == "meant":
            cols[box_idx] = "2"
            cols[due_idx] = "1" # due review card
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(int(time.time()) + 100000) # not due
            
        new_lines.append("\t".join(cols))
        
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")
        
    # With new_first, 'properly' (new card) should be presented first
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    assert code == 0
    clean_out_new = strip_ansi(out).replace("\n", " ")
    assert "clear way to use it" in clean_out_new
    assert "unified intelligence" not in clean_out_new
    
    # Change config to review_first (default)
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/q"])
    assert code == 0
    clean_out_rev = strip_ansi(out).replace("\n", " ")
    assert "unified intelligence" in clean_out_rev
    assert "clear way to use it" not in clean_out_rev

def test_utf8_hint_offsets(quiz_env):
    """Test 3-parameter hints with multi-byte UTF-8 words to verify no byte-slicing issues."""
    utf8_tsv = quiz_env / "utf8_hints.tsv"
    with open(utf8_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "Möbelstücke\tMöbelstücke\t\t\tfurniture\tWir kauften Möbelstücke.\t\t\t\t\t\tDeckA\t1\t0\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["utf8_hints.tsv"], ["/h 2 1 2", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Mö...s...ke" in clean_out
    assert "length: 11" in clean_out

def test_save_error_warning(quiz_env):
    """Test that file saving errors print a warning and don't crash the program."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    tmp_dir = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv.tmp"
    tmp_dir.mkdir()
    try:
        code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["properly", "/q"])
        assert code == 0
        assert "Warning: Failed to save progress" in strip_ansi(out)
    finally:
        tmp_dir.rmdir()

def test_unknown_command_handling(quiz_env):
    """Test that entering an unknown slash command prints a warning and reprompts."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["/invalidcmd", "properly", "/q"])
    assert code == 0
    assert "Unknown command: /invalidcmd" in strip_ansi(out)
    assert "Diff" in strip_ansi(out)


# === NEW BOUNDARY TESTS FOR REAL FIXTURE RECORDS ===

def test_boundary_separable_verbs(quiz_env):
    """Test target word with spaces and ellipses (German separable verb: stehe ... auf)."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    
    # 1. Test masking in the prompt
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    # The stem "stehe" and prefix "auf" should both be masked with the default "___" placeholder
    assert "Ich ___ morgen früh ___." in clean_out

    # 2. Test answering correctly WITHOUT dots ("stehe auf")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe auf", "/q"])
    assert code == 0
    assert "Diff" in out
    
    # Verify TSV box update
    tsv_file = quiz_env / "20260303214721-text1.de.tsv"
    entry = read_tsv_entry(tsv_file, "stehe ... auf")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"

    # 3. Test answering correctly WITH dots ("stehe ... auf")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe ... auf", "/q"])
    assert code == 0
    assert "Diff" in out

    # 4. Test per-word hint formatting and context prompt masking
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["/h 1 1", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    assert "💡 Hint: s...e ... a...f (length: 13)" in clean_out
    assert "Ich s___e morgen früh a_f." in clean_out

def test_boundary_extreme_length_and_multibyte(quiz_env):
    """Test extreme length word (42 chars) and UTF-8 characters (Donaudampfschifffahrtsgesellschaftskapitän)."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Donaudampfschifffahrtsgesellschaftskapitän")
    
    # Enable exact length mask
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Show hints with /h 2 1 2
    # Expect: Do...t...än (length: 42)
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["/h 2 1 2", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # Check exact length mask of 42 underscores is printed
    assert "_" * 42 in clean_out
    # Check hint output is exact and handles 'ä' correctly
    assert "Do...t...än" in clean_out
    assert "length: 42" in clean_out

def test_boundary_punctuation_and_apostrophes(quiz_env):
    """Test matching logic with punctuation like apostrophes (Microsoft's AI)."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "Microsoft's AI")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["microsoft's ai", "/q"])
    assert code == 0
    assert "Diff" in out
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "Microsoft's AI")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"

def test_boundary_hash_sign_in_context(quiz_env):
    """Test words containing hash signs (weg. ## Teil) are loaded and parsed successfully."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "weg. ## Teil")
    
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["weg.##teil", "/q"])
    assert code == 0
    assert "Diff" in out
    
    tsv_file = quiz_env / "20260303214721-text1.de.tsv"
    entry = read_tsv_entry(tsv_file, "weg. ## Teil")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"

def test_boundary_real_lnk_resolution(quiz_env):
    """Test that real Windows .lnk files in tests/fixtures are successfully resolved without writing edits."""
    # We run on 20260303214721-text1.de.tsv - Shortcut.lnk and immediately quit
    # This verifies path resolution prints correct load message
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv - Shortcut.lnk"], ["/q"])
    assert code == 0
    assert "Loading:" in out
    assert "20260303214721-text1.de.tsv" in out

def test_boundary_broken_lnk_error(quiz_env):
    """Test that resolving a broken link reports an error gracefully."""
    # test_data.lnk points to data.tsv at the root (which doesn't exist anymore)
    code, out, err = run_quiz(quiz_env, ["test_data.lnk"], [])
    assert "Error: File not found:" in out or "not found" in out

def test_boundary_multi_word_hints(quiz_env):
    """Test target word with spaces (multi-word phrase: Abend vorbei. Wir schlagen) hints are per-word."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    
    # Enable exact_length_mask
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")

    # Hint /h 2 on "Abend vorbei. Wir schlagen" (len: 26)
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["/h 2", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    assert "💡 Hint: Ab... vo... Wi... sc... (length: 26)" in clean_out
    assert "Er kommt heute Ab___ vo____. Wi_ sc______ einen neuen Weg ein." in clean_out

def test_incorrect_answer_shows_diff(quiz_env):
    """Test that incorrect answers display a two-line character diff."""
    # Test case 1: simple substitution / typo
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv"], ["properle", "/q"])
    
    assert code == 0
    clean_out = strip_ansi(out)
    assert "properle" in clean_out
    assert "properly" in clean_out
    assert "❌ Incorrect." not in clean_out

    # Test case 2: multi-word phrase mismatch
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["Abent vorbeu wie schon", "/q"])
    
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Abent vorbeu wie scho---n" in clean_out
    assert "Abend vorbei Wir schlagen" in clean_out
    assert "❌ Incorrect." not in clean_out

    # Test case 3: separable verbs with ellipses / punctuation stripped
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe aus", "/q"])
    
    assert code == 0
    clean_out = strip_ansi(out)
    assert "stehe aus" in clean_out
    assert "stehe auf" in clean_out
    assert "❌ Incorrect." not in clean_out

def test_config_case_sensitive_diff(quiz_env):
    """Test that case_sensitive_diff=false causes the diff to treat upper/lower case as a match."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "die Jacke")
    
    # Enable exact_length_mask and case_sensitive_diff = false
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncase_sensitive_diff = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    # Target is "die Jacke". Input is "die jacce" (wrong letter, wrong case).
    # Since case_sensitive_diff is false, 'j' matches 'J', so only 'c' vs 'k' is a mismatch.
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["die jacce", "/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # If case_sensitive_diff = false, 'j' and 'J' are matched. 
    # The output strings will be the same length: "die jacce" and "die Jacke"
    assert "die jacce" in clean_out
    assert "die Jacke" in clean_out

def test_config_ignore_punctuation(quiz_env):
    """Test that ignore_punctuation=false forces the user to type punctuation."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    
    # By default, ignore_punctuation = true, so "stehe auf" is correct.
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe auf", "/q"])
    assert code == 0
    assert "Diff" in out

    # Now test with ignore_punctuation = false
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nignore_punctuation = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    # Input without punctuation is now WRONG
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe auf", "/q"])
    assert code == 0
    assert "✅ Correct!" not in out
    
    # Input with punctuation is CORRECT
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["stehe ... auf", "/q"])
    assert code == 0
    assert "Diff" in out

def test_interactive_repeat_command(quiz_env):
    """Test that the /a command queues the previous card for a practice repeat."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"], ["properly", "/a", "/q"])
    
    assert code == 0
    clean_out = strip_ansi(out)
    # Repeat card should show "Practice Repeat:" label (not "Question X/Y")
    assert "Practice Repeat 1/2:" in clean_out

def test_interactive_skip_command(quiz_env):
    """Test that the /d command skips the current card."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    
    code, out, err = run_quiz(quiz_env, ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"], ["/d", "/q"])
    
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Skipping card..." in clean_out


def test_custom_field_mapping(quiz_env):
    """Test custom header mapping and custom Leitner fields."""
    custom_tsv = quiz_env / "custom.tsv"
    custom_tsv.write_text(
        "MyCustomWord\tMyCustomTranslation\tMyCustomSentence\tCustomBox\tCustomDue\n"
        "dog\tсобака\tI saw a dog.\t1\t0\n",
        encoding="utf-8", newline="\n"
    )
    
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[fields_mapping.word]\n"
        "MyCustomWord = source_word\n"
        "MyCustomSentence = source_sentence\n"
        "CustomBox = leitner_box\n"
        "CustomDue = leitner_due\n",
        encoding="utf-8", newline="\n"
    )
    
    code, out, err = run_quiz(quiz_env, ["custom.tsv"], ["dog", "/q"])
    assert code == 0
    assert "Diff" in out
    
    # Read the TSV back and verify box and due fields were updated at CustomBox and CustomDue
    with open(custom_tsv, "r", encoding="utf-8", newline="\n") as f:
        lines = f.read().splitlines()
    headers = lines[0].split("\t")
    data = lines[1].split("\t")
    row = dict(zip(headers, data))
    
    assert row["CustomBox"] == "2"
    assert int(row["CustomDue"]) > 0
    
    
def test_headerless_tsv_fields(quiz_env):
    """Test headerless TSV fallback parsing with custom [fields] list and comment preservation."""
    headerless_tsv = quiz_env / "headerless_custom.tsv"
    headerless_tsv.write_text(
        "#deck:MyDeck\n"
        "dog\tсобака\tI saw a dog.\t1\t0\n",
        encoding="utf-8", newline="\n"
    )
    
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[fields]\n"
        "CustomWord\n"
        "CustomTranslation\n"
        "CustomSentence\n"
        "CustomBox\n"
        "CustomDue\n\n"
        "[fields_mapping.word]\n"
        "CustomWord = source_word\n"
        "CustomSentence = source_sentence\n"
        "CustomBox = leitner_box\n"
        "CustomDue = leitner_due\n",
        encoding="utf-8", newline="\n"
    )
    
    code, out, err = run_quiz(quiz_env, ["headerless_custom.tsv"], ["dog", "/q"])
    assert code == 0
    assert "Diff" in out
    
    # Verify the file was written back, has #deck:MyDeck at the top, followed by generated headers, and updated data
    with open(headerless_tsv, "r", encoding="utf-8", newline="\n") as f:
        lines = f.read().splitlines()
        
    assert lines[0] == "#deck:MyDeck"
    assert lines[1] == "CustomWord\tCustomTranslation\tCustomSentence\tCustomBox\tCustomDue"
    headers = lines[1].split("\t")
    data = lines[2].split("\t")
    row = dict(zip(headers, data))
    assert row["CustomWord"] == "dog"
    assert row["CustomBox"] == "2"


def test_headerless_tsv_fields_with_holes(quiz_env):
    """Test headerless TSV fallback parsing with custom [fields] list containing blank placeholders (holes)."""
    headerless_tsv = quiz_env / "headerless_holes.tsv"
    headerless_tsv.write_text(
        "#deck:MyDeck\n"
        "dog\tсобака\tI saw a dog.\t1\t0\n",
        encoding="utf-8", newline="\n"
    )
    
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[fields]\n"
        "CustomWord\n"
        "\n"  # Empty line placeholder (hole) representing CustomTranslation
        "CustomSentence\n"
        "CustomBox\n"
        "CustomDue\n\n"
        "[fields_mapping.word]\n"
        "CustomWord = source_word\n"
        "CustomSentence = source_sentence\n"
        "CustomBox = leitner_box\n"
        "CustomDue = leitner_due\n",
        encoding="utf-8", newline="\n"
    )
    
    code, out, err = run_quiz(quiz_env, ["headerless_holes.tsv"], ["dog", "/q"])
    assert code == 0
    assert "Diff" in out
    
    with open(headerless_tsv, "r", encoding="utf-8", newline="\n") as f:
        lines = f.read().splitlines()
        
    assert lines[0] == "#deck:MyDeck"
    assert lines[1] == "CustomWord\t\tCustomSentence\tCustomBox\tCustomDue"
    headers = lines[1].split("\t")
    assert headers[1] == ""  # Hole preserved


def test_anki_grading_good_override(quiz_env):
    """Test that when anki_grading is true, an incorrect typed answer can be manually rated as Good (correct)."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["wrong_answer", "3", ""]
    )
    assert code == 0
    assert "Grade (press '?' for help, override with '1' as incorrect, '3' as correct)..." in strip_ansi(out)
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"
    assert int(entry["LeitnerDue"]) > 0


def test_anki_grading_again_override(quiz_env):
    """Test that when anki_grading is true, a correct typed answer can be manually rated as Again (incorrect)."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["properly", "1", ""]
    )
    assert code == 0
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "1"


def test_anki_grading_default_enter_correct(quiz_env):
    """Test that when anki_grading is true, pressing Enter/Space defaults to correct if typed answer was correct."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["properly", "", ""]
    )
    assert code == 0
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "2"


def test_anki_grading_default_enter_incorrect(quiz_env):
    """Test that when anki_grading is true, pressing Enter/Space defaults to incorrect if typed answer was incorrect."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["wrong_answer", "", ""]
    )
    assert code == 0
    
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "1"


def test_front_help_command(quiz_env):
    """Test that typing /help or /? on the front side displays the help message."""
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["/?", "/q"]
    )
    assert code == 0
    assert "Interactive Controls" in strip_ansi(out)
    assert "/hint" in strip_ansi(out)


def test_back_help_command_normal(quiz_env):
    """Test that pressing ? on the back side in normal grading mode shows controls help."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["properly", "?", ""]
    )
    assert code == 0
    assert "Back Side Options" in strip_ansi(out)
    assert "Continue to the next card" in strip_ansi(out)


def test_back_help_command_anki(quiz_env):
    """Test that pressing ? on the back side in anki manual grading mode shows manual grading help."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    code, out, err = run_quiz(
        quiz_env, 
        ["20260604184114-microsoft-just-shocked-the.en.tsv"], 
        ["properly", "?", "3", ""]
    )
    assert code == 0
    assert "Back Side Options" in strip_ansi(out)
    assert "Override as incorrect." in strip_ansi(out)


def test_source_index_duplicate_words(quiz_env):
    """Test that only the duplicate word at the logical SentenceSourceIndex is masked."""
    # Write a test TSV where 'die' appears twice, and we target the second 'die' at logical word index 6.
    # Sentence: "Sie hören die Nachrichtensendung nur einmal die Woche."
    # Logical index mapping:
    # 1: Sie, 2: hören, 3: die, 4: Nachrichtensendung, 5: nur, 6: einmal, 7: die, 8: Woche
    # Wait, in "Sie hören die Nachrichtensendung nur einmal die Woche.", the second 'die' is at logical word index 7.
    dup_tsv = quiz_env / "duplicates.tsv"
    dup_tsv.write_text(
        "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
        "die\tdie\t\t\tthe\tSie hören die Nachrichtensendung nur einmal die Woche.\t\t\t\t\t7\tDeckA\t1\t0\n",
        encoding="utf-8", newline="\n"
    )

    # Let's enable exact_length_mask to make verification unambiguous:
    # Expect: "Sie hören die Nachrichtensendung nur einmal ___ Woche."
    # If the first 'die' was masked instead, it would be: "Sie hören ___ Nachrichtensendung nur einmal die Woche."
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )

    code, out, err = run_quiz(quiz_env, ["duplicates.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)

    # Verify only the second occurrence is masked with '___'
    assert "Sie hören die Nachrichtensendung nur einmal ___ Woche." in clean_out
    assert "Sie hören ___" not in clean_out


def test_source_index_shifted_duplicates(quiz_env):
    """Test that if the TSV sentence is shifted (e.g. has an extra word at start), we still target the correct occurrence using the closest logical index."""
    # original index of second 'die' is 7.
    # shifted sentence: "Bitte hören Sie die Nachrichtensendung nur einmal die Woche." (added "Bitte" at start, pushing second 'die' to index 8)
    dup_tsv = quiz_env / "duplicates_shifted.tsv"
    dup_tsv.write_text(
        "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
        "die\tdie\t\t\tthe\tBitte hören Sie die Nachrichtensendung nur einmal die Woche.\t\t\t\t\t7\tDeckA\t1\t0\n",
        encoding="utf-8", newline="\n"
    )

    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )

    code, out, err = run_quiz(quiz_env, ["duplicates_shifted.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)

    # Verify only the second occurrence (now at index 8) is masked
    assert "Bitte hören Sie die Nachrichtensendung nur einmal ___ Woche." in clean_out
    assert "Bitte hören Sie ___" not in clean_out


def test_source_index_coordinate_map_separable(quiz_env):
    """Test that coordinate-grounded multi-pivot mapping correctly masks the specific occurrence of a separable verb."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "fährt ... ab")
    
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # Correct masking should target "Morgen ___ ... donauabwärts ___."
    # Unrelated "Er fährt morgen weg." should remain untouched.
    # Unrelated "donauabwärts" should NOT have "ab" replaced (i.e. not "donau__wärts").
    assert "Er fährt morgen weg." in clean_out
    assert "donauabwärts" in clean_out
    assert "Morgen ___ der neue" in clean_out
    assert "donauabwärts ___." in clean_out







def test_config_separable_verb_inline_diff(quiz_env):
    """Test that separable verbs respect case_sensitive_diff and ignore_punctuation in inline diffs."""
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")
    
    # Disable case sensitive diff
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncase_sensitive_diff = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    # Target is "stehe ... auf". Input is "STEHE AUS".
    # Since case_sensitive_diff is false, 'STEHE' matches 'stehe' perfectly.
    # We test that the context sentence outputs 'stehe' in green instead of red.
    code, out, err = run_quiz(quiz_env, ["20260303214721-text1.de.tsv"], ["STEHE AUS", "/q"])
    assert code == 0
    
    # bold(green("s")) -> \x1b[1m\x1b[32ms\x1b[0m\x1b[0m
    # We can just check that \x1b[31ms\x1b[0m (red 's') is NOT in the output,
    # but \x1b[32ms\x1b[0m (green 's') IS in the output, specifically for the context sentence.
    # To be safe, we verify that the red 's' is not applied to 'stehe'.
    # If the bug is present (case_sensitive_diff=nil/true), 's' and 'S' mismatch, so 's' becomes red.
    
    assert "\x1b[31ms\x1b[0m" not in out
    assert "\x1b[32ms\x1b[0m" in out


def test_fallback_individual_words_phrase_not_found(quiz_env):
    """Test that when the full phrase is not found, the algorithm falls back to individual words."""
    tsv = quiz_env / "fallback_phrase.tsv"
    tsv.write_text(
        "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
        "auf dem Tisch\tauf dem Tisch\t\t\ton the table\tAuf einem Tisch liegt ein Buch.\t\t\t\t\t\tDeckA\t1\t0\n",
        encoding="utf-8", newline="\n"
    )
    
    # Target phrase is "auf dem Tisch", but text has "Auf einem Tisch".
    # Should highlight "Auf" and "Tisch".
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )

    code, out, err = run_quiz(quiz_env, ["fallback_phrase.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # "Auf" and "Tisch" should be masked with "___"
    # Expected: "___ einem ___ liegt ein Buch."
    assert "___ einem ___ liegt ein Buch." in clean_out


def test_word_boundary_fallback(quiz_env):
    """Test that fallback word highlighting respects word boundaries."""
    tsv = quiz_env / "boundary_fallback.tsv"
    tsv.write_text(
        "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
        "Tisch\tTisch\t\t\ttable\tDie Tischdecke auf dem Tisch.\t\t\t\t\t\tDeckA\t1\t0\n",
        encoding="utf-8", newline="\n"
    )
    
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n",
        encoding="utf-8", newline="\n"
    )

    code, out, err = run_quiz(quiz_env, ["boundary_fallback.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # Only the standalone "Tisch" should be masked. "Tischdecke" should remain intact.
    # Expected: "Die Tischdecke auf dem ___."
    assert "Die Tischdecke auf dem ___." in clean_out


def test_command_mode_save_command(quiz_env):
    """Test that command_mode_save_command preserves command text when switching back to answer mode."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncommand_mode = true\ncommand_mode_save_input = true\ncommand_mode_save_command = true\nstart_in_command_mode = true\nsingle_card_mode = true\ncommand_mode_single_key = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Start in command mode:
    # 1. Type "h 2" and press Esc (represented as \x1bh 2) to switch to answer, saving "h 2".
    # 2. In answer mode, press Esc (\x1b) to switch back to command.
    # 3. Press Enter ("") to submit the restored "h 2" command.
    # 4. Press Enter ("") again in command mode to switch back to answer mode.
    # 5. Answer "properly" to finish.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["\x1bh 2", "\x1b", "", "", "properly", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "💡 Hint: pr" in clean_out


def test_command_mode_esc_skip_no_toggle(quiz_env):
    """Test that Esc in Command mode skips the card when command_mode_esc_toggles=false."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncommand_mode = true\ncommand_mode_esc_toggles = false\nstart_in_command_mode = true\ncommand_mode_single_key = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Absätze")

    # Start in Command mode. Press Esc (returned as /d) — should skip the card.
    # Then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"],
        ["/d", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Skipping card..." in clean_out


def test_command_mode_esc_save_no_toggle_skips(quiz_env):
    """Test that Esc in Command mode skips the card even when save_command=true and esc_toggles=false.

    Regression test for: when save_command=true, Esc was converted to /d internally but the
    esc_toggles=false guard caused it to be silently swallowed — card was never skipped.
    """
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += (
        "\ncommand_mode = true"
        "\ncommand_mode_esc_toggles = false"
        "\ncommand_mode_save_command = true"
        "\nstart_in_command_mode = true"
        "\ncommand_mode_single_key = false\n"
    )
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Absätze")

    # In Command mode (start_in_command_mode=true):
    # Send \x1b prefix to simulate Esc-with-save, which should skip the card.
    # If the bug is present, the quiz loops back to Command and times out.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"],
        ["\x1b", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Skipping card..." in clean_out


def test_start_in_command_mode(quiz_env):
    """Test that start_in_command_mode=true begins the card in Command mode, not Answer mode."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncommand_mode = true\nstart_in_command_mode = true\ncommand_mode_single_key = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # The Command prompt should appear first (not Answer).
    # Type Enter ("") to switch to Answer mode, then answer correctly.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["", "properly", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    # Command prompt must appear before Answer prompt
    cmd_pos = clean_out.find("Command ")
    ans_pos = clean_out.find("Answer ")
    assert cmd_pos != -1, "Expected 'Command ' prompt"
    assert ans_pos != -1, "Expected 'Answer ' prompt"
    assert cmd_pos < ans_pos, "Command prompt should appear before Answer prompt"
    assert "Diff" in clean_out


def test_command_mode_single_key(quiz_env):
    """Test that command_mode_single_key=true dispatches commands on single keypresses and supports Space to answer."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\ncommand_mode = true\nstart_in_command_mode = true\ncommand_mode_single_key = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "stehe ... auf")

    # In single_key mode, start in Command mode.
    # 1. Send " " (Space) to switch to Answer mode.
    # 2. In Answer mode, type "properly" to answer correctly.
    # 3. For the next card (starts in Command mode), send "d" to skip it.
    # 4. Quit using "/q".
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"],
        [" ", "properly", "d", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Skipping card..." in clean_out
    assert "Diff" in clean_out


def test_arrow_hints_config_parameters(quiz_env):
    """Test that arrow hints configurations are successfully parsed and quiz runs with them."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += (
        "\ncommand_mode = false"
        "\ncommand_mode_arrow_hints = true"
        "\nanswer_mode_arrow_hints = swap\n"
    )
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Verify that the quiz starts up and processes the exit command correctly under this config.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Exiting quiz early" in clean_out


def test_arrow_hints_legacy_fallback(quiz_env):
    """Test that the legacy arrow_hints key propagates to both modes when mode-specific keys are absent.

    Regression guard: if only arrow_hints is set (old config format), both command_mode_arrow_hints
    and answer_mode_arrow_hints must inherit its value — the quiz must run normally with no crash.
    """
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n"
        "command_mode = false\n"
        "arrow_hints = true\n",  # no command_mode_arrow_hints / answer_mode_arrow_hints
        encoding="utf-8", newline="\n"
    )

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    # Quiz must complete normally: answer processed, diff shown
    assert "Diff" in clean_out


def test_arrow_hints_independent_control(quiz_env):
    """Test that command_mode_arrow_hints and answer_mode_arrow_hints are independent.

    Scenario: command_mode_arrow_hints = false (disabled), answer_mode_arrow_hints = true (enabled).
    The quiz must accept a correct answer in Answer mode and complete normally — verifying that
    answer mode arrow hints enabled alongside command mode arrow hints disabled does not cause
    incorrect behavior or crashes.
    """
    config_path = quiz_env / "config.ini"
    config_path.write_text(
        "[Leitner]\n"
        "intervals = 5m, 1h, 1d\n"
        "new_cards_per_day = 10\n"
        "single_card_mode = false\n"
        "exact_length_mask = false\n"
        "new_review_order = review_first\n"
        "review_sort_order = due_date\n"
        "command_mode = true\n"
        "start_in_command_mode = true\n"
        "command_mode_single_key = false\n"
        "command_mode_arrow_hints = false\n"
        "answer_mode_arrow_hints = true\n",
        encoding="utf-8", newline="\n"
    )

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Start in command mode: press Enter to switch to answer mode, then answer correctly.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["", "properly", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Diff" in clean_out


def test_repeat_counts_in_stats_default_false(quiz_env):
    """Test that with repeat_counts_in_stats=false (default), repeat cards do not affect score or progress."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly, then press 's' to repeat, answer correctly on repeat, then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "properly", "", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    # Repeat card should show "Practice Repeat:" label (not "Question X/Y")
    assert "Practice Repeat 1/1:" in clean_out
    # The info message about score unaffected should appear
    assert "Practice Repeat" in clean_out
    assert "progress & score unaffected" in clean_out
    # Final score should be 1 out of 1 (repeat not counted)
    assert "You scored 1 out of 1" in clean_out


def test_repeat_counts_in_stats_enabled(quiz_env):
    """Test that with repeat_counts_in_stats=true, repeat cards ARE counted in score and progress."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly, then press 's' to repeat, answer correctly on repeat, then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "properly", "", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)

    # Repeat card should show "Question X/Y (Repeat):" label (not "Practice Repeat:")
    assert "(Repeat):" in clean_out
    # The "progress & score unaffected" message should NOT appear
    assert "progress & score unaffected" not in clean_out
    # Final score should be 2 out of 2 (repeat counted)
    assert "You scored 2 out of 2" in clean_out


def test_repeat_counts_in_stats_enabled_incorrect(quiz_env):
    """Test that with repeat_counts_in_stats=true, an incorrect repeat answer lowers the score denominator correctly."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly, then press 's' to repeat, answer WRONG on repeat, then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "wrong", "", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)

    # First answer correct (1 point), repeat answer wrong (0 points) = 1 out of 2
    assert "You scored 1 out of 2" in clean_out


def test_repeat_counts_in_stats_anki_grading(quiz_env):
    """Test that with repeat_counts_in_stats=true and anki_grading=true, pressing 's' saves progress for repeats."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly, press 's' (save + repeat), answer correctly on repeat, press '3' (correct), then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "properly", "3", ""]
    )
    assert code == 0
    clean_out = strip_ansi(out)

    # Repeat card should show "(Repeat):" label
    assert "(Repeat):" in clean_out
    # The "progress & score unaffected" message should NOT appear
    assert "progress & score unaffected" not in clean_out
    # Final score: 2 out of 2
    assert "You scored 2 out of 2" in clean_out


def test_repeat_counts_in_stats_anki_grading_default_false(quiz_env):
    """Test that with repeat_counts_in_stats=false (default) and anki_grading=true, repeats do not affect stats."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nanki_grading = true\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly, press 's' (save + repeat), answer correctly on repeat, press '3' (correct), then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "properly", "3", ""]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    # Repeat card should show "Practice Repeat:" label
    assert "Practice Repeat 1/1:" in clean_out
    # The info message about score unaffected should appear
    assert "progress & score unaffected" in clean_out
    # Final score should be 1 out of 1 (repeat not counted)
    assert "You scored 1 out of 1" in clean_out


def test_repeat_counts_in_stats_progress_saved(quiz_env):
    """Test that with repeat_counts_in_stats=true, the TSV is updated even for repeat cards."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    # Answer correctly (box 1 -> 2), then press 's' to repeat, answer correctly on repeat (box 2 -> 3), then quit.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "s", "properly", "", "/q"]
    )
    assert code == 0

    # Verify the TSV was updated: first correct bumps to box 2, repeat correct bumps to box 3.
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "3", f"Expected Box 3 (two correct answers), got {entry['LeitnerBox']}"


def test_tsv_whitespace_trimming(quiz_env):
    """Test that leading/trailing whitespaces in TSV cells are trimmed during loading."""
    issue_tsv_content = (
        "#deck column:85\n"
        "Quotation                                 \t WordSource                                \t SentenceSource                                                                                                                    \t LeitnerBox\t LeitnerDue\n"
        "  die Jacke                               \t   die Jacke                              \t   Ich ziehe die Jacke aus.                                                                                                        \t 1         \t 0         \n"
    )
    test_tsv = quiz_env / "issue.tsv"
    test_tsv.write_text(issue_tsv_content, encoding="utf-8", newline="\n")

    code, out, err = run_quiz(quiz_env, ["issue.tsv"], ["die Jacke", "/q"])
    print("STDOUT:", out)
    print("STDERR:", err)
    assert code == 0, f"run_quiz failed with code {code}, err: {err}, out: {out}"
    
    # Verify the TSV is cleaned up when written back
    entry = read_tsv_entry(test_tsv, "die Jacke")
    assert entry is not None, f"Could not find entry for 'die Jacke' in TSV. Content: {test_tsv.read_text(encoding='utf-8')}"
    assert entry["Quotation"] == "die Jacke"
    assert entry["WordSource"] == "die Jacke"
    assert entry["SentenceSource"] == "Ich ziehe die Jacke aus."


def test_sync_reverse_command(quiz_env):
    """Test that the /sync <zid> <timestamp> command jumps to the closest matching card."""
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/sync 20260604184114 387.841", "meant", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "unified intelligence" in clean_out


def test_sync_forward_hotkey_command_mode(quiz_env):
    """Test that pressing 'y' in command mode parses successfully."""
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["y", "/q"]
    )
    assert code == 0


def test_input_helper_media_resolution(tmp_path):
    """Test the media file matching logic in input_helper.py."""
    import sys
    import shutil
    import importlib.util
    
    # Copy input_helper.py to tmp_path
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)
    
    # Create test files
    tsv_file = tmp_path / "20260303214721-text1.de.tsv"
    tsv_file.touch()
    
    video_file = tmp_path / "20260303214721-text1.de.mp4"
    video_file.touch()
    
    resolved = input_helper_test.find_media_file(str(tsv_file))
    assert resolved is not None
    assert Path(resolved).name == "20260303214721-text1.de.mp4"
    
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    sub_video = sub_dir / "20260303214721-other.de.mkv"
    sub_video.touch()
    
    video_file.unlink()
    
    resolved2 = input_helper_test.find_media_file(str(tsv_file))
    assert resolved2 is None

    # Test es vs es-extra suffix collision resolution
    es_tsv = tmp_path / "20260622113607.es.tsv"
    es_tsv.touch()
    
    es_extra_video = tmp_path / "20260622113607.es-extra.mp4"
    es_extra_video.touch()
    es_video = tmp_path / "20260622113607.es.mp4"
    es_video.touch()
    
    resolved_es = input_helper_test.find_media_file(str(es_tsv))
    assert resolved_es is not None
    assert Path(resolved_es).name == "20260622113607.es.mp4"

    # Test alphabetical deterministic ordering of candidates
    multi_tsv = tmp_path / "20260622113608.en.tsv"
    multi_tsv.touch()
    
    video_b = tmp_path / "20260622113608-videoB.en.mp4"
    video_b.touch()
    video_a = tmp_path / "20260622113608-videoA.en.mp4"
    video_a.touch()
    
    resolved_multi = input_helper_test.find_media_file(str(multi_tsv))
    assert resolved_multi is not None
    assert Path(resolved_multi).name == "20260622113608-videoA.en.mp4"


def test_input_helper_sync_mpv_flow(tmp_path, monkeypatch):
    """Test the full sync_mpv execution path inside input_helper.py."""
    import importlib.util
    import shutil
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)

    tsv_file = tmp_path / "20260303214721-text1.de.tsv"
    tsv_file.touch()
    video_file = tmp_path / "20260303214721-text1.de.mp4"
    video_file.touch()

    sent_commands = []
    received_queries = []

    def mock_send_ipc_payload(pipe, cmd):
        sent_commands.append(cmd)

    def mock_send_receive_ipc(pipe, cmd):
        received_queries.append(cmd)
        return {"error": "success", "data": "other.mp4"}

    monkeypatch.setattr(input_helper_test, "send_ipc_payload", mock_send_ipc_payload)
    monkeypatch.setattr(input_helper_test, "send_receive_ipc", mock_send_receive_ipc)

    pipe_path = "mock_pipe"
    timestamp = 12.34

    # 1. Test with play_on_sync = False
    success = input_helper_test.sync_mpv(pipe_path, str(tsv_file), timestamp, play_on_sync=False)
    assert success is True

    media_file_mpv = str(video_file).replace('\\', '/')
    assert len(sent_commands) == 2
    assert sent_commands[0] == {"command": ["loadfile", media_file_mpv, "replace"]}
    assert sent_commands[1] == {"command": ["seek", timestamp, "absolute"]}

    # 2. Test with play_on_sync = True
    sent_commands.clear()
    success = input_helper_test.sync_mpv(pipe_path, str(tsv_file), timestamp, play_on_sync=True)
    assert success is True
    assert len(sent_commands) == 3
    assert sent_commands[0] == {"command": ["loadfile", media_file_mpv, "replace"]}
    assert sent_commands[1] == {"command": ["seek", timestamp, "absolute"]}
    assert sent_commands[2] == {"command": ["set_property", "pause", False]}

    # Test same file path check with play_on_sync = False
    sent_commands.clear()
    received_queries.clear()
    
    def mock_send_receive_ipc_same(pipe, cmd):
        received_queries.append(cmd)
        return {"error": "success", "data": media_file_mpv}
    monkeypatch.setattr(input_helper_test, "send_receive_ipc", mock_send_receive_ipc_same)

    success = input_helper_test.sync_mpv(pipe_path, str(tsv_file), timestamp, play_on_sync=False)
    assert success is True

    assert len(sent_commands) == 1
    assert sent_commands[0] == {"command": ["seek", timestamp, "absolute"]}

    # Test same file path check with play_on_sync = True
    sent_commands.clear()
    success = input_helper_test.sync_mpv(pipe_path, str(tsv_file), timestamp, play_on_sync=True)
    assert success is True
    assert len(sent_commands) == 2
    assert sent_commands[0] == {"command": ["seek", timestamp, "absolute"]}
    assert sent_commands[1] == {"command": ["set_property", "pause", False]}

def test_input_helper_sync_mpv_no_media(tmp_path):
    """Test that if find_media_file returns None, sync_mpv returns False."""
    import importlib.util
    import shutil
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)

    # Creating a TSV file but NO video files exist
    tsv_file = tmp_path / "20260303214721-text1.de.tsv"
    tsv_file.touch()

    success = input_helper_test.sync_mpv("mock_pipe", str(tsv_file), 12.34)
    assert success is False


def test_input_helper_sync_mpv_spawn_fallback(tmp_path, monkeypatch):
    """Test that if connection fails (send_receive_ipc returns None), spawn_mpv is called."""
    import importlib.util
    import shutil
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)

    tsv_file = tmp_path / "20260303214721-text1.de.tsv"
    tsv_file.touch()
    video_file = tmp_path / "20260303214721-text1.de.mp4"
    video_file.touch()

    spawned_mpv_args = []

    def mock_send_receive_ipc_none(pipe, cmd):
        return None

    def mock_spawn_mpv(pipe, path, start_time, mpv_cmd="mpv"):
        spawned_mpv_args.append((pipe, path, start_time, mpv_cmd))
        return True

    monkeypatch.setattr(input_helper_test, "send_receive_ipc", mock_send_receive_ipc_none)
    monkeypatch.setattr(input_helper_test, "spawn_mpv", mock_spawn_mpv)

    pipe_path = "mock_pipe"
    timestamp = 12.34
    media_file_mpv = str(video_file).replace('\\', '/')

    success = input_helper_test.sync_mpv(pipe_path, str(tsv_file), timestamp)
    assert success is True

    assert len(spawned_mpv_args) == 1
    assert spawned_mpv_args[0] == (pipe_path, media_file_mpv, timestamp, "mpv")


def test_input_helper_reverse_ipc_server(tmp_path):
    """Test the reverse IPC listener thread in input_helper.py using multiprocessing.connection."""
    import importlib.util
    import shutil
    from multiprocessing.connection import Client
    import time
    import sys
    
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)

    if sys.platform == 'win32':
        address = r'\\.\pipe\kardenwort-quiz-test'
        family = 'AF_PIPE'
    else:
        address = str(tmp_path / 'kardenwort-quiz-test')
        family = 'AF_UNIX'

    woken_up = []
    def mock_wake_up():
        woken_up.append(True)
    input_helper_test.wake_up_main_thread = mock_wake_up

    import threading
    t = threading.Thread(target=input_helper_test.run_ipc_server_thread, args=(address, family))
    t.daemon = True
    t.start()
    time.sleep(0.1)

    test_msg = {"zid": "20260624170848", "time": "45.67"}
    conn = Client(address, family=family)
    conn.send(test_msg)
    conn.close()

    for _ in range(20):
        if not input_helper_test.sync_event_queue.empty():
            break
        time.sleep(0.05)

    assert not input_helper_test.sync_event_queue.empty()
    received = input_helper_test.sync_event_queue.get()
    assert received == test_msg
    assert len(woken_up) == 1


def test_sync_forward_command_execution(quiz_env):
    """Test that pressing 'y' (forward sync) executes the correct Python background command when enabled."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nmpv_integration = true\nmpv_pipe_path = \\\\.\\pipe\\mpv-socket-test\ncommand_mode = true\nstart_in_command_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    log_file = quiz_env / "command_log.txt"
    
    import os
    test_env = os.environ.copy()
    test_env["TEST_COMMAND_LOG"] = str(log_file)

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["y", "/q"],
        env=test_env
    )
    assert code == 0
    
    assert log_file.exists()
    commands = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(commands) > 0
    
    found_sync = False
    for cmd in commands:
        if "--sync-mpv" in cmd and "mpv-socket-test" in cmd and "330.961" in cmd and "--play" in cmd:
            found_sync = True
            break
    assert found_sync, f"Expected sync command with --play not found in logged commands: {commands}"

    # Also test with mpv_play_on_sync = false
    log_file.unlink()
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("mpv_play_on_sync = true", "mpv_play_on_sync = false")
    if "mpv_play_on_sync = false" not in content:
        content += "\nmpv_play_on_sync = false\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["y", "/q"],
        env=test_env
    )
    assert code == 0
    
    assert log_file.exists()
    commands = log_file.read_text(encoding="utf-8").strip().splitlines()
    found_sync_no_play = False
    for cmd in commands:
        if "--sync-mpv" in cmd and "mpv-socket-test" in cmd and "330.961" in cmd and "--play" not in cmd:
            found_sync_no_play = True
            break
    assert found_sync_no_play, f"Expected sync command without --play not found in logged commands: {commands}"


def test_sync_disabled_gating(quiz_env):
    """Test that manual commands and hotkeys display a disabled warning when mpv_integration = false."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nmpv_integration = false\ncommand_mode = true\nstart_in_command_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")

    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/sync_forward", "/sync 20260604184114 12.3", "y", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert clean_out.count("MPV Integration is disabled in config.ini") >= 3


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows named pipe test")
def test_input_helper_win_pipe_busy_retry(tmp_path, monkeypatch):
    """Test that send_win_pipe handles ERROR_PIPE_BUSY and retries using WaitNamedPipeW."""
    import importlib.util
    import shutil
    import ctypes
    from ctypes import wintypes
    
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)
    
    calls = []
    create_file_calls = 0
    
    def mock_create_file(lpFileName, dwDesiredAccess, dwShareMode, lpSecurityAttributes, dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile):
        nonlocal create_file_calls
        create_file_calls += 1
        calls.append(("CreateFileW", create_file_calls))
        if create_file_calls < 3:
            return input_helper_test.INVALID_HANDLE
        return 42  # Dummy valid handle
        
    def mock_get_last_error():
        calls.append("GetLastError")
        return 231  # ERROR_PIPE_BUSY
        
    wait_calls = 0
    def mock_wait_named_pipe(lpNamedPipeName, nTimeOut):
        nonlocal wait_calls
        wait_calls += 1
        calls.append(("WaitNamedPipeW", nTimeOut))
        return True
        
    def mock_write_file(hFile, lpBuffer, nNumberOfBytesToWrite, lpNumberOfBytesWritten, lpOverlapped):
        calls.append("WriteFile")
        if lpNumberOfBytesWritten:
            lpNumberOfBytesWritten[0] = nNumberOfBytesToWrite
        return True
        
    def mock_close_handle(hObject):
        calls.append("CloseHandle")
        return True
        
    write_proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    )
    mock_write_c = write_proto(mock_write_file)
        
    monkeypatch.setattr(input_helper_test.kernel32, "CreateFileW", mock_create_file)
    monkeypatch.setattr(ctypes, "GetLastError", mock_get_last_error)
    monkeypatch.setattr(input_helper_test.kernel32, "WaitNamedPipeW", mock_wait_named_pipe)
    monkeypatch.setattr(input_helper_test.kernel32, "WriteFile", mock_write_c)
    monkeypatch.setattr(input_helper_test.kernel32, "CloseHandle", mock_close_handle)
    
    input_helper_test.send_win_pipe("dummy_pipe", b"test_data", timeout_ms=5000)
    
    assert create_file_calls == 3
    assert wait_calls == 2
    assert "WriteFile" in calls
    assert "CloseHandle" in calls
    # WaitNamedPipeW timeout should be 50ms (the refined granularity)
    assert any(c[0] == "WaitNamedPipeW" and c[1] == 50 for c in calls if isinstance(c, tuple))


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows named pipe test")
def test_input_helper_send_receive_ipc_busy_retry(tmp_path, monkeypatch):
    """Test that send_receive_ipc handles ERROR_PIPE_BUSY and retries using WaitNamedPipeW."""
    import importlib.util
    import shutil
    import ctypes
    from ctypes import wintypes
    
    shutil.copy2(Path(__file__).parent.parent.parent / "input_helper.py", tmp_path / "input_helper.py")
    spec = importlib.util.spec_from_file_location("input_helper_test", str(tmp_path / "input_helper.py"))
    input_helper_test = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(input_helper_test)
    
    calls = []
    create_file_calls = 0
    
    def mock_create_file(lpFileName, dwDesiredAccess, dwShareMode, lpSecurityAttributes, dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile):
        nonlocal create_file_calls
        create_file_calls += 1
        calls.append(("CreateFileW", create_file_calls))
        if create_file_calls < 3:
            return input_helper_test.INVALID_HANDLE
        return 42  # Dummy valid handle
        
    def mock_get_last_error():
        calls.append("GetLastError")
        return 231  # ERROR_PIPE_BUSY
        
    wait_calls = 0
    def mock_wait_named_pipe(lpNamedPipeName, nTimeOut):
        nonlocal wait_calls
        wait_calls += 1
        calls.append(("WaitNamedPipeW", nTimeOut))
        return True
        
    def mock_write_file(hFile, lpBuffer, nNumberOfBytesToWrite, lpNumberOfBytesWritten, lpOverlapped):
        calls.append("WriteFile")
        if lpNumberOfBytesWritten:
            lpNumberOfBytesWritten[0] = nNumberOfBytesToWrite
        return True
        
    peek_calls = 0
    def mock_peek_named_pipe(hNamedPipe, lpBuffer, nBufferSize, lpBytesRead, lpTotalBytesAvail, lpBytesLeftThisMessage):
        nonlocal peek_calls
        peek_calls += 1
        calls.append(("PeekNamedPipe", peek_calls))
        if lpTotalBytesAvail:
            if peek_calls == 1:
                lpTotalBytesAvail[0] = 0
            else:
                lpTotalBytesAvail[0] = 14
        return True
        
    def mock_read_file(hFile, lpBuffer, nNumberOfBytesToRead, lpNumberOfBytesRead, lpOverlapped):
        calls.append("ReadFile")
        if lpNumberOfBytesRead:
            lpNumberOfBytesRead[0] = 14
        ctypes.memmove(lpBuffer, b'{"res": "ok"}\n', 14)
        return True
        
    def mock_close_handle(hObject):
        calls.append("CloseHandle")
        return True
        
    write_proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    )
    mock_write_c = write_proto(mock_write_file)

    peek_proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)
    )
    mock_peek_c = peek_proto(mock_peek_named_pipe)

    read_proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    )
    mock_read_c = read_proto(mock_read_file)
        
    monkeypatch.setattr(input_helper_test.kernel32, "CreateFileW", mock_create_file)
    monkeypatch.setattr(ctypes, "GetLastError", mock_get_last_error)
    monkeypatch.setattr(input_helper_test.kernel32, "WaitNamedPipeW", mock_wait_named_pipe)
    monkeypatch.setattr(input_helper_test.kernel32, "WriteFile", mock_write_c)
    monkeypatch.setattr(input_helper_test.kernel32, "PeekNamedPipe", mock_peek_c)
    monkeypatch.setattr(input_helper_test.kernel32, "ReadFile", mock_read_c)
    monkeypatch.setattr(input_helper_test.kernel32, "CloseHandle", mock_close_handle)
    
    res = input_helper_test.send_receive_ipc("dummy_pipe", {"cmd": "test"}, timeout=1.0)
    assert res == {"res": "ok"}
    assert create_file_calls == 3
    assert wait_calls == 2
    assert "WriteFile" in calls
    assert "CloseHandle" in calls
    # WaitNamedPipeW timeout should be 50ms (the refined granularity)
    assert any(c[0] == "WaitNamedPipeW" and c[1] == 50 for c in calls if isinstance(c, tuple))


def test_word_wrap_extreme_length(quiz_env):
    """Test wrapping of an extremely long word (>120 chars) to ensure it is hard-wrapped and doesn't crash."""
    wrap_tsv = quiz_env / "wrap_test.tsv"
    long_word = "A" * 130
    with open(wrap_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            f"test\ttest\t\t\ttest\tHere is a long word: {long_word}.\t\t\t\t\t\tDeckA\t1\t0\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["wrap_test.tsv"], ["/q"])
    assert code == 0
    clean_out = strip_ansi(out)
    
    # The default console width in test environment is 119.
    # So the word 'A' * 130 should be hard-wrapped:
    # 'A' * 119 on the first line, and 'A' * 11 on the second line.
    first_part = "A" * 119
    second_part = "A" * 11
    # Verify the split happens at the right boundary on the same line sequence
    assert f"{first_part}\n{second_part}" in clean_out


def test_practice_repeat_progress_display(quiz_env):
    """4.1 Test that Practice Repeat displays X/Y progress when repeat_counts_in_stats is false."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    
    # 2 unique cards in deck. Answer 'properly' (card 1) correctly. Now on card 2.
    # Type '/a' to repeat card 1. This should display 'Practice Repeat 1/2:'
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"],
        ["properly", "/a", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Practice Repeat 1/2:" in clean_out


def test_nested_practice_repeat(quiz_env):
    """4.2 Test that repeating a repeat card (nested repeat) propagates original_question_num correctly."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    focus_single_card(quiz_env, "20260303214721-text1.de.tsv", "Abend vorbei. Wir schlagen")
    
    # Enable single card mode
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nsingle_card_mode = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    # Start quiz:
    # Front of Card 1: "properly"
    # Back of Card 1: "" (Enter, to continue to Card 2)
    # Front of Card 2: "Abend vorbei. Wir schlagen"
    # Back of Card 2: "a" (repeat previous, i.e. Card 1. Queues R1)
    # Front of R1: "properly"
    # Back of R1: "s" (repeat current. Queues R2)
    # Front of R2: "properly"
    # Back of R2: "q" (quit)
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv", "20260303214721-text1.de.tsv"],
        ["properly", "", "Abend vorbei. Wir schlagen", "a", "properly", "s", "properly", "q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert clean_out.count("Practice Repeat 1/2:") >= 2


def test_first_card_repeat_boundary(quiz_env):
    """4.3 Test that attempting to repeat on the first card does not crash and prints a warning."""
    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    
    # Type '/a' on the very first card. It should show a warning and not crash.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/a", "properly", "/q"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "There is no previous card to repeat." in clean_out


def test_in_memory_progress_syncing(quiz_env):
    """4.4 Test in-memory Leitner box and due date syncing for repeat cards when repeat_counts_in_stats is true."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("intervals = 5m, 1h, 1d", "intervals = 5m, 1h, 1d, 2d")
    content += "\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    focus_single_card(quiz_env, "20260604184114-microsoft-just-shocked-the.en.tsv", "properly")
    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    
    # Make both 'properly' and 'meant' due so they are both in the deck
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source in ["properly", "meant"]:
            cols[box_idx] = "1"
            cols[due_idx] = "0"
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(int(time.time()) + 100000)
        new_lines.append("\t".join(cols))
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")

    # Sequence of answers:
    # 1. Front Card 1 ("properly"): answer "properly" (promoted 1 -> 2)
    # 2. Front Card 2 ("meant"): "/a" (repeats previous card Card 1, spawning R1. R1 starts at 2)
    # 3. Front R1 ("properly"): answer "properly" (promoted 2 -> 3, syncs back to Card 1 in memory)
    # 4. Front Card 2 ("meant"): "/a" (repeats previous card R1, spawning R2. R2 starts at 3 in memory!)
    # 5. Front R2 ("properly"): answer "properly" (promoted 3 -> 4, syncs back to Card 1 in memory)
    # 6. Front Card 2 ("meant"): "/q" (quit)
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["properly", "/a", "properly", "/a", "properly", "/q"]
    )
    print("QUIZ OUTPUT:\n", out)
    print("TSV CONTENT:\n", tsv_file.read_text(encoding="utf-8"))
    assert code == 0
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    # Box should be promoted all the way to 4
    assert entry["LeitnerBox"] == "4", f"Expected Box 4, got {entry['LeitnerBox']}"


def test_sync_command_stats_and_header_repeat_false(quiz_env):
    """4.5.1 Test that the /sync command handles statistics and header formatting correctly when repeat_counts_in_stats is false."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nmpv_integration = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    
    # We set up 'properly' to have a known timestamp '10.5' in the Note field
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    note_idx = headers.index("Note")
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source == "properly":
            cols[box_idx] = "1"
            cols[due_idx] = "0"
            cols[note_idx] = "10.5"
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(int(time.time()) + 100000)
        new_lines.append("\t".join(cols))
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")

    # Start quiz.
    # 1. First card is 'properly'. Type '/sync 20260604184114 10.5'.
    #    This should load the synced card. Since repeat_counts_in_stats is false,
    #    the synced card is treated as a repeat (stats denominator stays at 1).
    # 2. Answer 'properly' correctly.
    # 3. Answer deferred 'properly' correctly.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/sync 20260604184114 10.5", "properly", "properly"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "Practice Repeat (Sync):" in clean_out
    assert "You scored 1 out of 1" in clean_out


def test_sync_command_stats_and_header_repeat_true(quiz_env):
    """4.5.2 Test that the /sync command handles statistics correctly when repeat_counts_in_stats is true."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "\nmpv_integration = true\nrepeat_counts_in_stats = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")

    tsv_file = quiz_env / "20260604184114-microsoft-just-shocked-the.en.tsv"
    
    # We set up 'properly' to have a known timestamp '10.5' in the Note field
    lines = tsv_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    header_line_idx = 0
    while header_line_idx < len(lines) and lines[header_line_idx].startswith("#"):
        new_lines.append(lines[header_line_idx])
        header_line_idx += 1
    headers = lines[header_line_idx].split("\t")
    new_lines.append(lines[header_line_idx])
    due_idx = headers.index("LeitnerDue")
    box_idx = headers.index("LeitnerBox")
    note_idx = headers.index("Note")
    for line in lines[header_line_idx + 1:]:
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        while len(cols) < len(headers):
            cols.append("")
        word_source = cols[1] if len(cols) > 1 else ""
        if word_source == "properly":
            cols[box_idx] = "1"
            cols[due_idx] = "0"
            cols[note_idx] = "10.5"
        else:
            cols[box_idx] = "2"
            cols[due_idx] = str(int(time.time()) + 100000)
        new_lines.append("\t".join(cols))
    tsv_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8", newline="\n")

    # Start quiz.
    # 1. First card is 'properly'. Type '/sync 20260604184114 10.5'.
    #    Since repeat_counts_in_stats is true, the synced card increases the total count.
    # 2. Answer 'properly' correctly.
    # 3. Answer deferred 'properly' correctly.
    code, out, err = run_quiz(
        quiz_env,
        ["20260604184114-microsoft-just-shocked-the.en.tsv"],
        ["/sync 20260604184114 10.5", "properly", "properly"]
    )
    assert code == 0
    clean_out = strip_ansi(out)
    assert "You scored 2 out of 2" in clean_out
    entry = read_tsv_entry(tsv_file, "properly")
    assert entry is not None
    assert entry["LeitnerBox"] == "3"
