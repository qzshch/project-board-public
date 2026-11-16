"""Stage recommendation is not task admission; organization preserves receipts."""
import unittest,hashlib,json
from copy import deepcopy
from . import test_workflow as wf
from . import test_planning as planning
from task_board.roadmap import tree_projection,task_hints,priority_key


class RoadmapCase(unittest.TestCase):
    setUp=wf.WorkflowCase.setUp;tearDown=wf.WorkflowCase.tearDown
    call=wf.WorkflowCase.call;gov=wf.WorkflowCase.gov;member=wf.WorkflowCase.member
    atomic=wf.WorkflowCase.atomic;event=wf.WorkflowCase.event;op=wf.WorkflowCase.op
    claimed=wf.WorkflowCase.claimed;scope=wf.WorkflowCase.scope;submit=wf.WorkflowCase.submit
    charter=planning.PlanningCase.charter;module=planning.PlanningCase.module
    snap=planning.PlanningCase.snap;review=planning.PlanningCase.review

    def roadmap(self,profile=None):return self.call('/api/projects/alpha/roadmap',profile=profile or self.admin)[1]
    def stage(self,id='minimum',**kw):
        p={'id':id,'version':'1','title':'Minimum usable result','goal':'A complete end-to-end workflow','scope':'One approved scenario','non_goals':'Unrelated extensions','priority':'P1','input_anchor':'sha256:'+hashlib.sha256(b'fixed deliverable').hexdigest(),'repo':'','tasks':[{'task':'new/one','stage':'accepted'}],'criteria':[{'id':'PLAY','expected':'Actual complete scenario and restart match fixed build'}],'entry_stages':[],'reviewer':'root','reason':'Explicit project SE delivery scope',**kw}
        result=self.gov('stage_plan',p);self.assertEqual(result[0],201,result);return p
    def tree(self,version='1',**kw):
        return {'version':version,'reason':'Organize product functions without changing execution','nodes':[{'id':'product','title':'Product','parent':'','description':'Root','module_ids':[],'task_ids':[]},{'id':'function','title':'Player function','parent':'product','description':'Capability','module_ids':[],'task_ids':['new/one']}],**kw}
    def accepted(self):
        result=self.submit();self.assertEqual(result[0],201,result)
        result=self.event('new/one','accept',{'submission':result[1]['event_id'],'summary':'Review actual fixed fixture','deliverable_ids':['D1'],'evidence':wf.EV},self.admin);self.assertEqual(result[0],201,result)
    def stage_review(self,ref='minimum@1',**kw):
        row=self.roadmap()['stages'][ref]
        return self.gov('stage_review',{'ref':ref,'scope':row['state']['scope'],'input_anchor':row['plan']['input_anchor'],'result':'pass','checks':[{'id':'PLAY','result':'pass','summary':'Read actual fixed fixture and restart evidence'}],'summary':'Scope-bound review','evidence':wf.EV,**kw})

    def test_project_scope_and_worker_write_rejection(self):
        self.claimed();self.stage();self.assertEqual(self.call('/api/projects/alpha/roadmap',profile=self.b)[0],404)
        self.assertEqual(self.gov('function_tree',self.tree(),profile=self.a)[0],403)
        self.assertEqual(self.gov('stage_focus',{'ref':'minimum@1','reason':'Not a project SE'},profile=self.a)[0],403)
        self.assertEqual(self.gov('stage_review',{},profile=self.a)[0],403)

    def test_unfinished_focus_does_not_block_independent_extension_or_remove_real_dependency(self):
        self.member();self.atomic();self.atomic('extension/free',['extension/free/']);s=self.atomic('extension/dependent',['extension/dependent/']);s['depends_on']=['new/one'];self.event('extension/dependent','scope',{'spec':s,'reason':'Real prerequisite'},self.admin)
        self.stage();self.gov('stage_focus',{'ref':'minimum@1','reason':'Core delivery is the priority'})
        self.assertFalse(self.roadmap()['stages']['minimum@1']['state']['passed'])
        self.assertEqual(self.event('extension/free','claim',{'summary':'Independent authorized work'})[0],201)
        self.assertEqual(self.event('extension/dependent','claim',{'summary':'Must retain real blocker'})[0],409)
        brief=self.call('/api/projects/alpha/brief?task=extension/free',profile=self.a)[1];self.assertFalse(brief['project_stage']['focused'])

    def test_same_priority_focus_is_recommended_but_explicit_urgent_work_stays_first(self):
        self.member();self.atomic();self.atomic('extension/free',['extension/']);s=self.atomic('urgent/fix',['urgent/']);s['priority']='P0';self.event('urgent/fix','scope',{'spec':s,'reason':'Explicit urgent priority'},self.admin)
        self.stage();self.gov('stage_focus',{'ref':'minimum@1','reason':'Prioritize core on equal priority'})
        ts={t['spec']['id']:t for t in self.hub.store('alpha').snapshot()['tasks']};h=self.roadmap()['task_hints'];ids=sorted(['extension/free','new/one','urgent/fix'],key=lambda tid:priority_key(ts[tid],h))
        self.assertEqual(ids,['urgent/fix','new/one','extension/free'])

    def test_tree_reorganization_preserves_task_and_module_approval_and_evidence(self):
        self.claimed();self.charter();self.gov('module_plan',self.module());self.assertEqual(self.review()[0],201);self.accepted()
        task=deepcopy(self.hub.store('alpha').get('new/one'));before=self.snap()['module_readiness']['core@1']
        p=self.tree();p['nodes'][1]['module_ids']=['core'];self.assertEqual(self.gov('function_tree',p)[0],201)
        p=self.tree('2');p['nodes'][1].update(parent='',title='Reorganized domain',module_ids=['core']);self.assertEqual(self.gov('function_tree',p)[0],201)
        self.assertEqual(self.hub.store('alpha').get('new/one'),task);after=self.snap()['module_readiness']['core@1'];self.assertEqual(after['scope'],before['scope']);self.assertTrue(after['review_current'])
        row=self.roadmap()['tree'];self.assertEqual(row['task_map']['new/one'],'function');self.assertEqual(row['total_tasks'],row['classified_tasks']+len(row['unclassified_tasks']))

    def test_tree_cycle_missing_and_duplicate_assignment_reject_atomically(self):
        self.claimed();self.gov('function_tree',self.tree())
        for nodes in [self.tree('2')['nodes']+[deepcopy(self.tree()['nodes'][1])], [dict(self.tree()['nodes'][0],parent='function'),self.tree()['nodes'][1]], [self.tree()['nodes'][0],dict(self.tree()['nodes'][1],parent='missing')], [dict(self.tree()['nodes'][0],task_ids=['new/one']),self.tree()['nodes'][1]], [self.tree()['nodes'][0],dict(self.tree()['nodes'][1],task_ids=['other/project-task'])]]:
            result=self.gov('function_tree',self.tree('2',nodes=nodes));self.assertIn(result[0],(400,409),result);self.assertEqual(self.roadmap()['tree']['definition']['version'],'1')

    def test_stage_no_auto_pass_missing_checks_wrong_anchor_and_reopen(self):
        self.claimed();self.stage();self.assertEqual(self.stage_review()[0],409);self.accepted();self.assertFalse(self.roadmap()['stages']['minimum@1']['state']['passed'])
        self.assertEqual(self.stage_review(checks=[])[0],400);self.assertEqual(self.stage_review(input_anchor='sha256:'+'a'*64)[0],409)
        self.assertEqual(self.stage_review()[0],201);self.assertTrue(self.roadmap()['stages']['minimum@1']['state']['passed'])
        self.event('new/one','note',{'summary':'Non-semantic status note'},self.admin);self.gov('function_tree',self.tree());self.assertTrue(self.roadmap()['stages']['minimum@1']['state']['passed'])
        t=self.hub.store('alpha').get('new/one');self.event('new/one','reopen',{'submission':t['latest_submission']['id'],'reason':'Actual scope result failed','findings':[{'description':'Wrong outcome','acceptance':'Repair and revalidate'}]},self.admin)
        row=self.roadmap()['stages']['minimum@1'];self.assertFalse(row['state']['passed']);self.assertEqual(len(row['plan']['reviews']),1)

    def test_stage_requires_declared_result_type_and_fixed_baseline(self):
        self.claimed();self.accepted();self.stage(input_anchor='',tasks=[{'task':'new/one','stage':'merged'}]);self.assertEqual(self.stage_review()[0],409)
        blockers=self.roadmap()['stages']['minimum@1']['state']['blockers'];self.assertTrue(any('merged' in b for b in blockers));self.assertTrue(any('基线' in b for b in blockers))

    def test_stage_git_target_must_contain_actual_merged_result(self):
        from . import test_git_tracking as git_fixture
        self.git=git_fixture.GitCase.git.__get__(self);self.action=git_fixture.GitCase.action.__get__(self)
        git_fixture.GitCase.repository(self);self.claimed(baseline=self.first)
        result=self.submit(commit=self.feature);self.assertEqual(result[0],201)
        self.assertEqual(self.event('new/one','accept',{'submission':result[1]['event_id'],'summary':'Fixture feature verified','deliverable_ids':['D1'],'evidence':wf.EV},self.admin)[0],201)
        self.assertEqual(self.event('new/one','merge',{'submission':result[1]['event_id'],'summary':'Actual merge contains feature','commit':self.merge,'evidence':wf.EV},self.admin)[0],201)
        self.stage(input_anchor='git:'+self.before_merge,repo='main',tasks=[{'task':'new/one','stage':'merged'}]);self.assertEqual(self.stage_review()[0],409)
        self.stage(version='2',input_anchor='git:'+self.head,repo='main',tasks=[{'task':'new/one','stage':'merged'}]);self.assertEqual(self.stage_review('minimum@2')[0],201)
        row=self.roadmap()['stages']['minimum@2'];self.assertTrue(row['state']['passed']);self.assertTrue(row['plan']['reviews'][-1]['git_observation']['commit_observed'])

    def test_stage_prerequisite_applies_only_to_stage_review_and_old_versions_remain(self):
        self.claimed();self.stage();self.stage('extension',entry_stages=['minimum@1']);self.atomic('independent/task',['other/']);self.assertEqual(self.event('independent/task','claim',{'summary':'No task prerequisites'})[0],201)
        self.accepted();self.assertEqual(self.stage_review('extension@1')[0],409);self.assertEqual(self.stage_review()[0],201);self.assertEqual(self.stage_review('extension@1')[0],201)
        self.stage(version='2',input_anchor='');self.assertEqual(self.stage_review()[0],409);self.assertEqual(len(self.roadmap()['stages']['minimum@1']['plan']['reviews']),1)


class LargeTreeCase(unittest.TestCase):
    def test_twelve_domains_thousand_tasks_and_unclassified_are_not_silently_dropped(self):
        nodes=[{'id':'product','title':'Product','parent':'','description':'','module_ids':[],'task_ids':[]}]
        g={'modules':{},'module_heads':{},'function_trees':{},'function_tree_head':'1'};ts={}
        for i in range(12):
            mid='domain-'+str(i);g['module_heads'][mid]=mid+'@1';g['modules'][mid+'@1']={'title':mid,'parent':''};nodes.append({'id':mid,'title':mid,'parent':'product','description':'','module_ids':[mid],'task_ids':[]})
            for j in range(100):
                tid=mid+'/'+str(j);ts[tid]={'status':'planned','spec':{'id':tid,'title':tid,'kind':'atomic','priority':'P1','work':{'planning':{'module':mid+'@1'}}}}
        ts['legacy/unmapped']={'status':'reported','spec':{'id':'legacy/unmapped','title':'Historical delivery','kind':'delivery','priority':'P2'}}
        g['function_trees']['1']={'version':'1','nodes':nodes};tree=tree_projection(g,ts)
        self.assertEqual(tree['total_tasks'],1201);self.assertEqual(tree['classified_tasks'],1200);self.assertEqual(len(tree['unclassified_tasks']),1)
        root=next(n for n in tree['nodes'] if n['id']=='product');self.assertEqual(root['task_count'],1200);self.assertEqual(sum(len(n['tasks']) for n in tree['nodes']),1200)
