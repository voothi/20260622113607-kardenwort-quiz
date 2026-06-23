import os
import shutil
import tempfile
from pathlib import Path
import pytest

@pytest.fixture
def quiz_env():
    """
    Creates an isolated environment for testing the TSV Quiz.
    Copies the main lua script and creates mock TSV files.
    """
    repo_root = Path(__file__).parent.parent.absolute()
    lua_script = repo_root / "tsv_quiz.lua"
    
    with tempfile.TemporaryDirectory() as tmpdir_name:
        tmpdir = Path(tmpdir_name)
        
        # Copy the lua script and python helper
        shutil.copy2(lua_script, tmpdir / "tsv_quiz.lua")
        shutil.copy2(repo_root / "_input_helper.py", tmpdir / "_input_helper.py")
        
        # Create a mock config.ini
        config_path = tmpdir / "config.ini"
        with open(config_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                "[Leitner]\n"
                "intervals = 5m, 1h, 1d\n"
                "new_cards_per_day = 10\n"
                "single_card_mode = false\n"
                "exact_length_mask = false\n"
                "sort_order = due_date\n"
                "incorrect_penalty = reset\n"
            )
        
        # Copy all real fixtures from tests/fixtures
        fixtures_dir = repo_root / "tests" / "fixtures"
        if fixtures_dir.is_dir():
            for item in fixtures_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, tmpdir / item.name)
        
        yield tmpdir

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
