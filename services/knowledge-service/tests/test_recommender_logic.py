from bs4 import BeautifulSoup

from app.main import _extract_structured_sections, range_fit


def test_inside_optimal_range_scores_high():
    score, reason = range_fit(25, 18, 30, 10)
    assert score >= 0.85
    assert "tối ưu" in reason


def test_far_outside_range_scores_low():
    score, reason = range_fit(45, 18, 30, 10)
    assert score <= 0.1
    assert "ngoài" in reason


def test_structured_extraction_preserves_heading_path_and_table_context():
    soup = BeautifulSoup(
        """
        <html><head><title>Hướng dẫn tưới</title></head><body>
          <h1>Cà chua</h1><h2>Giai đoạn ra hoa</h2>
          <p>Đoạn hướng dẫn này đủ dài để trở thành một chunk có cấu trúc và giữ đúng đường dẫn heading.</p>
          <table><tr><th>Chỉ số</th><th>Giá trị</th></tr><tr><td>pH</td><td>6.0</td></tr></table>
        </body></html>
        """,
        "html.parser",
    )

    title, sections = _extract_structured_sections(soup, "https://example.test/guide")

    assert title == "Hướng dẫn tưới"
    assert sections[0]["section_path"] == "Cà chua > Giai đoạn ra hoa"
    table = next(item for item in sections if item["content_type"] == "table")
    assert table["table_context"] == "Cà chua > Giai đoạn ra hoa"
    assert "Chỉ số | Giá trị" in table["content"]
