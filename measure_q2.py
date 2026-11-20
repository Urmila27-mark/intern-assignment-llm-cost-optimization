import sys

if len(sys.argv) > 1 and sys.argv[1] == "baseline":
    from question2.agent_baseline import SupportPipeline
else:
    from question2.agent import SupportPipeline

# T-1004 = physical fulfillment (replacement), T-1003 = escalation
for tid in ["T-1001", "T-1002", "T-1003", "T-1004"]:
    p = SupportPipeline()
    r = p.handle_ticket(tid)
    print(tid, r.action, r.kb_article, "TOTAL", p.session.total_points())
    for c in p.session.calls:
        print("  ", c.label, "in", c.input_tokens, "cached", c.cached_prefix_tokens,
              "out", c.output_tokens, "points", c.points())
    flags = getattr(p, "audit_flags", [])
    if flags:
        print("   audit flags:", flags)