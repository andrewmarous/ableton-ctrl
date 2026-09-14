from ableton_ctrl.adapter.compatibility import resolve_edition, runtime_supported, select_profile


def test_tested_target_uses_shared_live_12_profile() -> None:
    profile = select_profile((12, 4, 2))
    assert profile.state == "tested"
    assert profile.enabled is True
    assert "Song" in profile.manifest


def test_unverified_live_12_requires_explicit_opt_in() -> None:
    assert select_profile((12, 5, 0)).enabled is False
    opted_in = select_profile((12, 5, 0), allow_unverified=True)
    assert opted_in.state == "unverified"
    assert opted_in.enabled is True


def test_unsupported_major_stays_disabled_even_with_opt_in() -> None:
    profile = select_profile((13, 0, 0), allow_unverified=True)
    assert profile.state == "unsupported"
    assert profile.enabled is False
    assert profile.manifest == {}


def test_unknown_edition_is_not_intro() -> None:
    assert resolve_edition(None).name == "unknown"
    assert resolve_edition(None).source == "unavailable"
    assert resolve_edition("Standard").source == "configuration"


def test_embedded_runtime_bounds_are_explicit() -> None:
    assert runtime_supported((3, 11))
    assert runtime_supported((3, 12))
    assert not runtime_supported((3, 10))
    assert not runtime_supported((3, 13))
