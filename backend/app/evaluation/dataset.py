import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "evaluation_datasets"
    / "test_case_generation_v1.json"
)


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(gt=0)
    content: str = Field(min_length=1)


class ReferenceAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_key: str = Field(min_length=1)
    evidence_ids: list[int] = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)


class EvaluationExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    scenario_type: Literal[
        "positive",
        "negative",
        "boundary",
        "edge",
        "insufficient_evidence",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    requirements_prompt: str = Field(min_length=1)
    evidence_chunks: list[EvidenceChunk] = Field(min_length=1)
    expected_requirement_coverage: list[str]
    expected_categories: list[Literal["positive", "negative", "boundary", "edge"]]
    unsupported_behaviors: list[str]
    annotations: list[ReferenceAnnotation]
    known_constraints: list[str]
    evaluation_notes: list[str] = Field(min_length=1)
    scoring_guidance: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "EvaluationExample":
        chunk_ids = [chunk.id for chunk in self.evidence_chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError(f"{self.id}: evidence chunk IDs must be unique")
        known_ids = set(chunk_ids)
        if len(self.expected_requirement_coverage) != len(
            set(self.expected_requirement_coverage)
        ):
            raise ValueError(f"{self.id}: expected requirement keys must be unique")
        if len(self.expected_categories) != len(set(self.expected_categories)):
            raise ValueError(f"{self.id}: expected categories must be unique")

        annotation_keys = []
        evidence_by_id = {chunk.id: chunk.content for chunk in self.evidence_chunks}
        for annotation in self.annotations:
            annotation_keys.append(annotation.requirement_key)
            if not set(annotation.evidence_ids).issubset(known_ids):
                raise ValueError(f"{self.id}: annotation cites unknown evidence")
            if annotation.requirement_key not in self.expected_requirement_coverage:
                raise ValueError(
                    f"{self.id}: annotation requirement is not expected coverage"
                )
            quote_is_traceable = any(
                annotation.evidence_quote in evidence_by_id[evidence_id]
                for evidence_id in annotation.evidence_ids
            )
            if not quote_is_traceable:
                raise ValueError(
                    f"{self.id}: reference annotation quote is not in cited evidence"
                )
        if len(annotation_keys) != len(set(annotation_keys)):
            raise ValueError(f"{self.id}: annotation requirement keys must be unique")
        if set(annotation_keys) != set(self.expected_requirement_coverage):
            raise ValueError(
                f"{self.id}: each expected requirement needs one reference annotation"
            )
        if self.scenario_type == "insufficient_evidence" and (
            self.expected_requirement_coverage
            or self.expected_categories
            or self.annotations
        ):
            raise ValueError(
                f"{self.id}: insufficient-evidence examples cannot require cases"
            )
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    dataset_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    examples: list[EvaluationExample] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_example_ids(self) -> "EvaluationDataset":
        ids = [example.id for example in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("Dataset example IDs must be unique")
        return self


def load_dataset(
    path: str | Path = DEFAULT_DATASET_PATH,
    *,
    expected_version: str | None = None,
) -> EvaluationDataset:
    dataset_path = Path(path)
    try:
        raw_data = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load evaluation dataset: {dataset_path}") from exc
    dataset = EvaluationDataset.model_validate(raw_data)
    if expected_version is not None and dataset.dataset_version != expected_version:
        raise ValueError(
            f"Dataset version mismatch: expected {expected_version}, "
            f"found {dataset.dataset_version}"
        )
    return dataset
