from __future__ import annotations

from click.testing import CliRunner

from openjarvis.cli.org_cmd import org


def test_org_bootstrap_and_show(tmp_path):
    db = str(tmp_path / "agents.db")
    runner = CliRunner()

    res = runner.invoke(org, ["bootstrap", "--db-path", db])
    assert res.exit_code == 0, res.output
    assert "created" in res.output.lower()

    res = runner.invoke(org, ["show", "--db-path", db])
    assert res.exit_code == 0, res.output
    assert "Chief Orchestrator" in res.output
