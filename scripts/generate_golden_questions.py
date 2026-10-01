"""Create deterministic parser/query regression cases from canonical entities."""
from pathlib import Path
import json

TEMPLATES = [
 ('Độ ẩm đất khu {z} giờ bao nhiêu?','sensor_query','sensor'),
 ('Hôm qua tưới mấy lần ở khu {z}?','irrigation_history_query','irrigation'),
 ('Hôm qua tổng cộng tưới bao nhiêu phút khu {z}?','irrigation_history_query','irrigation'),
 ('Liệt kê các lần tưới hôm qua khu {z}.','irrigation_history_query','irrigation'),
 ('Trưa nay nhiệt độ cao nhất bao nhiêu?','sensor_query','sensor_history'),
 ('Hiện có bao nhiêu van đang mở?','device_state_query','operation'),
 ('Những van nào đang mở?','device_state_query','operation'),
 ('Bơm đang chạy không?','device_state_query','operation'),
 ('Hôm nay đã dùng bao nhiêu phân?','fertilizer_query','irrigation'),
 ('Kênh phân số 1 hôm nay dùng bao nhiêu ml?','fertilizer_query','irrigation'),
 ('Hôm nay có cảnh báo gì?','alert_query','alerts'),
 ('Ai vừa bật bơm?','command_log_query','commands'),
 ('Ngày mai có lịch tưới nào?','irrigation_schedule_query','schedules'),
 ('Độ ẩm hôm nay cao hơn hôm qua không?','comparison_query','sensor_history'),
]

def generate(path):
    rows=[]
    for farmer in range(1,4):
        for zone in ('A','B'):
            for question,intent,tool in TEMPLATES:
                for variant in (question, question.replace('bao nhiêu','mấy').replace('Hôm nay','Nay')):
                    q=variant.format(z=zone)
                    rows.append({'question':q,'farmer_id':f'farmer_{farmer:03d}','expected_intent':intent,'expected_tool':tool,'expected_time_range':{},'expected_result_source':'canonical_reset','must_not_contain':['farm_002'] if farmer==1 else []})
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n',encoding='utf-8'); return len(rows)

if __name__ == '__main__': print(generate(Path('benchmarks/golden_questions_reset.jsonl')))
