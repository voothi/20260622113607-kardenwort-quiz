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
