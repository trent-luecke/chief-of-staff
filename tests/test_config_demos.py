import json


def test_demos_config_present():
    c = json.load(open("config.json"))
    d = c["demos"]
    assert set(d["counted_reps"]) == {"Ryan Allwein", "Luke Martin", "Chris Reynolds",
                                      "Jeff Davidson", "Trent Luecke"}
    assert d["lookback_hours"] == 72
