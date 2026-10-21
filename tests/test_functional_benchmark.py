from app.experiment_e2 import evaluate


def test_frozen_expected_labels_and_engine_verdicts_agree():
    result = evaluate()
    failures = [d for d in result["details"] if not d["correct"]]
    assert not failures, failures
    assert result["false_accepts"] == 0
    assert result["valid_false_block_rate"] == 0
