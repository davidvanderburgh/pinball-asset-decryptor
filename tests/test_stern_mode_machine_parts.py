"""PAD-420: a machine's hardware decides which mechanism sections the Modes tab shows at all."""

import os

from pinball_decryptor.plugins.stern import mode_project as MP


def test_every_shipped_port_names_a_known_machine():
    for name in os.listdir(MP.PORTS_DIR):
        if name.endswith(".port"):
            game = name.rsplit("-", 1)[0]
            assert game in MP.MACHINE_HARDWARE, game


def test_the_inventory_only_names_hardware_parts():
    for game, parts in MP.MACHINE_HARDWARE.items():
        assert set(parts) <= set(MP.HARDWARE_PARTS), game


def test_absent_is_what_the_machine_lacks():
    assert MP.machine_absent("godzilla_pro") == ("coils", "shield", "shaker")
    assert MP.machine_absent("godzilla_le") == ("shaker",)
    assert MP.machine_absent("jaws_le") == ("magnet", "scoop", "shield", "shaker")
    assert MP.machine_absent("no_such_game") == ()


def test_profiles_carry_it():
    p = MP.profile_from_port(os.path.join(MP.PORTS_DIR, "jaws_le-1.02.port"))
    assert "magnet" in p.absent and "coils" not in p.absent
    assert MP.GODZILLA_PRO_1_15.absent == ("coils", "shield", "shaker")


def test_only_the_premium_has_the_shield_platform():
    assert [g for g, parts in MP.MACHINE_HARDWARE.items() if "shield" in parts] == ["godzilla_le"]
