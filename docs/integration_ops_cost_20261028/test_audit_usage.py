import json,pytest
from audit_usage import aggregate,parse_csv,valid_tokens,stamp,TOKEN_FIELDS

def test_valid_sum():assert valid_tokens(dict(input_tokens='2',output_tokens='3',total_tokens='5'))==[2,3,5]
@pytest.mark.parametrize('value',[True,-1,'NaN',None])
def test_bad_count(value):
 with pytest.raises(ValueError):valid_tokens(dict(input_tokens=value,output_tokens=0,total_tokens=0))
def test_mismatched_sum():
 with pytest.raises(ValueError,match='mismatch'):valid_tokens(dict(input_tokens=2,output_tokens=3,total_tokens=4))
def test_missing_timezone():
 with pytest.raises(ValueError):stamp('2026-10-28T00:00:00')
def test_malformed_csv_and_no_free_text():
 text=','.join(TOKEN_FIELDS)+'\n2026-10-28T00:00:00Z,paper_demo,rules,1,2,3,0.0,True,0,DO_NOT_COPY,DO_NOT_COPY\nmalformed\n'
 rows,notes=parse_csv(text,'token_usage.csv');assert len(rows)==1 and notes['invalid_width_or_header']==1
 assert 'DO_NOT_COPY' not in json.dumps(rows)
def test_nan_cost_and_overlap_not_summed():
 row=dict(schema='decision_estimate',timestamp='2026-10-28T00:00:00Z',input_tokens=1,output_tokens=2,total_tokens=3,model='rules',telemetry_source='estimated_rule_based',decision_key='same',estimated_cost='NaN')
 item=dict(records=[row],notes={});r=aggregate(dict(a=item,b=item))
 assert r['datasets']['a']['invalid_cost_rows']==1 and r['combined_token_total'] is None
 assert r['overlaps']['a :: b']['shared_decision_ids']==1

def test_archive_switches_schema_without_repeated_header():
 from audit_usage import BACK_FIELDS
 text=','.join(BACK_FIELDS)+'\n2026-10-28T00:00:00Z,paper_demo_backfill,rules,1,2,3,0.0,id1,NVDA,x,estimated_rule_based\n2026-10-28T00:00:00Z,paper_demo,rules,1,2,3,0.0,True,0,,\n'
 rows,notes=parse_csv(text,'token_usage_legacy_example.csv')
 assert [r['schema'] for r in rows]==['decision_estimate','runtime_summary']
 assert 'decision_key' not in rows[1]
