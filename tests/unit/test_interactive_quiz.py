import subprocess
import time
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

def run_quiz(env_dir, args, inputs):
    cmd = ["lua", "tsv_quiz.lua"] + args
    
    # Run the process
    process = subprocess.Popen(
        cmd,
        cwd=env_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
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
    assert "clear way to use it" in out
    assert "unified intelligence" not in out

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
    assert "Press Enter/Space to continue ('s' repeat, 'a' previous, 'd' skip, 'q' quit)..." in out

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
    empty_tsv = quiz_env / "empty.tsv"
    with open(empty_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write("Header1\tHeader2\n")
    
    code, out, err = run_quiz(quiz_env, ["empty.tsv"], [])
    
    assert "Error loading" in out
    assert "No vocabulary files could be loaded." in out

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
    assert "clear way to use it" in out
    assert "unified intelligence" not in out
    
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
    assert "unified intelligence" in out
    assert "clear way to use it" not in out

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
    assert "Practice Repeat:" in clean_out

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


