from utils import display_y_drive_path


def test_unc_share_is_displayed_as_y_drive():
    source = (
        r"\\EstInternetDisk\6B4-swj\07. 외부자료제공"
        r"\072. 수사기관\2025\251208 서울광진경찰서"
    )
    assert display_y_drive_path(source) == (
        r"Y:\07. 외부자료제공"
        r"\072. 수사기관\2025\251208 서울광진경찰서"
    )


def test_other_paths_are_not_changed():
    assert display_y_drive_path(r"G:\공유자료") == r"G:\공유자료"
    assert display_y_drive_path(r"\\OtherServer\Share\자료") == (
        r"\\OtherServer\Share\자료"
    )
