import numpy as np
import pandas as pd
from nextfarm_device.benchmark_training import make_frame

def test_missing_ground_truth_window_is_not_assumed_negative(tmp_path):
    folder=tmp_path/'customers'/'synthetic_customer_000';folder.mkdir(parents=True)
    times=pd.date_range('2026-09-01',periods=15,freq='10min',tz='UTC')
    sensor=pd.DataFrame({'observed_at':times,'customer_id':'synthetic_customer_000','device_id':'cabinet_000',
        'soil_moisture':45.,'temperature':27.,'ec':1.2,'ph':6.5,'quality':'good'})
    sensor.to_csv(folder/'sensor_readings.csv',index=False)
    pd.DataFrame({'observed_at':times,'pump_running':0}).to_csv(folder/'device_status.csv',index=False)
    truth=pd.DataFrame({'observed_at':times,'ground_truth_origin':'synthetic_latent_incident',
        **{key:0 for key in ['no_flow','leak','irrigation_abort','sensor_fault','power_loss','mqtt_loss']}})
    truth.loc[3,'power_loss']=1;truth.to_csv(folder/'incident_ground_truth.csv',index=False)
    complete,_=make_frame(tmp_path)
    assert complete.iloc[0]['power_loss_future']==1
    assert complete.iloc[0]['mqtt_loss_future']==0
    truth.loc[2,'mqtt_loss']=np.nan;truth.to_csv(folder/'incident_ground_truth.csv',index=False)
    unknown,_=make_frame(tmp_path)
    assert np.isnan(unknown.iloc[0]['mqtt_loss_future'])
    assert unknown.iloc[0]['power_loss_future']==1
