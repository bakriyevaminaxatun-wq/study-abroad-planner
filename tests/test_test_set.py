import json
from collections import Counter
from pathlib import Path

from tests.build_test_set import build

DATA = json.loads((Path(__file__).parent / "test_set.json").read_text(encoding="utf-8"))
TASKS = DATA["tasks"]


def test_file_is_up_to_date():
    assert DATA == json.loads(json.dumps(build(), ensure_ascii=False))


def test_counts():
    assert len(TASKS) == 24
    assert Counter(t["language"] for t in TASKS) == {"az": 12, "en": 12}
    assert Counter(t["category"] for t in TASKS) == {"simple": 8, "multi": 10, "forbidden": 6}
    assert Counter((t["language"], t["category"]) for t in TASKS) == {
        ("az", "simple"): 4, ("en", "simple"): 4, ("az", "multi"): 5, ("en", "multi"): 5,
        ("az", "forbidden"): 3, ("en", "forbidden"): 3}


def test_simple_tasks_need_exactly_one_tool_and_multi_need_more():
    for t in TASKS:
        if t["category"] == "simple":
            assert len(t["expected_tool_sequence"]) == 1
        if t["category"] == "multi":
            assert len(t["expected_tool_sequence"]) >= 2


def test_every_task_is_complete_and_checks_exist():
    ids = [t["id"] for t in TASKS]
    assert len(set(ids)) == 24
    for t in TASKS:
        assert t["user_message"].strip() and t["expected_behavior"].strip()
        assert t["profile_id"] in DATA["profiles"]
        for c in t["checks"]:
            assert c.split(":")[0] in DATA["check_definitions"], c
        if "fixture" in t:
            assert t["fixture"] in DATA["fixtures"]


def test_multi_and_simple_scenarios_exist_in_both_languages():
    by = Counter((t["scenario_id"], t["language"]) for t in TASKS if t["category"] != "forbidden")
    scenarios = {t["scenario_id"] for t in TASKS if t["category"] != "forbidden"}
    for s in scenarios:
        assert by[(s, "az")] == 1 and by[(s, "en")] == 1


def test_forbidden_types_from_the_plan_are_covered():
    text = " ".join(t["expected_behavior"].lower() for t in TASKS if t["category"] == "forbidden")
    for word in ("guarantee", "predict", "letter", "no fixed date", "injected"):
        assert word in text
    assert sum("ignores_injected_instruction" in t["checks"] for t in TASKS) == 2


def test_azerbaijani_tasks_use_azerbaijani_text():
    for t in TASKS:
        if t["language"] == "az" and t["category"] != "forbidden":
            assert any(ch in t["user_message"] for ch in "əıöüğşçƏ"), t["id"]
