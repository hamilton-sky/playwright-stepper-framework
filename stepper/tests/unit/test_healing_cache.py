import json
from engine.healer.healing_cache import HealCache


def test_make_key_determinism(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    step = step_factory()
    assert cache.make_key(step) == cache.make_key(step)


def test_make_key_length(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    key = cache.make_key(step_factory())
    assert len(key) == 16


def test_make_key_differs_by_action(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    assert cache.make_key(step_factory(action="click")) != cache.make_key(step_factory(action="fill"))


def test_make_key_differs_by_description(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    assert (
        cache.make_key(step_factory(description="desc A"))
        != cache.make_key(step_factory(description="desc B"))
    )


def test_make_key_differs_by_element(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    assert (
        cache.make_key(step_factory(element={"css": ".a"}))
        != cache.make_key(step_factory(element={"css": ".b"}))
    )


def test_get_miss(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    assert cache.get(step_factory()) is None


def test_put_and_get(step_factory, tmp_path):
    cache = HealCache(tmp_path / "heal.json")
    step = step_factory()
    cache.put(step, {"css": ".healed"})
    assert cache.get(step) == {"css": ".healed"}


def test_persists_to_disk(step_factory, tmp_path):
    path = tmp_path / "heal.json"
    cache = HealCache(path)
    step = step_factory()
    cache.put(step, {"id": "new-id"})
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert cache.make_key(step) in data


def test_load_from_existing_file(step_factory, tmp_path):
    path = tmp_path / "heal.json"
    step = step_factory()
    # Write the cache file manually before constructing HealCache
    key = HealCache.make_key(step)
    path.write_text(json.dumps({key: {"css": ".from-disk"}}), encoding="utf-8")
    cache = HealCache(path)
    assert cache.get(step) == {"css": ".from-disk"}


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "heal.json"
    path.write_text("not-json", encoding="utf-8")
    cache = HealCache(path)
    assert cache._data == {}
