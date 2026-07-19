from __future__ import annotations


def test_streamlit_source_has_persistent_replay_truth_labels(project_root) -> None:
    source = (project_root / "app.py").read_text(encoding="utf-8")
    assert "REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE" in source
    assert "Live Local</strong><br><code>unavailable" in source
    assert "Live Remote</strong><br><code>unavailable" in source
    assert "Run verified REPLAY" in source
    assert "RemoteBackend" not in source

