import datetime
import yaml


class SeasonError(Exception):
    pass


def load_season(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SeasonError("season file is not a mapping")
    for key in ("server", "session_defaults", "rounds"):
        if key not in data:
            raise SeasonError(f"missing top-level key: {key}")
    if not data["rounds"]:
        raise SeasonError("rounds is empty")
    for i, r in enumerate(data["rounds"], 1):
        for key in ("track", "date"):
            if key not in r:
                raise SeasonError(f"round {i} missing '{key}'")
        try:
            datetime.date.fromisoformat(r["date"])
        except (ValueError, TypeError) as exc:
            # TypeError: an unquoted YAML date scalar arrives as a datetime.date,
            # not a str — surface it as a clean SeasonError like a bad string does.
            raise SeasonError(f"round {i} bad date (quote it as a string): {exc}") from exc
    return data


def active_round(rounds: list, today: datetime.date) -> dict:
    dated = sorted(rounds, key=lambda r: datetime.date.fromisoformat(r["date"]))
    upcoming = [r for r in dated if datetime.date.fromisoformat(r["date"]) >= today]
    return upcoming[0] if upcoming else dated[-1]
