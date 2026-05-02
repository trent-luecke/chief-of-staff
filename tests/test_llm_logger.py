import json
from lib.storage import LocalStorage


def setup_function():
    from lib import llm_logger
    llm_logger.reset()


def teardown_function():
    from lib import llm_logger
    llm_logger.reset()


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_log_usage_accumulates_calls():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    llm_logger.log_usage("people", FakeUsage(), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 2


def test_log_usage_calculates_cost_correctly():
    from lib import llm_logger
    # Sonnet: $3.00/M input, $15.00/M output
    # 1000 input + 200 output = 1000*3/1_000_000 + 200*15/1_000_000 = 0.003 + 0.003 = 0.006
    llm_logger.log_usage("brief", FakeUsage(input_tokens=1000, output_tokens=200), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 1
    assert abs(llm_logger._calls[0]["estimated_cost_usd"] - 0.006) < 1e-9


def test_log_usage_unknown_model_zero_cost():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-unknown-99")
    assert llm_logger._calls[0]["estimated_cost_usd"] == 0.0


def test_flush_writes_jsonl(tmp_path):
    from lib import llm_logger
    storage = LocalStorage(base_dir=str(tmp_path))
    llm_logger.log_usage("brief", FakeUsage(input_tokens=500, output_tokens=100), "claude-sonnet-4-6")
    llm_logger.flush("daily_brief", storage)
    log_content = storage.read(llm_logger._LOG_KEY)
    assert log_content is not None
    lines = [json.loads(l) for l in log_content.splitlines() if l.strip()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["run_type"] == "daily_brief"
    assert entry["caller"] == "brief"
    assert entry["model"] == "claude-sonnet-4-6"
    assert entry["input_tokens"] == 500
    assert entry["output_tokens"] == 100
    assert "timestamp" in entry
    assert "estimated_cost_usd" in entry


def test_flush_clears_accumulator(tmp_path):
    from lib import llm_logger
    storage = LocalStorage(base_dir=str(tmp_path))
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    llm_logger.flush("daily_brief", storage)
    assert llm_logger._calls == []


def test_flush_non_fatal_on_bad_storage():
    from lib import llm_logger

    class BrokenStorage:
        def append_line(self, key, line):
            raise OSError("simulated storage failure")

    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    # Should not raise even when storage raises
    llm_logger.flush("daily_brief", BrokenStorage())
    # Accumulator is cleared regardless of write success
    assert llm_logger._calls == []


def test_reset_clears_calls():
    from lib import llm_logger
    llm_logger.log_usage("brief", FakeUsage(), "claude-sonnet-4-6")
    assert len(llm_logger._calls) == 1
    llm_logger.reset()
    assert llm_logger._calls == []
