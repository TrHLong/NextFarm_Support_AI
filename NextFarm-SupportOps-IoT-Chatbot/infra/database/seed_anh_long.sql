-- NextFarm SupportOps - seed data for Anh Long scenario
-- Run after infra/database/nextfarm_supportops_schema.sql
BEGIN;

INSERT INTO identity.roles(role_id, role_name, description) VALUES
 ('role_customer','customer','Khách hàng/chủ vườn'),
 ('role_technician','technician','Nhân viên kỹ thuật hỗ trợ'),
 ('role_manager','manager','Quản lý hỗ trợ'),
 ('role_admin','admin','Quản trị hệ thống')
ON CONFLICT (role_id) DO UPDATE SET description=EXCLUDED.description;

INSERT INTO identity.permissions(permission_id, permission_code, description) VALUES
 ('perm_read_farm_data','read_farm_data','Đọc dữ liệu vườn được phân quyền'),
 ('perm_request_control','request_control','Yêu cầu điều khiển thiết bị dạng lệnh nháp'),
 ('perm_manage_ticket','manage_ticket','Tiếp nhận và xử lý ticket'),
 ('perm_manage_knowledge','manage_knowledge','Quản lý kho tri thức')
ON CONFLICT (permission_id) DO UPDATE SET description=EXCLUDED.description;

INSERT INTO identity.user_accounts(user_id, display_name, phone, email, user_type, status) VALUES
 ('user_anh_long','Anh Long','0327555203','long.demo@example.local','customer','active'),
 ('user_tech_01','Kỹ thuật viên NextFarm 01','0902243822','tech01@example.local','technician','active'),
 ('user_manager_01','Quản lý hỗ trợ NextFarm','19006129','manager@example.local','manager','active')
ON CONFLICT (user_id) DO UPDATE SET display_name=EXCLUDED.display_name, phone=EXCLUDED.phone, user_type=EXCLUDED.user_type, status=EXCLUDED.status;

INSERT INTO identity.user_external_identities(external_identity_id, user_id, provider, provider_user_id, verified) VALUES
 ('ext_phone_anh_long','user_anh_long','phone','0327555203',true),
 ('ext_web_anh_long','user_anh_long','web_demo','demo_anh_long',true),
 ('ext_zalo_anh_long','user_anh_long','zalo_oa','zalo_demo_anh_long',true)
ON CONFLICT (provider, provider_user_id) DO UPDATE SET user_id=EXCLUDED.user_id, verified=EXCLUDED.verified;

INSERT INTO identity.user_roles(user_id, role_id) VALUES
 ('user_anh_long','role_customer'),('user_tech_01','role_technician'),('user_manager_01','role_manager')
ON CONFLICT DO NOTHING;

INSERT INTO knowledge.product_modules(module_id, module_name, module_slug, purpose_vi, public_url) VALUES
 ('mod_gis','GIS','gis','Bản đồ lô thửa, diện tích, vị trí thiết bị và khu canh tác.','https://nextfarm.vn/nen-tang/gis'),
 ('mod_irrigation','Tưới thông minh','tuoi-thong-minh','Tự động tưới theo lịch, cảm biến và điều khiển từ xa.','https://nextfarm.vn/nen-tang/tuoi-thong-minh'),
 ('mod_nmc','NMC','nmc','Quan trắc vi khí hậu tại vườn.','https://nextfarm.vn/nen-tang/nmc'),
 ('mod_fertikit','Fertikit','fertikit','Châm phân tự động theo EC/pH và công thức dinh dưỡng.','https://nextfarm.vn/nen-tang/fertikit'),
 ('mod_management','Management','management','Quản lý nhật ký canh tác, vật tư, công việc và hồ sơ VietGAP.','https://nextfarm.vn/nen-tang/management'),
 ('mod_yield','Yield','san-luong','Theo dõi và dự báo sản lượng.','https://nextfarm.vn/nen-tang/san-luong'),
 ('mod_qr','QR Check','qr-check','Truy xuất nguồn gốc nông sản.','https://nextfarm.vn/nen-tang/qr-check'),
 ('mod_ai_disease','AI sâu bệnh','ai-sau-benh','Nhận diện sâu bệnh qua ảnh và hỗ trợ xử lý sớm.','https://nextfarm.vn/nen-tang/ai-sau-benh'),
 ('mod_weather','Weather','weather','Dự báo thời tiết vi mô theo vị trí lô thửa.','https://nextfarm.vn/nen-tang/weather')
ON CONFLICT (module_id) DO UPDATE SET purpose_vi=EXCLUDED.purpose_vi, public_url=EXCLUDED.public_url;

INSERT INTO knowledge.knowledge_sources(source_id, source_type, title, url, owner, trust_level) VALUES
 ('src_nextfarm_public_platforms','website','Các trang nền tảng công khai của NextFarm','https://nextfarm.vn/','NextFarm public website','reviewed'),
 ('src_company_chatbot_pdf','company_pdf','Đề bài Chatbot NextFarm 31/07/2026',NULL,'NextFarm','reviewed'),
 ('src_supportops_demo_runbook','runbook','Runbook demo SupportOps cho Anh Long',NULL,'PoC team','reviewed')
ON CONFLICT (source_id) DO UPDATE SET title=EXCLUDED.title, trust_level=EXCLUDED.trust_level;

INSERT INTO knowledge.knowledge_articles(article_id, source_id, module_id, title, topic, body_vi, status, reviewer, version) VALUES
 ('art_platform_ecosystem','src_nextfarm_public_platforms',NULL,'NextFarm là hệ sinh thái nông nghiệp số','platform_ecosystem','NextFarm kết nối GIS, Tưới thông minh, NMC, Fertikit, Management, Yield, QR Check, AI sâu bệnh và Weather. Các module chia sẻ dữ liệu để hỗ trợ canh tác, vận hành, chứng nhận và truy xuất.','approved','PoC team',1),
 ('art_irrigation_intro','src_nextfarm_public_platforms','mod_irrigation','Tưới thông minh hoạt động như thế nào','irrigation','Tưới thông minh dùng lịch tưới, cảm biến độ ẩm đất, trạng thái van/bơm và dữ liệu thời tiết để tưới đúng khu, đúng thời điểm. Lợi ích là giảm công tưới, tiết kiệm nước và lưu lịch sử phục vụ quản lý.','approved','PoC team',1),
 ('art_nmc_intro','src_nextfarm_public_platforms','mod_nmc','NMC quan trắc vi khí hậu','nmc','NMC đo vi khí hậu tại vườn như nhiệt độ, độ ẩm không khí, ánh sáng, mưa/gió. Dữ liệu này giúp cảnh báo stress nhiệt, hỗ trợ dự báo sâu bệnh và tối ưu tưới.','approved','PoC team',1),
 ('art_fertikit_intro','src_nextfarm_public_platforms','mod_fertikit','Fertikit châm phân tự động','fertigation','Fertikit châm dinh dưỡng theo công thức EC/pH đã cấu hình. Chatbot chỉ giải thích nguyên lý và cảnh báo, không tự kê công thức phân khi thiếu dữ liệu cây trồng, giai đoạn và phác đồ kiểm duyệt.','approved','PoC team',1),
 ('art_gis_intro','src_nextfarm_public_platforms','mod_gis','GIS là nền để hiểu khu/lô','gis','GIS định danh lô thửa, diện tích, khu A/B/C và vị trí thiết bị. Nhờ GIS, chatbot hiểu câu hỏi theo ngữ cảnh vườn thay vì chỉ nhìn danh sách thiết bị rời rạc.','approved','PoC team',1),
 ('art_low_moisture_checklist','src_supportops_demo_runbook','mod_irrigation','Checklist khi khu vườn thiếu nước','troubleshooting_irrigation','Khi khu vườn thiếu nước, kiểm tra theo thứ tự: số đo độ ẩm mới nhất, xu hướng 1-2 giờ, lịch tưới gần nhất, van khu đó, bơm tổng, đường ống, đầu nhỏ giọt và vị trí cảm biến.','approved','PoC team',1),
 ('art_sensor_missing','src_supportops_demo_runbook','mod_irrigation','Cảm biến không gửi dữ liệu','iot_troubleshooting','Nếu cảm biến không gửi dữ liệu, kiểm tra nguồn thiết bị, dây RS485/Modbus, địa chỉ cảm biến, kết nối MQTT, Wi-Fi/Ethernet và thời điểm last_seen. Nếu dữ liệu quá cũ, chatbot phải báo dữ liệu trễ.','approved','PoC team',1)
ON CONFLICT (article_id) DO UPDATE SET body_vi=EXCLUDED.body_vi, status=EXCLUDED.status, updated_at=now();

INSERT INTO knowledge.knowledge_chunks(chunk_id, article_id, chunk_index, chunk_text_vi, token_count, status)
SELECT article_id || '_chunk_001', article_id, 1, body_vi, 120, 'approved'
FROM knowledge.knowledge_articles
WHERE article_id LIKE 'art_%'
ON CONFLICT (article_id, chunk_index) DO UPDATE SET chunk_text_vi=EXCLUDED.chunk_text_vi, status=EXCLUDED.status;

INSERT INTO knowledge.glossary_terms(term_id, term, explanation_vi, module_id) VALUES
 ('term_gis','GIS','Bản đồ số để quản lý lô thửa, diện tích và vị trí thiết bị.','mod_gis'),
 ('term_nmc','NMC','Node quan trắc vi khí hậu tại vườn.','mod_nmc'),
 ('term_ec','EC','Chỉ số nồng độ dinh dưỡng trong nước tưới.','mod_fertikit'),
 ('term_ph','pH','Chỉ số độ chua/kiềm của nước hoặc dung dịch dinh dưỡng.','mod_fertikit'),
 ('term_mqtt','MQTT','Giao thức để thiết bị IoT gửi dữ liệu lên server.','mod_irrigation'),
 ('term_modbus','Modbus','Giao thức đọc cảm biến công nghiệp qua RS485.','mod_irrigation')
ON CONFLICT (term_id) DO UPDATE SET explanation_vi=EXCLUDED.explanation_vi;

INSERT INTO knowledge.local_language_aliases(alias_id, alias_text, normalized_text, meaning, region, confidence) VALUES
 ('alias_bec','béc','dau nho giot','Đầu nhỏ giọt hoặc đầu tưới ngoài vườn','Lâm Đồng',0.95),
 ('alias_van_li','van lì','van khong dong mo','Van không đóng/mở đúng lệnh','Lâm Đồng',0.90),
 ('alias_dat_kho','đất khô','do am dat thap','Độ ẩm đất thấp hoặc bề mặt luống khô','Lâm Đồng',0.90),
 ('alias_cay_heo','cây héo','stress thieu nuoc hoac nhiet','Cây có thể thiếu nước hoặc bị stress nhiệt','Lâm Đồng',0.85)
ON CONFLICT (alias_id) DO UPDATE SET meaning=EXCLUDED.meaning;

INSERT INTO farm.crops(crop_id, crop_name, crop_group, notes) VALUES
 ('crop_tomato_greenhouse','Cà chua nhà màng','rau quả','Cây giá trị cao, nhạy với nước, EC/pH và vi khí hậu'),
 ('crop_leafy_vegetable','Rau ăn lá','rau','Dùng cho tư vấn khách mới vườn rau 1 ha')
ON CONFLICT (crop_id) DO UPDATE SET crop_name=EXCLUDED.crop_name, notes=EXCLUDED.notes;

INSERT INTO farm.farms(farm_id, farm_name, owner_user_id, region, address, area_ha, farm_type) VALUES
 ('farm_lamdong_01','Trang trại Lâm Đồng 01','user_anh_long','Lâm Đồng','Đơn Dương, Lâm Đồng',1.80,'greenhouse')
ON CONFLICT (farm_id) DO UPDATE SET farm_name=EXCLUDED.farm_name, area_ha=EXCLUDED.area_ha;

INSERT INTO identity.farm_memberships(farm_id, user_id, farm_role, can_read_data, can_request_control) VALUES
 ('farm_lamdong_01','user_anh_long','owner',true,true),
 ('farm_lamdong_01','user_tech_01','technician',true,false),
 ('farm_lamdong_01','user_manager_01','viewer',true,false)
ON CONFLICT (farm_id,user_id) DO UPDATE SET can_read_data=EXCLUDED.can_read_data, can_request_control=EXCLUDED.can_request_control;

INSERT INTO farm.plot_zones(zone_id, farm_id, zone_code, zone_name, crop_id, area_ha, geometry_json, target_moisture_min, target_moisture_max) VALUES
 ('zone_lamdong_a','farm_lamdong_01','A','Khu A - luống đầu nhà màng','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"A"}'::jsonb,55,70),
 ('zone_lamdong_b','farm_lamdong_01','B','Khu B - giữa nhà màng','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"B"}'::jsonb,55,70),
 ('zone_lamdong_c','farm_lamdong_01','C','Khu C - luống cuối nhà màng','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"C"}'::jsonb,55,70),
 ('zone_lamdong_d','farm_lamdong_01','D','Khu D - nhà màng phụ','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"D"}'::jsonb,55,70),
 ('zone_lamdong_e','farm_lamdong_01','E','Khu E - khu thử nghiệm','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"E"}'::jsonb,55,70),
 ('zone_lamdong_f','farm_lamdong_01','F','Khu F - khu cuối luống','crop_tomato_greenhouse',0.30,'{"type":"Polygon","demo":"F"}'::jsonb,55,70)
ON CONFLICT (zone_id) DO UPDATE SET zone_name=EXCLUDED.zone_name, target_moisture_min=EXCLUDED.target_moisture_min, target_moisture_max=EXCLUDED.target_moisture_max;

INSERT INTO farm.crop_cycles(cycle_id, farm_id, crop_id, start_date, expected_harvest_date, growth_stage, status) VALUES
 ('cycle_lamdong_tomato_2026_08','farm_lamdong_01','crop_tomato_greenhouse',DATE '2026-07-15',DATE '2026-10-20','ra hoa - dau trai','active')
ON CONFLICT (cycle_id) DO UPDATE SET growth_stage=EXCLUDED.growth_stage, status=EXCLUDED.status;

INSERT INTO iot.devices(device_id, farm_id, zone_id, device_type, model_name, firmware_version, connectivity, installed_at, status) VALUES
 ('dev_ctrl_4p_01','farm_lamdong_01',NULL,'esp32_controller','NextFarm ESP32 4 cổng','fw-1.8.0-demo','wifi',now()-interval '20 days','active'),
 ('dev_ctrl_3p_02','farm_lamdong_01',NULL,'esp32_controller','NextFarm ESP32 3 cổng','fw-1.8.0-demo','ethernet',now()-interval '20 days','active'),
 ('dev_nmc_01','farm_lamdong_01','zone_lamdong_b','nmc','NextFarm NMC node','nmc-2.1.0-demo','wifi',now()-interval '19 days','active'),
 ('dev_fertikit_01','farm_lamdong_01',NULL,'fertikit','NextFarm Fertikit','fertikit-1.4.0-demo','ethernet',now()-interval '18 days','active')
ON CONFLICT (device_id) DO UPDATE SET status=EXCLUDED.status, firmware_version=EXCLUDED.firmware_version;

INSERT INTO iot.device_ports(port_id, device_id, zone_id, port_number, port_name, port_type, normally_open) VALUES
 ('port_ctrl01_1','dev_ctrl_4p_01','zone_lamdong_a',1,'Van tưới khu A','valve',false),
 ('port_ctrl01_2','dev_ctrl_4p_01','zone_lamdong_b',2,'Van tưới khu B','valve',false),
 ('port_ctrl01_3','dev_ctrl_4p_01','zone_lamdong_c',3,'Van tưới khu C','valve',false),
 ('port_ctrl01_4','dev_ctrl_4p_01','zone_lamdong_d',4,'Van tưới khu D','valve',false),
 ('port_ctrl02_1','dev_ctrl_3p_02','zone_lamdong_e',1,'Van tưới khu E','valve',false),
 ('port_ctrl02_2','dev_ctrl_3p_02','zone_lamdong_f',2,'Van tưới khu F','valve',false),
 ('port_ctrl02_3','dev_ctrl_3p_02',NULL,3,'Bơm tổng','pump',false),
 ('port_fertikit_1','dev_fertikit_01',NULL,1,'Van châm phân Denso','fertilizer_valve',false)
ON CONFLICT (port_id) DO UPDATE SET port_name=EXCLUDED.port_name, zone_id=EXCLUDED.zone_id;

INSERT INTO iot.sensors(sensor_id, device_id, zone_id, sensor_type, unit, modbus_address, status) VALUES
 ('sen_soil_a','dev_ctrl_4p_01','zone_lamdong_a','soil_moisture','%','1','active'),
 ('sen_soil_b','dev_ctrl_4p_01','zone_lamdong_b','soil_moisture','%','2','active'),
 ('sen_soil_c','dev_ctrl_4p_01','zone_lamdong_c','soil_moisture','%','3','active'),
 ('sen_soil_d','dev_ctrl_4p_01','zone_lamdong_d','soil_moisture','%','4','active'),
 ('sen_soil_e','dev_ctrl_3p_02','zone_lamdong_e','soil_moisture','%','5','suspect'),
 ('sen_soil_f','dev_ctrl_3p_02','zone_lamdong_f','soil_moisture','%','6','active'),
 ('sen_flow_main','dev_ctrl_3p_02',NULL,'flow','L','7','active'),
 ('sen_nmc_temp','dev_nmc_01','zone_lamdong_b','temperature','C','11','active'),
 ('sen_nmc_humidity','dev_nmc_01','zone_lamdong_b','humidity','%','12','active'),
 ('sen_fertikit_ec','dev_fertikit_01',NULL,'ec','mS/cm','21','active'),
 ('sen_fertikit_ph','dev_fertikit_01',NULL,'ph','pH','22','active')
ON CONFLICT (sensor_id) DO UPDATE SET status=EXCLUDED.status;

-- Time-series readings for last 24 hours, every 10 minutes for selected metrics.
INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_soil_a_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01','zone_lamdong_a','dev_ctrl_4p_01','sen_soil_a','soil_moisture', round((62+3*sin(extract(epoch from ts)/3600.0))::numeric,2), '%','ok','mqtt'
FROM generate_series(now()-interval '24 hours', now(), interval '10 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_soil_b_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01','zone_lamdong_b','dev_ctrl_4p_01','sen_soil_b','soil_moisture', round((49+2*sin(extract(epoch from ts)/2700.0))::numeric,2), '%','ok','mqtt'
FROM generate_series(now()-interval '24 hours', now(), interval '10 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_soil_e_old_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01','zone_lamdong_e','dev_ctrl_3p_02','sen_soil_e','soil_moisture', round((58+1.5*sin(extract(epoch from ts)/3600.0))::numeric,2), '%','late','mqtt'
FROM generate_series(now()-interval '30 hours', now()-interval '6 hours', interval '20 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_nmc_temp_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01','zone_lamdong_b','dev_nmc_01','sen_nmc_temp','temperature', round((25+7*greatest(0,sin((extract(hour from ts)-7)/12.0*3.14159)))::numeric,2), 'C','ok','mqtt'
FROM generate_series(now()-interval '24 hours', now(), interval '10 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_ec_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01',NULL,'dev_fertikit_01','sen_fertikit_ec','ec', round((1.8+0.15*sin(extract(epoch from ts)/5400.0))::numeric,2), 'mS/cm','ok','mqtt'
FROM generate_series(now()-interval '24 hours', now(), interval '30 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.sensor_readings(reading_id,timestamp_utc,farm_id,zone_id,device_id,sensor_id,metric_type,value,unit,quality,source)
SELECT 'read_ph_'||to_char(ts,'YYYYMMDDHH24MI'), ts, 'farm_lamdong_01',NULL,'dev_fertikit_01','sen_fertikit_ph','ph', round((6.2+0.12*sin(extract(epoch from ts)/7200.0))::numeric,2), 'pH','ok','mqtt'
FROM generate_series(now()-interval '24 hours', now(), interval '30 minutes') AS ts
ON CONFLICT (reading_id) DO NOTHING;

INSERT INTO iot.device_status_events(status_event_id,timestamp_utc,farm_id,device_id,port_id,online,running,last_seen_utc,raw_status,source) VALUES
 ('status_ctrl01_port1_latest',now(),'farm_lamdong_01','dev_ctrl_4p_01','port_ctrl01_1',true,false,now(),'{"signal":"good"}'::jsonb,'mqtt'),
 ('status_ctrl01_port2_latest',now(),'farm_lamdong_01','dev_ctrl_4p_01','port_ctrl01_2',true,true,now(),'{"signal":"good"}'::jsonb,'mqtt'),
 ('status_ctrl01_port3_latest',now(),'farm_lamdong_01','dev_ctrl_4p_01','port_ctrl01_3',true,false,now(),'{"signal":"good"}'::jsonb,'mqtt'),
 ('status_ctrl01_port4_latest',now(),'farm_lamdong_01','dev_ctrl_4p_01','port_ctrl01_4',true,false,now(),'{"signal":"good"}'::jsonb,'mqtt'),
 ('status_ctrl02_port1_stale',now()-interval '6 hours','farm_lamdong_01','dev_ctrl_3p_02','port_ctrl02_1',false,false,now()-interval '6 hours','{"signal":"lost"}'::jsonb,'mqtt'),
 ('status_ctrl02_port2_latest',now(),'farm_lamdong_01','dev_ctrl_3p_02','port_ctrl02_2',true,false,now(),'{"signal":"good"}'::jsonb,'mqtt'),
 ('status_ctrl02_pump_latest',now(),'farm_lamdong_01','dev_ctrl_3p_02','port_ctrl02_3',true,true,now(),'{"signal":"good"}'::jsonb,'mqtt')
ON CONFLICT (status_event_id) DO UPDATE SET timestamp_utc=EXCLUDED.timestamp_utc, online=EXCLUDED.online, running=EXCLUDED.running, last_seen_utc=EXCLUDED.last_seen_utc;

INSERT INTO iot.irrigation_schedules(schedule_id,farm_id,zone_id,port_id,schedule_name,start_time_local,duration_minutes,days_of_week,mode,enabled) VALUES
 ('sched_a_morning','farm_lamdong_01','zone_lamdong_a','port_ctrl01_1','Tưới sáng khu A',TIME '06:00',12,'mon,tue,wed,thu,fri,sat,sun','fixed_time',true),
 ('sched_b_morning','farm_lamdong_01','zone_lamdong_b','port_ctrl01_2','Tưới sáng khu B',TIME '06:20',12,'mon,tue,wed,thu,fri,sat,sun','fixed_time',true),
 ('sched_b_noon_sensor','farm_lamdong_01','zone_lamdong_b','port_ctrl01_2','Tưới bù khu B theo cảm biến',TIME '12:30',8,'mon,tue,wed,thu,fri,sat,sun','sensor_threshold',true)
ON CONFLICT (schedule_id) DO UPDATE SET duration_minutes=EXCLUDED.duration_minutes, enabled=EXCLUDED.enabled;

INSERT INTO iot.irrigation_runs(run_id,farm_id,zone_id,schedule_id,port_id,started_at,ended_at,duration_minutes,water_liters,status,source) VALUES
 ('run_a_today_morning','farm_lamdong_01','zone_lamdong_a','sched_a_morning','port_ctrl01_1',date_trunc('day',now())+interval '6 hours',date_trunc('day',now())+interval '6 hours 12 minutes',12,420.5,'completed','schedule'),
 ('run_b_today_morning','farm_lamdong_01','zone_lamdong_b','sched_b_morning','port_ctrl01_2',date_trunc('day',now())+interval '6 hours 20 minutes',date_trunc('day',now())+interval '6 hours 32 minutes',12,390.0,'completed','schedule'),
 ('run_b_today_noon','farm_lamdong_01','zone_lamdong_b','sched_b_noon_sensor','port_ctrl01_2',date_trunc('day',now())+interval '12 hours 30 minutes',NULL,NULL,NULL,'running','sensor_rule')
ON CONFLICT (run_id) DO UPDATE SET status=EXCLUDED.status, ended_at=EXCLUDED.ended_at;

INSERT INTO support.ticket_checklists(checklist_id,category,title_vi,module_id,active) VALUES
 ('chk_low_moisture','LOW_SOIL_MOISTURE','Checklist kiểm tra khu thiếu nước','mod_irrigation',true),
 ('chk_sensor_missing','SENSOR_MISSING','Checklist cảm biến không gửi dữ liệu','mod_irrigation',true),
 ('chk_heat_stress','HEAT_STRESS','Checklist stress nhiệt trong nhà màng','mod_nmc',true)
ON CONFLICT (checklist_id) DO UPDATE SET title_vi=EXCLUDED.title_vi, active=EXCLUDED.active;

INSERT INTO support.ticket_checklist_items(item_id,checklist_id,item_order,instruction_vi) VALUES
 ('chk_low_moisture_1','chk_low_moisture',1,'Xem độ ẩm mới nhất và xu hướng 1-2 giờ gần đây.'),
 ('chk_low_moisture_2','chk_low_moisture',2,'Kiểm tra lịch tưới gần nhất của khu đang cảnh báo.'),
 ('chk_low_moisture_3','chk_low_moisture',3,'Kiểm tra van khu đó có mở đúng không.'),
 ('chk_low_moisture_4','chk_low_moisture',4,'Kiểm tra bơm, áp lực đường ống và đầu nhỏ giọt.'),
 ('chk_sensor_missing_1','chk_sensor_missing',1,'Kiểm tra nguồn thiết bị và đèn trạng thái.'),
 ('chk_sensor_missing_2','chk_sensor_missing',2,'Kiểm tra dây RS485/Modbus và địa chỉ cảm biến.'),
 ('chk_sensor_missing_3','chk_sensor_missing',3,'Kiểm tra MQTT, Wi-Fi/Ethernet và last_seen.'),
 ('chk_heat_stress_1','chk_heat_stress',1,'Kiểm tra nhiệt độ NMC trong khung giờ trưa.'),
 ('chk_heat_stress_2','chk_heat_stress',2,'Kiểm tra thông gió, lưới che và lịch tưới làm mát nếu có.')
ON CONFLICT (item_id) DO UPDATE SET instruction_vi=EXCLUDED.instruction_vi;

INSERT INTO iot.alerts(alert_id,farm_id,zone_id,device_id,alert_type,severity,message_vi,status,suggested_checklist_id,source) VALUES
 ('alert_low_moisture_b_open','farm_lamdong_01','zone_lamdong_b','dev_ctrl_4p_01','LOW_SOIL_MOISTURE','medium','Độ ẩm đất khu B thấp hơn ngưỡng mục tiêu. Cần kiểm tra lịch tưới, van khu B hoặc đầu nhỏ giọt.','open','chk_low_moisture','rule_engine'),
 ('alert_sensor_e_stale','farm_lamdong_01','zone_lamdong_e','dev_ctrl_3p_02','SENSOR_STALE','high','Cảm biến độ ẩm khu E không gửi dữ liệu mới trong nhiều giờ.','open','chk_sensor_missing','rule_engine'),
 ('alert_nmc_heat_noon','farm_lamdong_01','zone_lamdong_b','dev_nmc_01','HEAT_STRESS','low','NMC ghi nhận nhiệt độ nhà màng tăng cao vào buổi trưa.','acknowledged','chk_heat_stress','rule_engine')
ON CONFLICT (alert_id) DO UPDATE SET message_vi=EXCLUDED.message_vi, status=EXCLUDED.status, severity=EXCLUDED.severity;

INSERT INTO support.support_tickets(ticket_id,conversation_id,user_id,lead_id,farm_id,zone_id,title,description,product_module_id,category,priority,status,assigned_to,first_response_at,resolved_at) VALUES
 ('ticket_resolved_drip_b',NULL,'user_anh_long',NULL,'farm_lamdong_01','zone_lamdong_b','Khu B thiếu nước sau ca tưới','Khu B giảm ẩm nhanh dù đã tưới sáng. Kiểm tra thấy một nhánh đầu nhỏ giọt bị nghẹt.','mod_irrigation','LOW_SOIL_MOISTURE','high','resolved','user_tech_01',now()-interval '6 days 50 minutes',now()-interval '6 days'),
 ('ticket_open_sensor_e',NULL,'user_anh_long',NULL,'farm_lamdong_01','zone_lamdong_e','Cảm biến khu E không gửi dữ liệu','Sensor độ ẩm khu E không có bản tin mới, cần kiểm tra nguồn và đường truyền RS485.','mod_irrigation','SENSOR_STALE','high','open','user_tech_01',NULL,NULL)
ON CONFLICT (ticket_id) DO UPDATE SET status=EXCLUDED.status, description=EXCLUDED.description;

INSERT INTO support.resolution_notes(resolution_id,ticket_id,root_cause,resolution_vi,reusable_for_knowledge,reviewed_by) VALUES
 ('res_drip_b_clogged','ticket_resolved_drip_b','Đầu nhỏ giọt bị nghẹt một nhánh khu B','Kỹ thuật viên vệ sinh lọc, xả đường ống nhánh khu B và kiểm tra lại lưu lượng. Sau xử lý, độ ẩm khu B tăng ổn định về ngưỡng mục tiêu.',true,'user_manager_01')
ON CONFLICT (resolution_id) DO UPDATE SET resolution_vi=EXCLUDED.resolution_vi, reusable_for_knowledge=EXCLUDED.reusable_for_knowledge;

INSERT INTO support.sla_policies(sla_policy_id,priority,first_response_minutes,resolution_minutes) VALUES
 ('sla_low','low',240,2880),('sla_normal','normal',120,1440),('sla_high','high',30,480),('sla_urgent','urgent',10,120)
ON CONFLICT (sla_policy_id) DO UPDATE SET first_response_minutes=EXCLUDED.first_response_minutes, resolution_minutes=EXCLUDED.resolution_minutes;

INSERT INTO ai.model_registry(model_id,model_name,model_type,version,status,artifact_uri) VALUES
 ('model_intent_vi_agri_v1','Vietnamese Agriculture Intent Classifier','intent','0.1.0','staging','models/intent_vi_agri/v0.1.0'),
 ('model_rag_rerank_v1','NextFarm Knowledge Reranker','rerank','0.1.0','staging','models/rag_rerank/v0.1.0'),
 ('model_moisture_forecast_v1','Moisture Forecast 1h','forecast','0.1.0','staging','models/moisture_forecast/v0.1.0'),
 ('model_alert_root_cause_v1','Alert Root Cause Ranker','alert_root_cause','0.1.0','staging','models/alert_root_cause/v0.1.0')
ON CONFLICT (model_id) DO UPDATE SET status=EXCLUDED.status, artifact_uri=EXCLUDED.artifact_uri;

INSERT INTO ai.dataset_versions(dataset_id,dataset_name,source_tables,version,row_count) VALUES
 ('ds_anh_long_seed_v1','Anh Long seed dataset',ARRAY['identity','farm','iot','knowledge','support'],'0.1.0',1)
ON CONFLICT (dataset_id) DO UPDATE SET row_count=EXCLUDED.row_count;

INSERT INTO ai.evaluation_sets(eval_set_id,name,purpose,expected_metric) VALUES
 ('eval_farm_data_accuracy_v1','Farm data question accuracy','Đo câu hỏi tra số liệu vườn đúng với dữ liệu gốc','accuracy >= 0.95'),
 ('eval_hallucination_guard_v1','Hallucination guard','Đo tỷ lệ bot nói không biết khi thiếu dữ liệu','hallucination_rate ~= 0'),
 ('eval_permission_leak_v1','Permission leakage','Đảm bảo không đọc dữ liệu vườn không thuộc quyền','leakage_count = 0'),
 ('eval_latency_v1','Response latency','Đo thời gian phản hồi trung bình','avg_latency_seconds < target')
ON CONFLICT (eval_set_id) DO UPDATE SET purpose=EXCLUDED.purpose;


-- Pre-sales lead scenario: khách mới hỏi làm vườn vải 50 m2
INSERT INTO identity.customer_leads(lead_id, full_name, phone, region, note, status) VALUES
 ('lead_vuon_vai_50m2','Khách mới - vườn vải 50m2','0987000050','Chưa rõ','Khách hỏi muốn xây dựng một vườn vải 50 m2, cần tư vấn bắt đầu thế nào.','temp')
ON CONFLICT (lead_id) DO UPDATE SET note=EXCLUDED.note, status=EXCLUDED.status;

INSERT INTO sales.lead_profiles(lead_profile_id, lead_id, full_name, phone, region, channel, lead_status, interest_level) VALUES
 ('lead_profile_vuon_vai_50m2','lead_vuon_vai_50m2','Khách mới - vườn vải 50m2','0987000050','Chưa rõ','web_chat','qualifying','considering')
ON CONFLICT (lead_profile_id) DO UPDATE SET interest_level=EXCLUDED.interest_level, lead_status=EXCLUDED.lead_status;

INSERT INTO sales.lead_requirements(requirement_id, lead_profile_id, crop_text, area_value, area_unit, cultivation_type, province_or_region, water_source, has_pump, business_goal, raw_message, extracted_confidence) VALUES
 ('req_vuon_vai_50m2','lead_profile_vuon_vai_50m2','vải hoặc cây/vườn khách gọi là vải',50,'m2','home_garden','chưa rõ','chưa rõ',NULL,'unknown','Tôi muốn xây dựng một vườn vải 50m2 thì cần xây thế nào?',0.72)
ON CONFLICT (requirement_id) DO UPDATE SET raw_message=EXCLUDED.raw_message, extracted_confidence=EXCLUDED.extracted_confidence;

INSERT INTO sales.lead_pain_points(pain_point_id, lead_profile_id, pain_point_code, description_vi, severity) VALUES
 ('pain_start_from_zero_50m2','lead_profile_vuon_vai_50m2','NEED_STARTING_PLAN','Khách chưa biết bắt đầu thiết kế vườn nhỏ như thế nào.', 'normal'),
 ('pain_need_irrigation_advice_50m2','lead_profile_vuon_vai_50m2','NEED_IRRIGATION_ADVICE','Khách cần tư vấn tưới phù hợp quy mô nhỏ, tránh đầu tư quá mức.', 'normal')
ON CONFLICT (pain_point_id) DO UPDATE SET description_vi=EXCLUDED.description_vi;

INSERT INTO sales.module_recommendations(recommendation_id, lead_profile_id, module_id, fit_level, reason_vi, created_by) VALUES
 ('rec_50m2_irrigation','lead_profile_vuon_vai_50m2','mod_irrigation','must_have','Quy mô 50 m2 nên bắt đầu từ tưới nhỏ giọt/phun cục bộ và điều khiển đơn giản để giảm công chăm sóc.', 'chatbot'),
 ('rec_50m2_management','lead_profile_vuon_vai_50m2','mod_management','recommended','Nếu khách muốn học vận hành bài bản, nhật ký canh tác giúp ghi lại lịch tưới, phân bón và quan sát cây.', 'chatbot'),
 ('rec_50m2_gis','lead_profile_vuon_vai_50m2','mod_gis','later','GIS hữu ích khi mở rộng diện tích hoặc cần quản lý nhiều lô; với 50 m2 chưa phải ưu tiên đầu tiên.', 'chatbot'),
 ('rec_50m2_nmc','lead_profile_vuon_vai_50m2','mod_nmc','later','NMC phù hợp hơn nếu làm nhà màng, cây giá trị cao hoặc muốn theo dõi vi khí hậu liên tục.', 'chatbot')
ON CONFLICT (recommendation_id) DO UPDATE SET fit_level=EXCLUDED.fit_level, reason_vi=EXCLUDED.reason_vi;

INSERT INTO sales.consultation_notes(consultation_note_id, lead_profile_id, conversation_id, note_type, content_vi) VALUES
 ('note_50m2_bot_advice','lead_profile_vuon_vai_50m2',NULL,'bot_advice','Bot tư vấn không bán quá mức: với 50 m2 nên bắt đầu từ tưới đơn giản, hỏi rõ cây trồng/vùng/nguồn nước/mục tiêu trước khi đề xuất thêm NMC, GIS hoặc QR.'),
 ('note_50m2_clarify','lead_profile_vuon_vai_50m2',NULL,'clarifying_question','Cần hỏi lại: khách nói vải là vải thiều/cây ăn quả hay vật liệu phủ? Ở tỉnh nào? Có nguồn nước và bơm chưa? Làm để gia đình hay kinh doanh?')
ON CONFLICT (consultation_note_id) DO UPDATE SET content_vi=EXCLUDED.content_vi;

INSERT INTO sales.opportunities(opportunity_id, lead_profile_id, title, stage, estimated_value_vnd, assigned_to, next_action_vi) VALUES
 ('opp_vuon_vai_50m2','lead_profile_vuon_vai_50m2','Tư vấn vườn nhỏ 50 m2 dùng tưới thông minh', 'new', NULL, 'user_manager_01', 'Gọi lại để xác minh cây trồng, địa điểm, nguồn nước và mục tiêu đầu tư.')
ON CONFLICT (opportunity_id) DO UPDATE SET stage=EXCLUDED.stage, next_action_vi=EXCLUDED.next_action_vi;

INSERT INTO sales.proposal_drafts(proposal_id, opportunity_id, lead_profile_id, proposal_summary_vi, module_plan_json, assumptions_json, status) VALUES
 ('proposal_vuon_vai_50m2','opp_vuon_vai_50m2','lead_profile_vuon_vai_50m2','Đề xuất sơ bộ: bắt đầu bằng tưới thông minh quy mô nhỏ, 1-2 khu tưới, ghi nhật ký Management. GIS/NMC/QR để giai đoạn sau nếu khách mở rộng hoặc sản xuất thương mại.', '[{"module":"Tưới thông minh","fit":"must_have"},{"module":"Management","fit":"recommended"},{"module":"GIS","fit":"later"},{"module":"NMC","fit":"later"}]'::jsonb, '{"area":"50m2","needs_clarification":["cây vải hay vật liệu vải", "tỉnh/khu vực", "nguồn nước", "mục tiêu"]}'::jsonb, 'draft')
ON CONFLICT (proposal_id) DO UPDATE SET proposal_summary_vi=EXCLUDED.proposal_summary_vi, module_plan_json=EXCLUDED.module_plan_json;
COMMIT;

