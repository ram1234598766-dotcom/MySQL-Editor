from mysql_editor.ui.animations import MICRO_DURATION_MS, STANDARD_DURATION_MS, reduce_motion_enabled


class SettingsStub:
    def __init__(self, value):
        self._value = value

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self._value


def test_reduce_motion_defaults_to_disabled():
    assert reduce_motion_enabled(SettingsStub(False)) is False


def test_reduce_motion_setting_is_respected():
    assert reduce_motion_enabled(SettingsStub(True)) is True


def test_animation_durations_are_short_and_bounded():
    assert 0 < MICRO_DURATION_MS <= STANDARD_DURATION_MS <= 220
