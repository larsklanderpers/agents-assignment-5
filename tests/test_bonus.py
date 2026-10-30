"""Exercise real parallel tasks, durable audit records and simulated delivery."""
from copy import deepcopy
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from backend.agent.activity import ActivityStore
from backend.agent.graph import create_approval_graph
from backend.evaluation.dataset import EVAL_DATASET
from tests.test_workflow_execution import model


def high_request(request_id="BONUS-HIGH"):
    request = deepcopy(EVAL_DATASET[2]["input"])
    request.update(request_id=request_id, bonus_options={"request_id":request_id,"parallel_high_risk":True})
    return {**request,"messages":[]}


def test_parallel_tasks_pause_together_and_finance_can_finish_first(model,tmp_path):
    store=ActivityStore(tmp_path/'audit.db');graph=create_approval_graph(MemorySaver(),store)
    config={"configurable":{"thread_id":"parallel"}}
    first=graph.invoke(high_request(),config)
    interrupts={i.value['type']:i for i in first['__interrupt__']}
    assert set(interrupts)=={'manager_review','finance_review'}
    assert len({i.id for i in interrupts.values()})==2
    row=store.dashboard()['requests'][0]
    assert set(row['pending_stages'])=={'manager_review','finance_review'}
    assert store.dashboard()['counts']['awaiting_review']==1
    assert len(store.audit(row['run_id'])['notifications'])==4
    second=graph.invoke(Command(resume={interrupts['finance_review'].id:{'approved':True,'comments':'Funding verified'}}),config)
    assert second['status']=='pending'
    assert second['parallel_finance_decision']['approved'] is True
    assert second['parallel_manager_decision'] is None
    assert {i.value['type'] for i in second['__interrupt__']}=={'manager_review'}
    assert store.dashboard()['requests'][0]['pending_stages']==['manager_review']
    final=graph.invoke(Command(resume={interrupts['manager_review'].id:{'approved':True,'comments':'Need verified'}}),config)
    assert final['status']=='approved'
    assert [d['stage'] for d in final['decisions']]==['manager_review','finance_review']
    audit=store.audit(final['audit_run_id'])
    assert len([e for e in audit['events'] if e['event_type']=='decision'])==2
    assert all(e['timestamp'] for e in audit['events'])
    assert audit['request']['pending_stages']==[]
    assert len(audit['notifications'])==4
    assert all(n['delivery']=='simulated' for n in audit['notifications'])


@pytest.mark.parametrize('manager,finance',[(False,True),(True,False),(False,False)])
def test_either_parallel_rejection_prevents_approval(model,manager,finance):
    graph=create_approval_graph(MemorySaver());config={'configurable':{'thread_id':'reject'}}
    first=graph.invoke(high_request(),config)
    decisions={'manager_review':manager,'finance_review':finance}
    final=graph.invoke(Command(resume={i.id:{'approved':decisions[i.value['type']],'comments':'Test decision'} for i in first['__interrupt__']}),config)
    assert final['status']=='rejected'
    assert len(final['decisions'])==2
    assert final['manager_approved'] is manager and final['finance_approved'] is finance


def test_parallel_checkpoint_and_audit_survive_reopen(model,tmp_path):
    checkpoint=str(tmp_path/'checkpoint.db');audit_path=tmp_path/'audit.db'
    config={'configurable':{'thread_id':'restart'}}
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        store=ActivityStore(audit_path);graph=create_approval_graph(saver,store)
        first=graph.invoke(high_request(),config)
        finance=next(i for i in first['__interrupt__'] if i.value['type']=='finance_review')
        graph.invoke(Command(resume={finance.id:{'approved':True,'comments':'Verified'}}),config)
    with SqliteSaver.from_conn_string(checkpoint) as saver:
        reopened=ActivityStore(audit_path);graph=create_approval_graph(saver,reopened)
        snapshot=graph.get_state(config)
        remaining=[i for task in snapshot.tasks for i in task.interrupts]
        assert [i.value['type'] for i in remaining]==['manager_review']
        final=graph.invoke(Command(resume={remaining[0].id:{'approved':True,'comments':'Approved after restart'}}),config)
        assert final['status']=='approved'
        assert reopened.dashboard()['counts']['approved']==1
        assert len(reopened.audit(final['audit_run_id'])['notifications'])==4
        exported=reopened.export()
        assert exported['runs'][0]['request']['status']=='approved'


def test_notification_retries_do_not_duplicate_previews(model,tmp_path):
    store=ActivityStore(tmp_path/'audit.db');graph=create_approval_graph(MemorySaver(),store)
    config={'configurable':{'thread_id':'repeat'}}
    graph.invoke(high_request(),config);state=graph.get_state(config).values
    for _ in range(3):store.record(state,'manager_review',pending=True)
    assert len(store.audit(state['audit_run_id'])['notifications'])==4


def test_live_progress_records_assessment_before_model_finishes(model,tmp_path):
    from langchain_core.messages import AIMessage
    store=ActivityStore(tmp_path/'audit.db')
    def assess(_messages):
        row=store.dashboard()['requests'][0]
        assert row['current_stage']=='assess_risk'
        assert 'assess_risk' not in row['completed_stages']
        return AIMessage(content='{"risk_level":"high","risk_reasoning":"Amount rule"}')
    model.invoke.side_effect=assess
    result=create_approval_graph(MemorySaver(),store).invoke(high_request(),{'configurable':{'thread_id':'live'}})
    assert len(result['__interrupt__'])==2


@pytest.mark.parametrize('changes',[{'amount':'500'},{'amount':True},{'amount':float('inf')},
                                   {'department':{}},{'title':None}])
def test_audit_does_not_break_invalid_input_rejection(model,tmp_path,changes):
    store=ActivityStore(tmp_path/'audit.db');graph=create_approval_graph(MemorySaver(),store)
    result=graph.invoke({**high_request(),**changes},{'configurable':{'thread_id':'invalid'}})
    assert result['status']=='rejected'
    assert store.dashboard()['counts']['rejected']==1


def test_critical_keeps_three_sequential_reviews_and_new_request_resets_bonus(model):
    graph=create_approval_graph(MemorySaver());config={'configurable':{'thread_id':'sequence'}}
    request=high_request();request['priority']='urgent'
    result=graph.invoke(request,config)
    for stage in ('manager_review','finance_review','final_signoff'):
        assert len(result['__interrupt__'])==1
        assert result['__interrupt__'][0].value['type']==stage
        result=graph.invoke(Command(resume={'approved':True,'comments':'Test'}),config)
    assert result['status']=='approved'
    next_request=deepcopy(EVAL_DATASET[2]['input']);next_request['request_id']='STANDARD-NEXT'
    result=graph.invoke(next_request,config)
    assert result['parallel_approvals'] is False
    assert len(result['__interrupt__'])==1
    assert result['__interrupt__'][0].value['type']=='manager_review'


def test_audit_keeps_separate_runs_and_masked_comments(model,tmp_path):
    store=ActivityStore(tmp_path/'audit.db');graph=create_approval_graph(MemorySaver(),store)
    for index,approved in enumerate((True,False)):
        config={'configurable':{'thread_id':str(index)}}
        first=graph.invoke(high_request(),config)
        graph.invoke(Command(resume={i.id:{'approved':approved,'comments':'Contact alice@example.com'} for i in first['__interrupt__']}),config)
    data=ActivityStore(tmp_path/'audit.db').dashboard()
    assert data['counts']['total']==2
    assert data['counts']['approved']==data['counts']['rejected']==1
    assert data['counts']['awaiting_review']==0
    assert len({r['run_id'] for r in data['requests']})==2
    assert 'alice@example.com' not in str(store.export())


def test_activity_api_export_and_missing_audit(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from backend.server import app
    monkeypatch.setenv('APPROVAL_AUDIT_DB',str(tmp_path/'audit.db'))
    monkeypatch.setattr('backend.server.create_async_checkpointer',lambda:AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoints.db')))
    with TestClient(app) as client:
        assert client.get('/bonus/dashboard').json()['counts']['total']==0
        assert client.get('/bonus/audit/missing').status_code==404
        response=client.get('/bonus/export')
        assert response.status_code==200
        assert 'attachment' in response.headers['content-disposition']
        assert response.json()['runs']==[]


@pytest.mark.parametrize('finance_first',[False,True])
def test_agui_reports_both_interrupts_and_accepts_addressed_resumes(model,monkeypatch,tmp_path,finance_first):
    import json
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from backend.server import app
    monkeypatch.setenv('APPROVAL_AUDIT_DB',str(tmp_path/'audit.db'))
    monkeypatch.setattr('backend.server.create_async_checkpointer',lambda:AsyncSqliteSaver.from_conn_string(str(tmp_path/'checkpoint.db')))
    payload={'threadId':str(uuid4()),'runId':str(uuid4()),'state':high_request(),
             'messages':[{'id':str(uuid4()),'role':'user','content':'Synthetic parallel test'}],
             'tools':[],'context':[],'forwardedProps':{}}
    def events(response):
        assert response.status_code==200,response.text
        return [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith('data:')]
    with TestClient(app) as client:
        first=events(client.post('/',json=payload))
        finish=next(e for e in reversed(first) if e['type']=='RUN_FINISHED')
        assert finish['outcome']['type']=='interrupt'
        pending=finish['outcome']['interrupts']
        assert len(pending)==2
        assert {i['metadata']['langgraph']['raw']['type'] for i in pending}=={'manager_review','finance_review'}
        if finance_first:
            finance=next(i for i in pending if i['metadata']['langgraph']['raw']['type']=='finance_review')
            payload.update(runId=str(uuid4()),state={},resume=[{'interruptId':finance['id'],'status':'resolved',
                           'payload':{'approved':True,'comments':'Finance first through HTTP'}}])
            partial=events(client.post('/',json=payload))
            finish=next(e for e in reversed(partial) if e['type']=='RUN_FINISHED')
            pending=finish['outcome']['interrupts']
            assert len(pending)==1 and pending[0]['metadata']['langgraph']['raw']['type']=='manager_review'
        payload.update(runId=str(uuid4()),state={},resume=[{'interruptId':i['id'],'status':'resolved',
                       'payload':{'approved':True,'comments':'Synthetic protocol approval'}} for i in pending])
        final=events(client.post('/',json=payload))
        assert not any(e['type']=='RUN_ERROR' for e in final),final
        snapshot=[e['snapshot'] for e in final if e['type']=='STATE_SNAPSHOT'][-1]
        assert snapshot['status']=='approved'
        assert len(snapshot['decisions'])==2
        assert client.get('/bonus/dashboard').json()['counts']['approved']==1
