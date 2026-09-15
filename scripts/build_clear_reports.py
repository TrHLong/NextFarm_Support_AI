from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BLUE = "17365D"
PALE_BLUE = "F3F6FA"
LIGHT_BORDER = "D9D9D9"
BLACK = RGBColor(0, 0, 0)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top: int = 90, start: int = 100, bottom: int = 90, end: int = 100) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), "6")
        tag.set(qn("w:color"), LIGHT_BORDER)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_cell_width(cell, width_cm: float) -> None:
    cell.width = Cm(width_cm)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.first_child_found_in("w:tcW")
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width_cm * 567)))
    tc_w.set(qn("w:type"), "dxa")


def set_run_font(run, size: float, bold: bool = False, color: RGBColor = BLACK) -> None:
    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def set_cell_text(cell, value: Any, *, bold: bool = False, color: RGBColor = BLACK, size: float = 8.6, align=WD_ALIGN_PARAGRAPH.LEFT) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.08
    run = paragraph.add_run(str(value if value is not None else ""))
    set_run_font(run, size, bold=bold, color=color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_margins(cell)


def add_table(doc: Document, headers: list[str], rows: Iterable[Iterable[Any]], widths: list[float], *, font_size: float = 8.6):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for index, width_cm in enumerate(widths):
        table.columns[index].width = Cm(width_cm)
        grid_col = table._tbl.tblGrid.gridCol_lst[index]
        grid_col.set(qn("w:w"), str(int(width_cm * 567)))
    set_table_borders(table)
    header = table.rows[0]
    set_repeat_table_header(header)
    for index, label in enumerate(headers):
        set_cell_width(header.cells[index], widths[index])
        set_cell_shading(header.cells[index], BLUE)
        set_cell_text(
            header.cells[index],
            label,
            bold=True,
            color=RGBColor(255, 255, 255),
            size=font_size,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
    for row_index, values in enumerate(rows):
        row = table.add_row()
        if row_index % 2:
            for cell in row.cells:
                set_cell_shading(cell, PALE_BLUE)
        for index, value in enumerate(values):
            set_cell_width(row.cells[index], widths[index])
            alignment = WD_ALIGN_PARAGRAPH.CENTER if index == 0 or len(str(value)) < 18 else WD_ALIGN_PARAGRAPH.LEFT
            set_cell_text(row.cells[index], value, size=font_size, align=alignment)
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(2)
    return table


def configure_document(doc: Document, title: str) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(1.65)
    section.bottom_margin = Cm(1.55)
    section.left_margin = Cm(1.65)
    section.right_margin = Cm(1.65)
    section.header_distance = Cm(0.7)
    section.footer_distance = Cm(0.7)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    normal.font.size = Pt(10.3)
    normal.font.color.rgb = BLACK
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.16

    title_style = styles["Title"]
    title_style.font.name = "Arial"
    title_style._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    title_style.font.size = Pt(20)
    title_style.font.bold = True
    title_style.font.color.rgb = BLACK
    title_style.paragraph_format.space_after = Pt(8)

    for style_name, size in (("Heading 1", 14), ("Heading 2", 11.5)):
        style = styles[style_name]
        style.font.name = "Arial"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = BLACK
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(5)
        style.paragraph_format.keep_with_next = True

    doc.core_properties.title = title
    doc.core_properties.subject = "Báo cáo kỹ thuật dự án NextFarm AI Support V10.1"
    doc.core_properties.author = "NextFarm AI Support V10.1"

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("NextFarm AI Support V10.1  |  Trang ")
    set_run_font(run, 8.2, color=RGBColor(80, 80, 80))
    field_begin = OxmlElement("w:fldChar")
    field_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    field_end = OxmlElement("w:fldChar")
    field_end.set(qn("w:fldCharType"), "end")
    run._r.append(field_begin)
    run._r.append(instr)
    run._r.append(field_end)


def add_title_block(doc: Document, title: str, subtitle: str) -> None:
    paragraph = doc.add_paragraph(style="Title")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.add_run(title)
    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(9)
    run = sub.add_run(subtitle)
    set_run_font(run, 10.5, bold=True, color=RGBColor(70, 70, 70))
    date_paragraph = doc.add_paragraph()
    date_paragraph.paragraph_format.space_after = Pt(12)
    run = date_paragraph.add_run(f"Dự án NextFarm AI Support V10.1  |  Cập nhật {datetime.now().strftime('%d/%m/%Y')}")
    set_run_font(run, 9.2, color=RGBColor(80, 80, 80))


def add_bullets(doc: Document, items: Iterable[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.add_run(item)


def relative_path(path_value: str | None, root: Path) -> str:
    if not path_value:
        return "-"
    normalized = str(path_value).replace("\\", "/")
    if normalized.startswith("/models/"):
        return "model-artifacts/" + normalized[len("/models/"):]
    path = Path(path_value)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def min_holdout_metric(model: dict[str, Any], metric: str) -> float | None:
    values = []
    for result in (model.get("generalization_holdout") or {}).values():
        value = (result.get("metrics") or {}).get(metric)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return min(values) if values else None


def compact_reason(model: dict[str, Any]) -> str:
    reasons = (model.get("quality_gate") or {}).get("reasons") or []
    if not reasons:
        return "Đã vượt toàn bộ quality gate."
    return "; ".join(str(item) for item in reasons[:2])


def build_ml_report(root: Path, output: Path) -> None:
    suite = read_json(root / "model-artifacts" / "shared" / "latest_training_report.json")
    metadata = suite.get("dataset_metadata") or {}
    customers = metadata.get("customer_sources") or []
    models = suite.get("models") or []

    doc = Document()
    configure_document(doc, "Báo cáo thực nghiệm 10 model AI và 32 năng lực NextFarm")
    add_title_block(
        doc,
        "Báo cáo thực nghiệm 10 model AI và 32 năng lực NextFarm",
        "Dữ liệu đầu vào, quy trình train, chỉ số đánh giá, quality gate và phương án mở rộng nhiều khách hàng",
    )
    doc.add_paragraph(
        "Báo cáo này trình bày toàn bộ đường đi từ dữ liệu CSV đến model candidate. Kết luận tại thời điểm lập báo cáo: "
        "quy trình và bằng chứng có thể truy vết đã hình thành, nhưng chất lượng model chưa đạt điều kiện sử dụng production."
    )
    add_table(
        doc,
        ["Chỉ tiêu", "Giá trị", "Ý nghĩa"],
        [
            ("Kiến trúc", suite.get("architecture"), "10 model nền dùng chung và hiệu chỉnh nhỏ theo farm"),
            ("Dataset version", suite.get("dataset_version"), "Khóa số liệu của báo cáo vào đúng một lần train"),
            ("Thời điểm train", suite.get("trained_at"), "Các lần train tự động sau có dataset_version khác"),
            ("Khách hàng", metadata.get("customer_count"), "Dữ liệu vẫn tách và truy vết theo customer_id"),
            ("Sensor trong cửa sổ train", f"{int(metadata.get('raw_reading_count', 0)):,}", "Nguồn hiện tại là telemetry mô phỏng đã hiệu chỉnh"),
            ("Mẫu sau xử lý", metadata.get("row_count"), "Mẫu đã căn chỉnh thời gian và tạo feature/target"),
            ("Model candidate", suite.get("model_count"), "Đã có đủ artifact để đánh giá"),
            ("Model approved", suite.get("approved_model_count"), "Chưa model nào vượt toàn bộ quality gate"),
            ("Model active", suite.get("total_active_model_count", 0), "Chưa model candidate nào được dùng để khẳng định production"),
            ("Production ready", str(bool(suite.get("production_ready"))).lower(), "Kết quả hiện chỉ phục vụ nghiên cứu và demo"),
        ],
        [3.4, 5.2, 7.9],
        font_size=9,
    )

    doc.add_heading("1 Phân biệt ba lớp AI trong dự án", level=1)
    add_table(
        doc,
        ["Thành phần", "Số lượng", "Bản chất", "Vai trò"],
        [
            ("Model ML nghiệp vụ", "10", "RandomForest hoặc ExtraTrees được chọn qua validation", "Dự báo cảm biến và phân loại trạng thái"),
            ("Năng lực AI", "32", "Danh mục capability của sản phẩm", "Mỗi năng lực có thể dùng model, rule, tool hoặc RAG"),
            ("LLM hội thoại", "0 hoặc 1 provider", "Deterministic hoặc OpenAI", "Lập kế hoạch gọi tool và diễn đạt bằng chứng"),
        ],
        [3.2, 2.0, 5.3, 6.0],
        font_size=8.9,
    )
    doc.add_paragraph(
        "Ba khái niệm trên không được cộng chung. Ba mươi hai năng lực không đồng nghĩa với ba mươi hai file model. "
        "Mười model nghiệp vụ cũng không phải ChatGPT hay Gemini."
    )

    doc.add_heading("2 Dữ liệu dùng cho lần train", level=1)
    customer_rows = []
    for item in customers:
        customer_rows.append(
            (
                item.get("customer_id"),
                item.get("raw_sensor_reading_count"),
                item.get("processed_rows_before_cap"),
                item.get("processed_rows_used"),
                item.get("farm_count"),
                item.get("zone_count"),
            )
        )
    add_table(
        doc,
        ["Khách hàng", "Sensor trong cửa sổ", "Sau xử lý", "Được dùng", "Farm", "Zone"],
        customer_rows,
        [3.4, 2.6, 2.5, 2.5, 2.0, 2.0],
        font_size=8.8,
    )

    group_names = ["alerts", "control_commands", "device_status", "irrigation_runs", "sensor_readings", "telemetry_ingest_events"]
    group_rows = []
    for item in customers:
        counts = item.get("raw_group_counts") or {}
        group_rows.append([item.get("customer_id")] + [counts.get(name, 0) for name in group_names])
    group_rows.append(["Tổng"] + [sum(int((item.get("raw_group_counts") or {}).get(name, 0)) for item in customers) for name in group_names])
    doc.add_paragraph(
        "Bảng tiếp theo là số dòng tích lũy trong cơ sở dữ liệu tại thời điểm scheduler quyết định có retrain hay không. "
        "Các số này dùng để so ngưỡng kích hoạt, không phải số mẫu cuối cùng đưa vào model."
    )
    add_table(
        doc,
        ["Khách hàng", "Cảnh báo", "Lệnh", "Thiết bị", "Ca tưới", "Sensor", "Ingest"],
        group_rows,
        [3.0, 2.0, 1.7, 2.4, 1.9, 2.7, 2.5],
        font_size=8.2,
    )
    doc.add_paragraph(
        "Số bản ghi thô lớn hơn nhiều số mẫu train vì pipeline phải gom dữ liệu theo thời điểm, ghép các loại cảm biến, tạo cửa sổ lịch sử, "
        "tạo target tương lai và loại những dòng không đủ feature hoặc target. Một sensor reading không tương đương một mẫu ML hoàn chỉnh."
    )

    doc.add_heading("3 Tệp CSV và khả năng truy vết", level=1)
    source_rows = []
    for item in customers:
        source_rows.append(
            (
                str(item.get("customer_id") or "").replace("_", "_\u2060"),
                item.get("snapshot_id"),
                relative_path(item.get("processed_csv"), root),
                relative_path(item.get("source_manifest"), root),
            )
        )
    add_table(
        doc,
        ["Khách hàng", "Snapshot", "CSV feature và target", "Manifest hash và nguồn"],
        source_rows,
        [3.4, 3.7, 4.8, 4.7],
        font_size=7.9,
    )
    doc.add_paragraph(
        f"Dataset gộp của lần train: {suite.get('dataset_version')}. customer_id được giữ trong CSV để truy vết và kiểm định theo khách hàng, "
        "nhưng bị loại khỏi danh sách feature trước khi fit model."
    )

    doc.add_heading("4 Quy trình xử lý và train", level=1)
    add_table(
        doc,
        ["Bước", "Thao tác", "Bằng chứng hoặc kiểm soát"],
        [
            (1, "Xuất snapshot riêng theo customer_id", "Mỗi khách hàng có thư mục raw và snapshot_manifest.json riêng"),
            (2, "Kiểm tra số dòng tối thiểu theo nhóm dữ liệu", "Khách hàng thiếu nhóm bắt buộc không được đưa vào pool"),
            (3, "Làm sạch kiểu dữ liệu, timestamp và giá trị thiếu", "Tạo CSV đã xử lý và evidence_manifest.json"),
            (4, "Tạo 44 feature", "Feature thời gian, rolling, delta, sensor, crop, soil, climate và ngưỡng mục tiêu"),
            (5, "Tạo 10 target", "Bốn bài toán regression và sáu bài toán classification"),
            (6, "Chia train validation test theo thời gian", "Không xáo trộn ngẫu nhiên; ngăn model học trước dữ liệu tương lai"),
            (7, "So sánh RandomForest và ExtraTrees trên validation", "Chọn thuật toán theo chỉ số validation của từng target"),
            (8, "Đánh giá trên test và leave one customer out", "Đo khả năng khái quát sang khách hàng chưa xuất hiện trong train"),
            (9, "Áp dụng quality gate", "Candidate không đạt vẫn được lưu để giải trình nhưng không được active"),
            (10, "Phát hành manifest model active", "Chỉ artifact approved mới xuất hiện trong active_models.json"),
        ],
        [1.2, 6.2, 9.2],
        font_size=8.7,
    )

    doc.add_heading("5 Cách chia dữ liệu", level=1)
    first_model = models[0] if models else {}
    add_table(
        doc,
        ["Tập", "Số dòng", "Mục đích", "Ranh giới"],
        [
            ("Train", suite.get("train_count"), "Fit tham số model", f"Kết thúc {first_model.get('train_end', '-') }"),
            ("Validation", suite.get("validation_count"), "Chọn RandomForest hoặc ExtraTrees", f"Kết thúc {first_model.get('validation_end', '-') }"),
            ("Test", suite.get("test_count"), "Đánh giá cuối trên giai đoạn mới nhất", "Sau validation"),
            ("LOCO", "Theo từng customer", "Giữ một khách hàng làm holdout", "Không dùng customer holdout khi fit"),
        ],
        [2.5, 2.6, 6.0, 5.7],
        font_size=8.8,
    )

    doc.add_heading("6 Chỉ số đánh giá", level=1)
    add_table(
        doc,
        ["Nhóm", "Chỉ số", "Cách đọc"],
        [
            ("Hồi quy", "MAE", "Sai số tuyệt đối trung bình; càng thấp càng tốt và giữ nguyên đơn vị target"),
            ("Hồi quy", "RMSE", "Phạt mạnh sai số lớn; càng thấp càng tốt"),
            ("Hồi quy", "R bình phương", "Gần 1 là tốt; bằng 0 tương đương dự đoán trung bình; âm là kém hơn baseline trung bình"),
            ("Phân loại", "Accuracy", "Tỷ lệ dự đoán đúng tổng thể; có thể gây hiểu lầm khi lớp mất cân bằng"),
            ("Phân loại", "Macro F1", "Tính đều cho từng lớp rồi lấy trung bình; phù hợp hơn khi lớp hiếm"),
            ("Phân loại", "Recall lớp rủi ro", "Tỷ lệ phát hiện đúng lỗi hoặc tình trạng nguy hiểm; bằng 0 nghĩa là bỏ sót toàn bộ lớp đó"),
            ("Khái quát", "LOCO", "Đánh giá trên khách hàng bị giữ lại hoàn toàn; dùng để phát hiện model chỉ nhớ đặc điểm khách hàng cũ"),
        ],
        [2.5, 3.1, 10.9],
        font_size=8.8,
    )

    doc.add_heading("7 Kết quả của 10 model", level=1)
    result_rows = []
    for index, model in enumerate(models, start=1):
        metrics = model.get("test_metrics") or {}
        if model.get("task") == "regression":
            test_text = f"R² {metrics.get('r2', 0):.3f}; MAE {metrics.get('mae', 0):.3f}; RMSE {metrics.get('rmse', 0):.3f}"
            holdout = min_holdout_metric(model, "r2")
            holdout_text = f"Min R² {holdout:.3f}" if holdout is not None else "Không có"
        else:
            test_text = f"Accuracy {metrics.get('accuracy', 0) * 100:.1f}%; Macro F1 {metrics.get('f1_macro', 0):.3f}"
            holdout = min_holdout_metric(model, "f1_macro")
            holdout_text = f"Min F1 {holdout:.3f}" if holdout is not None else "Không có"
        result_rows.append(
            (
                index,
                model.get("model_name"),
                test_text,
                holdout_text,
                str(model.get("deployment_status", "")).upper(),
                compact_reason(model),
            )
        )
    add_table(
        doc,
        ["STT", "Model", "Test", "LOCO", "Trạng thái", "Lý do chính"],
        result_rows,
        [1.0, 3.1, 3.5, 2.3, 2.4, 4.7],
        font_size=7.8,
    )
    doc.add_paragraph(
        "Không được quy đổi R bình phương thành phần trăm chính xác. Với classification, không được chỉ công bố Accuracy. "
        "Ví dụ irrigation_need có Accuracy cao nhưng vẫn bị chặn vì kết quả LOCO thấp và một khách hàng thiếu lớp dương."
    )

    doc.add_heading("8 Trạng thái 32 năng lực AI", level=1)
    add_table(
        doc,
        ["Trạng thái", "Số năng lực trong runtime demo", "Ý nghĩa"],
        [
            ("READY", 3, "Đủ điều kiện ở mức capability hiện tại"),
            ("EXPERIMENTAL", 4, "Có thành phần thử nghiệm nhưng chưa được dùng để khẳng định production"),
            ("BLOCKED", 25, "Thiếu dữ liệu, model approved hoặc bằng chứng chuyên môn"),
            ("Tổng", 32, "Danh mục năng lực, không phải số file model"),
        ],
        [3.4, 4.2, 8.8],
        font_size=9,
    )

    doc.add_heading("9 Phương án khi có 500 khách hàng", level=1)
    add_table(
        doc,
        ["Vấn đề", "Cách triển khai"],
        [
            ("Số model", "Duy trì 10 model nền dùng chung; không tạo 5.000 model đầy đủ"),
            ("Tách dữ liệu", "Snapshot và CSV vẫn nằm riêng theo customer_id để kiểm soát tenant và provenance"),
            ("Cân bằng đóng góp", "Giới hạn tối đa 5.000 dòng đã xử lý cho mỗi khách hàng trong một lần train"),
            ("Cá nhân hóa", "Lưu hệ số hiệu chỉnh nhỏ theo farm như bias hoặc scale"),
            ("Kiểm định", "Dùng LOCO hoặc group holdout để kiểm tra khách hàng chưa xuất hiện trong train"),
            ("Khác biệt lớn", "Chỉ tách model theo nhóm cây trồng, khí hậu hoặc kiểu canh tác khi có bằng chứng thống kê"),
            ("Phát hành", "Candidate mới chỉ thay model active nếu vượt quality gate; nếu fail thì giữ model active cũ"),
        ],
        [4.3, 12.2],
        font_size=9,
    )

    doc.add_heading("10 Kết luận và dữ liệu cần bổ sung", level=1)
    doc.add_paragraph(
        "Hệ thống đã chứng minh được đường đi từ CSV đến artifact và kết quả đánh giá. Điểm chưa đạt nằm ở dữ liệu và khả năng khái quát, "
        "không nằm ở việc thiếu file model. Để nâng model lên approved cần bổ sung telemetry production ở nhiều khách hàng, tăng số sự kiện lớp hiếm, "
        "xây nhãn có chuyên gia xác nhận và tiếp tục đánh giá trên các giai đoạn thời gian chưa dùng khi train."
    )
    add_bullets(
        doc,
        [
            "Báo cáo con người đọc: model-artifacts/reports/LATEST_TRAINING_REPORT.md",
            "Báo cáo máy đọc: model-artifacts/shared/latest_training_report.json",
            "Model active: model-artifacts/shared/active_models.json",
            "Bằng chứng xác minh: docs/evidence/shared-ml-verification.json",
            f"Bản JSON đã khóa cùng báo cáo: docs/evidence/ML-REPORT-SNAPSHOT-{suite.get('dataset_version')}.json",
            "CSV gộp và split: model-artifacts/data/shared/processed/<dataset_version>/",
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def build_llm_report(root: Path, output: Path) -> None:
    suite = read_json(root / "model-artifacts" / "shared" / "latest_training_report.json")
    metadata = suite.get("dataset_metadata") or {}
    env = read_env(root / ".env")
    provider = (env.get("LLM_PROVIDER") or "deterministic").lower()
    configured_model = env.get("OPENAI_MODEL") or "gpt-5.6-luna"
    api_active = provider == "openai" and bool(env.get("OPENAI_API_KEY"))

    doc = Document()
    configure_document(doc, "Báo cáo kiến trúc LLM và luồng xử lý câu hỏi NextFarm")
    add_title_block(
        doc,
        "Báo cáo kiến trúc LLM và luồng xử lý câu hỏi NextFarm",
        "Provider đang hoạt động, dữ liệu được gửi tới đâu, khi nào dùng model ML và cơ chế chống trả lời không có căn cứ",
    )
    current_statement = (
        "Phiên hiện tại dùng bộ định tuyến deterministic và không gửi câu hỏi ra OpenAI hoặc Gemini."
        if provider != "openai"
        else f"Phiên hiện tại dùng OpenAI Responses API với model {configured_model}."
    )
    doc.add_paragraph(
        current_statement
        + " Câu hỏi của người dùng được lưu làm lịch sử và audit; nó không tự động trở thành dữ liệu train cho 10 model nghiệp vụ."
    )
    add_table(
        doc,
        ["Thông tin", "Giá trị hiện tại", "Diễn giải"],
        [
            ("Provider hội thoại", provider, "deterministic là rule based router; openai là chế độ API tùy chọn"),
            ("External LLM đang hoạt động", "Có" if api_active else "Không", "Chỉ có khi provider là openai và API key hợp lệ"),
            ("Model OpenAI cấu hình", configured_model, "Chưa hoạt động khi provider là deterministic"),
            ("API OpenAI", "OpenAI Responses API" if api_active else "Không gọi trong phiên hiện tại", "Dùng cho planner và verbalizer khi được bật"),
            ("Gemini", "Chưa hỗ trợ", "Chưa có adapter hoặc biến cấu hình Gemini trong LLM Gateway"),
            ("Model ML nghiệp vụ", "10 model RandomForest candidate", f"Approved {suite.get('approved_model_count', 0)}; active {suite.get('total_active_model_count', 0)}"),
            ("Chat dùng để train", "Không", "chat_messages_used_for_training=false"),
        ],
        [4.2, 4.3, 8.0],
        font_size=8.9,
    )

    doc.add_heading("1 Khái niệm cần phân biệt", level=1)
    add_table(
        doc,
        ["Khái niệm", "Trong dự án", "Có học từ câu hỏi chat không"],
        [
            ("LLM", "Bộ lập kế hoạch và diễn đạt hội thoại; deterministic hoặc OpenAI", "Không tự huấn luyện trong dự án"),
            ("API LLM", "OpenAI Responses API khi LLM_PROVIDER=openai", "Nhận request để suy luận, không phải quá trình train model NextFarm"),
            ("10 model ML", "RandomForest hoặc ExtraTrees cho sensor và trạng thái", "Không; học từ CSV dữ liệu vận hành đã xử lý"),
            ("RAG", "Truy xuất tài liệu đã duyệt từ Knowledge Service", "Không tự học; lấy đoạn tài liệu phù hợp tại thời điểm hỏi"),
            ("Tool", "API đọc sensor, thiết bị, tưới, cảnh báo và analytics", "Không; tool chỉ đọc dữ liệu được phân quyền"),
            ("Truth Guard", "Kiểm tra câu trả lời sau bước diễn đạt", "Không; là cổng xác minh trước khi phát hành"),
        ],
        [3.2, 8.1, 5.2],
        font_size=8.7,
    )

    doc.add_heading("2 Các chế độ provider", level=1)
    add_table(
        doc,
        ["Provider", "Trạng thái", "Cách hoạt động", "Dữ liệu ra bên ngoài"],
        [
            ("deterministic", "Đang dùng", "Rule based planner chọn tool và giữ bản nháp do backend tạo", "Không gửi câu hỏi tới nhà cung cấp LLM"),
            ("OpenAI", "Đã có mã hỗ trợ nhưng chưa bật", f"Responses API với model cấu hình {configured_model}", "Khi bật sẽ gửi câu hỏi cho planner và gửi draft cùng evidence giới hạn cho verbalizer"),
            ("Gemini", "Chưa triển khai", "Chưa có client, cấu hình hoặc audit adapter", "Không có dữ liệu gửi tới Gemini"),
        ],
        [2.7, 3.4, 6.4, 4.0],
        font_size=8.6,
    )

    doc.add_heading("3 Luồng xử lý một câu hỏi", level=1)
    add_table(
        doc,
        ["Bước", "Thành phần", "Dữ liệu vào", "Kết quả"],
        [
            (1, "Frontend", "Nội dung câu hỏi, farm đang chọn, token", "Gửi POST /chat"),
            (2, "Identity và Farm Context", "Token và danh sách farm được đọc", "Xác nhận user, farm và quyền tenant"),
            (3, "PostgreSQL", "Tin nhắn người dùng", "Lưu support_db.conversations và support_db.chat_messages"),
            (4, "Context Policy", "Câu hỏi, zone ghi rõ, tool payload gần nhất", "Chọn zone có căn cứ hoặc yêu cầu người dùng bổ sung"),
            (5, "LLM Gateway Planner", "Câu hỏi và allow list farm", "Chọn tối đa bốn tool; không có quyền truy cập DB"),
            (6, "Tool Service", "Farm, zone, metric đã kiểm soát", "Đọc sensor, thiết bị, tưới, cảnh báo, knowledge hoặc analytics"),
            (7, "Model nghiệp vụ", "Feature sensor hiện hành", "Chỉ chạy model approved phù hợp; hiện active count bằng 0"),
            (8, "Backend Draft", "Kết quả tool và rule", "Tạo câu trả lời nháp có số liệu, timestamp và nguồn"),
            (9, "LLM Verbalizer", "Draft và evidence giới hạn", "Deterministic giữ nguyên; OpenAI chỉ diễn đạt lại khi được bật"),
            (10, "Truth Guard", "Câu trả lời và evidence", "Cho phép, sửa mức chắc chắn hoặc chặn"),
            (11, "PostgreSQL", "Câu trả lời cuối và tool payload", "Lưu lịch sử, grounded, intent và provenance"),
            (12, "Frontend", "Kết quả đã xác minh", "Hiển thị trả lời, nguồn, dữ liệu hoặc đề nghị chuyển chuyên gia"),
        ],
        [1.1, 3.8, 5.9, 5.8],
        font_size=8.2,
    )

    doc.add_heading("4 Câu hỏi có quay về model hay không", level=1)
    add_table(
        doc,
        ["Loại câu hỏi", "Có qua LLM planner", "Có gọi 10 model ML", "Nguồn câu trả lời"],
        [
            ("Số đo cảm biến hiện tại", "Có, hoặc planner deterministic", "Không bắt buộc", "Farm Data Service và timestamp thực tế"),
            ("Trạng thái thiết bị hoặc lịch sử tưới", "Có, hoặc planner deterministic", "Không", "Tool đọc dữ liệu vận hành"),
            ("Kiến thức nông học", "Có, hoặc planner deterministic", "Không", "Knowledge Service và citation đã duyệt"),
            ("Dự báo hoặc đánh giá bằng AI", "Có, hoặc planner deterministic", "Có, nhưng chỉ model approved", "AI Analytics; nếu thiếu model thì từ chối đưa con số"),
            ("Hỏi hệ thống đang dùng model nào", "Không cần suy đoán", "Không", "Chatbot gọi health của LLM Gateway và trả provider thực tế"),
            ("Phản hồi sửa câu trả lời", "Không tự động", "Không", "Vào hàng đợi review; chỉ dùng sau khi người có quyền duyệt"),
        ],
        [4.5, 3.2, 3.4, 5.5],
        font_size=8.5,
    )
    doc.add_paragraph(
        "Câu trả lời ngắn gọn là: câu hỏi có thể đi qua planner để chọn công cụ, nhưng không được đưa vào RandomForest để train hoặc thay đổi trọng số. "
        "Khi câu hỏi cần dự báo, backend mới gọi model nghiệp vụ đã approved. Khi provider OpenAI được bật, câu hỏi có thể được gửi tới OpenAI API để lập kế hoạch, "
        "nhưng đây là suy luận tại thời điểm hỏi, không phải train lại model NextFarm."
    )

    doc.add_heading("5 Dữ liệu chat được lưu và quản trị thế nào", level=1)
    add_table(
        doc,
        ["Dữ liệu", "Nơi lưu", "Có tự động dùng train không", "Điều kiện sử dụng sau này"],
        [
            ("Câu hỏi và câu trả lời", "support_db.chat_messages", "Không", "Dùng làm lịch sử và audit"),
            ("Thông tin phiên", "support_db.conversations", "Không", "Giữ ngữ cảnh đúng user và farm"),
            ("Tool payload", "Cùng bản ghi chat bot", "Không", "Truy vết nguồn của câu trả lời"),
            ("Audit LLM", "ai_db.llm_audits", "Không", "Theo dõi provider, model, mục đích, latency và lỗi"),
            ("Phản hồi người dùng", "support_db.chat_feedback", "Không mặc định", "Phải approved và training_use_allowed=true sau kiểm tra privacy, tenant, provenance và độ đúng"),
        ],
        [3.5, 4.0, 3.5, 5.7],
        font_size=8.5,
    )

    doc.add_heading("6 Cơ chế khi thiếu dữ liệu hoặc model", level=1)
    add_table(
        doc,
        ["Tình huống", "Hành vi bắt buộc"],
        [
            ("Thiếu farm hoặc zone", "Hỏi lại; không tự chọn farm hoặc zone đầu tiên"),
            ("Sensor thiếu, cũ hoặc chất lượng kém", "Thông báo trạng thái; không khẳng định hiện trạng"),
            ("Không có model approved", "Không dùng candidate experimental để đưa kết luận production"),
            ("Thiếu nguồn nông học", "RAG trả không đủ dữ liệu và đề nghị bổ sung nguồn hoặc chuyển chuyên gia"),
            ("LLM API lỗi", "Rơi về deterministic draft"),
            ("Truth Guard lỗi", "Chặn câu trả lời có evidence; không phát hành kết luận chưa kiểm chứng"),
        ],
        [5.1, 11.4],
        font_size=8.9,
    )

    doc.add_heading("7 Cách kiểm tra trực tiếp", level=1)
    add_table(
        doc,
        ["Kiểm tra", "Lệnh hoặc câu hỏi", "Kết quả hiện tại mong đợi"],
        [
            ("LLM health", "curl http://127.0.0.1:18950/health", "provider deterministic; model null trước khi rebuild mã health mới"),
            ("Hỏi chatbot", "Chatbot đang sử dụng model nào?", "Nêu provider, API, model cấu hình và tách khỏi 10 RandomForest"),
            ("Hỏi về Gemini", "Hệ thống có dùng Gemini không?", "Trả lời chưa tích hợp và phiên hiện tại không gửi dữ liệu tới Gemini"),
            ("Hỏi dữ liệu chat", "Câu hỏi của tôi có được dùng để train không?", "Trả lời không tự động; phải qua hàng đợi review có kiểm soát"),
            ("Trạng thái ML", "Mở model-artifacts/shared/active_models.json", "Danh sách models hiện rỗng vì 0 model approved"),
        ],
        [3.3, 6.9, 6.4],
        font_size=8.5,
    )

    doc.add_heading("8 Kết luận", level=1)
    doc.add_paragraph(
        "Kiến trúc hiện tại tách rõ ba việc: LLM chọn cách lấy thông tin và diễn đạt; tool lấy dữ liệu thật theo quyền; model ML thực hiện dự báo chuyên biệt. "
        "Tin nhắn chat được lưu để truy vết nhưng không tự quay về pipeline train. Thiết kế này tránh việc một câu hỏi hoặc một câu trả lời sai làm thay đổi model tự động."
    )
    doc.add_paragraph(
        "Tệp đối chiếu: services/llm-gateway-service/app/main.py; services/chatbot-service/app/main.py; "
        "infra/database/07_v10_1_customer_ml_evidence.sql; docker-compose.yml; .env. "
        f"Bằng chứng ML ghi chat_messages_used_for_training={str(metadata.get('chat_messages_used_for_training', False)).lower()}."
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    build_ml_report(root, output_dir / "BAO-CAO-THUC-NGHIEM-10-MODEL-VA-32-NANG-LUC.docx")
    build_llm_report(root, output_dir / "BAO-CAO-KIEN-TRUC-LLM-VA-LUONG-XU-LY-CAU-HOI.docx")
    suite = read_json(root / "model-artifacts" / "shared" / "latest_training_report.json")
    evidence_name = f"ML-REPORT-SNAPSHOT-{suite['dataset_version']}.json"
    (output_dir / evidence_name).write_text(
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output_dir": str(output_dir),
        "files": sorted(path.name for path in output_dir.glob("*.docx")),
        "evidence_snapshot": evidence_name,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
