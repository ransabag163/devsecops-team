import json

import pytest

from main import main


@pytest.mark.parametrize("file_path, code, status", [
    ("samples/clean.py", 0, "no_findings"),
    ("samples/login.py", 1, "findings"),
    ("samples/notes.txt", 2, "input_error"),
    ("samples/missing.py", 2, "input_error"),
])
def test_exit_code_matches_the_report(capsys, file_path, code, status):
    assert main([file_path]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_no_file_path_is_an_input_error(capsys):
    assert main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "clarify"


def test_trace_flag_prints_the_trace(capsys):
    main(["samples/login.py", "--trace"])
    captured = capsys.readouterr()

    assert json.loads(captured.out)["file"] == "samples/login.py"
    assert [entry["step"] for entry in json.loads(captured.err)] == [1, 2]
