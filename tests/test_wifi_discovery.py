from ttc3018_control.wifi_discovery import subnet_candidates


def test_subnet_candidates_cover_local_24_without_local_host() -> None:
    candidates = subnet_candidates(["192.168.86.31"])
    assert "192.168.86.1" in candidates
    assert "192.168.86.254" in candidates
    assert "192.168.86.31" not in candidates
    assert len(candidates) == 253


def test_subnet_candidates_deduplicate_interfaces_on_same_network() -> None:
    candidates = subnet_candidates(["192.168.86.31", "192.168.86.32"])
    assert len(candidates) == 252
