import json

from app.utils.raw_storage import RawPageWriter


def test_write_page_creates_file_with_content(tmp_path):
    w = RawPageWriter("job1", base_dir=str(tmp_path))
    path = w.write_page("envelopes", 0, {"envelopes": [{"envelopeId": "a"}]})
    assert path.name == "page_000000.json"
    assert json.loads(path.read_text())["envelopes"][0]["envelopeId"] == "a"


def test_no_tmp_files_left_behind(tmp_path):
    w = RawPageWriter("job1", base_dir=str(tmp_path))
    w.write_page("envelopes", 0, {"x": 1})
    assert not list(tmp_path.rglob("*.tmp"))


def test_rewrite_same_page_overwrites(tmp_path):
    w = RawPageWriter("job1", base_dir=str(tmp_path))
    w.write_page("envelopes", 3, {"v": 1})
    w.write_page("envelopes", 3, {"v": 2})
    pages = w.list_pages("envelopes")
    assert len(pages) == 1
    assert w.read_page(pages[0]) == {"v": 2}


def test_jsonl_one_record_per_line(tmp_path):
    w = RawPageWriter("job1", base_dir=str(tmp_path))
    path = w.write_page_jsonl("envelopes", 0, [{"a": 1}, {"a": 2}])
    lines = path.read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"a": 2}]


def test_list_pages_sorted_and_empty_ok(tmp_path):
    w = RawPageWriter("job1", base_dir=str(tmp_path))
    assert w.list_pages("envelopes") == []
    for n in (10, 2, 1):
        w.write_page("envelopes", n, {})
    assert [p.name for p in w.list_pages("envelopes")] == [
        "page_000001.json", "page_000002.json", "page_000010.json"]