from intext.geometry import MINIMUM_SETTINGS, PREFERRED_SETTINGS, settings_size


def test_short_work_area_does_not_keep_the_old_tall_window():
    size = settings_size((1707, 912))
    assert size == (PREFERRED_SETTINGS[0], int(912 * 0.52))
    assert size[1] < 760
    assert size[1] / 912 < 0.56


def test_saved_size_is_not_forced_back_to_the_default_fraction():
    assert settings_size((1707, 912), (520, 760)) == (520, 760)


def test_saved_size_is_clamped_to_the_work_area():
    width, height = settings_size((900, 500), (1200, 900))
    assert width == 900 - 28
    assert height == 500 - 28
    assert width >= MINIMUM_SETTINGS[0]


def test_tiny_screen_never_exceeds_the_work_area():
    width, height = settings_size((320, 280))
    assert width <= 320 - 28
    assert height <= 280 - 28
