BEGIN;

-- Tài khoản demo
INSERT INTO user_db.users(user_id,username,password_hash,display_name,phone,email,role) VALUES
 ('farmer_long','nongdan.long','bootstrap_required','Anh Long','0327555203','long.demo@nextfarm.vn','farmer'),
 ('farmer_lan','nongdan.lan','bootstrap_required','Chị Lan','0901000002','lan.demo@nextfarm.vn','farmer'),
 ('farmer_minh','nongdan.minh','bootstrap_required','Anh Minh','0901000003','minh.demo@nextfarm.vn','farmer'),
 ('tech_01','kythuat.01','bootstrap_required','Kỹ thuật viên 01','0909000001','tech01@nextfarm.vn','technician')
ON CONFLICT (user_id) DO UPDATE SET display_name=EXCLUDED.display_name, password_hash=EXCLUDED.password_hash, status='active';

-- Ba vườn của ba nông dân
INSERT INTO farm_db.farms(farm_id,owner_user_id,farm_name,crop_name,region,address,area_ha,description) VALUES
 ('farm_long','farmer_long','Vườn cà chua nhà màng Anh Long','Cà chua','Lâm Đồng','Đức Trọng, Lâm Đồng',1.20,'Vườn demo có 3 khu, dữ liệu độ ẩm, EC, pH và hệ thống tưới.'),
 ('farm_lan','farmer_lan','Vườn sầu riêng Chị Lan','Sầu riêng','Đắk Lắk','Krông Pắc, Đắk Lắk',2.50,'Vườn demo có bộ điều khiển đang mất kết nối và lịch tưới bị ảnh hưởng.'),
 ('farm_minh','farmer_minh','Vườn rau ăn lá Anh Minh','Rau ăn lá','Đồng Tháp','Cao Lãnh, Đồng Tháp',0.80,'Vườn demo có van báo mở nhưng lưu lượng bằng 0.')
ON CONFLICT (farm_id) DO UPDATE SET farm_name=EXCLUDED.farm_name, description=EXCLUDED.description;

INSERT INTO user_db.farm_access(user_id,farm_id,access_role,can_read,can_support) VALUES
 ('farmer_long','farm_long','owner',true,false),
 ('farmer_lan','farm_lan','owner',true,false),
 ('farmer_minh','farm_minh','owner',true,false),
 ('tech_01','farm_long','technician',true,true),
 ('tech_01','farm_lan','technician',true,true),
 ('tech_01','farm_minh','technician',true,true)
ON CONFLICT (user_id,farm_id) DO UPDATE SET access_role=EXCLUDED.access_role, can_read=EXCLUDED.can_read, can_support=EXCLUDED.can_support;

INSERT INTO farm_db.zones(zone_id,farm_id,zone_code,zone_name,crop_name,area_ha,moisture_min,moisture_max,ec_min,ec_max,ph_min,ph_max) VALUES
 ('long_a','farm_long','A','Khu cà chua A','Cà chua',0.40,55,70,1.5,2.5,5.5,6.8),
 ('long_b','farm_long','B','Khu cà chua B','Cà chua',0.40,55,70,1.5,2.5,5.5,6.8),
 ('long_c','farm_long','C','Khu cà chua C','Cà chua',0.40,55,70,1.5,2.5,5.5,6.8),
 ('lan_a','farm_lan','A','Khu sầu riêng A','Sầu riêng',1.25,45,65,NULL,NULL,5.0,6.5),
 ('lan_b','farm_lan','B','Khu sầu riêng B','Sầu riêng',1.25,45,65,NULL,NULL,5.0,6.5),
 ('minh_a','farm_minh','A','Khu rau A','Rau ăn lá',0.40,60,75,1.0,2.0,5.5,7.0),
 ('minh_b','farm_minh','B','Khu rau B','Rau ăn lá',0.40,60,75,1.0,2.0,5.5,7.0)
ON CONFLICT (zone_id) DO UPDATE SET moisture_min=EXCLUDED.moisture_min, moisture_max=EXCLUDED.moisture_max;

-- Thiết bị và cổng
INSERT INTO farm_db.devices(device_id,farm_id,zone_id,device_name,device_type,model_name,firmware_version,connectivity,installed_at) VALUES
 ('dev_long_ctrl','farm_long',NULL,'Bộ điều khiển tưới 4 cổng','controller','NextFarm ESP32-4','2.1.0','ethernet',now()-interval '180 days'),
 ('dev_long_sensor','farm_long',NULL,'Gateway cảm biến nhà màng','sensor_gateway','NextFarm Sensor Hub','1.8.2','wifi',now()-interval '160 days'),
 ('dev_lan_ctrl','farm_lan',NULL,'Bộ điều khiển tưới sầu riêng','controller','NextFarm ESP32-4','2.0.4','wifi',now()-interval '240 days'),
 ('dev_minh_ctrl','farm_minh',NULL,'Bộ điều khiển tưới rau','controller','NextFarm ESP32-3','2.1.0','ethernet',now()-interval '90 days'),
 ('dev_minh_sensor','farm_minh',NULL,'Gateway cảm biến rau','sensor_gateway','NextFarm Sensor Hub','1.8.2','wifi',now()-interval '90 days')
ON CONFLICT (device_id) DO UPDATE SET firmware_version=EXCLUDED.firmware_version;

INSERT INTO farm_db.device_ports(port_id,device_id,zone_id,port_number,port_name,port_type) VALUES
 ('long_p1','dev_long_ctrl','long_a',1,'Van khu A','valve'),
 ('long_p2','dev_long_ctrl','long_b',2,'Van khu B','valve'),
 ('long_p3','dev_long_ctrl','long_c',3,'Van khu C','valve'),
 ('long_p4','dev_long_ctrl',NULL,4,'Bơm chính','pump'),
 ('lan_p1','dev_lan_ctrl','lan_a',1,'Van khu A','valve'),
 ('lan_p2','dev_lan_ctrl','lan_b',2,'Van khu B','valve'),
 ('lan_p4','dev_lan_ctrl',NULL,4,'Bơm chính','pump'),
 ('minh_p1','dev_minh_ctrl','minh_a',1,'Van khu A','valve'),
 ('minh_p2','dev_minh_ctrl','minh_b',2,'Van khu B','valve'),
 ('minh_p3','dev_minh_ctrl',NULL,3,'Bơm chính','pump')
ON CONFLICT (port_id) DO UPDATE SET port_name=EXCLUDED.port_name;

-- Cảm biến
INSERT INTO farm_db.sensors(sensor_id,farm_id,zone_id,device_id,sensor_name,metric_type,unit) VALUES
 ('s_long_a_m','farm_long','long_a','dev_long_sensor','Độ ẩm đất A','soil_moisture','%'),
 ('s_long_b_m','farm_long','long_b','dev_long_sensor','Độ ẩm đất B','soil_moisture','%'),
 ('s_long_c_m','farm_long','long_c','dev_long_sensor','Độ ẩm đất C','soil_moisture','%'),
 ('s_long_a_t','farm_long','long_a','dev_long_sensor','Nhiệt độ A','temperature','°C'),
 ('s_long_a_ec','farm_long','long_a','dev_long_sensor','EC A','ec','mS/cm'),
 ('s_long_a_ph','farm_long','long_a','dev_long_sensor','pH A','ph','pH'),
 ('s_lan_a_m','farm_lan','lan_a','dev_lan_ctrl','Độ ẩm đất A','soil_moisture','%'),
 ('s_lan_b_m','farm_lan','lan_b','dev_lan_ctrl','Độ ẩm đất B','soil_moisture','%'),
 ('s_minh_a_m','farm_minh','minh_a','dev_minh_sensor','Độ ẩm đất A','soil_moisture','%'),
 ('s_minh_b_m','farm_minh','minh_b','dev_minh_sensor','Độ ẩm đất B','soil_moisture','%'),
 ('s_minh_a_flow','farm_minh','minh_a','dev_minh_ctrl','Lưu lượng khu A','flow_rate','L/phút')
ON CONFLICT (sensor_id) DO UPDATE SET active=true;

-- V9 standalone không seed telemetry/device-status. Simulator sẽ tạo runtime mới sau reference bootstrap.

INSERT INTO farm_db.irrigation_schedules(schedule_id,farm_id,zone_id,port_id,schedule_name,start_time,duration_minutes,days_of_week,enabled) VALUES
 ('sch_long_a','farm_long','long_a','long_p1','Tưới sáng khu A','06:00',20,'1,2,3,4,5,6,7',true),
 ('sch_long_b','farm_long','long_b','long_p2','Tưới sáng khu B','06:25',20,'1,2,3,4,5,6,7',true),
 ('sch_lan_a','farm_lan','lan_a','lan_p1','Tưới sáng sầu riêng A','05:30',30,'1,3,5',true),
 ('sch_minh_a','farm_minh','minh_a','minh_p1','Tưới rau khu A','05:45',15,'1,2,3,4,5,6,7',true)
ON CONFLICT (schedule_id) DO UPDATE SET enabled=EXCLUDED.enabled;

-- V9 standalone không seed irrigation_runs/alerts; runtime sẽ sinh theo trạng thái mô phỏng.

-- Kho tri thức và checklist
INSERT INTO knowledge_db.articles(article_id,title,category,body_vi,keywords,source_name,approved_by) VALUES
 ('art_moisture','Cách hiểu độ ẩm đất','SENSOR','Độ ẩm phải được so sánh với ngưỡng của từng khu và cây trồng. Khi dữ liệu quá 30 phút, chatbot phải ghi rõ dữ liệu đã cũ và không coi đó là số liệu hiện tại.','độ ẩm đất thấp cao cảm biến dữ liệu cũ','Tài liệu kỹ thuật NextFarm','tech_01'),
 ('art_offline','Xử lý thiết bị mất kết nối','DEVICE','Kiểm tra nguồn điện, đèn trạng thái, cáp mạng hoặc Wi-Fi, sau đó kiểm tra thời điểm last_seen. Không kết luận thiết bị đang hoạt động nếu bản tin trạng thái đã quá cũ.','offline mất kết nối wifi ethernet nguồn last seen','Tài liệu kỹ thuật NextFarm','tech_01'),
 ('art_no_flow','Van mở nhưng không có lưu lượng','IRRIGATION','Kiểm tra bơm, nguồn nước, van khóa cơ, bộ lọc, đường ống và cảm biến lưu lượng. Không tiếp tục tưới kéo dài khi lưu lượng bằng 0.','van mở lưu lượng 0 bơm đường ống lọc','Kinh nghiệm SupportOps','tech_01'),
 ('art_ticket','Quy trình tiếp nhận ticket','SUPPORT','Ticket được xếp theo mức ưu tiên; trong cùng mức ưu tiên, ticket tạo trước được tiếp nhận trước. Kỹ thuật viên phản hồi, thực hiện checklist, cập nhật trạng thái và ghi nguyên nhân gốc khi đóng.','ticket ưu tiên fifo phản hồi checklist đóng','Quy trình SupportOps','tech_01')
ON CONFLICT (article_id) DO UPDATE SET body_vi=EXCLUDED.body_vi, keywords=EXCLUDED.keywords;

INSERT INTO knowledge_db.checklists(checklist_code,category,title) VALUES
 ('LOW_MOISTURE','LOW_SOIL_MOISTURE','Checklist kiểm tra độ ẩm thấp'),
 ('SENSOR_STALE','SENSOR_STALE','Checklist kiểm tra cảm biến không cập nhật'),
 ('DEVICE_OFFLINE','DEVICE_OFFLINE','Checklist kiểm tra thiết bị mất kết nối'),
 ('NO_FLOW','NO_FLOW','Checklist kiểm tra van mở nhưng không có lưu lượng'),
 ('GENERAL','GENERAL','Checklist kiểm tra sự cố ban đầu')
ON CONFLICT (checklist_code) DO UPDATE SET title=EXCLUDED.title;

INSERT INTO knowledge_db.checklist_items(item_id,checklist_code,item_order,instruction) VALUES
 ('lm_1','LOW_MOISTURE',1,'Kiểm tra số đo mới nhất và thời gian ghi nhận.'),
 ('lm_2','LOW_MOISTURE',2,'Kiểm tra ca tưới gần nhất của khu.'),
 ('lm_3','LOW_MOISTURE',3,'Kiểm tra trạng thái van và bơm.'),
 ('lm_4','LOW_MOISTURE',4,'Kiểm tra bộ lọc, đường ống và đầu nhỏ giọt.'),
 ('ss_1','SENSOR_STALE',1,'Kiểm tra nguồn cấp và đèn trạng thái cảm biến.'),
 ('ss_2','SENSOR_STALE',2,'Kiểm tra dây RS485/Modbus và địa chỉ cảm biến.'),
 ('ss_3','SENSOR_STALE',3,'Kiểm tra kết nối gateway, MQTT và thời điểm last_seen.'),
 ('do_1','DEVICE_OFFLINE',1,'Kiểm tra nguồn điện bộ điều khiển.'),
 ('do_2','DEVICE_OFFLINE',2,'Kiểm tra Ethernet hoặc Wi-Fi tại vườn.'),
 ('do_3','DEVICE_OFFLINE',3,'Khởi động lại thiết bị theo quy trình kỹ thuật nếu được phép.'),
 ('nf_1','NO_FLOW',1,'Kiểm tra nguồn nước và mực nước bể.'),
 ('nf_2','NO_FLOW',2,'Kiểm tra bơm có chạy thực tế hay không.'),
 ('nf_3','NO_FLOW',3,'Kiểm tra van khóa cơ, bộ lọc và đường ống.'),
 ('nf_4','NO_FLOW',4,'Kiểm tra cảm biến lưu lượng và dây tín hiệu.'),
 ('g_1','GENERAL',1,'Xác nhận vườn, khu và thời điểm xảy ra sự cố.'),
 ('g_2','GENERAL',2,'Kiểm tra cảnh báo và dữ liệu thiết bị mới nhất.'),
 ('g_3','GENERAL',3,'Ghi lại ảnh hoặc mô tả hiện trường nếu có.')
ON CONFLICT (item_id) DO UPDATE SET instruction=EXCLUDED.instruction;

INSERT INTO knowledge_db.resolved_cases(case_id,source_ticket_id,category,title,symptoms,root_cause,resolution,keywords,reusable,reviewed_by) VALUES
 ('case_drip_clog',NULL,'LOW_MOISTURE','Khu tưới vẫn khô sau ca tưới','Độ ẩm thấp dù lịch tưới đã chạy; lưu lượng giảm.','Một nhánh đầu nhỏ giọt bị nghẹt.','Vệ sinh bộ lọc, xả đường ống và thay đầu nhỏ giọt nghẹt; theo dõi lại độ ẩm sau 30 phút.','độ ẩm thấp lịch tưới đầu nhỏ giọt nghẹt lưu lượng',true,'tech_01'),
 ('case_controller_wifi',NULL,'DEVICE_OFFLINE','Bộ điều khiển mất kết nối Wi-Fi','Thiết bị offline, không nhận lệnh và lịch tưới không chạy.','Router tại vườn mất nguồn.','Cấp nguồn lại router, kiểm tra thiết bị kết nối và xác nhận bản tin mới trước khi chạy bù lịch tưới.','offline wifi router mất nguồn lịch tưới',true,'tech_01')
ON CONFLICT (case_id) DO UPDATE SET resolution=EXCLUDED.resolution;

-- V9 standalone khởi tạo hàng đợi ticket rỗng; ticket phát sinh từ người dùng/cảnh báo runtime.


COMMIT;

-- Bổ sung cảm biến đầy đủ hơn cho cả 3 nông dân để bộ sinh dữ liệu và AI có lịch sử đa chỉ số.
INSERT INTO farm_db.sensors(sensor_id,farm_id,zone_id,device_id,sensor_name,metric_type,unit) VALUES
 ('s_long_b_t','farm_long','long_b','dev_long_sensor','Nhiệt độ B','temperature','°C'),
 ('s_long_b_ec','farm_long','long_b','dev_long_sensor','EC B','ec','mS/cm'),
 ('s_long_b_ph','farm_long','long_b','dev_long_sensor','pH B','ph','pH'),
 ('s_long_a_flow','farm_long','long_a','dev_long_ctrl','Lưu lượng khu A','flow_rate','L/phút'),
 ('s_lan_a_t','farm_lan','lan_a','dev_lan_ctrl','Nhiệt độ A','temperature','°C'),
 ('s_lan_a_ec','farm_lan','lan_a','dev_lan_ctrl','EC A','ec','mS/cm'),
 ('s_lan_a_ph','farm_lan','lan_a','dev_lan_ctrl','pH A','ph','pH'),
 ('s_lan_a_flow','farm_lan','lan_a','dev_lan_ctrl','Lưu lượng khu A','flow_rate','L/phút'),
 ('s_minh_a_t','farm_minh','minh_a','dev_minh_sensor','Nhiệt độ A','temperature','°C'),
 ('s_minh_a_ec','farm_minh','minh_a','dev_minh_sensor','EC A','ec','mS/cm'),
 ('s_minh_a_ph','farm_minh','minh_a','dev_minh_sensor','pH A','ph','pH'),
 ('s_minh_b_flow','farm_minh','minh_b','dev_minh_ctrl','Lưu lượng khu B','flow_rate','L/phút')
ON CONFLICT (sensor_id) DO UPDATE SET active=true;

-- ============================================================
-- V5: dữ liệu khí hậu, kho tri thức web có nguồn và hồ sơ cây trồng
-- ============================================================
UPDATE farm_db.farms SET latitude=11.7356, longitude=108.3733, cultivation_type='greenhouse', soil_texture='đất đỏ bazan/giá thể', drainage='well' WHERE farm_id='farm_long';
UPDATE farm_db.farms SET latitude=12.7333, longitude=108.4500, cultivation_type='open_field', soil_texture='đất đỏ bazan', drainage='well' WHERE farm_id='farm_lan';
UPDATE farm_db.farms SET latitude=10.4938, longitude=105.6882, cultivation_type='open_field', soil_texture='phù sa', drainage='moderate' WHERE farm_id='farm_minh';

INSERT INTO farm_db.sensors(sensor_id,farm_id,zone_id,device_id,sensor_name,metric_type,unit) VALUES
 ('s_long_a_h','farm_long','long_a','dev_long_sensor','Độ ẩm không khí A','air_humidity','%RH'),
 ('s_long_b_t','farm_long','long_b','dev_long_sensor','Nhiệt độ B','temperature','°C'),
 ('s_long_b_h','farm_long','long_b','dev_long_sensor','Độ ẩm không khí B','air_humidity','%RH'),
 ('s_lan_a_t','farm_lan','lan_a','dev_lan_ctrl','Nhiệt độ A','temperature','°C'),
 ('s_lan_a_h','farm_lan','lan_a','dev_lan_ctrl','Độ ẩm không khí A','air_humidity','%RH'),
 ('s_minh_a_t','farm_minh','minh_a','dev_minh_sensor','Nhiệt độ A','temperature','°C'),
 ('s_minh_a_h','farm_minh','minh_a','dev_minh_sensor','Độ ẩm không khí A','air_humidity','%RH')
ON CONFLICT (sensor_id) DO UPDATE SET active=true;

INSERT INTO knowledge_db.sources(source_id,source_name,source_url,domain,source_type,trust_tier,language,usage_note,last_checked_at) VALUES
 ('src_nextfarm_home','NextFarm - Trang chủ nền tảng','https://nextfarm.vn/','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức về sản phẩm, module và định hướng nền tảng.',now()),
 ('src_nextfarm_help','NextFarm - Trung tâm hỗ trợ','https://nextfarm.vn/help-center','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức về thao tác sử dụng và chủ đề hỗ trợ.',now()),
 ('src_nextfarm_iot','NextFarm - IoT và cảm biến','https://nextfarm.vn/en/help-center/iot/dang-ky-quan-ly-thiet-bi-iot','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức mô tả quản lý thiết bị, cảm biến, cảnh báo và biểu đồ.',now()),
 ('src_nextfarm_irrigation','NextFarm Irrigation','https://nextfarm.vn/nen-tang/tuoi-thong-minh','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức về tưới theo lịch, cảm biến và dữ liệu thời tiết.',now()),
 ('src_nextfarm_soil','NextFarm - Cảm biến đất','https://nextfarm.vn/cam-bien-dat-nong-nghiep','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức giải thích độ ẩm, nhiệt độ, pH và EC.',now()),
 ('src_nextfarm_blog','NextFarm Blog','https://nextfarm.vn/blog','nextfarm.vn','nextfarm',2,'vi','Nguồn tham khảo kiến thức trồng trọt và triển khai; cần kiểm duyệt trước khi dùng.',now()),
 ('src_fao_ecocrop','FAO ECOCROP','https://www.fao.org/geospatial/data-and-tools/data-portals/ecocrop/en','fao.org','international',1,'en','Cơ sở dữ liệu yêu cầu môi trường của cây trồng; dùng cho sàng lọc mức phù hợp, không cam kết năng suất.',now()),
 ('src_khuyennong_tomato','Khuyến nông Quốc gia - Cà chua','https://khuyennongvn.gov.vn/khoa-hoc-cong-nghe/khcn-trong-nuoc/ky-thuat-trong-va-cham-soc-cay-ca-chua-3430.html','khuyennongvn.gov.vn','government',1,'vi','Nguồn kỹ thuật canh tác cà chua tại Việt Nam.',now()),
 ('src_khuyennong_melon','Khuyến nông Quốc gia - Dưa lưới nhà màng','https://khuyennongvn.gov.vn/khoa-hoc-cong-nghe/khcn-trong-nuoc/ky-thuat-trong-dua-luoi-tren-gia-the-trong-nha-mang-19550.html','khuyennongvn.gov.vn','government',1,'vi','Nguồn kỹ thuật dưa lưới trong nhà màng.',now()),
 ('src_ppd_process','Cục Trồng trọt và Bảo vệ thực vật - Quy trình kỹ thuật','https://sansangxuatkhau.ppd.gov.vn/quy-trinh-ky-thuat','ppd.gov.vn','government',1,'vi','Nguồn quy trình kỹ thuật và quản lý sinh vật gây hại.',now()),
 ('src_openmeteo_seasonal','Open-Meteo Seasonal Forecast','https://open-meteo.com/en/docs/seasonal-forecast-api','open-meteo.com','international',2,'en','Dự báo mùa vụ khu vực từ ECMWF; không hiệu chỉnh sai lệch cục bộ và không dùng riêng để cam kết năng suất.',now())
ON CONFLICT (source_id) DO UPDATE SET source_name=EXCLUDED.source_name, source_url=EXCLUDED.source_url, last_checked_at=EXCLUDED.last_checked_at;

INSERT INTO knowledge_db.documents(document_id,source_id,title,category,summary_vi,content_vi,crop_tags,product_tags,region_tags,approved,approved_by,checksum) VALUES
 ('doc_nf_platform','src_nextfarm_home','Hệ sinh thái nền tảng NextFarm','NEXTFARM_PRODUCT',
  'NextFarm tích hợp IoT, AI, GIS, truy xuất nguồn gốc, tưới và quản lý canh tác.',
  'Khi trả lời câu hỏi về tính năng NextFarm, chatbot chỉ được nêu các module đã có nguồn chính thức: IoT và cảm biến, tưới thông minh, GIS lô thửa, quản lý mùa vụ, truy xuất QR, dự báo và báo cáo. Không tự bịa tên màn hình hoặc tính năng chưa được tài liệu xác nhận.',
  '{}','{IoT,AI,GIS,Irrigation,QR}','{Vietnam}',true,'tech_01','nf-platform-v1'),
 ('doc_nf_help_scope','src_nextfarm_help','Phạm vi Trung tâm hỗ trợ NextFarm','NEXTFARM_PRODUCT',
  'Trung tâm hỗ trợ có các chủ đề cài đặt, IoT, GIS, trồng trọt, tưới, Fertikit, AI dự báo, báo cáo, mobile và bảo mật.',
  'Chatbot có thể dùng Trung tâm hỗ trợ làm nguồn ưu tiên khi người dùng hỏi cách cấu hình thiết bị, lịch tưới, cảm biến, phân quyền, ứng dụng và báo cáo. Nếu chưa tìm thấy bài phù hợp, bot phải nói chưa có tài liệu thay vì tự dựng quy trình.',
  '{}','{HelpCenter,IoT,Irrigation,Fertikit,Security}','{Vietnam}',true,'tech_01','nf-help-v1'),
 ('doc_nf_iot','src_nextfarm_iot','Quản lý thiết bị IoT và cảm biến','NEXTFARM_PRODUCT',
  'Module IoT quản lý thiết bị, cảm biến, cảnh báo, rule, điều khiển, biểu đồ và lịch tự động.',
  'Dữ liệu thiết bị cần gắn với mã khách hàng, khu vực, loại thiết bị, lần cuối online và topic MQTT. Khi trạng thái quá cũ, bot không được khẳng định thiết bị đang hoạt động. Biểu đồ phải lấy từ dữ liệu lịch sử của đúng vườn.',
  '{}','{IoT,Sensor,MQTT,Chart,Alert}','{Vietnam}',true,'tech_01','nf-iot-v1'),
 ('doc_nf_irrigation','src_nextfarm_irrigation','Tưới thông minh theo lịch và cảm biến','NEXTFARM_PRODUCT',
  'Tưới thông minh kết hợp lịch, độ ẩm đất và dữ liệu thời tiết để điều chỉnh tưới theo lô.',
  'Chatbot có thể giải thích lịch tưới, dữ liệu độ ẩm và cảnh báo thiếu nước. Mọi đề xuất điều khiển vật lý phải được coi là khuyến nghị và phải qua xác nhận, phân quyền cùng quy tắc an toàn của hệ thống.',
  '{}','{Irrigation,Sensor,Weather}','{Vietnam}',true,'tech_01','nf-irrigation-v1'),
 ('doc_nf_soil_sensor','src_nextfarm_soil','Ý nghĩa dữ liệu cảm biến đất','SENSOR_KNOWLEDGE',
  'Cảm biến đất có thể đo độ ẩm, nhiệt độ, pH và EC; giá trị hữu ích khi được đặt trong ngữ cảnh cây, tầng đất và thời gian.',
  'Không đánh giá một số đo là tốt hay xấu chỉ bằng một ngưỡng chung. Cần biết cây trồng, giai đoạn sinh trưởng, vị trí cảm biến, tầng đất, chất lượng số đo và thời gian ghi nhận. Khi dữ liệu thiếu hoặc nghi ngờ, bot phải yêu cầu kiểm tra cảm biến.',
  '{}','{Sensor,Soil,EC,pH,Moisture}','{Vietnam}',true,'tech_01','nf-soil-v1'),
 ('doc_tomato_vn','src_khuyennong_tomato','Cà chua: đất, pH và thời vụ tham khảo tại Việt Nam','CROP_GUIDE',
  'Cà chua phù hợp đất thoát nước tốt, giàu hữu cơ; tài liệu Khuyến nông nêu pH đất phù hợp khoảng 6,0-6,5 và các vụ trồng tham khảo.',
  'Khi tư vấn cà chua, cần xem điều kiện địa phương, giống, nhà màng hay ngoài trời, lịch sử sâu bệnh và thị trường. Không suy ra năng suất chỉ từ nhiệt độ và độ ẩm. Nếu trồng liên tiếp cây cùng họ, cần đánh giá rủi ro luân canh và bệnh tồn lưu.',
  '{Cà chua}','{}','{Vietnam}',true,'tech_01','tomato-vn-v1'),
 ('doc_melon_greenhouse','src_khuyennong_melon','Dưa lưới trên giá thể trong nhà màng','CROP_GUIDE',
  'Dưa lưới là cây giá trị cao nhưng cần nhà màng, giá thể, tưới và quản lý dinh dưỡng chặt chẽ.',
  'Khi đề xuất dưa lưới, bot phải kiểm tra loại hình canh tác, vốn đầu tư, khả năng quản lý dinh dưỡng, hệ thống tưới, thông gió, đầu ra và kinh nghiệm kỹ thuật. Phù hợp khí hậu không đồng nghĩa chắc chắn có hiệu quả kinh tế.',
  '{Dưa lưới}','{Greenhouse,Fertigation}','{Vietnam}',true,'tech_01','melon-gh-v1'),
 ('doc_crop_suitability','src_fao_ecocrop','Nguyên tắc sàng lọc cây trồng theo môi trường','CROP_SELECTION',
  'ECOCROP cho phép đối chiếu nhiệt độ, mưa, pH, đất, ánh sáng và các đặc tính khác để tìm cây phù hợp.',
  'Kết quả đối chiếu chỉ là mức phù hợp sinh thái sơ bộ. Để khuyến nghị mùa vụ cần bổ sung giống, sâu bệnh, nguồn nước, hệ thống canh tác, giá bán, chi phí, lao động, thị trường và dữ liệu năng suất địa phương. Bot phải gọi kết quả là mức phù hợp, không gọi là cây chắc chắn năng suất cao.',
  '{}','{}','{Global}',true,'tech_01','ecocrop-principle-v1'),
 ('doc_ppd_safety','src_ppd_process','Quy trình kỹ thuật và bảo vệ thực vật','PLANT_PROTECTION',
  'Cục Trồng trọt và Bảo vệ thực vật công bố quy trình kỹ thuật, tiêu chuẩn và tài liệu quản lý sinh vật gây hại.',
  'Câu trả lời về sâu bệnh, thuốc bảo vệ thực vật hoặc biện pháp có rủi ro phải ưu tiên nguồn quản lý nhà nước và yêu cầu chuyên gia xác nhận khi thiếu chẩn đoán. Chatbot không được tự kê tên thuốc, liều lượng hoặc thời gian cách ly nếu không có tài liệu được phê duyệt.',
  '{}','{}','{Vietnam}',true,'tech_01','ppd-safety-v1')
ON CONFLICT (document_id) DO UPDATE SET summary_vi=EXCLUDED.summary_vi, content_vi=EXCLUDED.content_vi, updated_at=now(), approved=EXCLUDED.approved;

INSERT INTO knowledge_db.document_chunks(chunk_id,document_id,chunk_order,content_vi,token_estimate,metadata)
SELECT 'chunk_'||document_id, document_id, 1, content_vi, greatest(1,length(content_vi)/4), jsonb_build_object('category',category,'title',title)
FROM knowledge_db.documents
ON CONFLICT (chunk_id) DO UPDATE SET content_vi=EXCLUDED.content_vi, metadata=EXCLUDED.metadata;

INSERT INTO knowledge_db.crop_profiles(
 crop_id,common_name_vi,scientific_name,family_name,crop_group,temp_opt_min,temp_opt_max,temp_abs_min,temp_abs_max,
 ph_opt_min,ph_opt_max,rainfall_opt_min,rainfall_opt_max,cycle_days_min,cycle_days_max,drainage_requirement,
 protected_cultivation,notes_vi,source_ids,reviewed
) VALUES
 ('crop_tomato','Cà chua','Solanum lycopersicum','Solanaceae','vegetable_fruit',18,28,10,35,6.0,6.5,400,1200,90,140,'well',true,'Ưu tiên đất/giá thể thoát nước tốt; độ ẩm không khí cao kéo dài có thể tăng rủi ro bệnh. Thông số là sàng lọc, cần hiệu chỉnh giống và vùng.','{src_fao_ecocrop,src_khuyennong_tomato}',true),
 ('crop_cucumber','Dưa leo','Cucumis sativus','Cucurbitaceae','vegetable_fruit',18,32,6,38,6.0,7.5,1000,1200,40,180,'well',true,'Cây ưa sáng, đất thoát nước; cần quản lý ẩm và bệnh trong điều kiện ẩm cao.','{src_fao_ecocrop}',true),
 ('crop_melon','Dưa lưới','Cucumis melo','Cucurbitaceae','fruit',18,30,9,35,6.0,7.5,1000,1300,50,120,'well',true,'Phù hợp nhà màng/giá thể khi có hệ thống tưới và dinh dưỡng chính xác; hiệu quả phụ thuộc đầu ra.','{src_fao_ecocrop,src_khuyennong_melon}',true),
 ('crop_watermelon','Dưa hấu','Citrullus lanatus','Cucurbitaceae','fruit',20,35,15,40,6.0,7.0,500,700,80,110,'well',false,'Cần thoát nước và ánh sáng; không suy ra lợi nhuận nếu thiếu dữ liệu thị trường.','{src_fao_ecocrop}',true),
 ('crop_chili','Ớt','Capsicum annuum','Solanaceae','vegetable_fruit',17,30,8,35,5.5,6.8,600,1250,60,180,'well',true,'Ẩm độ và nhiệt độ quá cao có thể ảnh hưởng đậu quả; cần xem giống và điều kiện canh tác.','{src_fao_ecocrop}',true),
 ('crop_pumpkin','Bí đỏ','Cucurbita maxima','Cucurbitaceae','vegetable_fruit',20,30,9,38,5.5,7.5,600,1000,80,140,'well',false,'Cây cần không gian và thoát nước; phù hợp chỉ là một phần của quyết định mùa vụ.','{src_fao_ecocrop}',true),
 ('crop_mungbean','Đậu xanh','Vigna radiata','Fabaceae','legume',21,36,8,40,5.5,6.2,650,900,50,120,'well',false,'Cây họ đậu có thể hữu ích trong luân canh; cần kiểm tra mùa vụ và khả năng tiêu thụ địa phương.','{src_fao_ecocrop}',true),
 ('crop_papaya','Đu đủ','Carica papaya','Caricaceae','fruit',21,30,12,44,5.5,7.0,1500,2500,330,365,'well',false,'Cây dài ngày, cần đất sâu và thoát nước; không phù hợp quyết định ngắn hạn nếu nông hộ cần quay vòng vốn nhanh.','{src_fao_ecocrop}',true),
 ('crop_jackfruit','Mít','Artocarpus heterophyllus','Moraceae','fruit_tree',20,30,16,34,5.5,7.5,1500,3000,210,365,'well',false,'Cây lâu năm; cần đánh giá đất, nước, vốn, đầu ra và thời gian kiến thiết cơ bản.','{src_fao_ecocrop}',true),
 ('crop_lemongrass','Sả','Cymbopogon citratus','Poaceae','herb',24,30,18,34,5.0,5.8,1500,3000,120,365,'well',false,'Có biên độ sử dụng rộng nhưng quyết định trồng cần dựa vào thị trường và mục tiêu sản xuất.','{src_fao_ecocrop}',true)
ON CONFLICT (crop_id) DO UPDATE SET notes_vi=EXCLUDED.notes_vi, updated_at=now(), reviewed=EXCLUDED.reviewed;

BEGIN;

-- V6: profile cá nhân hóa nhẹ, không có model artifact riêng theo nông dân.
INSERT INTO farm_db.farm_ai_profiles(
  farm_id,crop_code,crop_variety,growth_stage,cultivation_type,climate_region,soil_type,
  target_moisture_min,target_moisture_max,target_ec_min,target_ec_max,target_ph_min,target_ph_max,
  active_model_scope,active_model_version
) VALUES
 ('farm_long','tomato','Cà chua nhà màng','ra hoa','greenhouse','highland','loam',55,70,1.5,2.5,5.8,6.8,'global','1.0.0'),
 ('farm_lan','durian','Sầu riêng','kiến thiết','open_field','central_highlands','basalt',50,68,1.0,2.0,5.3,6.5,'global','1.0.0'),
 ('farm_minh','leafy_vegetable','Rau ăn lá','thu hoạch luân phiên','net_house','mekong_delta','alluvial',62,78,1.1,2.0,5.8,7.0,'global','1.0.0')
ON CONFLICT (farm_id) DO UPDATE SET
 crop_code=EXCLUDED.crop_code,cultivation_type=EXCLUDED.cultivation_type,
 climate_region=EXCLUDED.climate_region,soil_type=EXCLUDED.soil_type,
 target_moisture_min=EXCLUDED.target_moisture_min,target_moisture_max=EXCLUDED.target_moisture_max,
 target_ec_min=EXCLUDED.target_ec_min,target_ec_max=EXCLUDED.target_ec_max,
 target_ph_min=EXCLUDED.target_ph_min,target_ph_max=EXCLUDED.target_ph_max,
 active_model_scope='global',active_model_version='1.0.0',updated_at=now();

COMMIT;

-- V9: gắn nhãn mục/điểm trích dẫn cho các tài liệu demo đã duyệt.
UPDATE knowledge_db.document_chunks c
SET heading = COALESCE(c.heading, d.title),
    section_path = COALESCE(c.section_path, 'Mục 1 — Nội dung đã kiểm duyệt'),
    source_locator = COALESCE(c.source_locator, s.source_url || '#muc-1'),
    approved_snapshot = d.approved
FROM knowledge_db.documents d
JOIN knowledge_db.sources s ON s.source_id=d.source_id
WHERE c.document_id=d.document_id;

-- V9: nguồn chính thức phục vụ Data Studio và câu trả lời có mục trích dẫn.
INSERT INTO knowledge_db.sources(source_id,source_name,source_url,domain,source_type,trust_tier,language,usage_note,last_checked_at) VALUES
 ('src_nf_iot_chart','NextFarm Help — Biểu đồ cảm biến và cảnh báo IoT','https://nextfarm.vn/en/help-center/iot/bieu-do-canh-bao-iot','nextfarm.vn','nextfarm',1,'vi','Nguồn chính thức về truy vấn lịch sử, khoảng thời gian, xuất CSV và rule cảnh báo.',now()),
 ('src_fao_cropwat','FAO CROPWAT','https://www.fao.org/land-water/resources/tools/software/cropwat/en','fao.org','international',1,'en','Nguồn chính thức về nhu cầu nước cây trồng, lịch tưới và cân bằng nước đất.',now()),
 ('src_oasis_mqtt','OASIS MQTT Version 5.0','https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html','oasis-open.org','international',1,'en','Tiêu chuẩn publish/subscribe dùng cho luồng dữ liệu IoT.',now()),
 ('src_postgres_stats','PostgreSQL — Aggregate Functions','https://www.postgresql.org/docs/current/functions-aggregate.html','postgresql.org','international',1,'en','Nguồn hàm thống kê avg, stddev_pop, corr và regr_slope.',now())
ON CONFLICT (source_id) DO UPDATE SET source_name=EXCLUDED.source_name,source_url=EXCLUDED.source_url,last_checked_at=now();

INSERT INTO knowledge_db.documents(document_id,source_id,title,category,summary_vi,content_vi,product_tags,approved,approved_by,checksum) VALUES
 ('doc_nf_iot_chart_v9','src_nf_iot_chart','Biểu đồ dữ liệu cảm biến và rule cảnh báo','NEXTFARM_PRODUCT','NextFarm cho phép chọn thiết bị, chỉ số, khoảng thời gian, tự làm mới biểu đồ, xuất CSV và cấu hình cảnh báo theo ngưỡng.','Dữ liệu lịch sử phải được truy xuất theo đúng thiết bị, chỉ số và khoảng thời gian. Cảnh báo phải chỉ rõ chỉ số, điều kiện, ngưỡng và thời điểm kích hoạt.','{IoT,Chart,Alert,CSV}',true,'tech_01','nf-iot-chart-v9'),
 ('doc_fao_water_eval_v9','src_fao_cropwat','Đánh giá nhu cầu nước và lịch tưới theo FAO','AGRONOMIC_ANALYTICS','CROPWAT tính nhu cầu nước và tưới dựa trên dữ liệu đất, khí hậu và cây trồng; lịch tưới dùng cân bằng nước đất theo ngày.','Các chỉ số độ ẩm và ca tưới có thể dùng để đánh giá đáp ứng sau tưới và lịch sử cấp nước. Không được tuyên bố đã tính ETo FAO-56 nếu thiếu các biến khí tượng cần thiết hoặc chưa có dữ liệu cục bộ đủ chất lượng.','{Irrigation,FAO56,WaterBalance}',true,'tech_01','fao-water-v9'),
 ('doc_mqtt_pipeline_v9','src_oasis_mqtt','MQTT cho truyền dữ liệu cảm biến','IOT_ARCHITECTURE','MQTT là giao thức client/server publish-subscribe nhẹ, phù hợp môi trường IoT và tách rời thiết bị gửi với dịch vụ nhận.','Trong PoC, simulator publish gói telemetry theo topic của vườn và khu. Ingestion service subscribe, chống trùng packet_id, kiểm tra payload rồi lưu từng số đo vào Farm DB.','{MQTT,IoT,Telemetry}',true,'tech_01','mqtt-v9'),
 ('doc_pg_functions_v9','src_postgres_stats','Hàm thống kê cho chuỗi dữ liệu cảm biến','DATA_ANALYTICS','PostgreSQL cung cấp các hàm trung bình, độ lệch chuẩn, tương quan và độ dốc hồi quy.','Data Studio dùng avg để tính trung bình cửa sổ, stddev_pop để đo mức dao động và regr_slope theo thời gian để nhận biết xu hướng tăng hoặc giảm. Các hàm này mô tả dữ liệu; kết luận nông học vẫn cần ngưỡng, hồ sơ cây và nguồn đã kiểm duyệt.','{PostgreSQL,Statistics,TimeSeries}',true,'tech_01','pg-stats-v9')
ON CONFLICT (document_id) DO UPDATE SET summary_vi=EXCLUDED.summary_vi,content_vi=EXCLUDED.content_vi,approved=true,updated_at=now();

INSERT INTO knowledge_db.document_chunks(chunk_id,document_id,chunk_order,content_vi,token_estimate,metadata,heading,section_path,source_locator,approved_snapshot) VALUES
 ('chunk_nf_chart_1','doc_nf_iot_chart_v9',1,'Người dùng chọn thiết bị, chỉ số cảm biến và khoảng thời gian để xem dữ liệu lịch sử; giao diện có thể xuất CSV cho phân tích ngoài.',60,'{"topic":"chart"}','Biểu đồ cảm biến','Mục 1 — Xem và xuất dữ liệu cảm biến','https://nextfarm.vn/en/help-center/iot/bieu-do-canh-bao-iot#bieu-do-cam-bien',true),
 ('chunk_nf_chart_2','doc_nf_iot_chart_v9',2,'Rule cảnh báo được cấu hình bằng thiết bị, chỉ số, điều kiện so sánh, ngưỡng và hành động thông báo hoặc ghi alert.',55,'{"topic":"alert"}','Rule cảnh báo','Mục 2 — Cấu hình rule cảnh báo','https://nextfarm.vn/en/help-center/iot/bieu-do-canh-bao-iot#rule-canh-bao',true),
 ('chunk_fao_water_1','doc_fao_water_eval_v9',1,'CROPWAT dùng dữ liệu đất, khí hậu và cây trồng để tính nhu cầu nước, nhu cầu tưới và xây dựng lịch tưới; quy trình dựa trên FAO-56 và cân bằng nước đất.',65,'{"topic":"water"}','Nhu cầu nước và lịch tưới','Mục 1 — Dữ liệu đầu vào và cân bằng nước','https://www.fao.org/land-water/resources/tools/software/cropwat/en',true),
 ('chunk_fao_water_2','doc_fao_water_eval_v9',2,'Khi thiếu dữ liệu khí tượng cần thiết, hệ thống chỉ được báo mức sẵn sàng hoặc thông tin còn thiếu; không tạo giá trị ETo giả để tư vấn.',45,'{"topic":"guard"}','Giới hạn tính toán','Mục 2 — Điều kiện đủ trước khi tính ETo','https://www.fao.org/land-water/resources/tools/software/cropwat/en',true),
 ('chunk_mqtt_1','doc_mqtt_pipeline_v9',1,'MQTT dùng mô hình publish-subscribe để thiết bị gửi dữ liệu theo topic mà không cần biết trực tiếp dịch vụ nào sẽ xử lý dữ liệu.',45,'{"topic":"mqtt"}','Mô hình publish-subscribe','Mục 1 — Luồng truyền telemetry','https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html',true),
 ('chunk_pg_1','doc_pg_functions_v9',1,'avg mô tả mức trung tâm, stddev_pop mô tả độ biến động, regr_slope đo xu hướng tuyến tính theo thời gian; cần kết hợp độ đầy đủ, độ mới và ngưỡng mục tiêu.',55,'{"topic":"statistics"}','Hàm đánh giá chuỗi thời gian','Mục 1 — Trung bình, biến động và xu hướng','https://www.postgresql.org/docs/current/functions-aggregate.html',true)
ON CONFLICT (chunk_id) DO UPDATE SET content_vi=EXCLUDED.content_vi,heading=EXCLUDED.heading,section_path=EXCLUDED.section_path,source_locator=EXCLUDED.source_locator,approved_snapshot=true;

-- V9: bổ sung cảm biến để dashboard có đủ chuỗi nhiệt độ/ẩm/EC/pH/lưu lượng.
INSERT INTO farm_db.sensors(sensor_id,farm_id,zone_id,device_id,sensor_name,metric_type,unit) VALUES
 ('s_long_a_h','farm_long','long_a','dev_long_sensor','Độ ẩm không khí A','air_humidity','%'),
 ('s_long_a_flow','farm_long','long_a','dev_long_ctrl','Lưu lượng khu A','flow_rate','L/phút'),
 ('s_lan_a_t','farm_lan','lan_a','dev_lan_ctrl','Nhiệt độ A','temperature','°C'),
 ('s_lan_a_h','farm_lan','lan_a','dev_lan_ctrl','Độ ẩm không khí A','air_humidity','%'),
 ('s_lan_a_ec','farm_lan','lan_a','dev_lan_ctrl','EC đất A','ec','mS/cm'),
 ('s_lan_a_ph','farm_lan','lan_a','dev_lan_ctrl','pH đất A','ph','pH'),
 ('s_lan_a_flow','farm_lan','lan_a','dev_lan_ctrl','Lưu lượng khu A','flow_rate','L/phút'),
 ('s_minh_a_t','farm_minh','minh_a','dev_minh_sensor','Nhiệt độ A','temperature','°C'),
 ('s_minh_a_h','farm_minh','minh_a','dev_minh_sensor','Độ ẩm không khí A','air_humidity','%'),
 ('s_minh_a_ec','farm_minh','minh_a','dev_minh_sensor','EC A','ec','mS/cm'),
 ('s_minh_a_ph','farm_minh','minh_a','dev_minh_sensor','pH A','ph','pH')
ON CONFLICT (sensor_id) DO UPDATE SET active=true;

INSERT INTO research_db.sources(source_id,title,doi,repository,license,cadence,variables,intended_use) VALUES
 ('figshare_iot_28667981','Datasets from IoT devices',NULL,'Figshare','CC0','5 seconds','["temperature","air_humidity","light","ph","ec"]','["high-frequency empirical calibration","sensor step-size","cross-variable correlation"]'),
 ('agridatavalue_iot_18954708','AgriDataValue - IoT Environmental Data','10.5281/zenodo.18954708','Zenodo','CC BY 4.0',NULL,'["soil_moisture","soil_temperature","soil_water_tension","air_temperature","air_humidity","precipitation"]','["soil/environment empirical calibration","open-field dynamics"]'),
 ('parma_tomato_iot_2023','IoT-based Dataset of a Tomato Cultivation Under Different Irrigation Regimes','10.17632/35wh56287y.2','Mendeley Data','CC BY 4.0','10 minutes','["air_temperature","air_humidity","soil_moisture","soil_temperature","ec","water_volume"]','["tomato calibration","irrigation response"]'),
 ('parma_tomato_evolving_2023_2025','IoT Dataset from an Evolving Tomato Cultivation Testbed','10.17632/h8sfcf9487.1','Mendeley Data','CC BY 4.0','10 minutes','["air_temperature","air_humidity","soil_moisture","ec","water_volume","valve_state","water_pressure"]','["automated irrigation","event duration","multi-season context"]'),
 ('nasa_power_2025','NASA POWER Hourly Point API',NULL,'NASA POWER',NULL,'hourly','["T2M","RH2M","PRECTOTCORR","ALLSKY_SFC_SW_DWN","WS2M"]','["Vietnam farm climate baseline"]')
ON CONFLICT (source_id) DO UPDATE SET title=EXCLUDED.title,cadence=EXCLUDED.cadence,variables=EXCLUDED.variables,intended_use=EXCLUDED.intended_use;
