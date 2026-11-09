import json

import pytest

from voicetriage.engine import Tree
from voicetriage.facilities import Directory
from voicetriage.languages import (
    LANG_DIR,
    available,
    load_packs,
    recording_sheet,
    required_keys,
    scaffold_pack,
)


@pytest.fixture(scope="module")
def setup():
    tree, directory = Tree.load(), Directory.load()
    return load_packs(LANG_DIR), required_keys(tree, directory)


def test_english_and_swahili_are_complete(setup):
    packs, required = setup
    for code in ("en", "sw"):
        assert packs[code].missing(required) == [], code
        assert packs[code].is_ready(required)


def test_menu_order_and_cap(setup):
    packs, required = setup
    assert [p.code for p in available(packs, required)][:2] == ["en", "sw"]


def test_unfinished_pack_is_never_offered(setup, tmp_path):
    packs, required = setup
    scaffold_pack("kln", "Kalenjin", tmp_path, required)
    unfinished = load_packs(tmp_path)["kln"]
    assert not unfinished.is_ready(required)
    assert available({"kln": unfinished}, required) == []


def test_scaffold_creates_every_required_key(setup, tmp_path):
    _, required = setup
    folder = scaffold_pack("ki", "Kikuyu", tmp_path, required)
    data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert set(data["prompts"]) == set(required)
    assert data["reviewed"] is False
    assert (folder / "audio").is_dir()
    with pytest.raises(FileExistsError):
        scaffold_pack("ki", "Kikuyu", tmp_path, required)


def test_scaffold_rejects_unsafe_codes(setup, tmp_path):
    _, required = setup
    for bad in ("../x", "A", "x" * 20, "a b"):
        with pytest.raises(ValueError):
            scaffold_pack(bad, "Bad", tmp_path, required)


def test_audio_only_prompts_count_as_covered(setup, tmp_path):
    packs, required = setup
    folder = scaffold_pack("luo", "Dholuo", tmp_path, required)
    data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    data["audio"] = {key: f"{key}.mp3" for key in required}
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    pack = load_packs(tmp_path)["luo"]
    assert pack.missing(required) == []
    assert set(pack.audio_problems()) == set(required)  # files not delivered yet
    for key in required:
        (folder / "audio" / f"{key}.mp3").write_bytes(b"x")
    assert load_packs(tmp_path)["luo"].is_ready(required)


def test_recording_sheet_has_a_row_per_key(setup):
    packs, required = setup
    sheet = recording_sheet(packs["sw"], packs["en"], required).strip().splitlines()
    assert sheet[0].startswith("key,english_reference")
    assert len(sheet) == len(required) + 1
