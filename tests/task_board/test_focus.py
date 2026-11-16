"""Focus views retain evidence, project authority and original delivery gates."""
import unittest,json,uuid
from copy import deepcopy
from . import test_workflow as wf
from . import test_resources as resources
from task_board.focus import groups,task_view
from task_board.operations import Operations
from task_board.governance import Governance


class FocusCase(unittest.TestCase):
    setUp=wf.WorkflowCase.setUp
    tearDown=wf.WorkflowCase.tearDown
    call=wf.WorkflowCase.call
    gov=wf.WorkflowCase.gov
    member=wf.WorkflowCase.member
    atomic=wf.WorkflowCase.atomic
    event=wf.WorkflowCase.event
    op=wf.WorkflowCase.op
    claimed=wf.WorkflowCase.claimed
    scope=wf.WorkflowCase.scope
    submit=wf.WorkflowCase.submit
    plan=wf.WorkflowCase.plan
    thread_payload=wf.WorkflowCase.thread_payload
    payload=resources.ResourcesCase.payload

    def test_current_authority_is_project_scoped_and_cannot_be_overridden_by_report(self):
        self.claimed()
        self.assertEqual(self.gov('resource_register',self.payload(title='Current state says DONE'))[0],201)
        status,current,_=self.call('/api/projects/alpha/current',profile=self.a)
        self.assertEqual(status,200,current);self.assertEqual(current['authority'],'project_journals')
        task=next(t for t in current['tasks'] if t['id']=='new/one');self.assertEqual(task['status'],'active')
        self.assertEqual(current['heads']['tasks'],self.hub.store('alpha').head())
        self.assertNotIn('Current state says DONE',json.dumps(current))
        self.assertEqual(self.call('/api/projects/alpha/current',profile=self.b)[0],404)
        self.assertEqual(self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1]['delivery_path']['steps'],['claim','work','submit','se_review'])

    def test_structure_and_completed_are_views_not_deletion_or_scope_changes(self):
        self.claimed();raw=self.hub.store('alpha').snapshot()
        current=self.call('/api/projects/alpha/current',profile=self.a)[1]
        self.assertEqual({t['id'] for t in current['tasks']},{t['spec']['id'] for t in raw['tasks']})
        self.assertTrue(any(t['view']=='structure' for t in current['tasks']))
        t=deepcopy(self.hub.store('alpha').get('new/one'));t['status']='merged';self.assertEqual(task_view(t),'completed')
        t['spec']['kind']='delivery';t['status']='active';self.assertEqual(task_view(t),'current')
        t['status']='reported';self.assertEqual(task_view(t),'structure')

    def test_snapshot_material_is_separated_but_explicit_task_input_is_kept(self):
        self.claimed();p=self.payload(information_role='snapshot');self.gov('resource_register',p)
        location=p['locations'][0]['location'];m={'title':'Old report','location':location,'version':'old','sha256':'b'*64}
        self.gov('knowledge',{'background':'Project','goals':'One','non_goals':'Other','constraints':'Scope','materials':[m],'entries':[]})
        brief=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1]
        self.assertEqual(brief['read_materials'],[]);self.assertEqual(brief['historical_materials'][0]['location'],location)
        spec=deepcopy(self.hub.store('alpha').get('new/one')['spec']);spec['work']['inputs'].append(location)
        self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'Pin historical report as actual input'},self.admin)[0],201)
        brief=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1]
        self.assertEqual(brief['read_materials'][0]['information_role'],'snapshot');self.assertEqual(brief['historical_materials'],[])

    def test_explicit_snapshot_classification_retains_versions_and_permissions(self):
        self.member();self.assertEqual(self.gov('resource_register',self.payload())[0],201)
        p={'id':'research','expected_version':1,'information_role':'snapshot','reason':'Prior round report; preserve bytes and input'}
        self.assertEqual(self.gov('resource_classify',p,profile=self.a)[0],403)
        self.assertEqual(self.gov('resource_classify',p)[0],201)
        self.assertEqual(self.gov('resource_classify',p)[0],409)
        self.assertEqual(self.call('/api/projects/alpha/resources?view=current',profile=self.a)[1]['entries'],[])
        rows=self.call('/api/projects/alpha/resources?view=history',profile=self.a)[1]['entries'];self.assertEqual(rows[0]['id'],'research')
        self.assertEqual(rows[0]['authority'],'historical_snapshot')
        history=self.call('/api/projects/alpha/resources/research/history',profile=self.admin)[1]['versions']
        self.assertEqual(len(history),2);self.assertEqual(history[0]['locations'],history[1]['locations'])
        self.assertTrue(Governance(self.hub.store('alpha')).verify()['passed'])

    def discussion(self,id,**kwargs):
        return self.op('thread_open',self.thread_payload('discussion',id=id,pause=False,**kwargs),self.a)

    def test_discussion_succession_is_explicit_scoped_and_idempotent(self):
        self.claimed();self.assertEqual(self.discussion('old')[0],201);self.assertEqual(self.discussion('current')[0],201)
        p={'thread':'old','replacement':'current','summary':'Same reminder, new exact input; follow current discussion'}
        self.assertEqual(self.op('thread_supersede',p,self.a)[0],403)
        rid=uuid.uuid4().hex;rev=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['revision']
        first=self.op('thread_supersede',p,rid=rid,revision=rev);self.assertEqual(first[0],201,first)
        self.assertTrue(self.op('thread_supersede',p,rid=rid,revision=rev)[1]['replayed'])
        data=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.admin)[1]
        self.assertEqual(data['threads']['old']['superseded_by'],'current');self.assertEqual(data['threads']['old']['messages'][0]['kind'],'opening')
        self.assertEqual([x['id'] for x in data['action_groups'][0]['items']],['current'])
        self.assertTrue(any(x['id']=='old' for x in data['notifications']))
        self.assertEqual(self.op('thread_supersede',{'thread':'current','replacement':'old','summary':'No cycles'})[0],409)
        self.assertTrue(Operations(self.hub.store('alpha')).verify()['passed'])

    def test_succession_never_hides_blockers_waits_stops_or_other_tasks(self):
        self.claimed();self.discussion('old');self.discussion('new');self.op('thread_open',self.thread_payload(id='blocked'),self.a)
        for source,target in [('blocked','new'),('old','blocked')]:
            self.assertEqual(self.op('thread_supersede',{'thread':source,'replacement':target,'summary':'Must not clear gate'})[0],409)
        self.op('thread_decide',{'thread':'old','decision':'stop','summary':'Do not proceed','reference':''})
        self.assertEqual(self.op('thread_supersede',{'thread':'old','replacement':'new','summary':'Cannot hide stop'})[0],409)
        self.atomic('other/task',['other/']);other=self.hub.store('alpha').get('other/task')
        self.op('thread_open',{**self.thread_payload('discussion',id='foreign',pause=False),'task':'other/task','scope':other['scope_hash'],'scope_version':other['scope_version']})
        self.assertEqual(self.op('thread_supersede',{'thread':'new','replacement':'foreign','summary':'No cross-task merge'})[0],409)

    def test_candidate_can_arrive_before_claims_or_review_but_cannot_be_accepted(self):
        self.claimed();self.assertEqual(self.op('criteria_plan',self.plan())[0],201)
        result=self.submit();self.assertEqual(result[0],201,result)
        self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'submitted')
        self.assertEqual(self.event('new/one','accept',{'submission':result[1]['event_id'],'summary':'Missing claims','deliverable_ids':['D1'],'evidence':wf.EV},self.admin)[0],409)

    def test_grouping_keeps_findings_even_on_completed_tasks_and_splits_notifications(self):
        rows=[{'kind':'thread','id':'old','task':'one','status':'resolved'}, {'kind':'thread','id':'reply','task':'one','status':'awaiting_worker'}, {'kind':'finding','id':'bug','task':'one','status':'open'}, {'kind':'submission','id':'two','task':'two','status':'submitted'}]
        view=groups(rows);self.assertEqual(len(view['action_groups']),2);self.assertEqual(len(view['notifications']),1)
        one=view['action_groups'][0];self.assertEqual(one['roles'],['worker','se']);self.assertEqual(len(one['items']),2)
