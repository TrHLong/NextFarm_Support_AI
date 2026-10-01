from datetime import datetime,timezone
from pathlib import Path

from nextfarm_device.answers import sensor_answer
from nextfarm_device.question_plan import route
from nextfarm_device.verified_answers import answer
from nextfarm_device.store import demo_business_events


ROOT=Path(__file__).resolve().parents[1]


def test_farmer_home_is_chat_first_and_hides_internal_concepts():
    html=(ROOT/'apps/device-web/index.html').read_text(encoding='utf-8')
    assert 'Trợ lý NextFarm' in html
    assert 'Tóm tắt tình trạng {zone} hôm nay cho tôi' in html
    assert '10 model dự báo' not in html
    assert '32 năng lực' not in html
    assert 'Tủ điều khiển' not in html
    assert 'data-tab=' not in html


def test_farmer_home_supports_automatic_or_explicit_farm_selection():
    javascript=(ROOT/'apps/device-web/app.js').read_text(encoding='utf-8')
    assert 'if (state.farms.length === 1) await selectFarm(state.farms[0])' in javascript
    assert "else $('#farmChooser').hidden = false" in javascript
    assert 'groupFarms(state.devices)' in javascript


def test_farmer_home_exposes_profile_zone_switcher_and_six_company_data_groups():
    html=(ROOT/'apps/device-web/index.html').read_text(encoding='utf-8')
    javascript=(ROOT/'apps/device-web/app.js').read_text(encoding='utf-8')
    assert 'id="farmProfileToggle"' in html
    assert 'id="zoneSelector"' in html and 'id="zoneDialog"' in html
    assert 'Cây trồng, số khu, cảm biến và ngưỡng' in html
    for label in ['Số đo cảm biến','Trạng thái thiết bị','Lịch tưới','Lịch sử tưới','Nhật ký lệnh','Cảnh báo']:
        assert f'<strong>{label}</strong>' in html
    assert 'zone_id: state.zone' in javascript
    assert 'Số đo cảm biến luôn có sai số' in javascript


def test_sensor_questions_keep_current_history_and_forecast_separate():
    javascript=(ROOT/'apps/device-web/app.js').read_text(encoding='utf-8')
    html=(ROOT/'apps/device-web/index.html').read_text(encoding='utf-8')
    assert "function sensorQuestionMode(question)" in javascript
    assert "sensorMode === 'history'" in javascript
    assert "period=hours:${windowHours}" in javascript
    assert 'Nhiệt độ hiện tại' in html and 'Xu hướng 2 giờ' in html and 'Dự báo 6 giờ' in html

    current=route('Nhiệt độ hiện tại của Khu A là bao nhiêu?')['requests'][0]
    history=route('Nhiệt độ Khu A trong 2 giờ gần đây biến động thế nào?')['requests'][0]
    forecast=route('Dự báo nhiệt độ Khu A trong 6 giờ tới')['requests'][0]
    assert (current['tool'],current['answer_mode'])==('sensor','current')
    assert (history['tool'],history['answer_mode'],history['period'])==('sensor_history','history','hours:2')
    assert (forecast['tool'],forecast['answer_mode'],forecast['requested_horizons'])==('models','forecast',[360])


def test_forecast_router_supports_agronomic_horizons_and_multi_metric_request():
    default=route('Dự báo nhiệt độ sắp tới')['requests'][0]
    day=route('Dự báo pH trong 24 giờ tới')['requests'][0]
    mixed=route('Trong 6 giờ tới, nhiệt độ, độ ẩm không khí, độ ẩm đất, EC và pH sẽ biến động thế nào?')['requests'][0]
    assert default['requested_horizons']==[360]
    assert day['requested_horizons']==[1440]
    assert mixed['tool']=='models' and mixed['requested_horizons']==[360]
    assert set(mixed['metrics'])=={'temperature','air_humidity','soil_moisture','ec','ph'}
    assert set(mixed['model_names'])=={'temperature_forecast','air_humidity_forecast','moisture_forecast','ec_forecast','ph_forecast'}


def test_temperature_answer_explains_crop_effect_without_overclaiming():
    now=datetime.now(timezone.utc)
    text=sensor_answer(
        {'items':[{'temperature':27,'observed_at':now.isoformat(),'quality':'good'}]},
        'temperature','Tình hình nhiệt độ thế nào?',
        {'crop':'Cà chua','thresholds':{'temperature':[18,32]},'agronomy_approved':False},now)
    assert 'thuận lợi để Cà chua' in text
    assert 'ngưỡng cấu hình tham chiếu' in text
    assert 'chưa thay thế tư vấn chuyên gia' in text
    assert 'có sai số' in text and 'không kết luận tuyệt đối' in text


def test_zone_a_natural_questions_route_to_the_right_data():
    overview=route('Khu A thế nào rồi?')
    assert overview['tools']==['overview']
    assert overview['requests'][0]['zone_id']=='zone_a'
    assert route('Tóm tắt tình trạng khu A hôm nay cho tôi')['tools']==['overview']
    assert route('Điện áp nguồn hiện tại bao nhiêu?')['tools']==['device_metrics']
    assert route('Có gì bất thường trong 24 giờ qua không?')['requests'][0]['period']=='days:1'
    assert route('Nhiệt độ khu A trong 2 giờ gần đây thế nào?')['requests'][0]['period']=='hours:2'
    assert route('Đất khu A có cần tưới chưa?')['tools']==['sensor']


def test_compound_irrigation_question_is_one_intent_and_one_answer_request():
    plan=route('Hôm nay Khu A đã tưới mấy lần và hết bao nhiêu nước?')
    assert plan['tools']==['irrigation']
    assert len(plan['requests'])==1
    assert plan['requests'][0]['zone_id']=='zone_a'


def test_chat_history_failure_examples_route_to_specific_business_operations():
    command=route('Ai vừa gửi lệnh điều khiển cho Khu A và kết quả ra sao?')
    assert command['tools']==['commands'] and len(command['requests'])==1
    irrigation_list=route('Cho tôi danh sách thời gian của những lần tưới nước hôm nay')['requests'][0]
    assert (irrigation_list['tool'],irrigation_list['operation'])==('irrigation','list')
    noon_ph=route('Cho tôi độ pH của đất trưa nay')['requests'][0]
    assert (noon_ph['tool'],noon_ph['period'],noon_ph['operation'])==('sensor_history','noon','period_last')
    valves=route('Hiện tại có mấy van đang mở?')['requests'][0]
    assert (valves['tool'],valves['operation'])==('operation','count_open')
    fertilizer=route('Hôm nay lượng phân sử dụng là bao nhiêu?')['requests'][0]
    assert fertilizer['tool']=='irrigation'
    pumps=route('Hôm nay có bơm nước và bơm phân không?')['requests'][0]
    assert (pumps['tool'],pumps['operation'],pumps['historical'])==('operation','ran_in_period',True)


def test_fertilizer_failure_question_is_diagnosis_not_schedule_edit():
    plan=route('Sao đặt lịch bón mà chưa thấy bón?')
    assert plan['tools']==['operation']
    assert plan['requests'][0]['operation']=='reason'


def test_unknown_garden_question_reports_missing_database_scope_without_guessing():
    task=route('Cây ở khu A có sâu không?')['requests'][0]
    assert task['tool']=='out_of_scope'
    assert task['scope_kind']=='garden_data_missing'


def test_zone_overview_is_short_grounded_and_actionable():
    now=datetime.now(timezone.utc);stamp=now.isoformat()
    value=answer('overview',{
        'sensor':{'items':[{'zone_id':'zone_a','observed_at':stamp,'quality':'good','temperature':34,'soil_moisture':57,'air_humidity':70,'ec':1.7,'ph':6.4}]},
        'status':{'items':[{'observed_at':stamp,'online':True,'pump_running':False,'valve_running':False}]},
        'irrigation':{'items':[]},'alerts':{'items':[]}},
        {'zone_id':'zone_a','metrics':['temperature','soil_moisture','air_humidity','ec','ph']},
        'Khu A thế nào rồi?',{'thresholds':{'temperature':[18,32],'soil_moisture':[55,75],'ec':[1,2.5],'ph':[5.5,7]}},now=now)
    assert 'Tóm tắt Khu A' in value['text']
    assert 'Nhiệt độ: 34.00 °C (cao)' in value['text']
    assert 'Việc cần làm:' in value['text']
    assert value['facts']['metrics']['temperature']['level']=='cao'


def test_multiple_thresholds_are_returned_together():
    value=answer('profile',{'items':[]},{'zone_id':'zone_a','metrics':['temperature','soil_moisture','ec','ph']},
        'Ngưỡng nhiệt độ, độ ẩm đất, EC, pH khu A là bao nhiêu?',
        {'crop':'Cà chua','thresholds':{'temperature':[18,32],'soil_moisture':[55,75],'ec':[1,2.5],'ph':[5.5,7]}})
    assert all(label in value['text'] for label in ['nhiệt độ: 18–32 °C','độ ẩm đất: 55–75 %','EC: 1–2.5 mS/cm','pH: 5.5–7 pH'])


def test_empty_records_are_missing_not_zero_and_include_check_time():
    now=datetime(2026,9,22,8,15,tzinfo=timezone.utc)
    irrigation=answer('irrigation',{'items':[]},{'zone_id':'zone_a','period':'today'},'Hôm nay tưới mấy lần?',{'zones':[{'zone_id':'zone_a'}]},now=now)
    alerts=answer('alerts',{'items':[]},{'zone_id':'zone_a','period':'today','operation':'active'},'Có cảnh báo chưa xử lý?',{'zones':[{'zone_id':'zone_a'}]},now=now)
    assert irrigation['facts']['water_liters'] is None and irrigation['facts']['fertilizer_ml'] is None
    assert 'không được tính lượng nước/phân bằng 0' in irrigation['text']
    assert '15:15 22/09/2026' in irrigation['text'] and '15:15 22/09/2026' in alerts['text']


def test_demo_baseline_contains_enabled_schedule_completed_run_and_command():
    now=datetime(2026,9,22,8,15,tzinfo=timezone.utc)
    events=demo_business_events(now)
    by_group={group:payload for group,stamp,payload,key in events}
    assert by_group['irrigation_schedules']['enabled'] is True
    assert by_group['irrigation_schedules']['start_time']=='06:00'
    assert by_group['irrigation_runs']['water_liters']>0
    assert by_group['irrigation_runs']['fertilizer_ml']>0
    assert by_group['control_commands']['status']=='acknowledged'
