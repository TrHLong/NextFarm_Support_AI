import pandas as pd
import numpy as np
from nextfarm_device.historical_training import features,split_frame,KEYS

def sample():
    rows=[]
    for customer in ['customer_lan','customer_long','customer_minh']:
        stamps=pd.date_range('2026-09-08',periods=433,freq='10min',tz='UTC')
        part=pd.DataFrame({'decision_at':stamps,'observed_at':stamps-pd.Timedelta(seconds=10),
            'reading_id':range(len(stamps)),'value':np.arange(len(stamps),dtype=float)})
        for key in KEYS:part[key]=customer if key=='customer_id' else key+'_a'
        rows.append(part)
    return pd.concat(rows,ignore_index=True)

def test_future_target_is_not_feature_and_missing_is_not_filled():
    raw=sample();frame=features(raw)
    raw.loc[(raw.customer_id=='customer_lan')&(raw.reading_id==100),'value']=999
    changed=features(raw)
    before=(frame.customer_id=='customer_lan')&(frame.reading_id<100)
    pd.testing.assert_series_equal(frame.loc[before,'value'],changed.loc[before,'value'])
    assert changed.loc[(changed.customer_id=='customer_lan')&(changed.reading_id==97),'target'].iloc[0]==999
    raw.loc[(raw.customer_id=='customer_lan')&(raw.reading_id==100),'value']=np.nan
    assert np.isnan(features(raw).loc[(frame.customer_id=='customer_lan')&(frame.reading_id==97),'target'].iloc[0])

def test_time_and_customer_split_purges_future_labels():
    frame,report=split_frame(features(sample()),'customer_minh')
    train=frame.loc[frame.split=='train'];val=frame.loc[frame.split=='validation'];test=frame.loc[frame.split=='test_unseen_customer']
    assert set(train.customer_id).isdisjoint(test.customer_id)
    assert set(val.customer_id).isdisjoint(test.customer_id)
    assert train.label_end.max()<val.decision_at.min()
    assert val.label_end.max()<test.decision_at.min()

def test_target_with_old_timestamp_is_not_labeled_30min():
    raw=sample();mask=(raw.customer_id=='customer_lan')&(raw.reading_id==100)
    raw.loc[mask,'observed_at']=raw.loc[mask,'decision_at']-pd.Timedelta(minutes=5)
    frame=features(raw)
    assert np.isnan(frame.loc[(frame.customer_id=='customer_lan')&(frame.reading_id==97),'target'].iloc[0])
