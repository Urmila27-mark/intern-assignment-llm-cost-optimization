# ShopAssist: support copilot cost lab (my solution)

Hi, I'm Urmila, a third-year B.Tech CSE student at IIIT Kota. This is my submission for the
LLM cost optimization assignment.

ShopAssist is a Tier-1 support agent for an e-commerce company. For each ticket it reads the
customer thread, loads the order facts, picks one action (`REFUND`, `REPLACE`, `SEND_ARTICLE`,
`ESCALATE_TIER2`) and cites the help-center article that backs the decision. The task was to make
it cheaper without changing the graded fields (`action` and `kb_article`).

**A note about the video:** I was not able to record a demo video in time, so instead of a video I
have written the full walkthrough as a script at the bottom of this file
(see "Video walkthrough script"). I'm happy to record it if that is needed.

## Results

| | Baseline (4 tickets) | Final (4 tickets) | Avg per ticket | Drop | Target |
|---|---|---|---|---|---|
| Question 1 | 35,265 | 4,888 | 8,816 -> 1,222 | 86.1% | <= 3,000 |
| Question 2 | 293,997 | 4,888 | 73,499 -> 1,222 | 98.3% | <= 2,500 |

All four public tickets (T-1001 to T-1004) give exactly the same `action` and `kb_article` as the
baseline, and the T-1091 holdout test still passes.

| Ticket | Q1 before | Q1 after | Q2 before | Q2 after |
|---|---|---|---|---|
| T-1001 (refund) | 8,901 | 1,348 | 73,602 | 1,348 |
| T-1002 (digital license) | 8,994 | 1,219 | 73,458 | 1,219 |
| T-1003 (custom item, escalate) | 8,901 | 1,180 | 73,356 | 1,180 |
| T-1004 (replacement) | 8,886 | 1,141 | 73,581 | 1,141 |

The raw outputs I measured are committed in the repo: `baseline_measure.txt`, `after_measure.txt`,
`baseline_measure_q2.txt`, `after_measure_q2.txt`, `baseline_q1.txt`, `after_q1.txt`,
`baseline_q2.txt` and `after_q2.txt`.

## Question 1: one LLM call per ticket

### What I found

First I ran the baseline and printed the tokens for every call (`measure.py`). Each ticket cost
about 8,900 points: around 500 input tokens (about 1,500 points) and around 490 output tokens
(about 7,300 points). Output costs 15 per token, so the long answer was 82% of the bill.

Reading `question1/agent.py` and `shared/llm.py`, I found these problems:

1. The prompt says "think step by step", "full reasoning" and "quote any article". The model then writes
   about 490 tokens that nobody uses. `shared/llm.py` also switches to a long output when it sees
   phrases like these anywhere in the prompt.
2. The system prompt starts with `Run id {uuid4()}`. This changes on every call, so the beginning of the
   prompt is never the same twice and can never be cached.
3. `handle_ticket` never passes `cached_prefix`, so the cache discount was never asked for.
4. The order JSON was printed with `indent=2`, and a `customer_reply` was requested, which is not graded.

### What I changed (`question1/agent.py`)

- Removed the reasoning instructions and the run id. The model now only returns
  `{"action": "...", "kb_article": "..."}`. Output went from about 490 to about 40 tokens.
- Put everything that never changes first (instructions, examples, help center, policy guide) and the
  ticket thread and order facts last. The static part is the same on every call and is passed as
  `cached_prefix`.
- Minified the order JSON.
- Replaced the trigger phrases with a neutral word in the KB text and the customer thread, so they can
  never inflate the output.
- Added a short policy guide and more examples, written only from the five real articles in `data/kb`.

### The cache threshold surprise

My first optimized version cost about 3,900 points per ticket, not 1,200. The output was fixed, but the
cache was not working: my prefix was 1,009 tokens and the cache needs at least 1,024. Missing it by 15
tokens meant the whole prefix was still billed at 3 per token. I added two more useful rules to the
policy guide, the prefix became 1,074 tokens, `cached` went from 0 to 1,074 and the cost dropped to
about 1,200. It showed me that the cache is all or nothing around the threshold.

| Version | Points per ticket (average) |
|---|---|
| Baseline | ~8,800 |
| Output fixed, prefix 1,009 tokens (cache not active) | ~3,900 |
| Prefix 1,074 tokens (cache active) | ~1,220 |

### Breakdown for T-1001 (final)

| Part | Tokens | Price | Points |
|---|---|---|---|
| Uncached input | 112 | 3 | 336 |
| Cached input | 1,074 | 0.3 | 322 |
| Output | 46 | 15 | 690 |
| **Total** | | | **1,348** |

### Why I stopped here

More than half of the remaining cost is output that the simulator always writes (about 40 tokens, because
it adds a short `customer_reply` itself). The cached prefix has to stay above 1,024 tokens to be cached at
all. The only part left to trim is the ticket text, and cutting it could remove facts the answer depends on
for a saving of under 10%. I preferred to keep the answers safe.

## Question 2: four-node pipeline

### What I found

In the baseline every ticket cost about 73,500 points. For T-1001 (73,602):

| Node | Input tokens | Output tokens | Points |
|---|---|---|---|
| triage | 8,453 | 490 | 32,709 |
| retrieve | 598 | 46 | 2,484 |
| compose | 1,199 | 489 | 10,932 |
| audit | 6,724 | 487 | 27,477 |

69% of the cost was input (pieces of the huge help center sent again in triage and audit) and 31% was
output (verbose answers in three of the nodes). The uuid cache problem was here too.

### What I changed (`question2/agent.py`)

I kept the same four stages, but only `compose` uses the LLM now.

| Node | Before | After |
|---|---|---|
| triage | LLM call with 120k characters of help center | plain code: clean the thread, minify the order (0 points) |
| retrieve | LLM asked to print eight articles | plain code: rank the real articles by word overlap (0 points) |
| compose | long LLM answer | one LLM call with a cached prefix and a tiny JSON answer |
| audit | LLM call with 80k characters of help center | plain code: checks (0 points) |

- The big "expanded help center" is mostly filler. It repeats a note that says it does not change customer
  policy, so I used only the five real articles from `data/kb`.
- The audit is now a set of checks: is the action valid, does the cited article exist, does the action make
  sense for that article, and is the article one of the retrieved candidates. It only fixes broken output
  (invalid action means escalate, unknown article means use the top candidate) and otherwise just records a
  flag in `audit_flags`. It never overrides a valid answer. No flags came up on the public tickets.
- The compose prompt uses the same cached prefix as Question 1.

### Breakdown for two tickets

| Node | T-1004 (replacement, physical fulfillment) | T-1003 (escalation) |
|---|---|---|
| triage | 32,733 -> 0 | 32,742 -> 0 |
| retrieve | 2,355 -> 0 | 2,400 -> 0 |
| compose | 10,965 -> 1,141 | 10,743 -> 1,180 |
| audit | 27,528 -> 0 | 27,471 -> 0 |
| **Total** | **73,581 -> 1,141** | **73,356 -> 1,180** |

After the change, compose for T-1004 is 93 uncached x 3 + 1,074 cached x 0.3 + 36 output x 15 = 1,141,
and for T-1003 it is 91 x 3 + 1,074 x 0.3 + 39 x 15 = 1,180.

## Options I thought about and did not use

- **No LLM calls at all, by copying the rules from `eval/reference.py`.** This would be cheapest, but the
  README says not to use that file, and the point of the task is to optimize an LLM agent.
- **Only sending the top few articles in the prompt.** With only five real articles, a shorter prompt would
  fall under 1,024 tokens and lose the cache discount, and it could cite the wrong article.
- **Adding filler text to reach 1,024 tokens.** That felt like a hack, so I added a policy guide that is
  actually useful.
- **Keeping step-by-step reasoning.** It cost about 7,000 points per ticket and the answers did not change
  without it.
- **Removing the audit stage.** I replaced it with free checks so that the safety step is still there.

## Limits and honest notes

- In this simulator the first call already gets the cache discount. A real API usually charges for the first
  call and gives the discount from the second call.
- The simulator decides its answer from the order data, not from my prompt text. So the policy guide would
  help a real model be consistent, but it does not change the score here.
- A few rules in my policy guide go beyond the five articles: a damage report after day 7 goes to Tier 2,
  a subscription cancelled after day 30 gets `SEND_ARTICLE`, and mixed issues follow a priority order.
  These are my own choices and should be confirmed by whoever owns the policy. Also, the article
  `returns-within-30-days` mentions an "opened-goods article" that is not in the KB.
- If the knowledge base had thousands of articles, I would send only the top few into the uncached part
  of the prompt instead of caching the whole KB.

## Changes to tests

Both test files had a test called `test_baseline_cost_is_high` that checks the original code is expensive
(over 15,000 points for Q1, over 70,000 for one Q2 ticket). Once the code is optimized this test fails on
purpose, so I replaced it with `test_optimized_cost_under_target` (<= 3,000 per ticket for Q1 and <= 2,500
per ticket for Q2). The correctness tests, including the T-1091 holdout, are unchanged and pass. I kept the
original Q2 agent as `question2/agent_baseline.py` so the baseline can be measured again.

## How to run

```
pip install -r requirements.txt
pytest -q
python question1/run.py
python question2/run.py

# token and points breakdown per call
python measure.py                  # Question 1
python measure_q2.py               # Question 2 (optimized)
python measure_q2.py baseline      # Question 2 (original, slow)
```

The full `pytest -q` takes several minutes because `test_help_center_exceeds_context` builds the
210k-token help center. For a quick check:
`pytest tests/test_question2.py -k "resolves or optimized"`.

On my Windows laptop I had two Python versions installed, so I ran everything with `py -3.11`.

## What I learned

- Output tokens are the most expensive, so the first thing to check is what the model is asked to write.
- Caching only helps if the start of the prompt is identical every time and long enough, and one random
  id at the top can break it completely.
- Not every pipeline stage needs a model. Lookups and checks are free in plain code.
- Measure first. Printing the tokens and points of each call told me exactly where the money went.

## Billing

| Input | Cached input | Output |
|---|---|---|
| 3 | 0.3 | 15 |

Cached input = identical prefix of at least 1,024 tokens across calls.
`points = uncached_input x 3 + cached_input x 0.3 + output x 15`

---

## Video walkthrough script

I could not record the video, so this is the script I would have followed (about 4 to 5 minutes, screen
recording of the terminal and the code).

**0:00 Introduction (show this README)**

"Hi, I'm Urmila, a third-year CSE student at IIIT Kota. This is my solution to the ShopAssist cost
lab. The job is to make the support agent cheaper without changing its answers. I'll show where the cost
came from, what I changed, and the options I decided not to use."

**0:30 The baseline (show `baseline_measure.txt`)**

"The original Question 1 code costs about 8,900 points for one ticket. When I split it up, about 7,300 of
that is output: around 490 tokens at 15 points each. Only about 1,500 is input. So the model was writing
a long answer that nobody reads, and output is the most expensive part."

**1:00 The causes (show the original `question1/agent.py`)**

"I found three causes. First, the prompt says to think step by step and write full reasoning, which makes
the model write a lot. Second, a random run id is the first line of the prompt, so the start of the prompt
changes on every call and can never be cached. Third, the code never passes `cached_prefix`, so the cache
discount was never even asked for."

**1:45 Question 1 changes (show the new `agent.py`, then `after_measure.txt`)**

"I removed the reasoning and the run id, so the model only returns the action and the article id. I put
everything that never changes first, which is the instructions, examples, help center and a short policy
guide, and the ticket and order facts last. I pass that static part as `cached_prefix`. I also minified
the order JSON and removed trigger phrases from the text.

My first try cost about 3,900 points per ticket because my prefix was 1,009 tokens and the cache needs
1,024. I added two useful rules to the policy guide, the prefix became 1,074 tokens, and the cost dropped
to about 1,200 per ticket. The target was 3,000, and the answers are identical, and the tests pass."

**2:30 Question 2 (show `baseline_measure_q2.txt`, then `question2/agent.py`)**

"Question 2 costs about 73,500 per ticket. It has four steps and each one called the model with a big
chunk of the help center. Most of that help center is filler text, and the real policy is just five
articles. So I kept the four steps but made three of them plain code: triage cleans the input, retrieve
ranks the real articles by word overlap, and audit checks the answer. Only compose calls the model, with
the same cached prefix as Question 1. The cost is now about 1,220 per ticket, against a target of 2,500."

**3:30 Two ticket breakdown (show `after_measure_q2.txt` and the table in the README)**

"For T-1004, a replacement, the cost went from 73,581 to 1,141. For T-1003, an escalation, it went from
73,356 to 1,180. Only the compose step has a cost now, and the other three steps are zero."

**4:00 What I did not do (show the 'Options' section)**

"I did not copy the reference rules to skip the model, because the task is to optimize an LLM agent. I did
not send only a few articles, because it would drop the prompt under 1,024 tokens and lose the cache. I
did not add filler to reach the cache limit, so I wrote a policy guide instead. And I did not remove the
audit step, I made it free with simple checks."

**4:30 Limits and closing**

"Two things to keep in mind. This simulator gives the cache discount on the very first call, but a real API
usually does not. And the simulator decides answers from the order data, so my policy guide helps a real
model but does not change the score here. Overall I got Question 1 down by 86% and Question 2 down by 98%
with the same answers. Thank you for reading and for the opportunity."

(Before the live demo, run `pytest tests/test_question2.py -k "resolves or optimized"`, which takes a
couple of seconds, instead of the full test suite.)
