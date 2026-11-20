from __future__ import annotations

import json
import re
from dataclasses import dataclass

from question1.agent import (
    _FEW_SHOT,
    _INSTRUCTIONS,
    _POLICY_GUIDE,
    _defuse,
    parse_resolution,
)
from shared.billing import CostSession
from shared.kb import all_articles_blob, article_ids, load_article
from shared.llm import ChatMessage, LlmClient
from shared.tools import format_thread, get_order, get_ticket

ACTIONS = {"REFUND", "REPLACE", "SEND_ARTICLE", "ESCALATE_TIER2"}

# Which actions each article can legitimately back (used only to flag oddities).
EXPECTED_ACTIONS = {
    "custom-items-no-replace": {"ESCALATE_TIER2"},
    "damage-replacement-7-days": {"REPLACE", "ESCALATE_TIER2"},
    "digital-license-no-refund": {"SEND_ARTICLE"},
    "returns-within-30-days": {"REFUND", "SEND_ARTICLE", "ESCALATE_TIER2"},
    "subscription-cooling-off": {"REFUND", "SEND_ARTICLE"},
}

_WORD = re.compile(r"[a-z0-9]{4,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


@dataclass
class TicketResolution:
    action: str
    kb_article: str


class SupportPipeline:
    """Same product as Question 1: triage -> retrieve -> compose -> audit.

    Only compose calls the LLM. Triage, retrieve and audit are plain code, so
    they cost 0 points. The static prompt prefix is identical on every call and
    is passed as cached_prefix, so it is billed at the cached-input rate.
    """

    def __init__(self, session: CostSession | None = None):
        self.session = session or CostSession()
        self.llm = LlmClient(self.session)
        self.audit_flags: list[str] = []

        system = _defuse(
            "\n\n".join(
                [
                    _INSTRUCTIONS,
                    _FEW_SHOT,
                    "HELP CENTER:",
                    all_articles_blob(),
                    _POLICY_GUIDE,
                ]
            )
        )
        assert "ORDER_SNAPSHOT:" not in system
        self._system = system
        self._prefix = f"SYSTEM:\n{system}\n\nUSER:\n"
        # Pre-computed once: the words of each real article, for retrieval.
        self._article_words = {
            aid: _words(aid.replace("-", " ") + " " + load_article(aid))
            for aid in article_ids()
        }

    def handle_ticket(self, ticket_id: str) -> TicketResolution:
        ticket = get_ticket(ticket_id)
        order = get_order(ticket["order_id"])

        facts = self._triage(ticket_id, ticket, order)  # 0 points
        candidates = self._retrieve(facts)  # 0 points
        raw = self._compose(facts)  # the only LLM call
        return self._audit(ticket_id, raw, candidates)  # 0 points

    # node 1: normalise inputs, no model needed
    def _triage(self, ticket_id: str, ticket: dict, order: dict) -> dict:
        thread = _defuse(format_thread(ticket))
        snapshot = json.dumps(order, separators=(",", ":"))
        return {"ticket_id": ticket_id, "thread": thread, "snapshot": snapshot}

    # node 2: rank the real articles by word overlap, no model needed
    def _retrieve(self, facts: dict) -> list[str]:
        query = _words(facts["thread"] + " " + facts["snapshot"])
        ranked = sorted(
            self._article_words,
            key=lambda aid: (-len(query & self._article_words[aid]), aid),
        )
        return ranked[:3]

    # node 3: one cached, compact LLM call
    def _compose(self, facts: dict) -> str:
        user = (
            f"{facts['ticket_id']}\n{facts['thread']}\n"
            f"ORDER_SNAPSHOT:\n{facts['snapshot']}\nEND_SNAPSHOT"
        )
        return self.llm.chat(
            "compose",
            [ChatMessage("system", self._system), ChatMessage("user", user)],
            cached_prefix=self._prefix,
        )

    # node 4: deterministic safety checks instead of a second LLM pass
    def _audit(self, ticket_id: str, raw: str, candidates: list[str]) -> TicketResolution:
        try:
            parsed = parse_resolution(raw)
            action, kb = parsed.action, parsed.kb_article
        except (ValueError, KeyError) as exc:
            self.audit_flags.append(f"{ticket_id}: unparseable output ({exc})")
            return TicketResolution("ESCALATE_TIER2", candidates[0] if candidates else "")

        if action not in ACTIONS:
            self.audit_flags.append(f"{ticket_id}: invalid action {action}, escalating")
            action = "ESCALATE_TIER2"
        if kb not in self._article_words:
            self.audit_flags.append(f"{ticket_id}: unknown article {kb}")
            kb = candidates[0] if candidates else kb
        if kb in EXPECTED_ACTIONS and action not in EXPECTED_ACTIONS[kb]:
            self.audit_flags.append(f"{ticket_id}: {action} unusual for {kb}")
        if kb not in candidates:
            self.audit_flags.append(f"{ticket_id}: {kb} not in retrieved candidates")
        return TicketResolution(action, kb)