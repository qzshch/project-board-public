"""Resource metadata and handoff privacy over real project HTTP fixtures."""
from copy import deepcopy
import hashlib,json,unittest,uuid
from urllib.parse import urlencode
from . import test_governance as fixture
from task_board.resources import run_records
from task_board.governance import Governance


class ResourcesCase(unittest.TestCase):
    setUp=fixture.GovernanceCase.setUp
    tearDown=fixture.GovernanceCase.tearDown
    call=fixture.GovernanceCase.call
    gov=fixture.GovernanceCase.gov
    member=fixture.GovernanceCase.member
    atomic=fixture.GovernanceCase.atomic
    event=fixture.GovernanceCase.event

    def payload(self,id='research',**kw):
        return {'id':id,'title':'研究入口','category':'research','description':'本地原始调研与材料，不放Git','owner':'root','visibility':'project',
            'locations':[{'kind':'nas','location':'/volume1/alpha/research','machine':'NAS','access':'同一Tailscale内按本项目文件权限访问；向SE申请，不分发实例凭据'}],
            'version':'live','mutable':True,'integrity':{'kind':'none','sha256':'','subject':''},'availability':'unknown',
            'retention':'保留原件；缓存另按负责人核定规则清理','tasks':[],'modules':[],'asset_refs':[],
            'usage_notes':'目录登记不等于文件已校验或获共享许可','reason':'实际项目资料接手入口',**kw}

    def listing(self,profile=None,**query):
        return self.call('/api/projects/alpha/resources?'+urlencode(query),profile=profile or self.a)

    def test_catalog_is_project_scoped_and_privileged_metadata_stays_hidden(self):
        for id,visibility,loc in [('research','project','project-folder'),('managed','managers','secret-manager-folder'),('operator-state','operator','secret-operator-folder')]:
            p=self.payload(id,visibility=visibility);p['locations'][0]['location']='/volume1/alpha/'+loc
            self.assertEqual(self.gov('resource_register',p)[0],201)
        self.assertEqual({e['id'] for e in self.listing()[1]['entries']},{'research'})
        self.assertEqual({e['id'] for e in self.listing(self.reviewer)[1]['entries']},{'research','managed'})
        self.assertEqual(len(self.listing(self.admin)[1]['entries']),3)
        for path in ('governance','governance/export','search?q=secret','resources?category=research'):
            data=self.call('/api/projects/alpha/'+path,profile=self.a)[1];serialized=json.dumps(data)
            self.assertNotIn('secret-manager-folder',serialized);self.assertNotIn('secret-operator-folder',serialized)
        for path in ('resources','resources/research','resources/research/history'):
            status,body,headers=self.call('/api/projects/alpha/'+path,profile=self.b);self.assertEqual(status,404);self.assertNotIn('ETag',headers)
        self.assertEqual(self.call('/api/projects/alpha/resources/operator-state',profile=self.reviewer)[0],404)
        self.assertEqual(self.call('/api/projects/alpha/resources/managed/history',profile=self.a)[0],404)

    def test_metadata_updates_are_versioned_idempotent_and_retirement_never_deletes_files(self):
        file=self.state/'keep.txt';file.write_text('Keep original bytes');p=self.payload();p['locations'][0].update(kind='local',location=str(file),machine='fixture computer')
        rev=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['revision'];rid=uuid.uuid4().hex
        first=self.gov('resource_register',p,rid=rid,revision=rev);self.assertEqual(first[0],201)
        self.assertTrue(self.gov('resource_register',p,rid=rid,revision=rev)[1]['replayed'])
        changed={**deepcopy(p),'expected_version':1,'title':'新入口标题','reason':'位置原件不变，只补充接手说明'};self.assertEqual(self.gov('resource_update',changed)[0],201)
        self.assertEqual(self.gov('resource_update',changed)[0],409)
        self.assertEqual(self.gov('resource_retire',{'id':'research','expected_version':2,'reason':'另有新入口，保留原件和历史'})[0],201)
        self.assertTrue(file.exists());self.assertEqual(file.read_text(),'Keep original bytes')
        self.assertEqual(self.listing()[1]['entries'],[])
        history=self.call('/api/projects/alpha/resources/research/history',profile=self.admin)[1]['versions'];self.assertEqual([e['entry_version'] for e in history],[1,2,3]);self.assertEqual(history[-1]['status'],'retired')
        self.assertTrue(Governance(self.hub.store('alpha')).verify()['passed'])

    def test_project_owner_cannot_change_operator_entry_and_credentials_are_not_catalogued(self):
        operator=self.payload('operator-state',visibility='operator');self.assertEqual(self.gov('resource_register',operator,profile=self.reviewer)[0],403)
        self.assertEqual(self.gov('resource_register',operator)[0],201)
        self.assertEqual(self.gov('resource_update',{**operator,'expected_version':1},profile=self.reviewer)[0],403)
        for location in ('/volume1/alpha/_private/admin.json','https://example.org/x?token=secret','https://u:p@example.org/data','G:/alpha/.ssh/id_rsa','G:/alpha/.env','http://[bad'):
            p=self.payload();p['locations'][0]['location']=location;self.assertEqual(self.gov('resource_register',p)[0],400,location)
        self.assertEqual(self.gov('resource_register',self.payload(),profile=self.a)[0],403)
        self.member(role='tracker');self.assertEqual(self.gov('resource_register',self.payload(),profile=self.a)[0],403)
        p=self.payload(mutable=False);self.assertEqual(self.gov('resource_register',p)[0],400)
        p['integrity']={'kind':'manifest','sha256':'0'*64,'subject':'MANIFEST.json'};self.assertEqual(self.gov('resource_register',p)[0],400)

    def test_brief_includes_relevant_entries_with_scope_safe_historical_metadata(self):
        self.atomic();self.atomic('second',['second/'])
        for p in [self.payload(),self.payload('matching',tasks=['new/one']),self.payload('other-task',tasks=['second']),self.payload('managed',visibility='managers'),self.payload('operator-state',visibility='operator')]:
            self.assertEqual(self.gov('resource_register',p)[0],201)
        brief=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1]['resource_directory'];self.assertEqual({e['id'] for e in brief['entries']},{'research','matching'});self.assertIn('/alpha/resources',brief['endpoint'])
        manager=self.call('/api/projects/alpha/brief?task=new/one',profile=self.reviewer)[1]['resource_directory'];self.assertIn('managed',{e['id'] for e in manager['entries']});self.assertNotIn('operator-state',json.dumps(manager))
        self.assertEqual(self.listing(task='foreign-task')[0],404)
        self.assertEqual(self.listing(category='art')[1]['total'],0)
        self.assertEqual(self.listing(q='研究',limit=1)[1]['next'],1)

    def test_handoff_rechecks_shared_directory_changes_but_does_not_transfer_operator_scope(self):
        next=self.hub.invite('alpha','next-se');self.member(actor='next-se',role='se');self.member(role='owner')
        p=self.payload();self.gov('resource_register',p);operator=self.payload('operator-state',visibility='operator');self.gov('resource_register',operator)
        propose={'to':'next-se','risks':'核对本地NAS入口和权限','materials':['resources@current'],'reason':'按实际目录接手'}
        self.assertEqual(self.gov('handoff_propose',propose,profile=self.a)[0],201);h=self.call('/api/projects/alpha/governance',profile=self.a)[1]['handoff']
        self.gov('resource_update',{**p,'expected_version':1,'version':'live-2','reason':'目录迁移后需要重新确认'})
        self.assertEqual(self.gov('handoff_accept',{'scope':h['scope'],'summary':'旧入口不可误接受'},profile=next)[0],409)
        self.gov('handoff_propose',propose,profile=self.a);h=self.call('/api/projects/alpha/governance',profile=self.a)[1]['handoff']
        self.gov('resource_update',{**operator,'expected_version':1,'version':'admin-2','reason':'实例独立资料变化，不转交项目SE'})
        self.assertEqual(self.gov('handoff_accept',{'scope':h['scope'],'summary':'已核对当前项目目录，实例资料仍需单独授权'},profile=next)[0],201)
        data=self.listing(next)[1];self.assertNotIn('operator-state',json.dumps(data))

    def test_history_never_reveals_previously_private_versions_to_current_public_readers(self):
        p=self.payload(visibility='managers');self.gov('resource_register',p)
        p2={**deepcopy(p),'visibility':'project','expected_version':1,'description':'脱敏后共享','reason':'审核后只公开当前资料入口'};self.gov('resource_update',p2)
        history=self.call('/api/projects/alpha/resources/research/history',profile=self.a)[1]['versions'];self.assertEqual([e['entry_version'] for e in history],[2])
        history=self.call('/api/projects/alpha/resources/research/history',profile=self.reviewer)[1]['versions'];self.assertEqual([e['entry_version'] for e in history],[1,2])

    def test_run_receipts_become_readonly_metadata_without_claiming_current_file_availability(self):
        h=hashlib.sha256(b'actual fixture content').hexdigest();a={'path':'report.json','sha256':h,'location':'/nas/alpha/output/report.json'}
        op={'runs':{'r1':{'id':'r1','suite':'checks@1','finished':2,'status':'failed','input_anchor':'git:'+'a'*40,'artifacts':[a,{'path':'case.log','sha256':h,'location':'/nas/alpha/output/case.log'},{'path':'private.json','sha256':h,'location':'/nas/alpha/_private/key.json'}],'scopes':{'new/one':'b'*64},'scope_versions':{'new/one':1},'lease':{'actor':'project-runner'},'environment':'NAS fixture'}}}
        rows=run_records(op,{'assets':{'result@1':{'sha256':h,'location':a['location']}}})
        self.assertEqual(len(rows),2);self.assertEqual({r['category'] for r in rows},{'test_records','logs'});self.assertTrue(all(r['availability']=='unknown' and r['test_status']=='failed' for r in rows));self.assertEqual(rows[0]['asset_refs'],['result@1'])

    def test_existing_knowledge_entries_are_visible_without_guessing_category_or_granting_access(self):
        item={'title':'既有材料','location':'https://example.org/board?project=alpha','version':'original','sha256':'a'*64}
        private={**item,'title':'旧凭据位置','location':'/nas/_private/admin.json'}
        self.gov('knowledge',{'background':'project','goals':'goal','non_goals':'other','constraints':'private','materials':[item,private],'entries':[]})
        before=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['revision']
        data=self.listing(origin='knowledge')[1];self.assertEqual(data['total'],1)
        entry=data['entries'][0];self.assertEqual(entry['category'],'other');self.assertEqual(entry['availability'],'unknown');self.assertEqual(entry['integrity']['sha256'],item['sha256'])
        self.assertEqual(data['revision'],before)
        self.assertEqual(len(self.call('/api/projects/alpha/resources/'+entry['id']+'/history',profile=self.a)[1]['versions']),1)
        p=self.payload(visibility='managers',mutable=False,integrity={'kind':'file','sha256':item['sha256'],'subject':item['title']})
        p['locations'][0].update(kind='http',location=item['location'])
        self.gov('resource_register',p)
        self.assertEqual(self.listing(origin='knowledge')[1]['total'],1,'hidden manager metadata must not conceal pre-existing public knowledge')
        self.assertEqual(self.listing(self.reviewer,origin='knowledge')[1]['total'],0)
