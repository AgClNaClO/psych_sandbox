"""Validate post-session decisions against visible dialogue, not turn scores."""
from ..domain import CounselorSessionReview, SessionRecord
from ..runtime.evidence import is_grounded


def objective_priority(session: SessionRecord, item) -> str:
    configured = session.plan.objective_priorities.get(item.objective, "standard")
    # Review may promote a newly recognized prerequisite, never lower a configured gate.
    return "critical" if "critical" in {configured, item.priority} else configured


def validated_review(review: CounselorSessionReview, session: SessionRecord) -> CounselorSessionReview:
    review = review.model_copy(deep=True)
    expected = set(session.plan.objectives)
    seen = set()
    assessments = []
    for item in review.objective_assessments:
        if item.objective not in expected or item.objective in seen:
            review.validation_warnings.append("Unknown or duplicate objective rejected")
            continue
        seen.add(item.objective)
        item.evidence = [quote for quote in item.evidence if is_grounded(quote, session.messages)]
        if item.status in {"completed", "partial"} and not item.evidence:
            item.status = "not_assessed"
            review.validation_warnings.append("Objective status lacks dialogue evidence")
        item.priority = objective_priority(session, item)
        assessments.append(item)
    review.objective_assessments = assessments
    missing = expected - seen
    unfinished = [item.objective for item in assessments if item.status != "completed"]
    priorities = {item.objective: item.priority for item in assessments}
    required = {objective for objective in expected
                if priorities.get(objective, session.plan.objective_priorities.get(objective, "standard")) != "optional"}
    review.goals_achieved = (bool(expected) and not (missing & required)
                            and not (set(unfinished) & required))
    review.unmet_objectives = [objective for objective in session.plan.objectives
                              if objective in missing or objective in unfinished]
    if not review.goals_achieved:
        review.replanning_required = True
    for field in ("mutual_agreement", "relapse_plan", "support_plan"):
        quotes = getattr(review.termination, field)
        setattr(review.termination, field, [quote for quote in quotes
                if is_grounded(quote, session.messages)
                and (field != "mutual_agreement" or quote.role == "client")])
    return review


def stage_is_ready(session: SessionRecord) -> bool:
    review = session.counselor_review
    if review is None or not review.stage_ready or not session.plan.objectives:
        return False
    review = validated_review(review, session)
    by_objective = {item.objective: item for item in review.objective_assessments}
    if not any(item.status == "completed"
               and item.priority != "optional"
               for item in review.objective_assessments):
        return False
    for objective in session.plan.objectives:
        item = by_objective.get(objective)
        if item is None:
            return False
        if item.status == "completed":
            continue
        priority = item.priority
        if priority == "critical":
            return False
        if priority == "optional":
            continue
        if not (item.defer_to_next_stage and item.reason.strip()
                and objective in review.next_objectives):
            return False
    return True


def trajectory_can_close(session: SessionRecord) -> bool:
    if not stage_is_ready(session) or session.counselor_review is None:
        return False
    review = validated_review(session.counselor_review, session)
    return (review.goals_achieved
            and all(getattr(review.termination, field)
                    for field in ("mutual_agreement", "relapse_plan", "support_plan")))
