"""Actual project HTTP gates, collaboration and compensating changes."""
import json,uuid,unittest
from copy import deepcopy
from . import test_git_tracking as fixture
from task_board.store import digest

EV=[{'path':'fixture/actual-review.txt','sha256':'b'*64}]
class WorkflowCase(unittest.TestCase):
    setUp=fixture.GitCase.setUp
    tearDown=fixture.GitCase.tearDown
    call=fixture.GitCase.call
    gov=fixture.GitCase.gov
    member=fixture.GitCase.member
    atomic=fixture.GitCase.atomic
    event=fixture.GitCase.event
    git=fixture.GitCase.git
    action=fixture.GitCase.action
    query=fixture.GitCase.query
    repository=fixture.GitCase.repository

    def op(self,action,p,profile=None,rid=None,revision=None):
        snap=self.call('/api/projects/alpha/operations',profile=profile or self.admin)[1]
        return self.call('/api/projects/alpha/operations',{'request_id':rid or uuid.uuid4().hex,'expected_revision':snap['revision'] if revision is None else revision,'action':action,'payload':p},profile or self.admin)
    def scope(self):
        t=self.hub.store('alpha').get('new/one');return {'task':'new/one','scope':t['scope_hash'],'scope_version':t['scope_version']}
    def claimed(self,baseline='a'*40):
        self.member();self.atomic(baseline=baseline);self.assertEqual(self.event('new/one','claim',{'summary':'Take bounded work'})[0],201)
    def thread_payload(self,kind='blocker',**kw):return {**self.scope(),'id':'question','kind':kind,'title':'Blocked on required input','body':'Missing fixed API input; cannot infer','to':['SE'],'pause':True,'affected_step':'integration',**kw}
    def plan(self,git_required=False):return {**self.scope(),'id':'accept-v1','items':[{'id':'AC1','deliverable':'D1','expected':'Actual behavior and negative boundary','method':'manual'}],'defaults':'','git_required':git_required,'repo':'main' if git_required else '','reason':'SE fixed scope and verification expectation'}
    def submit(self,commit='c'*40):return self.event('new/one','submit',{'summary':'Delivered bounded behavior','completeness':'full','deliverable_ids':['D1'],'implementation_commit':commit,'evidence':EV,'tests':'Actual checked behavior','remaining':'none','addresses':[]})
    def rollback(self,**kw):return {'id':'restore','kind':'task','object':'new/one','target':'current','tasks':['new/one'],'repo':'','target_ref':'','base':'','commits':[],'mainlines':{},'mapping':{},'reason':'Withdraw broken implementation and re-plan','data_plan':'No persistent data changed; original artifacts retained','tests':'Re-assess new task scope before dispatch',**kw}
    def approved(self,p):
        result=self.op('rollback_plan',p);self.assertEqual(result[0],201,result[1]);h=result[1]['manifest_hash']
        self.assertEqual(self.op('rollback_confirm',{'id':p['id'],'manifest_hash':h,'summary':'Owner checked actual impact'},self.a)[0],201)
        self.assertEqual(self.op('rollback_confirm',{'id':p['id'],'manifest_hash':h,'summary':'SE checked actual impact'})[0],201)
        result=self.op('rollback_approve',{'id':p['id'],'manifest_hash':h,'summary':'Approved exact compensating change'});self.assertEqual(result[0],201,result[1]);return h

    def test_blocker_thread_waits_for_real_decision_and_never_releases_exclusion(self):
        self.claimed();before=self.hub.store('alpha').get('new/one');p=self.thread_payload();rid=uuid.uuid4().hex;rev=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['revision']
        first=self.op('thread_open',p,self.a,rid,rev);self.assertEqual(first[0],201,first[1]);self.assertTrue(self.op('thread_open',p,self.a,rid,rev)[1]['replayed'])
        after=self.hub.store('alpha').get('new/one');self.assertEqual(before,after)
        self.assertEqual(self.submit()[0],409)
        self.assertEqual(self.op('thread_reply',{'thread':'question','body':'Have you tried the documented input?'})[0],201)
        self.assertEqual(self.op('thread_ack',{'thread':'question','summary':'A reply alone must not unlock'},self.a)[0],409)
        self.assertEqual(self.op('thread_decide',{'thread':'question','decision':'continue','summary':'Confirmed input version; remain in assigned scope','reference':''})[0],201)
        self.assertEqual(self.op('thread_ack',{'thread':'question','summary':'Input acquired and checked'},self.a)[0],201)
        self.assertEqual(self.submit()[0],201)
        wf=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1];self.assertEqual(wf['threads']['question']['status'],'resolved')
        self.assertTrue(all(s['end'] is not None for s in self.call('/api/projects/alpha/operations',profile=self.a)[1]['sessions'].values()))

    def test_foreign_members_readers_and_worker_decisions_cannot_cross_authority(self):
        self.claimed();self.assertEqual(self.op('thread_open',self.thread_payload(),self.a)[0],201)
        for suffix in ('workflow','workflow/task?task=new/one','workflow/inbox'):
            self.assertEqual(self.call('/api/projects/alpha/'+suffix,profile=self.b)[0],404)
        self.assertEqual(self.op('thread_decide',{'thread':'question','decision':'continue','summary':'self approval','reference':''},self.a)[0],403)
        self.assertEqual(self.op('thread_decide',{'thread':'question','decision':'changes','summary':'No actual change decision','reference':'missing'})[0],409)
        self.assertEqual(self.op('thread_open',self.thread_payload(id='other',to=['foreign-member']),self.a)[0],404)
        self.member(role='viewer');self.assertEqual(self.op('thread_reply',{'thread':'question','body':'write'},self.a)[0],403)

    def test_criteria_claim_review_exact_input_and_findings_close_independently(self):
        self.claimed();self.assertEqual(self.op('criteria_plan',self.plan())[0],201);self.assertEqual(self.submit()[0],409)
        claim={**self.scope(),'plan':'accept-v1','criterion':'AC1','input_anchor':'git:'+'c'*40,'summary':'Observed correct result','runs':[],'evidence':EV};result=self.op('criteria_claim',claim,self.a);self.assertEqual(result[0],201,result[1])
        self.assertEqual(self.submit()[0],201)
        sub=self.hub.store('alpha').get('new/one')['latest_submission']['id'];accept={'submission':sub,'summary':'Review','deliverable_ids':['D1'],'evidence':EV}
        self.assertEqual(self.event('new/one','accept',accept,self.admin)[0],409)
        verdict={**self.scope(),'plan':'accept-v1','criterion':'AC1','claim':result[1]['claim'],'result':'passed','summary':'Independent role checked exact input','evidence':EV};self.assertEqual(self.op('criteria_review',verdict)[0],201)
        finding={**self.scope(),'id':'issue','criterion':'AC1','description':'Boundary behavior wrong','acceptance':'Boundary rejects invalid input','blocking':True,'anchor':{'commit':'c'*40,'path':'src/one/a.py','line':1,'resource':''},'previous':''};self.assertEqual(self.op('review_open',finding)[0],201)
        self.assertEqual(self.event('new/one','accept',accept,self.admin)[0],409)
        disposition={**self.scope(),'finding':'issue','status':'rejected','input_anchor':'git:'+'c'*40,'summary':'Actual counterexample establishes report false','runs':[],'evidence':EV};d=self.op('review_disposition',disposition,self.a);self.assertEqual(d[0],201)
        wf=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.admin)[1];self.assertEqual(wf['findings']['issue']['status'],'awaiting_review')
        review={**self.scope(),'finding':'issue','disposition':wf['findings']['issue']['disposition']['id'],'result':'fixed','summary':'False fixed','evidence':EV};self.assertEqual(self.op('review_resolve',review)[0],409)
        review['result']='dismissed';self.assertEqual(self.op('review_resolve',review)[0],201)
        self.assertEqual(self.event('new/one','accept',accept,self.admin)[0],201)

    def test_git_checks_real_objects_exact_baseline_and_paths(self):
        self.repository();self.claimed(self.first)
        # Root -> feature only modifies feature.py, outside src/one.
        p={**self.scope(),'repo':'main','baseline':self.first,'implementation':self.feature,'target':self.head,'phase':'submit','reason':'Actual Git input'}
        self.assertEqual(self.op('git_check',p,self.a)[0],409)
        t=self.hub.store('alpha').get('new/one');spec=deepcopy(t['spec']);spec['allowed_paths']=['feature.py'];self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'SE approved actual file'},self.admin)[0],201)
        p.update(self.scope());self.assertEqual(self.op('git_check',p,self.a)[0],201)
        p['baseline']=self.before_merge;self.assertEqual(self.op('git_check',p)[0],409)
        p['baseline']=self.first;p['target']=self.first;self.assertEqual(self.op('git_check',p)[0],409)

    def test_task_rollback_preserves_all_chains_and_requires_every_confirmation(self):
        self.claimed();before=self.hub.store('alpha').get('new/one');p=self.rollback();result=self.op('rollback_plan',p);self.assertEqual(result[0],201,result[1]);h=result[1]['manifest_hash']
        self.assertEqual(self.op('rollback_approve',{'id':'restore','manifest_hash':h,'summary':'Cannot skip owner'})[0],409)
        for profile in (self.a,self.admin):self.assertEqual(self.op('rollback_confirm',{'id':'restore','manifest_hash':h,'summary':'Frozen impact confirmed'},profile)[0],201)
        self.assertEqual(self.op('rollback_approve',{'id':'restore','manifest_hash':h,'summary':'Approved'})[0],201)
        self.assertEqual(self.op('rollback_apply',{'id':'restore','manifest_hash':h,'summary':'Withdraw current delivery','runs':[],'commit':'','evidence':EV})[0],201)
        after=self.hub.store('alpha').get('new/one');self.assertEqual(after['scope_version'],before['scope_version']+1);self.assertEqual(after['status'],'planned');self.assertEqual(after['spec'],before['spec'])
        for suffix in ('verify','operations/verify','governance/verify'):self.assertTrue(self.call('/api/projects/alpha/'+suffix,profile=self.admin)[1]['passed'])

    def test_rollback_stale_preview_and_code_merge_mainline_fail_closed(self):
        self.repository();self.claimed(self.first);p=self.rollback(kind='code',object=self.feature,target='revert',repo='main',target_ref='refs/heads/main',base=self.head,commits=[self.merge],mapping={self.merge:['new/one']})
        self.assertEqual(self.op('rollback_plan',p)[0],409)
        p['mainlines']={self.merge:1};res=self.op('rollback_plan',p);self.assertEqual(res[0],201,res[1]);h=res[1]['manifest_hash']
        self.assertEqual(self.event('new/one','progress',{'summary':'New task facts'})[0],201)
        self.assertEqual(self.op('rollback_confirm',{'id':'restore','manifest_hash':h,'summary':'stale'},self.a)[0],409)

    def test_read_cursors_and_brief_keep_comment_scope_without_rewriting_task(self):
        self.claimed();self.op('thread_open',self.thread_payload(kind='discussion',pause=False),self.a)
        wf=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1];self.assertEqual(wf['unread']['question'],1)
        self.assertEqual(self.op('thread_read',{'thread':'question','count':99},self.a)[0],400)
        self.assertEqual(self.op('thread_read',{'thread':'question','count':1},self.a)[0],201)
        wf=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1];self.assertEqual(wf['unread']['question'],0)
        brief=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1];self.assertIn('question',brief['collaboration']['threads'])

    def restorer(self,kinds,targets):
        profile=self.hub.invite('alpha','restorer-one');self.member('restorer-one','restorer')
        self.assertEqual(self.op('rollback_executor',{'actor':'restorer-one','kinds':kinds,'targets':targets,'enabled':True,'reason':'Operator approved fixture-only targets'})[0],201)
        from tools.task_board_client import Client
        return profile,Client(self.url,{**profile,'url':self.url})

    def test_real_reverse_commit_candidate_checks_and_current_target_verification(self):
        self.repository();self.claimed(self.first);profile,client=self.restorer(['code'],['main'])
        p=self.rollback(kind='code',object=self.feature,target='reverse feature',repo='main',target_ref='refs/heads/main',base=self.head,commits=[self.feature],mapping={self.feature:['new/one']});h=self.approved(p)
        self.assertEqual(self.event('new/one','progress',{'summary':'Restorer cannot modify tasks'},profile)[0],403)
        from tools.rollback_runner import execute
        config={'project_id':'alpha','approved_plans':{'restore':h},'scratch':str(self.state/'restore-scratch'),'output':str(self.state/'restore-output'),'repositories':{'main':{'path':str(self.work)}},'checks':[['{python}','-c','from pathlib import Path; assert not Path("feature.py").exists(); assert Path("src/main.py").is_file()']]}
        import io,zipfile,sys
        from task_board.help import runner_kit
        from tools.owned_process import run
        kit=self.state/'downloaded-rollback-kit';kit.mkdir()
        with zipfile.ZipFile(io.BytesIO(runner_kit(True))) as archive:archive.extractall(kit)
        config_path=self.state/'rollback-local.json';config_path.write_text(json.dumps({**config,'url':self.url}));profile_path=self.state/'restorer-profile.json';profile_path.write_text(json.dumps({**profile,'url':self.url}))
        code,out,err=run([sys.executable,'-B',str(kit/'tools/rollback_runner.py'),'--config',str(config_path),'--profile',str(profile_path),'--id','restore'],cwd=kit,evidence=self.state/'standalone-rollback-audit',purpose='Actual downloaded standalone rollback executor',timeout=45)
        self.assertEqual(code,0,err.decode());self.assertIn('revision',json.loads(out)['result'])
        wf=self.call('/api/projects/alpha/workflow',profile=self.admin)[1];job=wf['rollbacks']['restore'];self.assertEqual(job['status'],'prepared');candidate=job['result']['commit'];self.assertNotEqual(candidate,self.head)
        self.assertFalse(list((self.state/'restore-scratch').iterdir()));self.assertEqual(self.git(['rev-parse','HEAD']),self.head,'original work repository must remain unchanged')
        bundle=self.state/'restore-output/restore/candidate.bundle';self.assertTrue(bundle.exists())
        mirror=self.state/'git-mirrors/alpha/main.git';self.git(['--git-dir='+str(mirror),'fetch','--quiet',str(bundle),'refs/heads/rollback/restore:refs/heads/main'])
        state=self.call('/api/projects/alpha/git',profile=self.admin)[1];repo=state['repos']['main'];refs=repo['refs'];refs['refs/heads/main']=candidate
        self.assertEqual(self.action('sync_result',{'repo':'main','repository':'fixture/private','request':repo['request'],'refs':refs,'error':'','default_branch':'refs/heads/main','alerts':[],'rewritten':[]})[0],201)
        apply={'id':'restore','manifest_hash':h,'summary':'Candidate now in target, actual checks passed','runs':[],'commit':candidate,'evidence':EV};self.assertEqual(self.op('rollback_apply',apply)[0],409,'candidate alone cannot replace exact final-input test record')
        self.assertEqual(self.op('case',{'id':'restore-check','version':'1','title':'Actual candidate checked by executor','kind':'manual','priority':'normal','targets':['task:new/one'],'preconditions':'Candidate in authorized mirror','inputs':candidate,'steps':'Review retained actual local executor command outputs and hashes','expected':'Feature absent, unrelated renamed source present','environment':'isolated fixture','resources':[]})[0],201)
        self.assertEqual(self.op('test_plan',{'task':'new/one','scope':self.scope()['scope'],'cases':['restore-check@1'],'reason':'Exact candidate post-integration check'})[0],201)
        run=self.op('manual_run',{'tasks':['new/one'],'scopes':{'new/one':self.scope()['scope']},'input_anchor':'git:'+candidate,'reason':'Different reviewer checked actual executor logs','results':[{'case':'restore-check@1','status':'passed','exit_code':None,'seconds':1,'summary':'Actual isolated reverse-commit checks succeeded'}],'evidence':job['result']['evidence'],'artifacts':[]});self.assertEqual(run[0],201,run[1]);apply['runs']=[run[1]['run']];self.assertEqual(self.op('rollback_apply',apply)[0],201)
        replay=execute(client,config,'restore');self.assertTrue(replay['replayed'],'lost result replay cannot execute reverse commits twice')

    def test_deployment_failure_restores_original_release_with_real_readback(self):
        self.claimed();profile,client=self.restorer(['deploy'],['fixture-service']);p=self.rollback(kind='deploy',object='fixture-service',target='old');h=self.approved(p)
        import sys
        state=self.state/'release.json';state.write_text(json.dumps({'release':'current','commit':'a'*40}))
        adapter=self.state/'deployment-fixture.py';adapter.write_text('import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1])\nif len(sys.argv)==2: print(p.read_text())\nelse:\n p.write_text(json.dumps({"release":sys.argv[2],"commit":sys.argv[3]}))\n if sys.argv[2]=="old": raise SystemExit(7)\n',encoding='utf8')
        from tools.rollback_runner import execute
        config={'project_id':'alpha','approved_plans':{'restore':h},'scratch':str(self.state/'restore-scratch'),'output':str(self.state/'restore-output'),'deployments':{'fixture-service':{'expected_current':'current','probe_argv':[sys.executable,str(adapter),str(state)],'releases':{'current':{'argv':[sys.executable,str(adapter),str(state),'current','a'*40],'commit':'a'*40,'compatible':True},'old':{'argv':[sys.executable,str(adapter),str(state),'old','b'*40],'commit':'b'*40,'compatible':True}}}}}
        execute(client,config,'restore');job=self.call('/api/projects/alpha/workflow',profile=self.admin)[1]['rollbacks']['restore'];self.assertEqual(job['status'],'failed');self.assertIn('original deployment restored',job['result']['summary']);self.assertEqual(json.loads(state.read_text())['release'],'current');self.assertFalse(list((self.state/'restore-scratch').iterdir()))

    def test_module_recovery_creates_new_unreviewed_version_and_keeps_original(self):
        self.claimed();m={'id':'feature','version':'1','title':'Original feature','parent':'','goal':'goal','scope':'bounded','non_goals':'other','owner':'root','path':'research then implementation','inputs':[],'outputs':[],'interfaces':[],'no_interface_reason':'isolated module','risks':'known','unknowns':[],'planning_tasks':[],'decisions':[],'depends_on':[],'acceptance':'actual check','stage':'design','evidence':EV}
        self.assertEqual(self.gov('module_plan',m)[0],201);m2={**m,'version':'2','goal':'Revised goal'};self.assertEqual(self.gov('module_plan',m2)[0],201)
        p=self.rollback(kind='module',object='feature',target='feature@1');h=self.approved(p)
        result=self.op('rollback_apply',{'id':'restore','manifest_hash':h,'summary':'Restore original design as a new reviewed-later version','runs':[],'commit':'','evidence':EV});self.assertEqual(result[0],201,result[1])
        g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];self.assertEqual(g['modules']['feature@1']['goal'],'goal');self.assertEqual(g['module_heads']['feature'],'feature@restore-restore');self.assertFalse(g['module_readiness']['feature@restore-restore']['ready']);self.assertTrue(self.call('/api/projects/alpha/governance/verify',profile=self.admin)[1]['passed'])

    def test_new_public_fields_reject_wrong_types_without_server_errors(self):
        self.claimed()
        for action,p in [('thread_reply',{'thread':[],'body':'x'}),('rollback_confirm',{'id':{},'manifest_hash':'x','summary':'x'}),('criteria_plan',{**self.plan(),'defaults':[]}),('review_open',{**self.scope(),'id':[]})]:self.assertEqual(self.op(action,p)[0],400,(action,p))

    def test_merge_and_native_require_exact_final_input_not_ancestor_test(self):
        self.repository();self.member();self.atomic(paths=['feature.py'],baseline=self.first);self.event('new/one','claim',{'summary':'Take actual fixture'})
        self.assertEqual(self.op('criteria_plan',self.plan(True))[0],201)
        claim=self.op('criteria_claim',{**self.scope(),'plan':'accept-v1','criterion':'AC1','input_anchor':'git:'+self.feature,'summary':'Observed feature version','runs':[],'evidence':EV},self.a)
        self.assertEqual(self.op('criteria_review',{**self.scope(),'plan':'accept-v1','criterion':'AC1','claim':claim[1]['claim'],'result':'passed','summary':'Checked submitted version','evidence':EV})[0],201)
        check={**self.scope(),'repo':'main','baseline':self.first,'implementation':self.feature,'target':self.feature,'phase':'submit','reason':'Actual input'}
        self.assertEqual(self.op('git_check',check)[0],201);self.assertEqual(self.submit(self.feature)[0],201);sub=self.hub.store('alpha').get('new/one')['latest_submission']['id']
        self.assertEqual(self.event('new/one','accept',{'submission':sub,'summary':'Reviewed','deliverable_ids':['D1'],'evidence':EV},self.admin)[0],201)
        self.assertEqual(self.op('criteria_claim',{**self.scope(),'plan':'accept-v1','criterion':'AC1','input_anchor':'git:'+self.feature,'summary':'Cannot rewrite accepted claim','runs':[],'evidence':EV},self.a)[0],409)
        self.assertEqual(self.op('git_check',{**check,'target':self.head,'phase':'merge'})[0],201)
        self.op('case',{'id':'final','version':'1','title':'Final input review','kind':'manual','priority':'normal','targets':['task:new/one'],'preconditions':'Known Git fixture','inputs':'exact commit','steps':'Inspect actual Git fixture files','expected':'Unrelated files retained','environment':'fixture','resources':[]})
        self.op('test_plan',{'task':'new/one','scope':self.scope()['scope'],'cases':['final@1'],'reason':'Final target check'})
        def observed(anchor):return self.op('manual_run',{'tasks':['new/one'],'scopes':{'new/one':self.scope()['scope']},'input_anchor':'git:'+anchor,'reason':'Checked actual selected fixture input','results':[{'case':'final@1','status':'passed','exit_code':None,'seconds':1,'summary':'Expected actual fixture content'}],'evidence':EV,'artifacts':[]})
        observed(self.feature);merge={'submission':sub,'summary':'Integrate exact input','commit':self.head,'evidence':EV};self.assertEqual(self.event('new/one','merge',merge,self.admin)[0],409)
        observed(self.head);self.assertEqual(self.event('new/one','merge',merge,self.admin)[0],201)
        self.assertEqual(self.event('new/one','native',merge,self.admin)[0],409)
        self.assertEqual(self.op('git_check',{**check,'target':self.head,'phase':'native'})[0],201);self.assertEqual(self.event('new/one','native',merge,self.admin)[0],201)

    def test_project_defaults_are_fixed_and_scope_changes_invalidate_old_plan(self):
        self.claimed();self.op('criteria_defaults',{'id':'done-v1','items':['Actual preview inspected'],'reason':'SE completion policy'})
        self.assertEqual(self.op('criteria_plan',{**self.plan(),'defaults':'done-v1'})[0],201)
        self.op('criteria_defaults',{'id':'done-v2','items':['Additional project check'],'reason':'New default for later tasks only'})
        p=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['current_plan'];self.assertEqual([i['id'] for i in p['items']],['AC1','DOD-1']);self.assertEqual(p['items'][-1]['expected'],'Actual preview inspected')
        spec=deepcopy(self.hub.store('alpha').get('new/one')['spec']);spec['description']='New scope after clarification';self.event('new/one','scope',{'spec':spec,'reason':'Changed input'},self.admin)
        self.assertIsNone(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['current_plan']);self.assertEqual(self.submit()[0],409)

    def test_precise_knowledge_references_keep_unrelated_material_edits_out_of_scope(self):
        self.claimed();k={'background':'context','goals':'goal','non_goals':'other','constraints':'bounded','materials':[{'title':'required','location':'docs/required','version':'1','sha256':'a'*64}],'entries':[]};self.gov('knowledge',k)
        m={'id':'feature','version':'1','title':'Feature','parent':'','goal':'goal','scope':'bounded','non_goals':'other','owner':'root','path':'known','inputs':[],'outputs':[],'interfaces':[],'no_interface_reason':'isolated','risks':'known','unknowns':[],'planning_tasks':[],'decisions':[],'depends_on':[],'acceptance':'check','stage':'design','evidence':EV,'knowledge_refs':['docs/required']};self.assertEqual(self.gov('module_plan',m)[0],201)
        def scope():return self.call('/api/projects/alpha/governance',profile=self.admin)[1]['module_readiness']['feature@1']['scope']
        original=scope();k['materials'].append({'title':'unrelated guide','location':'help/new','version':'1','sha256':'b'*64});self.gov('knowledge',k);self.assertEqual(scope(),original)
        k['materials'][0]['sha256']='c'*64;self.gov('knowledge',k);self.assertNotEqual(scope(),original)

    def test_unrelated_operations_do_not_break_comments_but_new_facts_stale_decisions(self):
        self.claimed();self.op('thread_open',self.thread_payload(),self.a);revision=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['revision']
        decision={'thread':'question','decision':'continue','summary':'SE checked known obstacle','reference':''}
        self.op('time_change',{'task':'new/one','scope':self.scope()['scope'],'mode':'work','phase':'review','reason':'Independent SE review clock','rework':False})
        r=self.op('thread_decide',decision,revision=revision);self.assertEqual(r[0],201,r[1]);self.assertIn('independent_changes_since',r[1])
        revision=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['revision'];self.op('thread_reply',{'thread':'question','body':'New input fact requires consideration'},self.a)
        self.assertEqual(self.op('thread_decide',decision,revision=revision)[0],409,'new facts on this thread must not be overwritten by an old decision')
