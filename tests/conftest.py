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
        
        # Copy the lua script
        shutil.copy2(lua_script, tmpdir / "tsv_quiz.lua")
        
        # Create a mock config.ini
        config_path = tmpdir / "config.ini"
        config_path.write_text(
            "[Leitner]\n"
            "intervals = 5m, 1h, 1d\n"
            "new_cards_per_day = 10\n"
            "single_card_mode = false\n"
            "exact_length_mask = false\n",
            encoding="utf-8"
        )
        
        # Create mock data.tsv
        data_tsv = tmpdir / "data.tsv"
        data_tsv.write_text(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "apple\tapple\t\t\tяблоко\tI ate an apple today.\t\t\t\t\t\tDeckA\t1\t0\n"
            "banana\tbanana\t\t\tбанан\tA yellow banana.\t\t\t\t\t\tDeckA\t2\t0\n",
            encoding="utf-8"
        )
        
        # Create another mock data file for multi-file tests
        data2_tsv = tmpdir / "data2.tsv"
        data2_tsv.write_text(
            "WordSource\tWordSourceInflectedForm\tWordSource2\tQuotation\tWordDestination\tSentenceSource\tNote\tSourceURL\tSource-en-GB\tSource-en-US\tSentenceSourceIndex\tDeck\tLeitnerBox\tLeitnerDue\n"
            "cherry\tcherry\t\t\tвишня\tA sweet cherry.\t\t\t\t\t\tDeckB\t1\t0\n",
            encoding="utf-8"
        )
        
        yield tmpdir
