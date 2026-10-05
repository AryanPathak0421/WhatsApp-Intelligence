import sys, json; sys.path.insert(0,'tests')
from scenario_chat import CHAT
from app.parsers.whatsapp import WhatsAppParser
from app.intelligence.types import Msg
from app.intelligence.pipeline import analyze
msgs=[Msg.from_parsed(m) for m in WhatsAppParser().parse_text(CHAT)]
r=analyze(msgs)
p=r['progress']; print({k:p[k] for k in ('overall','development','design','testing','deployment','client_approval')}); print(p['explanation']['warnings'], p['explanation']['reliability'])
print(json.dumps(r['health'],default=str,indent=1)[:1500])
for c in r['contribution']: print(c['person'],c['score'],c['assigned'],c['completed'],{k:v.get('contribution',v.get('multiplier')) for k,v in c['components'].items()})
print(r['sales']); print(r['velocity']); print(r['progress_timeline'][:3])
