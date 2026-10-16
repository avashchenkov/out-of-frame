"""The end-to-end tasks together, see docs/eval-architecture.md#ground-truth-labels."""

from evals.graders.end_to_end import ExpectedRun
from evals.load import load_all
from out_of_frame import research_scope


def test_every_category_has_a_scored_label_at_one_address_at_least():
    scored = {
        label.category
        for task in load_all()
        if isinstance(task.expected, ExpectedRun)
        for label in task.expected.labels
        if label.left_out is None
    }
    assert scored == {category.id for category in research_scope.load().categories}
