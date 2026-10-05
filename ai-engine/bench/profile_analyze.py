import cProfile, pstats, sys
from bench.bench_scale import make_chat
from app.intelligence.pipeline import analyze
from app.intelligence.types import Msg
from app.parsers.whatsapp import WhatsAppParser
n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
msgs = [Msg.from_parsed(m) for m in WhatsAppParser().parse_text(make_chat(n))]
pr = cProfile.Profile(); pr.enable(); analyze(msgs); pr.disable()
pstats.Stats(pr).sort_stats("cumulative").print_stats(22)
