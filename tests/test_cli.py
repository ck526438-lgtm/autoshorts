import json

from autoshorts.cli import main


def test_run_with_only_a_job_resumes(tmp_path, capsys):
    job = tmp_path / "job"
    assert main(["run", "--job", str(job), "--dry-run"]) == 0
    out = capsys.readouterr().out
    plan = json.loads(out[out.index("{"):])
    assert plan["job_root"] == str(job)


def test_run_needs_something_to_do(capsys):
    assert main(["run"]) == 2
    assert "--job" in capsys.readouterr().err
