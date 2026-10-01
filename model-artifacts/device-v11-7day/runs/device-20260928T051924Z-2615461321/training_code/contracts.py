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

# Only these capabilities are eligible for future evidence collection. The
# remaining historical specs stay in SPECS for backward-compatible reports but
# are not advertised or trained by the default runtime.
ACTIVE_MODEL_NAMES = (
    'moisture_forecast',
    'flow_fault_forecast',
    'sensor_fault_forecast',
)
ACTIVE_SPECS = tuple(spec for spec in SPECS if spec.name in ACTIVE_MODEL_NAMES)

# Agronomic serving policy for tomato production. These are the horizons the
# product understands, not a claim that a validated model already exists for
# every metric/horizon. The prediction endpoint remains closed until each
# requested model passes its data and validation gates.
FORECAST_HORIZONS_BY_METRIC = {
    'temperature': [60,180,360,720,1440],
    'air_humidity': [60,180,360,720,1440],
    'soil_moisture': [60,180,360,720,1440],
    'light': [60,180,360,720,1440],
    'ec': [360,720,1440],
    'ph': [360,720,1440],
}
FORECAST_TIERS = [
    {'key':'immediate','from_minutes':0,'to_minutes':60,'purpose':'điều khiển tức thời và phát hiện bất thường'},
    {'key':'same_day','from_minutes':60,'to_minutes':360,'purpose':'quyết định tưới và điều chỉnh môi trường trong ngày'},
    {'key':'day_plan','from_minutes':360,'to_minutes':1440,'purpose':'chuẩn bị kế hoạch nửa ngày đến một ngày'},
]
METRICS = {
    'soil_moisture': ('độ ẩm đất','%'), 'temperature': ('nhiệt độ','°C'),
    'ec': ('EC','mS/cm'), 'ph': ('pH','pH'), 'air_humidity': ('độ ẩm không khí','%RH'),
    'light': ('ánh sáng','lux'),
    'flow_rate': ('lưu lượng','L/phút'), 'pressure': ('áp suất','bar'),
    'supply_voltage': ('điện áp nguồn','V'), 'rssi': ('cường độ sóng','dBm'),
}
GROUPS = ['sensor_readings','device_status','irrigation_schedules','irrigation_runs',
          'control_commands','alerts','device_profile']
# Farmer-facing capabilities are intentionally grouped by the six company data
# domains. Fine-grained operations remain implementation details, not products
# or "AI capabilities" shown to farmers.
RULE_CAPS = [
 ('sensor_data','Số đo cảm biến','sensor_readings'),
 ('device_status','Trạng thái thiết bị','device_status'),
 ('irrigation_schedule','Lịch tưới','irrigation_schedules'),
 ('irrigation_history','Lịch sử tưới, tổng nước và tổng phân','irrigation_runs'),
 ('command_audit','Nhật ký lệnh điều khiển','control_commands'),
 ('alerts','Cảnh báo và sự kiện kết nối','alerts'),
]

def catalog(models=None, available_groups=None, include_legacy=False):
    models = models or {}; groups=set(available_groups or [])
    items=[]
    specs = SPECS if include_legacy else ACTIVE_SPECS
    for s in specs:
        m=models.get(s.name,{})
        items.append({'key':s.name,'title':s.title,'kind':'trained_model','status':m.get('status','BLOCKED'),
                      'scope':m.get('scope','simulation_only'),'reason':m.get('gate_reasons',['Chưa có artifact qua kiểm định']),
                      'horizon_minutes':s.horizon_minutes})
    for key,title,group in RULE_CAPS:
        items.append({'key':key,'title':title,'kind':'rule_or_query','status':'AVAILABLE' if group in groups else 'NO_DATA',
                      'scope':'available_device_data','reason':[] if group in groups else ['Nhóm dữ liệu chưa khả dụng'], 'group':group})
    return items
