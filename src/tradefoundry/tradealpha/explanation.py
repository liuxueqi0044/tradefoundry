from sqlalchemy.orm import Session

from tradefoundry.tradealpha.contracts import ScoreExplanation, ScoreSnapshotView
from tradefoundry.tradealpha.models import ScoreSnapshotRow


class ExplanationService:
    def __init__(self, session: Session):
        self.session = session

    def explain(self, score_id: str) -> ScoreExplanation:
        row = self.session.get(ScoreSnapshotRow, score_id)
        if row is None:
            raise LookupError(f"score snapshot {score_id} not found")
        ordered = sorted(row.factors_json, key=lambda item: abs(item["contribution"]), reverse=True)
        why = [
            f"{item['feature']} contributed {item['contribution']:.3f} "
            f"from value {item['value']:.3f} and weight {item['weight']:.3f}."
            for item in ordered[:5]
        ]
        valuable = [f"Obtain non-missing evidence for {feature}." for feature in row.gaps_json[:5]]
        if not valuable:
            valuable = [
                f"Reduce uncertainty in {item['feature']}." for item in row.sensitivities_json[:3]
            ]
        return ScoreExplanation(
            score=ScoreSnapshotView.model_validate(row),
            why_high_or_low=why,
            hard_constraints=row.hard_reasons_json,
            assumptions=row.assumptions_json,
            evidence_gaps=row.gaps_json,
            sensitivities=row.sensitivities_json,
            most_valuable_new_evidence=valuable,
        )
