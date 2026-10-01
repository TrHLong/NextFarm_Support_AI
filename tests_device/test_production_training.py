import pandas as pd
from nextfarm_device.production_training import audit_and_clean, build_moisture_features, readiness

def test_synthetic_never_passes_production_readiness():
    t=pd.date_range('2026-01-01',periods=500,freq='10min',tz='UTC')
    df=pd.DataFrame({'customer_id':'c1','farm_id':'f1','zone_id':'z1','device_id':'d1','sensor_id':'s1','observed_at':t,
                     'metric_type':'soil_moisture','value':50.0,'data_origin':'synthetic','quality':'good'})
    clean,audit=audit_and_clean(df);feat=build_moisture_features(clean);r=readiness(clean,feat,{'irrigation_events':pd.DataFrame()},audit)
    assert r['status']=='FAIL'
    assert r['checks']['production_origin_only_available']['pass'] is False

def test_invalid_physical_value_removed_but_valid_anomaly_retained():
    t=pd.date_range('2026-01-01',periods=3,freq='10min',tz='UTC')
    df=pd.DataFrame({'customer_id':'c1','farm_id':'f1','zone_id':'z1','device_id':'d1','sensor_id':'s1','observed_at':t,
                     'metric_type':['soil_moisture']*3,'value':[45.0,99.0,130.0],'data_origin':'real_device','quality':'good'})
    clean,audit=audit_and_clean(df)
    assert clean['value'].tolist()==[45.0,99.0]
    assert audit['invalid_rows']==1
