import numpy as np
import pytest
from nextfarm_device.forecast_acceptance import regression_acceptance,classification_acceptance

def test_tolerance_boundary_and_abstention_are_visible():
    result=regression_acceptance(np.zeros(80),np.full(80,5.0),'soil_moisture',100)
    assert result['hit_rate']==1 and result['prediction_coverage']==.8
    assert result['success_on_all_labeled_rows']==.8 and result['numeric_gate_passed']
    assert result['field_acceptance'] is False and result['tolerances_approved'] is False

def test_perfect_tiny_subset_does_not_satisfy_target():
    r=regression_acceptance(np.zeros(50),np.zeros(50),'ph',100)
    assert r['hit_rate']==1 and not r['numeric_gate_passed']

def test_more_than_tolerance_is_failure():
    assert not regression_acceptance(np.zeros(50),np.full(50,5.001),'soil_moisture',50)['numeric_gate_passed']

@pytest.mark.parametrize('truth,pred,total',[([1],[float('nan')],1),([1],[1],0),([1],[1,2],2)])
def test_invalid_metric_input_must_not_be_reported(truth,pred,total):
    with pytest.raises(ValueError):regression_acceptance(truth,pred,'ph',total)

def test_majority_accuracy_99_percent_does_not_pass_risk_classifier():
    r=classification_acceptance([[990,0],[10,0]],.4975,0)
    assert r['balanced_accuracy']==.5 and r['numeric_gate_passed'] is False

def test_weakest_classifier_gate_blocks():
    assert not classification_acceptance([[95,5],[20,80]],.79,.8)['numeric_gate_passed']
