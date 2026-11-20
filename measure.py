from question1.agent import SupportCopilot
from shared.billing import CACHE_MIN_PREFIX
from shared.tokens import count_tokens

for tid in ["T-1001", "T-1002", "T-1003", "T-1004"]:
    agent = SupportCopilot()
    r = agent.handle_ticket(tid)
    print(tid, r.action, r.kb_article, "TOTAL", agent.session.total_points())
    prefix = getattr(agent, "_prefix", None)
    if prefix:
        print("   prefix tokens:", count_tokens(prefix), "(cache needs", CACHE_MIN_PREFIX, ")")
    for c in agent.session.calls:
        print("  ", c.label, "in", c.input_tokens, "cached", c.cached_prefix_tokens,
              "out", c.output_tokens, "points", c.points())