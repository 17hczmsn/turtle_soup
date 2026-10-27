"""题库缓存健壮性测试。"""

from __future__ import annotations

import json

from ..cache import TurtleSoupPuzzleCache
from ..models import TurtleSoupPuzzle


def _make_puzzle(surface: str = "一个足够长的汤面内容用于通过校验", answer: str = "一个足够长的汤底内容用于通过校验") -> TurtleSoupPuzzle:
    return TurtleSoupPuzzle(title="t", surface=surface, answer=answer)


def test_malformed_entries_skipped(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps(
            [
                _make_puzzle().to_dict(),
                {"surface": "x", "used_count": "not-a-number"},
                "not-a-dict",
                None,
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    puzzles = TurtleSoupPuzzleCache(str(cache_path)).load()
    assert len(puzzles) == 1


def test_corrupt_file_returns_empty(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{broken json", encoding="utf-8")
    assert TurtleSoupPuzzleCache(str(cache_path)).load() == []


def test_append_unique_dedupes_by_surface_and_answer(tmp_path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = TurtleSoupPuzzleCache(str(cache_path))
    first = _make_puzzle()
    duplicate = _make_puzzle()
    other = _make_puzzle(surface="另一个足够长的汤面内容用于通过校验区分")

    cache.append_unique([first])
    cache.append_unique([duplicate, other])
    puzzles = cache.load()

    assert len(puzzles) == 2
    assert {p.surface for p in puzzles} == {first.surface, other.surface}


def test_save_load_roundtrip(tmp_path) -> None:
    cache_path = tmp_path / "nested" / "cache.json"
    cache = TurtleSoupPuzzleCache(str(cache_path))
    puzzle = _make_puzzle()
    puzzle.used_count = 3
    cache.save([puzzle])

    loaded = TurtleSoupPuzzleCache(str(cache_path)).load()
    assert len(loaded) == 1
    assert loaded[0].used_count == 3
    assert loaded[0].surface == puzzle.surface
