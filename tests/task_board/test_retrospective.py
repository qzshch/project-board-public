"""Historical metadata imports through real project HTTP transactions."""
import json,time,uuid,unittest
from copy import deepcopy
from . import test_workflow as w

class RetrospectiveCase(unittest.TestCase):
    setUp=w.WorkflowCase.setUp;tearDown=w.WorkflowCase.tearDown
    call=w.WorkflowCase.call;gov=w.WorkflowCase.gov;member=w.WorkflowCase.member
    atomic=w.WorkflowCase.atomic;event=w.WorkflowCase.event;op=w.WorkflowCase.op
    scope=w.WorkflowCase.scope;claimed=w.WorkflowCase.claimed
    git=w.WorkflowCase.git;action=w.WorkflowCase.action;query=w.WorkflowCase.query;repository=w.WorkflowCase.repository

    def draft(self):
        self.claimed();scope=self.scope();now=time.time();actor=self.a['actor']
        self.assertEqual(self.op('session_register',{'id':'retro-session','session':'native-history','runtime':'antigravity','machine':'fixture-pc','role':'worker','tasks':['new/one'],'previous':'','status':'completed'},self.a)[0],201)
        common={'actor':actor,'session':'native-history','task':'new/one','scope':scope['scope'],'scope_version':scope['scope_version'],'start':now-600,'end':now-300,'phase':'testing','origin':{'path':'G:/fixture/evidence/source.json','sha256':'b'*64},'reason':'Recorded explicit per-turn usage and declared effective work, not conversation elapsed time'}
        return {'id':'archive-one','version':1,'title':'Historical project records','summary':'Project-specific explicit source reconstruction','period':{'start':now-700,'end':now-200},
          'archive':{'path':'G:/fixture/evidence/MANIFEST.json','sha256':'a'*64,'kind':'local','machine':'fixture-pc','access':'Project OS permissions required','retention':'Retain original evidence'},'missing':['cache_write unknown'],
          'entries':[{**common,'id':'usage-1','kind':'usage','model':'actual-route','attribution':'bound_task','basis':{'mode':'call','before':None,'after':{'input':100,'output':10,'cache_read':50,'cache_write':None,'reasoning':2}}},
                     {**common,'id':'time-1','kind':'time','seconds':80,'mode':'work','rework':True}]}

    def post(self,action,p,profile=None,rid=None):return self.call('/api/projects/alpha/retrospectives',{'request_id':rid or uuid.uuid4().hex,'project_id':'alpha','action':action,'payload':p},profile or self.admin)
    def listing(self):return self.call('/api/projects/alpha/retrospectives',profile=self.admin)[1]
    def decide(self,p,decision='approved',profile=None,rid=None):
        v=self.listing()['batches'][p['id']]['versions'][str(p['version'])]
        return self.post('decide',{'id':p['id'],'version':p['version'],'draft_hash':v['hash'],'decision':decision,'reason':'Checked original source, scope and overlap'},profile,rid)
    def usage(self):return self.call('/api/projects/alpha/usage',profile=self.admin)[1]
    def test_worker_draft_se_atomic_approval_time_and_archive(self):
        p=self.draft();before=self.hub.store('alpha').get('new/one');rid=uuid.uuid4().hex
        self.assertEqual(self.post('submit',p,self.a,rid)[0],201);self.assertTrue(self.post('submit',p,self.a,rid)[1]['replayed'])
        self.assertEqual(self.usage()['revision'],0);self.assertEqual(self.decide(p,profile=self.a)[0],403)
        rid=uuid.uuid4().hex;r=self.decide(p,rid=rid);self.assertEqual(r[0],201,r[1])
        self.assertTrue(self.decide(p,rid=rid)[1]['replayed']);u=self.usage();self.assertEqual(u['revision'],1);self.assertTrue(u['chain_valid']);self.assertEqual(u['buckets'][0]['counts']['input'],100)
        self.assertEqual(u['samples'][0]['actor'],self.a['actor']);self.assertIn('reviewer',u['samples'][0]['retrospective'])
        o=self.call('/api/projects/alpha/operations',profile=self.admin)[1];self.assertEqual(o['time_report']['work_seconds'],80);self.assertFalse(o['time_report']['tasks'][0]['time_complete'])
        resources=self.call('/api/projects/alpha/resources?origin=retrospective',profile=self.a)[1];self.assertEqual(resources['total'],1);self.assertEqual(resources['entries'][0]['integrity']['sha256'],'a'*64)
        self.assertEqual(self.hub.store('alpha').get('new/one'),before)
        for endpoint in ('retrospectives','usage','resources?origin=retrospective'):self.assertEqual(self.call('/api/projects/alpha/'+endpoint,profile=self.b)[0],404)
    def test_revision_keeps_old_statistics_until_review_and_preserves_unknown(self):
        p=self.draft();self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        p['version']=2;p['entries'][0]['basis']['after']['input']=150;p['entries'][1]['seconds']=40
        self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.usage()['buckets'][0]['counts']['input'],100)
        self.assertEqual(self.decide(p)[0],201);u=self.usage();self.assertEqual(u['revision'],2);self.assertEqual(u['buckets'][0]['counts']['input'],150);self.assertTrue(u['chain_valid'])
        self.assertEqual(u['buckets'][0]['unknown']['cache_write'],1);self.assertEqual(self.call('/api/projects/alpha/operations',profile=self.admin)[1]['time_report']['work_seconds'],40)
        p['version']=3;p['entries'][0]['task']='';self.assertEqual(self.post('submit',p,self.a)[0],400)
    def test_overlap_rolls_back_usage_and_no_automatic_complete(self):
        p=self.draft();self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        other=deepcopy(p);other['id']='overlap';self.assertEqual(self.post('submit',other,self.a)[0],201);self.assertEqual(self.decide(other)[0],409);self.assertEqual(self.usage()['revision'],1)
        other['id']='rollback';other['entries'][0]['session']='unregistered';other['entries'][1]['actor']='root'
        self.assertEqual(self.post('submit',other,self.a)[0],201);self.assertEqual(self.decide(other)[0],409);self.assertEqual(self.usage()['revision'],1)
        self.assertEqual(self.listing()['batches']['rollback']['versions']['1']['status'],'pending')
    def test_input_bounds_stale_version_reader_and_unverified_scope(self):
        p=self.draft();p['entries'][1]['seconds']=400;self.assertEqual(self.post('submit',p,self.a)[0],400)
        p['entries'][1]['seconds']=80;p['entries'][1]['scope']='0'*64;self.assertEqual(self.post('submit',p,self.a)[0],409)
        p['entries'][1]['scope']=self.scope()['scope'];p['archive']['path']='G:/private/admin.json';self.assertEqual(self.post('submit',p,self.a)[0],400)
        p['archive']['path']='G:/fixture/MANIFEST.json';self.assertEqual(self.post('submit',p,self.a)[0],201)
        p['version']=2;self.assertEqual(self.post('submit',p,self.a)[0],201)
        old=self.listing()['batches'][p['id']]['versions']['1'];self.assertEqual(self.post('decide',{'id':p['id'],'version':1,'draft_hash':old['hash'],'decision':'approved','reason':'stale'})[0],409)
        self.assertEqual(self.decide(p,'rejected')[0],201);self.assertEqual(self.usage()['revision'],0)

    def test_cumulative_baseline_missing_and_counter_reset_are_conservative(self):
        p=self.draft();e=p['entries'][0];e['basis']['mode']='cumulative';e['basis']['before']=None
        self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        u=self.usage();self.assertIsNone(u['samples'][0]['amounts']['input']);self.assertEqual(u['buckets'][0]['unknown']['input'],1)
        p['version']=2;e['basis']['before']={k:0 for k in e['basis']['after']};e['basis']['before']['input']=200
        self.assertEqual(self.post('submit',p,self.a)[0],409);self.assertEqual(self.usage()['revision'],1)
        e['basis']['before']['input']=20;self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201);self.assertEqual(self.usage()['buckets'][0]['counts']['input'],80)

    def test_late_overlap_rolls_back_an_earlier_successful_usage_append(self):
        p=self.draft();self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        other=deepcopy(p);other['id']='atomic-late-conflict';other['entries'][0]['session']='native-second'
        self.assertEqual(self.op('session_register',{'id':'retro-second','session':'native-second','runtime':'codex','machine':'fixture-pc','role':'worker','tasks':['new/one'],'previous':'','status':'completed'},self.a)[0],201)
        self.assertEqual(self.post('submit',other,self.a)[0],201);self.assertEqual(self.decide(other)[0],409);self.assertEqual(self.usage()['revision'],1)
        self.assertEqual(len(self.call('/api/projects/alpha/operations',profile=self.admin)[1]['sessions']),1)

    def test_historical_scope_is_preserved_and_pending_review_is_in_se_workbench(self):
        p=self.draft();old=deepcopy(self.hub.store('alpha').get('new/one'));spec=deepcopy(old['spec']);spec['description']='Approved new task scope'
        self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'New scope retains historical records'},self.admin)[0],201)
        self.assertEqual(self.post('submit',p,self.a)[0],201)
        items=self.call('/api/projects/alpha/convergence',profile=self.admin)[1]['workbench']['items'];self.assertEqual(sum(e['kind']=='retrospective' for e in items),1)
        self.assertEqual(self.decide(p)[0],201)
        o=self.call('/api/projects/alpha/operations',profile=self.admin)[1];row=next(x for x in o['time_report']['tasks'] if x['task']=='new/one');self.assertEqual(row['current_work_seconds'],0);self.assertEqual(row['work_seconds'],80);self.assertFalse(row['time_complete'])
        self.assertEqual(next(iter(o['sessions'].values()))['scope'],old['scope_hash'])

    def test_archive_only_and_project_package_guard(self):
        p=self.draft();p['entries']=[]
        request={'request_id':uuid.uuid4().hex,'project_id':'beta','action':'submit','payload':p};self.assertEqual(self.call('/api/projects/alpha/retrospectives',request,self.a)[0],404)
        self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201);self.assertEqual(self.usage()['revision'],0)
        self.assertEqual(self.call('/api/projects/alpha/resources?origin=retrospective',profile=self.a)[1]['total'],1)

    def test_time_revision_requires_new_completeness_confirmation(self):
        p=self.draft();self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        current={'task':'new/one','scope':self.scope()['scope'],'summary':'Owner confirms reviewed current historical time coverage'}
        self.assertEqual(self.op('time_complete',current,self.a)[0],201)
        p['version']=2;p['entries'][1]['seconds']=40;self.assertEqual(self.post('submit',p,self.a)[0],201);self.assertEqual(self.decide(p)[0],201)
        report=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['time_report'];self.assertFalse(next(x for x in report['tasks'] if x['task']=='new/one')['time_complete']);self.assertEqual(self.usage()['revision'],1)
