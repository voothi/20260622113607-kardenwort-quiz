import subprocess
import time
from pathlib import Path
import struct
def read_tsv_entry(path, word):
    """
    Helper to safely read a TSV file and return a card entry as a dictionary by matching the WordSource.
    """
    with open(path, "r", encoding="utf-8", newline="\n") as f:
        lines = f.read().splitlines()
        
    if not lines:
        return None
        
    headers = lines[0].split("\t")
    
    for line in lines[1:]:
        cols = line.split("\t")
        if cols and cols[0] == word:
            return dict(zip(headers, cols))
            
    return None

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
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    assert code == 0
    assert "Exiting quiz early" in out

def test_correct_answer_updates_box(quiz_env):
    """Test answering a card correctly updates its Leitner Box in the TSV."""
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["apple", "/q"])
    
    assert code == 0
    assert "✅ Correct!" in out
    
    # Verify the TSV was updated
    data_tsv = quiz_env / "data.tsv"
    entry = read_tsv_entry(data_tsv, "apple")
    assert entry is not None
    assert entry["LeitnerBox"] == "2", f"Expected Box 2, got {entry['LeitnerBox']}"
    assert int(entry["LeitnerDue"]) > 0, "Expected LeitnerDue to be updated to a future timestamp"

def test_case_insensitivity_and_spacing(quiz_env):
    """Test the normalizer for user inputs with odd casing and spacing."""
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["  APPle  ", "/q"])
    
    assert code == 0
    assert "✅ Correct!" in out
    
    data_tsv = quiz_env / "data.tsv"
    entry = read_tsv_entry(data_tsv, "apple")
    assert entry["LeitnerBox"] == "2"

def test_study_ahead(quiz_env):
    """Test the scheduling algorithm's behavior when no cards are currently due."""
    # Set study_ahead = true
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content += "study_ahead = true\n"
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Mock TSV with cards in the far future
    data_tsv = quiz_env / "data.tsv"
    future_time = int(time.time()) + 100000
    with open(data_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            f"apple\tapple\t\t\tяблоко\tI ate an apple today.\t\t\t\t\t\tDeckA\t1\t{future_time}\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    assert code == 0
    assert "Entering \"Study Ahead\" mode" in out
    assert "Question 1/1" in out

def test_review_sort_order(quiz_env):
    """Test presentation order sort algorithms for due reviews."""
    # Box 1 (apple) and Box 5 (banana), both due (LeitnerDue = 1)
    data_tsv = quiz_env / "data.tsv"
    with open(data_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "apple\tapple\t\t\tяблоко\tI ate an apple today.\t\t\t\t\t\tDeckA\t1\t1\n"
            "banana\tbanana\t\t\tбанан\tA yellow banana.\t\t\t\t\t\tDeckA\t5\t1\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    assert code == 0
    
    # Apple is Box 1, should be sorted first
    assert "I ate an" in out and "today" in out
    banana_pos = out.find("yellow")
    assert banana_pos == -1, "Banana shouldn't be asked yet because we quit on the first card."

def test_incorrect_penalty_decrease(quiz_env):
    """Test answering a card incorrectly lowers its Leitner Box."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("incorrect_penalty = reset", "incorrect_penalty = decrease")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Mock a card in Box 3
    data_tsv = quiz_env / "data.tsv"
    with open(data_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "banana\tbanana\t\t\tбанан\tA yellow banana.\t\t\t\t\t\tDeckA\t3\t0\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["wrong_answer", "/q"])
    assert code == 0
    assert "❌ Incorrect." in out
    
    entry = read_tsv_entry(data_tsv, "banana")
    assert entry["LeitnerBox"] == "2", f"Expected Box 2 (decreased from 3), got {entry['LeitnerBox']}"

def test_utf8_masking_alignment(quiz_env):
    """Test exact length masking configuration with multibyte UTF-8 characters."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    # Mock a card with an umlaut
    data_tsv = quiz_env / "data.tsv"
    with open(data_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "Absätze\tAbsätze\t\t\tparagraphs\tDie ersten zwei Absätze.\t\t\t\t\t\tDeckA\t1\t0\n"
        )
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    assert code == 0
    # Target word 'Absätze' has 7 characters, should be 7 underscores
    assert "_______" in out

def test_lua_lnk_resolution(quiz_env):
    """Test pure Lua .lnk parser universally via a mock binary payload."""
    # We will craft a tiny mock binary that the Lua string.unpack logic can successfully parse as a Windows Shortcut.
    # The Lua logic checks:
    # 1. 76 bytes minimum, magic starts with 'L\0\0\0' (4C 00 00 00).
    # 2. Flags at offset 21 (1-indexed: 20 in 0-indexed).
    # 3. LinkTargetIDList (flag 0x01), LinkInfo (flag 0x02).
    # 4. If LinkInfo, it reads link_info_flags at offset + 8, local_base_path_offset at offset + 16.
    
    lnk_path = quiz_env / "test.lnk"
    target_path = "data2.tsv"
    
    # Constructing the binary
    # Header: 76 bytes
    header = bytearray(76)
    header[0:4] = b"L\0\0\0"
    flags = 0x02 # Only HasLinkInfo
    struct.pack_into("<I", header, 20, flags)
    
    # LinkInfo
    link_info_start = 76
    link_info_size = 28 + len(target_path) + 1
    link_info = bytearray(link_info_size)
    struct.pack_into("<I", link_info, 0, link_info_size) # Size
    struct.pack_into("<I", link_info, 4, 28) # Header size
    struct.pack_into("<I", link_info, 8, 0x01) # Flags (VolumeIDAndLocalBasePath)
    struct.pack_into("<I", link_info, 16, 28) # LocalBasePathOffset
    
    # Append the target path string at LocalBasePathOffset (which is 28 bytes into LinkInfo)
    link_info[28:28+len(target_path)] = target_path.encode('utf-8')
    link_info[28+len(target_path)] = 0 # Null terminator
    
    with open(lnk_path, "wb") as f:
        f.write(header)
        f.write(link_info)
        
    code, out, err = run_quiz(quiz_env, ["test.lnk"], ["/q"])
    assert code == 0
    assert "Loading: data2.tsv" in out

def test_multi_file_loading(quiz_env):
    """Test passing multiple files correctly aggregates the queue."""
    code, out, err = run_quiz(quiz_env, ["data.tsv", "data2.tsv"], ["/q"])
    
    assert code == 0
    assert "Loading: data.tsv" in out
    assert "Loading: data2.tsv" in out
    
    assert "Queue Summary: 0 due reviews, 3 new cards selected." in out

def test_hints_display(quiz_env):
    """Test standard and advanced hints."""
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/h", "/h 2 1 1", "/q"])
    
    assert code == 0
    assert "💡 Hint:" in out
    assert "(length: 5)" in out

def test_single_card_mode(quiz_env):
    """Test flashcard mode toggling."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("single_card_mode = false", "single_card_mode = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["apple", "", "/q"])
    
    assert code == 0
    assert "\x1b[2J\x1b[H" in out
    assert "Press Enter or Space to continue..." in out

def test_exact_length_masking(quiz_env):
    """Test exact length masking configuration."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8", newline="\n")
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    
    assert code == 0
    assert "_____" in out

def test_empty_table_error(quiz_env):
    """Test handling of invalid or empty TSV gracefully."""
    empty_tsv = quiz_env / "empty.tsv"
    with open(empty_tsv, "w", encoding="utf-8", newline="\n") as f:
        f.write("Header1\tHeader2\n")
    
    code, out, err = run_quiz(quiz_env, ["empty.tsv"], [])
    
    assert "Error loading" in out
    assert "No vocabulary files could be loaded." in out
