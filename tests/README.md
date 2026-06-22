# Kardenwort TSV Quiz - Test Suite

This project contains a comprehensive automated test suite to verify the interactive CLI quiz application, heavily inspired by the `kardenwort-mpv` testing methodology.

## Requirements

The tests run in Python using the `pytest` framework and interface with the Lua application using subprocess pipes. This allows simulated standard input and console output verification.

Install the requirements:

```cmd
pip install -r tests/requirements.txt
```

## Running the tests

You can run all tests from the repository root:

```cmd
pytest tests/ -v
```

## Structure

- **`tests/conftest.py`**: Contains the `quiz_env` fixture which creates an isolated temporary directory with a clean copy of `tsv_quiz.lua`, `config.ini`, and mock data TSVs. This guarantees tests never corrupt your real study data.
- **`tests/unit/test_interactive_quiz.py`**: Core interactive tests simulating right/wrong answers and `/q` commands, and verifying TSV persistence (e.g. Leitner Box and Due Date updates).
