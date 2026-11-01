# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import logging

from src.active_plan import active_plan, plan_step_counts   # `B1415`

logger = logging.getLogger(__name__)


class AskUserTool:
    async def execute(self, content, ctx):
        """
        ask_user: the agent poses a multiple-choice question to the user to get a
        decision/clarification. This is a pure UI-control marker — no subprocess,
        no filesystem. It returns an `ask_user` payload that the agent loop turns
        into an `ask_user` SSE event and then ENDS the turn, so the chat waits for
        the user's selection (their choice arrives as the next message).
        """
        question, options, multi = "", [], False
        raw = (content or "").strip()
        try:
            parsed = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            parsed = {}

        if isinstance(parsed, dict):
            question = str(parsed.get("question", "")).strip()
            multi = bool(parsed.get("multi") or parsed.get("multiSelect"))
            options = _options(parsed.get("options"))
            if parsed.get("questions"):
                return _brief(question, parsed.get("questions"))
        else:
            question = raw

        if not question or len(options) < 2:
            return "ask_user: invalid", {
                "error": (
                    "ask_user needs a non-empty `question` and at least 2 `options` "
                    "(each an object with a `label`, optional `description`)."
                ),
                "exit_code": 1,
            }

        options = options[:6]  # keep the choice list sane
        desc = f"ask_user: {question[:80]}"
        labels = ", ".join(o["label"] for o in options)
        result = {
            "ask_user": {"question": question, "options": options, "multi": multi},
            "output": f"Asked the user: {question}\nOptions: {labels}\nAwaiting their selection.",
            "exit_code": 0,
        }
        logger.info("Tool executed: %s (%d options, multi=%s)", desc, len(options), multi)
        return desc, result

def _options(raw) -> list:
    """`[{label, description}]` out of whatever the model sent for options."""
    options = []
    for opt in (raw if isinstance(raw, list) else []):
        if isinstance(opt, dict):
            label = str(opt.get("label", "")).strip()
            descr = str(opt.get("description", "")).strip()
        elif isinstance(opt, str):
            label, descr = opt.strip(), ""
        else:
            continue
        if label:
            options.append({"label": label, "description": descr})
    return options[:6]


#: How many questions one brief may carry. A plan needs the few things that
#: change its steps, and a form longer than this is a questionnaire nobody
#: finishes on a phone.
BRIEF_MAX_QUESTIONS = 5

#: The card's lead-in when the model gave none.
BRIEF_DEFAULT_LEAD = "A few things before I plan this."


def _brief(lead: str, raw_questions) -> tuple:
    """Several questions on one card, each with suggested answers or none.

    Plan mode's way to gather what a plan rests on (the outcome, what done
    looks like, the limits, the taste) in one round trip rather than one
    question per turn. Every question takes a typed answer as well as its
    suggestions, so a question with no options is a plain prompt for the
    person's own words. The answers come back as one message that repeats each
    question beside its answer, so the model reads them together.
    """
    questions = []
    for item in (raw_questions if isinstance(raw_questions, list) else []):
        if isinstance(item, str):
            item = {"question": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("question", "")).strip()
        if not text:
            continue
        questions.append({
            "id": f"q{len(questions) + 1}",
            "question": text,
            "options": _options(item.get("options")),
            "multi": bool(item.get("multi") or item.get("multiSelect")),
            "placeholder": str(item.get("placeholder", "")).strip()[:120],
        })
    if not questions:
        return "ask_user: invalid", {
            "error": (
                "ask_user with `questions` needs at least one entry, each an object "
                "with a non-empty `question` (and optional `options`, `multi`)."
            ),
            "exit_code": 1,
        }
    dropped = len(questions) - BRIEF_MAX_QUESTIONS
    questions = questions[:BRIEF_MAX_QUESTIONS]
    lead = lead or BRIEF_DEFAULT_LEAD
    listed = "\n".join(f"{i}. {q['question']}" for i, q in enumerate(questions, 1))
    output = (f"Asked the user {len(questions)} question(s): {lead}\n{listed}\n"
              f"Awaiting their answers.")
    if dropped > 0:
        output += (f"\n{dropped} more question(s) were not shown: one card holds "
                   f"{BRIEF_MAX_QUESTIONS}. Ask the rest only if the answers leave them open.")
    logger.info("Tool executed: ask_user brief (%d questions)", len(questions))
    return f"ask_user: {len(questions)} question(s)", {
        "ask_user": {"kind": "brief", "question": lead, "questions": questions,
                     "options": [], "multi": False},
        "output": output,
        "exit_code": 0,
    }


class UpdatePlanTool:
    async def execute(self, content, ctx):
        """
        update_plan: the agent writes back to the active plan — tick an item done
        or revise steps (e.g. when the user asks to change something). Pure UI
        marker: returns a `plan_update` payload the agent loop turns into a
        `plan_update` SSE event; the frontend replaces the stored plan and refreshes
        the docked plan window. Does NOT end the turn.
        """
        raw = (content or "").strip()
        plan = ""
        try:
            parsed = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            parsed = {}

        if isinstance(parsed, dict) and parsed.get("plan"):
            plan = str(parsed.get("plan", "")).strip()
        else:
            plan = raw

        if not plan:
            return "update_plan: invalid", {
                "error": "update_plan needs a non-empty `plan` (the full updated checklist as markdown).",
                "exit_code": 1,
            }

        plan = plan[:8192]
        done = plan.count("- [x]") + plan.count("- [X]")
        total = done + plan.count("- [ ]")

        # `B1415`. Against the plan the turn holds: fewer steps than it has is
        # a deletion, and a deletion the call does not name in
        # `removing_steps` is answered here, in the model's own channel, so it
        # sends the whole checklist again. A truncated write cannot name what
        # it lost — its JSON does not even close.
        holder = active_plan()
        held_steps, held_done = plan_step_counts(holder.plan) if holder is not None else (0, 0)
        steps, now_done = plan_step_counts(plan)
        if holder is not None and holder.plan and steps < held_steps:
            removing = parsed.get("removing_steps") if isinstance(parsed, dict) else None
            named = [str(r).strip() for r in removing if str(r).strip()] if isinstance(removing, list) else []
            if len(named) < held_steps - steps:
                last = next((line.strip() for line in reversed(plan.splitlines()) if line.strip()), "")
                return "update_plan: refused (steps would be lost)", {
                    "error": (
                        f"update_plan was not applied: the plan has {held_steps} steps and this "
                        f"checklist has {steps}, so {held_steps - steps} would be deleted, and "
                        f"nothing in this call says which or why. It may have been cut off — it "
                        f"ends “{last[:80]}”. Send the COMPLETE checklist again, every step, done "
                        f"or not. If the person asked to drop steps, name each one in "
                        f"`removing_steps`."
                    ),
                    "exit_code": 1,
                }
        ticked = max(0, now_done - held_done) if holder is not None and holder.plan else 0
        if holder is not None:
            holder.plan = plan

        desc = f"update_plan: {done}/{total} done" if total else "update_plan"
        result = {
            "plan_update": {"plan": plan},
            "output": f"Plan updated ({done}/{total} steps complete)." if total else "Plan updated.",
            "exit_code": 0,
        }
        if ticked:
            # `B1415`: how many steps this call marked done, for the loop's
            # completion verifier (a tick with no work behind it is checked).
            result["plan_ticked"] = ticked
        logger.info("Tool executed: %s", desc)
        return desc, result