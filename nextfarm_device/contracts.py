from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class ModelSpec:
    name: str
    title: str
    task: str
    target: str
    horizon_minutes: int
    metric: str = ''

SPECS = [
    ModelSpec('moisture_forecast','Độ ẩm đất sau 30 phút','regression','soil_moisture_future',30,'soil_moisture'),
    ModelSpec('temperature_forecast','Nhiệt độ sau 30 phút','regression','temperature_future',30,'temperature'),
    ModelSpec('ec_forecast','EC sau 30 phút','regression','ec_future',30,'ec'),
    ModelSpec('ph_forecast','pH sau 30 phút','regression','ph_future',30,'ph'),
    ModelSpec('flow_fault_forecast','Sự cố mất lưu lượng trong 60 phút','classification','no_flow_future',60),
    ModelSpec('leak_forecast','Rò rỉ trong 60 phút','classification','leak_future',60),
    ModelSpec('irrigation_failure_forecast','Ca tưới gián đoạn trong 60 phút','classification','irrigation_abort_future',60),
    ModelSpec('sensor_fault_forecast','Sự cố cảm biến trong 60 phút','classification','sensor_fault_future',60),
    ModelSpec('power_loss_forecast','Nguy cơ mất nguồn trong 60 phút','classification','power_loss_future',60),
    ModelSpec('mqtt_loss_forecast','Nguy cơ gián đoạn MQTT trong 60 phút','classification','mqtt_loss_future',60),
]
METRICS = {
    'soil_moisture': ('độ ẩm đất','%'), 'temperature': ('nhiệt độ','°C'),
    'ec': ('EC','mS/cm'), 'ph': ('pH','pH'), 'air_humidity': ('độ ẩm không khí','%RH'),
    'flow_rate': ('lưu lượng','L/phút'), 'pressure': ('áp suất','bar'),
    'supply_voltage': ('điện áp nguồn','V'), 'rssi': ('cường độ sóng','dBm'),
}
GROUPS = ['sensor_readings','device_status','irrigation_schedules','irrigation_runs',
          'control_commands','alerts','device_profile']
# Ten planned training tasks plus 32 explicitly non-trained support capabilities.
RULE_CAPS = [
 ('latest_readings','Số đo mới nhất','sensor_readings'),('sensor_history','Chuỗi số đo theo thời gian','sensor_readings'),
 ('sensor_extrema','Giá trị cao nhất và thấp nhất','sensor_readings'),('sensor_trend','Thay đổi số đo đầu và cuối kỳ','sensor_readings'),
 ('sensor_freshness','Độ mới dữ liệu','sensor_readings'),('sensor_quality','Chất lượng cảm biến','sensor_readings'),
 ('threshold_check','So sánh ngưỡng đã cấu hình','sensor_readings'),('connection_status','Kết nối tủ hiện tại','device_status'),
 ('power_diagnosis','Bằng chứng mất nguồn','connection_observer'),('mqtt_diagnosis','Bằng chứng gián đoạn MQTT','connection_observer'),
 ('pump_status','Trạng thái bơm','device_status'),('valve_status','Trạng thái van','device_status'),
 ('fertilizer_interlock','Lý do khóa bơm phân','device_status'),('output_mapping','Vai trò từng ngõ ra','device_profile'),
 ('irrigation_schedule','Lịch tưới đang cấu hình','irrigation_schedules'),('irrigation_history','Các ca tưới đã chạy','irrigation_runs'),
 ('water_totals','Tổng nước theo kỳ','irrigation_runs'),('fertilizer_totals','Tổng phân theo kênh','irrigation_runs'),
 ('period_comparison','So sánh hai kỳ tưới','irrigation_runs'),('command_audit','Ai gửi lệnh và kết quả','control_commands'),
 ('active_alerts','Cảnh báo theo bằng chứng','alerts'),('device_profile','Thông tin tủ và cảm biến lắp đặt','device_profile'),
 ('command_failure_summary','Đếm lệnh báo lỗi trong kỳ','control_commands'),
 ('missing_sensor_fields','Chỉ ra các chỉ số đang thiếu','sensor_readings'),
 ('status_age','Mốc giờ và độ trễ trạng thái','device_status'),
 ('counter_integrity','Loại số đếm thiếu hoặc reset khỏi tổng','irrigation_runs'),
 ('irrigation_duration','Thời lượng ca có đủ mốc giờ','irrigation_runs'),
 ('run_outcome_summary','Thống kê kết quả ca tưới','irrigation_runs'),
 ('timezone_periods','Lọc kỳ lịch theo múi giờ UTC cộng 7','device_profile'),
 ('export_lineage','Xuất CSV có mã khách hàng và tủ','device_profile'),
 ('device_access_scope','Kiểm tra quyền truy cập từng tủ','device_profile'),
 ('answer_provenance','Lưu công cụ và bằng chứng câu trả lời','device_profile'),
]

def catalog(models=None, available_groups=None):
    models = models or {}; groups=set(available_groups or [])
    items=[]
    for s in SPECS:
        m=models.get(s.name,{})
        items.append({'key':s.name,'title':s.title,'kind':'trained_model','status':m.get('status','BLOCKED'),
                      'scope':m.get('scope','simulation_only'),'reason':m.get('gate_reasons',['Chưa có artifact qua kiểm định']),
                      'horizon_minutes':s.horizon_minutes})
    for key,title,group in RULE_CAPS:
        items.append({'key':key,'title':title,'kind':'rule_or_query','status':'AVAILABLE' if group in groups else 'NO_DATA',
                      'scope':'available_device_data','reason':[] if group in groups else ['Nhóm dữ liệu chưa khả dụng'], 'group':group})
    return items
