from scripts.check_cron_health import (
    JobSpec,
    Thresholds,
    consecutive_failures,
    evaluate_job,
    is_command_tool_unavailable_ok,
)


def test_is_command_tool_unavailable_ok_detects_hidden_non_execution():
    entry = {
        "summary": "Final status: failed to run; no `exec`/`process` terminal tool was exposed in this automation turn, so the command could not be executed."
    }
    assert is_command_tool_unavailable_ok(entry) is True


def test_consecutive_failures_treats_command_tool_unavailable_as_failure():
    entries = [
        {"status": "ok", "summary": "no `exec`/`process` terminal tool was exposed"},
        {"status": "ok", "summary": "healthy"},
    ]
    assert consecutive_failures(entries) == 1


def test_evaluate_job_marks_hidden_non_execution_critical():
    job = JobSpec(
        key="paper_demo_market_open",
        job_id="job-1",
        label="paper demo",
        thresholds=Thresholds(consecutive_fail_warn=1, consecutive_fail_critical=1),
        expect_delivery=True,
    )
    latest = {
        "status": "ok",
        "summary": "Final status: failed to run; no `exec`/`process` terminal tool was exposed in this automation turn, so the command could not be executed.",
        "runAtMs": 1,
        "durationMs": 12000,
        "deliveryStatus": "delivered",
        "nextRunAtMs": 9999999999999,
    }
    result = evaluate_job(job, [latest])
    assert result["status"] == "critical"
    assert "latest run was marked ok but no exec/process command tool was exposed" in result["issues"]
