import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remap import apply_pit_rules


def test_30min_race_has_no_mandatory_pitstop():
    er = {"mandatoryPitstopCount": 1, "isMandatoryPitstopRefuellingRequired": True,
          "isMandatoryPitstopTyreChangeRequired": True, "isMandatoryPitstopSwapDriverRequired": True}
    apply_pit_rules(er, 30)
    assert er["mandatoryPitstopCount"] == 0
    assert er["isMandatoryPitstopRefuellingRequired"] is False
    assert er["isMandatoryPitstopTyreChangeRequired"] is False
    assert er["isMandatoryPitstopSwapDriverRequired"] is False


def test_60min_race_has_one_fuel_only_mandatory_pitstop():
    er = {"mandatoryPitstopCount": 0, "isRefuellingAllowedInRace": False,
          "isMandatoryPitstopRefuellingRequired": False,
          "isMandatoryPitstopTyreChangeRequired": True,
          "isMandatoryPitstopSwapDriverRequired": True}
    apply_pit_rules(er, 60)
    assert er["mandatoryPitstopCount"] == 1
    assert er["isRefuellingAllowedInRace"] is True
    assert er["isMandatoryPitstopRefuellingRequired"] is True      # fuel required
    assert er["isMandatoryPitstopTyreChangeRequired"] is False     # ...only fuel
    assert er["isMandatoryPitstopSwapDriverRequired"] is False
