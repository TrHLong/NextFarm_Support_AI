-- NextFarm V10 - Crop-aware AI Encyclopedia + LLM audit foundation
-- Idempotent migration, safe on fresh DB or upgraded V9 volume.
\set ON_ERROR_STOP on
BEGIN;

CREATE SCHEMA IF NOT EXISTS ai_db;

CREATE TABLE IF NOT EXISTS ai_db.crop_catalog (
  crop_key TEXT PRIMARY KEY,
  display_name_vi TEXT NOT NULL,
  crop_group TEXT NOT NULL,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  perennial BOOLEAN NOT NULL DEFAULT false,
  notes_vi TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_db.model_capabilities (
  capability_key TEXT PRIMARY KEY,
  display_name_vi TEXT NOT NULL,
  category TEXT NOT NULL,
  implementation_type TEXT NOT NULL CHECK (implementation_type IN ('trained_model','formula','rule','remote_sensing','computer_vision','llm_rag','hybrid')),
  model_family TEXT,
  required_inputs TEXT[] NOT NULL DEFAULT '{}',
  optional_inputs TEXT[] NOT NULL DEFAULT '{}',
  output_kind TEXT NOT NULL DEFAULT 'assessment',
  risk_level TEXT NOT NULL DEFAULT 'low' CHECK (risk_level IN ('low','medium','high')),
  default_status TEXT NOT NULL DEFAULT 'blocked' CHECK (default_status IN ('ready','experimental','blocked')),
  source_title TEXT,
  source_url TEXT,
  evidence_note TEXT,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ai_db.model_capabilities
  ADD COLUMN IF NOT EXISTS implementation_state TEXT NOT NULL DEFAULT 'catalog_only';
ALTER TABLE ai_db.model_capabilities
  ADD COLUMN IF NOT EXISTS implementation_ref TEXT;
ALTER TABLE ai_db.model_capabilities DROP CONSTRAINT IF EXISTS model_capabilities_implementation_state_check;
ALTER TABLE ai_db.model_capabilities
  ADD CONSTRAINT model_capabilities_implementation_state_check
  CHECK (implementation_state IN ('available','registry_gated','catalog_only'));

CREATE TABLE IF NOT EXISTS ai_db.crop_capability_map (
  crop_key TEXT NOT NULL REFERENCES ai_db.crop_catalog(crop_key) ON DELETE CASCADE,
  capability_key TEXT NOT NULL REFERENCES ai_db.model_capabilities(capability_key) ON DELETE CASCADE,
  applicability TEXT NOT NULL DEFAULT 'recommended' CHECK (applicability IN ('core','recommended','optional','not_applicable')),
  crop_specific_status TEXT CHECK (crop_specific_status IN ('ready','experimental','blocked')),
  reason_vi TEXT,
  min_history_days INTEGER,
  PRIMARY KEY (crop_key, capability_key)
);

CREATE TABLE IF NOT EXISTS ai_db.farm_crop_inventory (
  farm_id TEXT NOT NULL REFERENCES farm_db.farms(farm_id) ON DELETE CASCADE,
  zone_id TEXT NOT NULL REFERENCES farm_db.zones(zone_id) ON DELETE CASCADE,
  crop_key TEXT NOT NULL REFERENCES ai_db.crop_catalog(crop_key),
  source_crop_name TEXT NOT NULL,
  confidence NUMERIC(6,5) NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
  mapping_method TEXT NOT NULL DEFAULT 'catalog_alias',
  active BOOLEAN NOT NULL DEFAULT true,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (farm_id, zone_id, crop_key)
);
CREATE INDEX IF NOT EXISTS idx_farm_crop_inventory_farm ON ai_db.farm_crop_inventory(farm_id, active);
WITH ranked_inventory AS (
  SELECT ctid,row_number() OVER (PARTITION BY farm_id,zone_id ORDER BY detected_at DESC,crop_key) AS row_no
  FROM ai_db.farm_crop_inventory
  WHERE active
)
UPDATE ai_db.farm_crop_inventory inventory
SET active=false
FROM ranked_inventory ranked
WHERE inventory.ctid=ranked.ctid AND ranked.row_no>1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_farm_crop_inventory_one_active_zone
  ON ai_db.farm_crop_inventory(farm_id,zone_id) WHERE active;

CREATE TABLE IF NOT EXISTS ai_db.capability_assignment_audits (
  assignment_id BIGSERIAL PRIMARY KEY,
  user_id TEXT,
  farm_id TEXT,
  zone_id TEXT,
  crop_key TEXT,
  capability_key TEXT NOT NULL,
  resolved_status TEXT NOT NULL,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  model_family TEXT,
  model_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_capability_audits_farm_time
  ON ai_db.capability_assignment_audits(farm_id,created_at DESC);

CREATE TABLE IF NOT EXISTS ai_db.llm_audits (
  audit_id BIGSERIAL PRIMARY KEY,
  user_id TEXT,
  farm_id TEXT,
  provider TEXT NOT NULL,
  model_name TEXT,
  purpose TEXT NOT NULL,
  request_id TEXT,
  input_chars INTEGER NOT NULL DEFAULT 0,
  output_chars INTEGER NOT NULL DEFAULT 0,
  tool_name TEXT,
  tool_arguments JSONB,
  success BOOLEAN NOT NULL DEFAULT false,
  error_code TEXT,
  latency_ms NUMERIC(14,3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llm_audits_farm_time ON ai_db.llm_audits(farm_id, created_at DESC);

-- 34 crop/product keys. Aliases are Vietnamese/common names only; scientific identity belongs in Knowledge DB.
INSERT INTO ai_db.crop_catalog(crop_key,display_name_vi,crop_group,aliases,perennial,notes_vi) VALUES
('tomato','Cà chua','vegetable_fruit','{cà chua,ca chua,tomato}',false,'Demo V9 có dữ liệu hiệu chỉnh cho cà chua.'),
('grape','Nho','fruit_vine','{nho,grape}',true,NULL),
('apple','Táo','fruit_tree','{táo,tao,apple}',true,NULL),
('lychee','Vải','fruit_tree','{vải,vai,lychee,litchi}',true,NULL),
('rice','Lúa','grain','{lúa,lua,rice}',false,NULL),
('maize','Ngô','grain','{ngô,ngo,bắp,bap,maize,corn}',false,NULL),
('durian','Sầu riêng','fruit_tree','{sầu riêng,sau rieng,durian}',true,'Demo V9 có dữ liệu hiệu chỉnh cho sầu riêng.'),
('cucumber','Dưa leo','vegetable_fruit','{dưa leo,dua leo,dưa chuột,dua chuot,cucumber}',false,NULL),
('pepper_chili','Ớt','vegetable_fruit','{ớt,ot,chili,chilli}',false,NULL),
('citrus','Cam/quýt','fruit_tree','{cam,quýt,quyt,citrus,bưởi,buoi,chanh}',true,NULL),
('mango','Xoài','fruit_tree','{xoài,xoai,mango}',true,NULL),
('coffee','Cà phê','industrial_perennial','{cà phê,ca phe,coffee}',true,NULL),
('banana','Chuối','fruit','{chuối,chuoi,banana}',true,NULL),
('dragon_fruit','Thanh long','fruit','{thanh long,dragon fruit}',true,NULL),
('avocado','Bơ','fruit_tree','{bơ,bo,avocado}',true,NULL),
('passion_fruit','Chanh dây','fruit_vine','{chanh dây,chanh day,chanh leo,passion fruit}',true,NULL),
('longan','Nhãn','fruit_tree','{nhãn,nhan,longan}',true,NULL),
('rambutan','Chôm chôm','fruit_tree','{chôm chôm,chom chom,rambutan}',true,NULL),
('watermelon','Dưa hấu','fruit','{dưa hấu,dua hau,watermelon}',false,NULL),
('melon','Dưa lưới','fruit','{dưa lưới,dua luoi,melon,cantaloupe}',false,NULL),
('pumpkin','Bí','vegetable_fruit','{bí,bi,bí đỏ,bi do,pumpkin}',false,NULL),
('green_bean','Đậu xanh','legume','{đậu xanh,dau xanh,mung bean,green bean}',false,NULL),
('soybean','Đậu tương','legume','{đậu tương,dau tuong,đậu nành,dau nanh,soybean}',false,NULL),
('peanut','Lạc','legume','{lạc,lac,đậu phộng,dau phong,peanut}',false,NULL),
('cassava','Sắn','root_crop','{sắn,san,khoai mì,khoai mi,cassava}',false,NULL),
('sweet_potato','Khoai lang','root_crop','{khoai lang,sweet potato}',false,NULL),
('sugarcane','Mía','industrial_crop','{mía,mia,sugarcane}',false,NULL),
('tea','Chè','industrial_perennial','{chè,che,trà,tra,tea}',true,NULL),
('black_pepper','Hồ tiêu','industrial_perennial','{hồ tiêu,ho tieu,tiêu,tieu,black pepper}',true,NULL),
('cashew','Điều','industrial_perennial','{điều,dieu,cashew}',true,NULL),
('coconut','Dừa','industrial_perennial','{dừa,dua,coconut}',true,NULL),
('rubber','Cao su','industrial_perennial','{cao su,rubber}',true,NULL),
('leafy_vegetable','Rau ăn lá','leafy_vegetable','{rau,rau ăn lá,rau an la,leafy vegetable,xà lách,xa lach}',false,'Demo V9 có dữ liệu hiệu chỉnh cho rau ăn lá.'),
('other','Cây trồng khác','other','{khác,khac,other}',false,'Fallback: chỉ cho phép capability không phụ thuộc cây cho tới khi catalog được bổ sung.')
ON CONFLICT (crop_key) DO UPDATE SET display_name_vi=EXCLUDED.display_name_vi,crop_group=EXCLUDED.crop_group,aliases=EXCLUDED.aliases,perennial=EXCLUDED.perennial,notes_vi=EXCLUDED.notes_vi,updated_at=now();

INSERT INTO ai_db.model_capabilities(capability_key,display_name_vi,category,implementation_type,model_family,required_inputs,optional_inputs,output_kind,risk_level,default_status,source_title,source_url,evidence_note) VALUES
('sensor_quality_guard','Kiểm tra chất lượng dữ liệu cảm biến','data_quality','rule',NULL,'{sensor_value,observed_at,sensor_id}','{quality_flag,expected_interval}','quality','medium','ready','NextFarm PoC data quality rules',NULL,'Chặn missing/stale/out-of-range trước khi model khác sử dụng.'),
('soil_moisture_forecast','Dự báo độ ẩm đất','forecast','trained_model','moisture_forecast','{soil_moisture,temperature,air_humidity}','{flow_rate,irrigation_history,soil_type,crop_key}','forecast','medium','experimental','NextFarm V9 trained shared model',NULL,'Chỉ được READY khi model quality gate và crop-domain gate cùng đạt.'),
('microclimate_forecast','Dự báo vi khí hậu','forecast','trained_model','temperature_forecast','{temperature,air_humidity}','{hour,season,region}','forecast','low','ready','NextFarm V9 trained shared model',NULL,'Nhiệt độ/ẩm là đầu vào chính cho rủi ro bệnh và nước.'),
('ec_forecast','Dự báo EC','forecast','trained_model','ec_forecast','{ec}','{irrigation_history,fertilizer_events,crop_key}','forecast','medium','experimental','NextFarm V9 trained shared model',NULL,'Cần hiệu chỉnh theo cảm biến, cây và chiến lược dinh dưỡng.'),
('ph_forecast','Dự báo pH','forecast','trained_model','ph_forecast','{ph}','{irrigation_history,fertilizer_events,crop_key}','forecast','medium','experimental','NextFarm V9 trained shared model',NULL,'Chưa dùng để kê liều dinh dưỡng.'),
('multisensor_anomaly','Phát hiện bất thường đa cảm biến','anomaly','trained_model','anomaly_multisensor','{soil_moisture,temperature}','{air_humidity,ec,ph,flow_rate}','classification','medium','ready','NextFarm V9 trained shared model',NULL,'Phát hiện sai lệch trạng thái/cảm biến, không tự chẩn đoán bệnh cây.'),
('flow_fault','Chẩn đoán lưu lượng/rò rỉ/tắc','irrigation','trained_model','flow_fault','{flow_rate,valve_state,pump_state}','{pressure}','classification','high','experimental','NextFarm V9 trained shared model',NULL,'Cần dữ liệu flow thực từ NextFarm để xác nhận.'),
('irrigation_failure','Phát hiện ca tưới thất bại','irrigation','trained_model','irrigation_failure','{flow_rate,valve_state,pump_state,irrigation_schedule}','{soil_moisture_after}','classification','high','experimental','NextFarm V9 trained shared model',NULL,'Quality gate bắt buộc recall lớp sự cố.'),
('irrigation_need','Ước lượng nhu cầu tưới','irrigation','trained_model','irrigation_need','{soil_moisture,crop_key}','{eto,rainfall,soil_type,growth_stage}','classification','high','experimental','NextFarm V9 trained shared model',NULL,'Không tự bật van; chỉ tạo assessment.'),
('device_health','Sức khỏe thiết bị','device','trained_model','device_health','{device_online,sensor_age_seconds}','{packet_loss_rate,command_failure_rate}','classification','medium','ready','NextFarm V9 trained shared model',NULL,'Tách khỏi crop; có thể áp dụng cho mọi farm nếu đủ telemetry thiết bị.'),
('farm_health','Sức khỏe tổng thể vườn/thửa','composite','trained_model','farm_health','{soil_moisture,temperature,device_online}','{ec,ph,flow_rate}','classification','high','ready','NextFarm V9 trained shared model',NULL,'Chỉ là tổng hợp rủi ro PoC, không thay chuyên gia nông học.'),
('eto_fao56','Bốc thoát hơi tham chiếu FAO-56 (ETo)','water','formula',NULL,'{temperature,air_humidity,wind_speed,solar_radiation}','{latitude,elevation,pressure}','numeric','medium','blocked','FAO Irrigation and Drainage Paper 56','https://www.fao.org/4/X0490E/x0490e06.htm','FAO Penman-Monteith cần dữ liệu khí tượng đầy đủ; thiếu biến thì BLOCKED.'),
('crop_water_requirement','Nhu cầu nước cây trồng ETc','water','formula',NULL,'{eto,crop_coefficient,growth_stage,crop_key}','{soil_water_balance}','numeric','high','blocked','FAO Crop Evapotranspiration','https://www.fao.org/4/x0490E/x0490e0a.htm','ETc = Kc × ETo; Kc phải theo cây/giai đoạn và được kiểm duyệt.'),
('water_stress_risk','Rủi ro stress nước','water','hybrid',NULL,'{soil_moisture,crop_key}','{eto,ndmi,growth_stage,soil_type}','risk_score','high','blocked','FAO/NASA evidence bundle','https://science.nasa.gov/mission/landsat/hls-vegetation-indices/','Cần tối thiểu target theo cây; NDMI/ETo là dữ liệu bổ sung.'),
('irrigation_efficiency','Hiệu quả tưới','water','rule',NULL,'{irrigation_volume,soil_moisture_before,soil_moisture_after}','{flow_rate,eto}','assessment','medium','experimental','FAO CROPWAT','https://www.fao.org/land-water/resources/tools/software/cropwat/en','Đánh giá đáp ứng sau tưới; chưa thay kiểm toán nước.'),
('root_zone_stability','Ổn định vùng rễ','soil','hybrid',NULL,'{soil_moisture_timeseries,crop_key}','{soil_type,root_depth}','assessment','medium','blocked','FAO soil-water balance',NULL,'Cần root depth/soil profile theo cây.'),
('nutrient_stress_risk','Rủi ro dinh dưỡng','nutrition','hybrid',NULL,'{ec,ph,crop_key}','{leaf_analysis,fertilizer_events,growth_stage}','risk_score','high','blocked','Knowledge-base governed',NULL,'Không kê liều phân nếu chưa có nguồn và chuyên gia duyệt.'),
('salinity_risk','Rủi ro mặn/EC cao','soil','rule',NULL,'{ec,crop_key}','{soil_ec,water_ec,growth_stage}','risk_score','high','experimental','Knowledge-base governed',NULL,'Ngưỡng phải theo crop profile và đơn vị cảm biến.'),
('disease_climate_risk','Rủi ro bệnh theo vi khí hậu','disease','hybrid',NULL,'{temperature,air_humidity,crop_key}','{leaf_wetness,rainfall,growth_stage}','risk_score','high','blocked','Agronomy knowledge required',NULL,'Không chẩn đoán bệnh chỉ từ khí hậu; chỉ báo điều kiện thuận lợi khi có rule đã duyệt.'),
('pest_climate_risk','Rủi ro sâu hại theo khí hậu','pest','hybrid',NULL,'{temperature,crop_key}','{air_humidity,rainfall,growth_stage,pest_history}','risk_score','high','blocked','Agronomy knowledge required',NULL,'Cần dữ liệu sâu hại/phenology để huấn luyện và xác minh.'),
('crop_environment_fit','Mức phù hợp cây–môi trường','agronomy','llm_rag',NULL,'{crop_key,temperature}','{rainfall,ph,soil_type,region,market_data}','ranking','high','experimental','FAO ECOCROP','https://www.fao.org/geospatial/data-and-tools/data-portals/ecocrop/en','Chỉ sàng lọc mức phù hợp; không cam kết năng suất/lợi nhuận.'),
('yield_forecast','Dự báo năng suất','yield','hybrid',NULL,'{crop_key,growth_stage,weather_history}','{soil,remote_sensing,management_history,harvest_labels}','forecast','high','blocked','Crop-yield AI literature review','https://www.mdpi.com/2223-7747/14/18/2841','Cần nhãn năng suất thật theo vụ; không dùng telemetry mô phỏng để tuyên bố yield accuracy.'),
('growth_stage_detection','Nhận diện giai đoạn sinh trưởng','phenology','hybrid',NULL,'{crop_key}','{images,thermal,weather,planting_date}','classification','medium','blocked','Precision agriculture research',NULL,'Có thể rule theo ngày sau trồng hoặc CV; cần crop-specific validation.'),
('harvest_date_forecast','Dự báo thời điểm thu hoạch','phenology','hybrid',NULL,'{crop_key,growth_stage}','{weather,degree_days,images,variety}','forecast','high','blocked','Precision agriculture research',NULL,'Cần giống, ngày trồng và nhãn thu hoạch thật.'),
('ndvi_health','NDVI sức khỏe/độ xanh','remote_sensing','remote_sensing',NULL,'{satellite_red,satellite_nir,field_geometry}','{crop_key,growth_stage}','index','medium','blocked','NASA HLS Vegetation Indices','https://science.nasa.gov/mission/landsat/hls-vegetation-indices/','HLS cung cấp NDVI/EVI và các chỉ số 30 m; cần polygon thửa và imagery.'),
('ndmi_water_stress','NDMI theo dõi ẩm/stress nước','remote_sensing','remote_sensing',NULL,'{satellite_nir,satellite_swir,field_geometry}','{crop_key,growth_stage}','index','medium','blocked','NASA HLS Vegetation Indices','https://science.nasa.gov/mission/landsat/hls-vegetation-indices/','NDMI/NDWI hỗ trợ theo dõi moisture/water stress, không thay sensor tại chỗ.'),
('canopy_biomass','Tán lá/sinh khối','remote_sensing','remote_sensing',NULL,'{multispectral_or_rgb_imagery,field_geometry}','{lidar,crop_key,growth_stage}','assessment','medium','blocked','Remote sensing + ML precision agriculture review','https://www.mdpi.com/2073-4395/14/9/1975','Cần ảnh vệ tinh/UAV đã hiệu chỉnh và ground truth.'),
('disease_vision','Nhận diện dấu hiệu bệnh từ ảnh','vision','computer_vision',NULL,'{plant_images,crop_key}','{growth_stage,location}','classification','high','blocked','Plant disease ML/DL review','https://www.mdpi.com/2077-0472/14/12/2188/html','CNN/vision phổ biến nhưng cần dataset ảnh crop-specific và expert labels.'),
('pest_vision','Nhận diện sâu hại từ ảnh','vision','computer_vision',NULL,'{pest_or_plant_images,crop_key}','{trap_data,location}','classification','high','blocked','UAV/precision agriculture survey','https://www.mdpi.com/2624-7402/8/6/249','Cần ảnh/nhãn thực tế, không bật trong PoC telemetry-only.'),
('weed_vision','Nhận diện cỏ dại','vision','computer_vision',NULL,'{field_images}','{crop_key,segmentation_labels}','detection','medium','blocked','Precision weed control review','https://www.mdpi.com/2073-4395/15/8/1954','YOLO/segmentation là hướng phù hợp khi có ảnh và nhãn.'),
('ripeness_vision','Đánh giá độ chín','vision','computer_vision',NULL,'{fruit_images,crop_key}','{variety,color_calibration}','classification','medium','blocked','Smart agriculture multimodal review','https://www.mdpi.com/1424-8220/25/2/472','Cần bộ ảnh theo nông sản/giống và nhãn chuyên gia.'),
('fruit_quality_grading','Phân hạng chất lượng nông sản','vision','computer_vision',NULL,'{product_images,crop_key}','{weight,size,brix,defect_labels}','grading','high','blocked','Smart agriculture multimodal review','https://www.mdpi.com/1424-8220/25/2/472','Cần tiêu chuẩn phân hạng riêng của doanh nghiệp/thị trường và dữ liệu nhãn.' )
ON CONFLICT (capability_key) DO UPDATE SET display_name_vi=EXCLUDED.display_name_vi,category=EXCLUDED.category,implementation_type=EXCLUDED.implementation_type,model_family=EXCLUDED.model_family,required_inputs=EXCLUDED.required_inputs,optional_inputs=EXCLUDED.optional_inputs,output_kind=EXCLUDED.output_kind,risk_level=EXCLUDED.risk_level,default_status=EXCLUDED.default_status,source_title=EXCLUDED.source_title,source_url=EXCLUDED.source_url,evidence_note=EXCLUDED.evidence_note,updated_at=now();

-- A catalog entry describes a possible capability, not proof that executable code exists.
-- Only these two implementation paths are present in the V10 runtime today.
UPDATE ai_db.model_capabilities
SET implementation_state='catalog_only',implementation_ref=NULL;
UPDATE ai_db.model_capabilities
SET implementation_state='registry_gated',implementation_ref='knowledge_db.model_registry'
WHERE implementation_type='trained_model';
UPDATE ai_db.model_capabilities
SET implementation_state='available',implementation_ref='farm-data-service:data-quality-evaluation'
WHERE capability_key='sensor_quality_guard';

-- Default mapping: core telemetry capabilities for all known crops. Crop-specific/advanced modules remain gated by data readiness.
INSERT INTO ai_db.crop_capability_map(crop_key,capability_key,applicability,crop_specific_status,reason_vi)
SELECT c.crop_key, m.capability_key,
       CASE WHEN m.capability_key IN ('sensor_quality_guard','multisensor_anomaly','device_health','farm_health') THEN 'core' ELSE 'recommended' END,
       CASE
         WHEN c.crop_key IN ('tomato','durian','leafy_vegetable') AND m.capability_key IN ('microclimate_forecast','multisensor_anomaly','device_health','farm_health') THEN 'ready'
         WHEN m.default_status='ready' AND m.capability_key IN ('sensor_quality_guard','device_health') THEN 'ready'
         WHEN m.default_status='blocked' THEN 'blocked'
         ELSE 'experimental'
       END,
       CASE
         WHEN c.crop_key IN ('tomato','durian','leafy_vegetable') THEN 'Có dữ liệu PoC hiệu chỉnh cho crop này; vẫn cần NextFarm sandbox để xác nhận production.'
         ELSE 'Chưa có dữ liệu NextFarm thật theo crop; capability được biết trong bách khoa nhưng chưa được phép coi là production-ready.'
       END
FROM ai_db.crop_catalog c
CROSS JOIN ai_db.model_capabilities m
WHERE c.crop_key <> 'other' OR m.capability_key IN ('sensor_quality_guard','device_health','multisensor_anomaly')
ON CONFLICT (crop_key,capability_key) DO UPDATE SET applicability=EXCLUDED.applicability,crop_specific_status=EXCLUDED.crop_specific_status,reason_vi=EXCLUDED.reason_vi;

-- A trained time-series model needs a minimum observable history even when its
-- artifact and crop-domain quality gates have passed.
UPDATE ai_db.crop_capability_map mapping
SET min_history_days = CASE
  WHEN mapping.capability_key='device_health' THEN 0
  ELSE 1
END
FROM ai_db.model_capabilities capability
WHERE capability.capability_key=mapping.capability_key
  AND capability.implementation_type='trained_model';

-- Seed inventory at zone level. Farm-level crop is derived at request time and is not duplicated
-- because the physical/AI applicability unit is a farm zone.
UPDATE ai_db.farm_crop_inventory inventory
SET active=false,detected_at=now()
FROM farm_db.zones zone
JOIN ai_db.crop_catalog crop
  ON zone.crop_name IS NOT NULL AND lower(crop.display_name_vi)=lower(zone.crop_name)
WHERE inventory.zone_id=zone.zone_id AND inventory.active AND inventory.crop_key<>crop.crop_key;

INSERT INTO ai_db.farm_crop_inventory(farm_id,zone_id,crop_key,source_crop_name,confidence,mapping_method)
SELECT z.farm_id,z.zone_id,c.crop_key,z.crop_name,1.0,'catalog_alias'
FROM farm_db.zones z
JOIN ai_db.crop_catalog c ON z.crop_name IS NOT NULL AND lower(c.display_name_vi) = lower(z.crop_name)
ON CONFLICT (farm_id,zone_id,crop_key) DO UPDATE SET active=true,source_crop_name=EXCLUDED.source_crop_name,detected_at=now();

COMMIT;
