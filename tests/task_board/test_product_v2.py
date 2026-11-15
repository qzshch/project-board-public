"""Product decisions and usage behavior through the real project HTTP API."""
import unittest, uuid, time
from copy import deepcopy
from unittest.mock import patch
from . import test_workflow as w
from task_board.usage import Usage
from task_board.git_onboarding import Onboarding

class ProductCase(unittest.TestCase):
    setUp=w.WorkflowCase.setUp;tearDown=w.WorkflowCase.tearDown
    call=w.WorkflowCase.call;gov=w.WorkflowCase.gov;member=w.WorkflowCase.member
    atomic=w.WorkflowCase.atomic;event=w.WorkflowCase.event;op=w.WorkflowCase.op
    scope=w.WorkflowCase.scope;claimed=w.WorkflowCase.claimed;submit=w.WorkflowCase.submit
    git=w.WorkflowCase.git;action=w.WorkflowCase.action;query=w.WorkflowCase.query;repository=w.WorkflowCase.repository

    def products(self):return self.call('/api/projects/alpha/product',profile=self.admin)[1]
    def create(self,kind='requirement',id='REQ-one'):
        d={'title':'Project outcome','body':'Original user goal','audience':'Project users','outcome':'Correct visible behavior','scope':'Parser only','non_goals':'No migration','owner':'owner','criteria':[{'id':'A1','expected':'Observed exact behavior'},{'id':'A2','expected':'Retain unrelated behavior'}]}
        if kind=='defect':d={k:v for k,v in d.items() if k!='criteria'};d.update(actual='Observed wrong output',expected='Known expected output',environment='fixture',observed_version='git:'+'a'*40,steps='Input then inspect output')
        self.assertEqual(self.op('product_open',{'id':id,'kind':kind,'definition':d,'sources':[]})[0],201)
        return self.products()['items'][id]
    def operation(self,action,e,**kw):return self.op(action,{'id':e['id'],'expected_version':e['version'],'reason':'Actual product decision',**kw})
    def test_draft_confirm_change_stale_and_legacy_cannot_bypass(self):
        e=self.create();self.assertEqual(e['status'],'idea');self.assertIsNone(e['commitment'])
        self.assertEqual(self.operation('product_confirm',e)[0],201);e=self.products()['items'][e['id']]
        self.assertEqual(self.operation('product_edit',e,definition=e['definition'])[0],409)
        self.assertEqual(self.op('intake_decide',{'id':e['id'],'expected_version':e['version'],'status':'resolved','reason':'Bypass','duplicate':'','tasks':[],'modules':[]})[0],409)
        d=deepcopy(e['definition']);d['criteria'][0]['expected']='Changed result'
        self.assertEqual(self.operation('product_change',e,change='change-1',definition=d)[0],201)
        s=self.products();e=s['items'][e['id']];c=s['changes']['change-1'];self.assertEqual(c['impact']['criteria'],['A1']);self.assertEqual(e['definition_version'],1)
        self.assertEqual(self.operation('product_change_decide',e,change='change-1',decision='approve',impact_hash='0'*64,migration='No task exists')[0],409)
        self.assertEqual(self.operation('product_change_decide',e,change='change-1',decision='approve',impact_hash=c['impact_hash'],migration='No task exists')[0],201)
        self.assertEqual(self.products()['items'][e['id']]['definitions']['1']['criteria'][0]['expected'],'Observed exact behavior')
        self.assertEqual(self.operation('product_confirm',e)[0],409)
    def test_worker_captures_but_cannot_confirm_and_cross_project_denied(self):
        self.claimed();d={'id':'worker-idea','kind':'requirement','definition':{'title':'Small idea','body':'Post-project idea'},'sources':[{'kind':'task','id':'new/one'}]}
        self.assertEqual(self.op('product_open',d,self.a)[0],201)
        self.assertEqual(self.op('product_confirm',{'id':'worker-idea','expected_version':1,'reason':'Self approve'},self.a)[0],403)
        for endpoint in ('product','usage','sessions','git-onboarding?repo=main'):self.assertEqual(self.call('/api/projects/alpha/'+endpoint,profile=self.b)[0],404)
    def test_old_intake_adoption_preserves_historical_resolution(self):
        self.op('intake_open',{'id':'old','kind':'requirement','title':'History','body':'Old recorded scope','sources':[]})
        self.op('intake_decide',{'id':'old','expected_version':1,'status':'resolved','reason':'Legacy only','duplicate':'','tasks':[],'modules':[]})
        self.assertEqual(self.operation('product_adopt',self.products()['items']['old'])[0],201)
        e=self.products()['items']['old'];self.assertEqual(e['legacy_disposition']['status'],'resolved');self.assertEqual(e['status'],'idea');self.assertFalse(e['confirmed'])
    def test_product_verification_requires_current_task_acceptance(self):
        self.claimed();e=self.create();self.operation('product_confirm',e);e=self.products()['items'][e['id']]
        self.assertEqual(self.operation('product_link',e,criterion='A1',task='new/one',task_scope=self.scope()['scope'])[0],201);e=self.products()['items'][e['id']]
        self.assertEqual(self.operation('product_verify',e,criterion='A1',evidence=w.EV)[0],409)
        self.submit();t=self.hub.store('alpha').get('new/one');self.event('new/one','accept',{'submission':t['latest_submission']['id'],'summary':'Reviewed task','deliverable_ids':['D1'],'evidence':w.EV},self.admin)
        self.assertEqual(self.operation('product_verify',e,criterion='A1',evidence=w.EV)[0],201)
        e=self.products()['items'][e['id']];self.assertNotEqual(e['status'],'achieved');self.assertIn('A1',e['verifications'])
        self.assertEqual(self.operation('product_link',e,criterion='A1',task='new/one',task_scope=self.scope()['scope'])[0],201);self.assertNotIn('A1',self.products()['items'][e['id']]['verifications'])
    def session(self):
        self.claimed();p={'id':'ref-one','session':'native-session-123','runtime':'codex','machine':'fixture-machine','role':'worker','tasks':['new/one'],'previous':'','status':'active','attempt':'','locator':'G:/fixture'}
        self.assertEqual(self.op('session_register',p,self.a)[0],201);return p
    def sample(self,**kw):return {'sample':'request-1','revision':1,'session':'native-session-123','task':'new/one','phase':'implementation','model':'fixture-model','source':'observed','mode':'call','epoch':'epoch-1','ordinal':1,'from_start':True,'occurred':time.time()-10,'counters':{'input':100,'output':20,'cache_read':60,'cache_write':0,'reasoning':5},'origin':{'path':'G:/fixture/usage.jsonl','sha256':'b'*64},**kw}
    def usage(self,p,profile=None):return self.call('/api/projects/alpha/usage',p,profile or self.a)
    def report(self):return self.call('/api/projects/alpha/usage',profile=self.admin)[1]
    def test_usage_revision_dedup_subsets_and_unknown(self):
        self.session();p=self.sample();self.assertEqual(self.usage(p)[0],201);self.assertTrue(self.usage(p)[1]['replayed'])
        q=deepcopy(p);q['counters']['input']=101;self.assertEqual(self.usage(q)[0],409);q['revision']=2;self.assertEqual(self.usage(q)[0],201)
        data=self.report();self.assertEqual(data['buckets'][0]['counts']['input'],101);self.assertEqual(data['buckets'][0]['counts']['output'],20);self.assertEqual(data['coverage']['observed_sessions'],1);self.assertTrue(data['chain_valid'])
        p=self.sample(sample='request-2',counters=dict.fromkeys(('input','output','cache_read','cache_write','reasoning')));self.assertEqual(self.usage(p)[0],201);self.assertEqual(self.report()['buckets'][0]['unknown']['input'],1)
        self.assertEqual(self.usage(self.sample(sample='bad',counters={'input':1,'output':0,'cache_read':2,'cache_write':0,'reasoning':0}))[0],400)
    def test_cumulative_attach_reset_and_separate_sources(self):
        self.session();p=self.sample(mode='cumulative',from_start=False);self.assertEqual(self.usage(p)[0],201)
        p=self.sample(sample='cum-2',mode='cumulative',ordinal=2,from_start=False,counters={'input':150,'output':30,'cache_read':80,'cache_write':0,'reasoning':7});self.usage(p)
        data=self.report();b=data['buckets'][0];self.assertEqual(b['counts']['input'],50);self.assertEqual(b['unknown']['input'],1)
        p=self.sample(sample='reset',mode='cumulative',ordinal=3,from_start=False,counters={'input':5,'output':2,'cache_read':0,'cache_write':0,'reasoning':0});self.usage(p)
        self.assertEqual(self.report()['buckets'][0]['anomalies'],1)
        self.usage(self.sample(sample='estimate',source='estimated'));self.assertEqual(len(self.report()['buckets']),2)
    def test_usage_unbound_session_and_fake_task_are_denied(self):
        self.session();self.assertEqual(self.usage(self.sample(session='foreign'))[0],409);self.assertEqual(self.usage(self.sample(task='foreign/task'))[0],404)
        self.member(role='viewer');self.assertEqual(self.usage(self.sample())[0],403)
    def test_session_ids_references_and_unknown_are_not_control_authority(self):
        p=self.session();p.update(id='ref-two',session='',previous='ref-one',status='unknown');self.assertEqual(self.op('session_register',p,self.a)[0],201)
        data=self.call('/api/projects/alpha/sessions',profile=self.a)[1];self.assertEqual(data['references']['ref-one']['session'],'native-session-123');self.assertEqual(data['managed'],[]);self.assertEqual(data['references']['ref-two']['session'],'')
        self.assertEqual(self.op('session_register',{**p,'id':'bad','previous':'missing'},self.a)[0],404)
    def test_defect_cannot_close_by_disposition_or_empty_retest(self):
        self.claimed();e=self.create('defect','BUG-one');self.operation('product_confirm',e);e=self.products()['items'][e['id']]
        self.assertEqual(self.operation('product_dispose',e,status='closed',duplicate='')[0],400)
        p={'input_anchor':'git:'+'c'*40,'environment':'fixture','runs':[],'evidence':w.EV,'result':'passed'};self.assertEqual(self.operation('defect_retest',e,**p)[0],409)
        self.assertEqual(self.operation('defect_reopen',e)[0],201)
    def test_defect_exact_retest_close_reopen_and_finding_promotion_idempotence(self):
        self.claimed();e=self.create('defect','BUG-exact');self.operation('product_confirm',e);e=self.products()['items'][e['id']]
        self.operation('product_link',e,criterion='',task='new/one',task_scope=self.scope()['scope']);e=self.products()['items'][e['id']]
        case={'id':'fix-check','version':'1','title':'Reproduce original defect','kind':'manual','priority':'normal','targets':['task:new/one'],'preconditions':'Fixed repair','inputs':'Original repro input','steps':'Reproduce then check','expected':'Expected output','environment':'fixture','resources':[]}
        self.assertEqual(self.op('case',case)[0],201);self.op('test_plan',{'task':'new/one','scope':self.scope()['scope'],'cases':['fix-check@1'],'reason':'Exact regression'})
        run=self.op('manual_run',{'tasks':['new/one'],'scopes':{'new/one':self.scope()['scope']},'input_anchor':'git:'+'c'*40,'reason':'Actual defect retest','results':[{'case':'fix-check@1','status':'passed','exit_code':None,'seconds':1,'summary':'Expected output observed'}],'evidence':w.EV,'artifacts':[]});self.assertEqual(run[0],201,run[1])
        self.submit();t=self.hub.store('alpha').get('new/one');self.assertEqual(self.event('new/one','accept',{'submission':t['latest_submission']['id'],'summary':'Verified repair','deliverable_ids':['D1'],'evidence':w.EV},self.admin)[0],201)
        p={'input_anchor':'git:'+'d'*40,'environment':'fixture','runs':[run[1]['run']],'evidence':w.EV,'result':'passed'};self.assertEqual(self.operation('defect_retest',e,**p)[0],409);p['input_anchor']='git:'+'c'*40
        self.assertEqual(self.operation('defect_retest',e,**p)[0],201);e=self.products()['items'][e['id']];self.assertEqual(e['status'],'closed');self.operation('defect_reopen',e);self.assertEqual(self.products()['items'][e['id']]['status'],'reopened')
        f={**self.scope(),'id':'finding-exact','criterion':'','description':'Preserve observed defect','acceptance':'Original expectation','blocking':True,'anchor':{'commit':'','path':'','line':0,'resource':''},'previous':''};self.assertEqual(self.op('review_open',f)[0],201)
        p={'finding':'finding-exact','id':'BUG-promoted','reason':'Needs cross-version followup'};a=self.op('finding_promote',p);self.assertEqual(a[0],201,a[1]);b=self.op('finding_promote',{**p,'id':'different'});self.assertEqual(b[1]['intake'],'BUG-promoted');self.assertTrue(b[1]['already_promoted'])
        self.assertEqual(self.products()['items']['BUG-promoted']['title'],'Preserve observed defect')
        self.assertEqual(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.admin)[1]['findings']['finding-exact']['status'],'open')
    def test_git_onboarding_scoped_public_key_and_external_readonly_verification(self):
        self.action('bind',{'id':'main','repository':'example/project','title':'Code','reason':'Approved project code'})
        path='/api/projects/alpha/git-onboarding';self.assertEqual(self.call(path+'/request',{'repo':'main'},self.a)[0],403)
        status=self.call(path+'/request',{'repo':'main'},self.admin);self.assertEqual(status[0],201,status[1]);self.assertIn('public_key',status[1]);self.assertNotIn('key',status[1]);self.assertEqual(self.call(path,profile=self.admin)[0],400)
        self.assertEqual(self.call(path+'/authorize',{'repo':'main','grant':'ghp_classic-not-accepted'},self.admin)[0],400)
        pub=status[1]['public_key'];calls=[]
        def api(token,method,url,body=None):
            calls.append((method,url,body))
            if url.endswith('/project'):return {'full_name':'example/project'}
            if method=='GET' and '/keys?' in url:return []
            return {'id':42,'key':pub,'read_only':True}
        with patch('task_board.git_onboarding.github',api),patch.object(Onboarding,'sync',return_value={'stage':'ready'}):
            result=self.call(path+'/authorize',{'repo':'main','grant':'github_pat_'+'x'*60},self.admin);self.assertEqual(result[0],201,result[1])
        self.assertTrue(next(c for c in calls if c[0]=='POST')[2]['read_only'])
        config=(self.state/'_private/github.json').read_text();self.assertNotIn('github_pat_',config)
