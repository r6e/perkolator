"""The workflows must apply the checks the prompt, README and security policy promise."""

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"
WATCH_WORKFLOW = WORKFLOWS / "watch.yml"
CI_WORKFLOW = WORKFLOWS / "ci.yml"


@pytest.mark.parametrize("flag", ["--verified-today", "--keeps-benefits-of"])
def test_commit_job_validates_with(flag: str) -> None:
    workflow = WATCH_WORKFLOW.read_text(encoding="utf-8")
    _, _, after = workflow.partition("uv run perkolator validate")
    validate_command, _, _ = after.partition("uv run perkolator normalize")
    assert flag in validate_command


def load_workflow(path: Path) -> dict[str, Any]:
    workflow: dict[str, Any] = yaml.safe_load(path.read_text("utf-8"))
    return workflow


def watch_jobs() -> dict[str, dict[str, object]]:
    jobs: dict[str, dict[str, object]] = load_workflow(WATCH_WORKFLOW)["jobs"]
    return jobs


def steps_text(job: dict[str, object]) -> str:
    steps = job["steps"]
    assert isinstance(steps, list)
    return "\n".join(f"{step.get('uses', '')} {step.get('run', '')}" for step in steps)


def test_only_the_model_job_may_ask_for_an_identity_token() -> None:
    jobs = watch_jobs()
    assert jobs["watch"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert jobs["page"]["permissions"] == {"contents": "read"}
    assert jobs["commit"]["permissions"] == {"contents": "write"}


def test_model_job_installs_no_python_dependencies() -> None:
    # Every step of a job with `id-token: write` can obtain the model credential.
    model_job = steps_text(watch_jobs()["watch"])
    assert "setup-project" not in model_job
    assert "uv " not in model_job
    assert "setup-project" in steps_text(watch_jobs()["page"])


def test_jobs_run_in_order_on_main_only() -> None:
    jobs = watch_jobs()
    assert [jobs[name].get("needs") for name in ("page", "watch", "commit", "publish")] == [
        None,
        "page",
        "watch",
        "commit",
    ]
    for name in ("page", "watch", "commit"):
        assert jobs[name]["if"] == "github.ref == 'refs/heads/main'"


def test_model_step_receives_every_credential_setting() -> None:
    steps = watch_jobs()["watch"]["steps"]
    assert isinstance(steps, list)
    (model_step,) = [step for step in steps if step.get("run") == "scripts/run-watcher.sh"]
    assert model_step["env"] == {
        name: f"${{{{ secrets.{name} }}}}"
        for name in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_FEDERATION_RULE_ID",
            "ANTHROPIC_ORGANIZATION_ID",
            "ANTHROPIC_SERVICE_ACCOUNT_ID",
            "ANTHROPIC_WORKSPACE_ID",
            "CLAUDE_CODE_OAUTH_TOKEN",
        )
    }


def test_pull_requests_get_a_dependency_review_with_a_read_only_token() -> None:
    ci = load_workflow(CI_WORKFLOW)
    job = ci["jobs"]["dependencies"]
    assert ci["permissions"] == {"contents": "read"}
    assert "permissions" not in job
    assert job["if"] == "github.event_name == 'pull_request'"
    assert "actions/dependency-review-action@" in steps_text(job)
