import subprocess
import time
from pathlib import Path

def run_quiz(env_dir, args, inputs):
    """
    Helper to run the Lua script in a subprocess with given inputs.
    """
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

def test_single_file_quit(quiz_env):
    """Test that the user can start and quit the quiz gracefully."""
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    
    assert code == 0
    assert "Exiting quiz early" in out

def test_correct_answer_updates_box(quiz_env):
    """Test answering a card correctly updates its Leitner Box in the TSV."""
    # The data.tsv has "apple" in Box 1 and "banana" in Box 2
    # The quiz presents cards ordered by Box first, so Box 1 ("apple") should come up first.
    # We will answer "apple" correctly, then "/q" to quit.
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["apple", "/q"])
    
    assert code == 0
    assert "✅ Correct!" in out
    
    # Verify the TSV was updated
    data_tsv = quiz_env / "data.tsv"
    content = data_tsv.read_text(encoding="utf-8")
    
    # "apple" was in Box 1. Since it was correct, it should be in Box 2 now.
    # The line is: apple \t apple ... \t 1 \t 0
    # Let's find the apple line
    apple_line = [line for line in content.splitlines() if line.startswith("apple")][0]
    columns = apple_line.split("\t")
    
    # 13th column is LeitnerBox (index 12 in 0-based Python)
    box = columns[12]
    assert box == "2", f"Expected Box 2, got {box} in line: {apple_line}"
    
    # 14th column is LeitnerDue (index 13)
    due = int(columns[13])
    assert due > 0, "Expected LeitnerDue to be updated to a future timestamp"

def test_multi_file_loading(quiz_env):
    """Test passing multiple files correctly aggregates the queue."""
    # We pass both data.tsv and data2.tsv
    # Then we quit immediately
    code, out, err = run_quiz(quiz_env, ["data.tsv", "data2.tsv"], ["/q"])
    
    assert code == 0
    assert "Loading: data.tsv" in out
    assert "Loading: data2.tsv" in out
    
    # Total cards should be 3 (apple, banana, cherry)
    assert "Queue Summary: 0 due reviews, 3 new cards selected." in out

def test_incorrect_answer_penalty(quiz_env):
    """Test answering a card incorrectly lowers its Leitner Box."""
    # banana is in Box 2. Since apple is Box 1, apple comes first.
    # We answer apple correctly, then banana incorrectly, then quit.
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["apple", "wrong_answer", "/q"])
    
    assert code == 0
    assert "❌ Incorrect." in out
    
    data_tsv = quiz_env / "data.tsv"
    content = data_tsv.read_text(encoding="utf-8")
    
    banana_line = [line for line in content.splitlines() if line.startswith("banana")][0]
    columns = banana_line.split("\t")
    
    box = columns[12]
    # Config penalty is "reset" (box 1) or "decrease" (box 1). Let's assume it drops to 1.
    assert box == "1", f"Expected Box 1 for incorrect answer, got {box}"

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
    config_path.write_text(content, encoding="utf-8")
    
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["apple", "", "/q"])
    
    assert code == 0
    # verify clear screen ANSI code
    assert "\x1b[2J\x1b[H" in out
    assert "Press Enter or Space to continue..." in out

def test_exact_length_masking(quiz_env):
    """Test exact length masking configuration."""
    config_path = quiz_env / "config.ini"
    content = config_path.read_text(encoding="utf-8")
    content = content.replace("exact_length_mask = false", "exact_length_mask = true")
    config_path.write_text(content, encoding="utf-8")
    
    # Target word 'apple' -> 5 underscores: _____
    code, out, err = run_quiz(quiz_env, ["data.tsv"], ["/q"])
    
    assert code == 0
    assert "_____" in out

def test_empty_table_error(quiz_env):
    """Test handling of invalid or empty TSV gracefully."""
    empty_tsv = quiz_env / "empty.tsv"
    empty_tsv.write_text("Header1\tHeader2\n", encoding="utf-8")
    
    code, out, err = run_quiz(quiz_env, ["empty.tsv"], [])
    
    assert "Error loading" in out
    assert "No vocabulary files could be loaded." in out
