from openbridge.request_summary import format_request_summary_line, parse_usage


def test_parse_usage_reads_tokens_and_cost():
    summary = parse_usage(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost": 0.95,
        }
    )
    assert summary.prompt_tokens == 10
    assert summary.completion_tokens == 5
    assert summary.total_tokens == 15
    assert summary.cost == 0.95
    assert summary.cached_tokens is None
    assert summary.reasoning_tokens is None


def test_parse_usage_falls_back_to_input_output_tokens():
    summary = parse_usage({"input_tokens": 7, "output_tokens": 9, "total_tokens": 16})
    assert summary.prompt_tokens == 7
    assert summary.completion_tokens == 9
    assert summary.total_tokens == 16
    assert summary.cached_tokens is None
    assert summary.reasoning_tokens is None


def test_parse_usage_reads_cached_and_reasoning_details():
    summary = parse_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens_details": {"reasoning_tokens": 20},
        }
    )
    assert summary.prompt_tokens == 100
    assert summary.completion_tokens == 50
    assert summary.cached_tokens == 80
    assert summary.reasoning_tokens == 20


def test_format_request_summary_line_includes_tps_and_finish_reason():
    line = format_request_summary_line(
        duration_s=2.0,
        model="openai/gpt-4.1",
        source="codex-cli/0.92.0",
        usage={
            "prompt_tokens": 40,
            "completion_tokens": 60,
            "total_tokens": 100,
            "cost": 0.1234,
        },
        finish_reason="stop",
    )
    assert "REQ" in line
    assert "2000ms" in line
    assert "model=openai/gpt-4.1" in line
    assert "input=40" in line
    assert "output=60" in line
    assert "cost=0.1234cr" in line
    assert "tps=50.0" in line
    assert "finish=stop" in line
    assert "src=codex-cli/0.92.0" in line


def test_format_request_summary_line_includes_cached_and_reasoning_breakdowns():
    line = format_request_summary_line(
        duration_s=2.0,
        model="openai/gpt-4.1",
        source="codex-cli/0.92.0",
        usage={
            "prompt_tokens": 68457 + 355328,
            "completion_tokens": 8379,
            "input_tokens_details": {"cached_tokens": 355328},
            "output_tokens_details": {"reasoning_tokens": 4877},
            "cost": 0.1234,
        },
        finish_reason="stop",
    )
    assert "input=68,457 (+ 355,328 cached)" in line
    assert "output=8,379 (reasoning 4,877)" in line
    # TPS uses uncached input + output
    assert "tps=38418.0" in line
