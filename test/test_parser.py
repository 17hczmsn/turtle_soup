"""解析器链测试。"""

from __future__ import annotations

from ..parser import TurtleSoupPageParser

SURFACE = "一个男人走进餐厅，点了一碗海龟汤，尝了一口后走出餐厅自杀了。"
ANSWER = "他曾在海难中靠同伴的肉汤幸存，认出眼前这碗是普通龟汤后崩溃自责。"


class TestLabeledPageParser:
    def test_basic_pairs(self) -> None:
        content = f"标题：海龟汤\n汤面：{SURFACE}\n汤底：{ANSWER}"
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 1
        assert puzzles[0].surface == SURFACE
        assert puzzles[0].answer == ANSWER
        assert puzzles[0].title == "海龟汤"

    def test_answer_label_variants(self) -> None:
        for label in ("汤底", "答案", "解析", "真相", "谜底"):
            content = f"汤面：{SURFACE}\n{label}：{ANSWER}"
            assert len(TurtleSoupPageParser().parse(content)) == 1, label

    def test_multiple_puzzles_in_one_page(self) -> None:
        content = (
            f"标题：第一题\n汤面：{SURFACE}\n汤底：{ANSWER}\n\n"
            f"标题：第二题\n汤面：{SURFACE}第二\n汤底：{ANSWER}第二\n"
        )
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 2

    def test_html_page_normalized(self) -> None:
        content = (
            "<html><head><style>body{color:red}</style></head><body>"
            f"<p>汤面：{SURFACE}</p><br><p>汤底：{ANSWER}</p>"
            "<script>alert('x')</script></body></html>"
        )
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 1
        assert "alert" not in puzzles[0].answer

    def test_inline_single_line_pair(self) -> None:
        content = f"某题库整理：汤面：{SURFACE} 汤底：{ANSWER}。"
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 1


class TestNumberedListParser:
    def test_numbered_items_with_bracket_title(self) -> None:
        content = (
            f"1、【自杀的男人】{SURFACE}\n汤底：{ANSWER}\n"
            f"2、【雨夜出租车】她深夜上车后要求绕开了那段路。\n汤底：司机看到了不该看的东西，她只得提前下车。\n"
        )
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 2
        assert puzzles[0].title == "自杀的男人"
        assert puzzles[0].surface == SURFACE

    def test_numbered_item_with_surface_label(self) -> None:
        content = f"1、汤面：{SURFACE}\n答案：{ANSWER}\n"
        puzzles = TurtleSoupPageParser().parse(content)
        assert len(puzzles) == 1
        assert puzzles[0].surface == SURFACE
        assert puzzles[0].answer == ANSWER


class TestParserChain:
    def test_duplicate_puzzles_deduped_across_parsers(self) -> None:
        labeled = f"汤面：{SURFACE}\n汤底：{ANSWER}\n"
        numbered = f"1、{SURFACE}\n汤底：{ANSWER}\n"
        puzzles = TurtleSoupPageParser().parse(labeled + numbered)
        surfaces = [p.surface for p in puzzles]
        assert surfaces.count(SURFACE) == 1
