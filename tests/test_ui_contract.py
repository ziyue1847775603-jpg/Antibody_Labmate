from __future__ import annotations


def test_streamlit_source_has_persistent_replay_truth_labels(project_root) -> None:
    source = (project_root / "app.py").read_text(encoding="utf-8")
    assert "REPLAY · FIXED HASH-VERIFIED DEMO · NOT LIVE COMPUTE" in source
    assert "Live Local</strong><br><code>verified_live" in source
    assert "Benchmark Local</strong><br><code>implemented_unverified" in source
    assert "Live Remote</strong><br><code>unavailable" in source
    assert "Run verified REPLAY" in source
    assert "Structure prediction backend" in source
    assert '"Replay (Demo)"' in source
    assert '"ColabFold"' in source
    assert '"IgFold"' in source
    assert "Deterministic offline demonstration" in source
    assert "AlphaFold2 based local prediction" in source
    assert (
        "Local paired VH/VL prediction-only; unavailable on this Replay web host"
        in source
    )
    assert "The web workflow remains the hash-verified Replay demo." in source
    assert "prediction_backend_name != \"replay\"" in source
    assert "RemoteBackend" not in source
