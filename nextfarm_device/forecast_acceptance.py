"""Proposed business tolerances, separate from measured model fit and deployment."""
TOLERANCES={'soil_moisture':5.0,'temperature':2.0,'ec':0.2,'ph':0.2}
POLICY={
 'version':'farmer_acceptance_proposal_v1','requested_hit_rate':0.80,
 'regression':'Fraction of eligible 30-minute forecasts within the stated absolute error tolerance.',
 'tolerance_units':{'soil_moisture':'percentage_points','temperature':'degC','ec':'mS/cm','ph':'pH_units'},
 'tolerances':TOLERANCES,'business_tolerances_approved':False,
 'classification':{'min_balanced_accuracy':0.80,'min_f1_macro':0.80,'min_risk_recall':0.80},
 'min_prediction_coverage':0.80,'min_test_rows':50,
 'query_acceptance':'Exact grounded facts and correct abstention on the declared test suite; no claim of universal 100% natural language understanding.',
 'limits':['Tolerances are proposed engineering criteria, not confirmed sensor accuracy or agronomic recommendations.',
           'Passing a simulated or reused historical test is not field acceptance.']}

def regression_acceptance(y,pred,metric,total_labeled_rows):
    import numpy as np
    y=np.asarray(y,dtype=float);pred=np.asarray(pred,dtype=float)
    if y.ndim!=1 or pred.shape!=y.shape or not (np.isfinite(y).all() and np.isfinite(pred).all()):raise ValueError('Expected finite, paired predictions and targets')
    if total_labeled_rows<len(y) or total_labeled_rows<0:raise ValueError('Invalid labeled denominator')
    error=np.abs(y-pred);count=len(error)
    hit_rate=float(np.mean(error<=TOLERANCES[metric])) if count else 0
    coverage=count/total_labeled_rows if total_labeled_rows else 0
    return {'absolute_error_tolerance':TOLERANCES[metric],'correct_within_tolerance':int((error<=TOLERANCES[metric]).sum()),
      'predicted_rows':count,'total_labeled_rows':total_labeled_rows,'hit_rate':hit_rate,'prediction_coverage':coverage,
      'success_on_all_labeled_rows':float((error<=TOLERANCES[metric]).sum()/total_labeled_rows) if total_labeled_rows else 0,
      'numeric_gate_passed':bool(hit_rate>=.8 and coverage>=.8 and count>=50),
      'field_acceptance':False,'tolerances_approved':False}

def classification_acceptance(matrix,f1,recall):
    tn,fp=matrix[0];fn,tp=matrix[1]
    balanced=.5*((tn/(tn+fp) if tn+fp else 0)+(tp/(tp+fn) if tp+fn else 0))
    return {'balanced_accuracy':balanced,'f1_macro':f1,'risk_recall':recall,
      'numeric_gate_passed':balanced>=.8 and f1>=.8 and recall>=.8,'field_acceptance':False}
