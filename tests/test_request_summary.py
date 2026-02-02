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


def test_parse_usage_falls_back_to_input_output_tokens():
    summary = parse_usage({"input_tokens": 7, "output_tokens": 9, "total_tokens": 16})
    assert summary.prompt_tokens == 7
    assert summary.completion_tokens == 9
    assert summary.total_tokens == 16


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
    assert "src=codex-cli/0.92.0" in line
    assert "in=40 out=60" in line
    assert "cost=0.1234cr" in line
    assert "tps=50.0" in line
    assert "finish=stop" in line
