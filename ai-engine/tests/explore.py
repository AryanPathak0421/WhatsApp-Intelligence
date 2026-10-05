import sys; sys.path.insert(0,'tests')
from scenario_chat import CHAT
from app.parsers.whatsapp import WhatsAppParser
from app.intelligence.types import Msg
from app.intelligence.pipeline import analyze
msgs=[Msg.from_parsed(m) for m in WhatsAppParser().parse_text(CHAT)]
r=analyze(msgs)
print({k:v['role'] for k,v in r['roles'].items()})
for t in r['tasks']: print('TASK',t['title'],'|',t['assigned_to'],'|',t['status'],'|',t['deadline_text'],'|',t['confidence'],t['needs_review'],t['review_reasons'],t['external_dependency'])
for c in r['client_pending']: print('CP',c['title'],c['type'],c['status'],c['age_days'],c['impact'])
for c in r['requirement_changes']: print('RC',c['key'],c['old_value'],'->',c['new_value'],c['changed_by'])
for c in r['conflicts']: print('CF',c['topic'],c['severity'],c['statement_a']['text'],'||',c['statement_b']['text'])
print('RISK',r['risk']['score'],r['risk']['level'])
for k in r['risk']['risks']: print('  ',k['severity'],k['title'])
