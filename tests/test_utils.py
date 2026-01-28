import time


from openbridge.utils import drop_none, json_dumps, new_id, now_ts


def test_now_ts_returns_current_timestamp():
    """Test that now_ts returns a valid Unix timestamp."""
    before = int(time.time())
    result = now_ts()
    after = int(time.time())

    assert before <= result <= after


def test_new_id_has_correct_prefix():
    """Test that new_id generates IDs with the correct prefix."""
    resp_id = new_id("resp")
    assert resp_id.startswith("resp_")

    item_id = new_id("item")
    assert item_id.startswith("item_")


def test_new_id_unique():
    """Test that new_id generates unique IDs."""
    id1 = new_id("test")
    id2 = new_id("test")
    assert id1 != id2


def test_new_id_format():
    """Test that new_id generates IDs in the correct format."""
    test_id = new_id("test")
    parts = test_id.split("_", 1)

    assert len(parts) == 2
    assert parts[0] == "test"
    # UUID hex is 32 characters
    assert len(parts[1]) == 32


def test_json_dumps_basic_types():
    """Test json_dumps with basic data types."""
    assert json_dumps({"key": "value"}) == '{"key":"value"}'
    assert json_dumps([1, 2, 3]) == "[1,2,3]"
    assert json_dumps("hello") == '"hello"'
    assert json_dumps(42) == "42"
    assert json_dumps(True) == "true"
    assert json_dumps(None) == "null"


def test_json_dumps_nested_structure():
    """Test json_dumps with nested structures."""
    data = {"user": {"name": "Alice", "age": 30}, "items": [1, 2, 3]}
    result = json_dumps(data)
    assert '"user"' in result
    assert '"name":"Alice"' in result
    assert '"items":[1,2,3]' in result


def test_json_dumps_returns_string():
    """Test that json_dumps returns a string."""
    result = json_dumps({"test": 123})
    assert isinstance(result, str)


def test_drop_none_removes_none_values():
    """Test that drop_none removes None values from dict."""
    data = {"a": 1, "b": None, "c": "test", "d": None}
    result = drop_none(data)

    assert result == {"a": 1, "c": "test"}
    assert "b" not in result
    assert "d" not in result


def test_drop_none_preserves_other_falsy_values():
    """Test that drop_none preserves falsy values that are not None."""
    data = {"zero": 0, "empty_str": "", "false": False, "none": None}
    result = drop_none(data)

    assert result == {"zero": 0, "empty_str": "", "false": False}
    assert "none" not in result


def test_drop_none_empty_dict():
    """Test drop_none with empty dict."""
    result = drop_none({})
    assert result == {}


def test_drop_none_no_none_values():
    """Test drop_none when there are no None values."""
    data = {"a": 1, "b": 2, "c": 3}
    result = drop_none(data)
    assert result == data


def test_drop_none_all_none_values():
    """Test drop_none when all values are None."""
    data = {"a": None, "b": None, "c": None}
    result = drop_none(data)
    assert result == {}
