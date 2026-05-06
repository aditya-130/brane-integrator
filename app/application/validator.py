from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from app.domain.config import IntegratorConfig, InterpretedWorkflow, RuleResult, ValidationResult
from app.application.policy_interpreter import (
    PARTICIPANT_REGISTRY,
    PARTICIPANT_SKIP_FIELDS,
    WORKFLOW_REGISTRY,
    WF_SKIP_FIELDS,
)

TAG_STRIPPED_NOTE = "stripped before Brane submission (eFLINT bug workaround)"





class Validator:

    def validate(
        self, branescript: str, config: IntegratorConfig, interpreted: InterpretedWorkflow
    ) -> ValidationResult:
        rules = []
        lines = branescript.splitlines()

        # Rule 1: import present
        expected_import = f"import {config.workflow.package};"
        import_present = any(line.strip() == expected_import for line in lines)
        rules.append(RuleResult(
            rule="import_present",
            passed=import_present,
            message=None if import_present else f"Missing: {expected_import}",
        ))

        # Rule 2: return present
        return_present = any(line.strip().startswith("return") for line in lines)
        rules.append(RuleResult(
            rule="return_present",
            passed=return_present,
            message=None if return_present else "Missing: return statement",
        ))

        # Rule 3: every participant has #[on()]
        for p in interpreted.participants:
            present = p.on_annotation in branescript
            rules.append(RuleResult(
                rule=f"on_annotation_{p.brane_node}",
                passed=present,
                message=None if present else f"Missing: {p.on_annotation} for {p.brane_node}",
            ))

        # Rule 4: combine step pinned to coordinator
        coordinator_on = f'#[on("{config.workflow.coordinator_node}")]'
        combine_fn = config.workflow.combine_function
        found = False
        prev_was_coordinator = False
        for line in lines:
            stripped = line.strip()
            if stripped == coordinator_on:
                prev_was_coordinator = True
            elif stripped.startswith("#[on("):
                prev_was_coordinator = False
            if combine_fn in stripped and prev_was_coordinator:
                found = True
                break
        rules.append(RuleResult(
            rule="combine_pinned_to_coordinator",
            passed=found,
            message=None if found else f"Combine step not pinned to coordinator '{config.workflow.coordinator_node}'",
        ))

        # Rule 5: wf_tags present in .bs
        for wf_tag in interpreted.wf_tags:
            present = wf_tag in branescript
            rules.append(RuleResult(
                rule="wf_tag_present",
                passed=present,
                message=None if present else f"Missing wf_tag: {wf_tag}",
            ))

        # Rule 6: tag annotations present in .bs
        for p in interpreted.participants:
            for tag in p.tag_annotations:
                present = tag in branescript
                rules.append(RuleResult(
                    rule=f"tag_annotation_{p.brane_node}",
                    passed=present,
                    message=None if present else f"Missing tag: {tag} for {p.brane_node}",
                ))

        # Rule 7: dataset new Data construct present
        for p in interpreted.participants:
            present = p.dataset_name in branescript
            rules.append(RuleResult(
                rule=f"dataset_ref_{p.brane_node}",
                passed=present,
                message=None if present else f"Missing dataset ref: {p.dataset_name} for {p.brane_node}",
            ))

        return ValidationResult(
            passed=all(r.passed for r in rules),
            rules=rules,
        )

    def generate_traceability_report(
        self, branescript: str, config: IntegratorConfig, interpreted: InterpretedWorkflow
    ) -> dict:
        lines = branescript.splitlines()

        def find_line(construct: str) -> Optional[int]:
            for i, line in enumerate(lines, start=1):
                if construct in line:
                    return i
            return None

        mappings = []

        # workflow-level mappings
        for field, value in config.project.model_dump().items():
            if field in WF_SKIP_FIELDS or not value:
                continue
            if field in WORKFLOW_REGISTRY:
                construct = WORKFLOW_REGISTRY[field](value)
                mappings.append({
                    "participant_node": None,
                    "participant_user_id": None,
                    "policy_field": field,
                    "policy_value": value,
                    "generated_construct": construct,
                    "line": find_line(construct),
                    "flagged": False,
                    "note": None,
                })
            else:
                mappings.append({
                    "participant_node": None,
                    "participant_user_id": None,
                    "policy_field": field,
                    "policy_value": str(value),
                    "generated_construct": None,
                    "line": None,
                    "flagged": True,
                    "reason": "Not enforceable at BraneScript level. Requires human review.",
                    "note": None,
                })

        # jurisdiction mappings — aggregated from participant onboarding answers
        seen_jurisdictions: set[str] = set()
        for participant in config.participants:
            for j in (participant.jurisdictions or []):
                if j not in seen_jurisdictions:
                    seen_jurisdictions.add(j)
                    construct = f'#![wf_tag("jurisdiction.{j}")]'
                    mappings.append({
                        "participant_node": None,
                        "participant_user_id": None,
                        "policy_field": "jurisdictions",
                        "policy_value": j,
                        "generated_construct": construct,
                        "line": find_line(construct),
                        "flagged": False,
                        "note": "Aggregated from participant onboarding answers and deduplicated",
                    })

        # participant-level mappings
        for participant in config.participants:
            for field, value in participant.model_dump().items():
                if field in PARTICIPANT_SKIP_FIELDS or value is None:
                    continue
                if field in PARTICIPANT_REGISTRY:
                    construct = PARTICIPANT_REGISTRY[field](value)
                    note = TAG_STRIPPED_NOTE if field == "identifiability" else None
                    mappings.append({
                        "participant_node": participant.brane_node,
                        "participant_user_id": participant.user_id,
                        "policy_field": field,
                        "policy_value": value,
                        "generated_construct": construct,
                        "line": find_line(construct),
                        "flagged": False,
                        "note": note,
                    })
                else:
                    mappings.append({
                        "participant_node": participant.brane_node,
                        "participant_user_id": participant.user_id,
                        "policy_field": field,
                        "policy_value": str(value),
                        "generated_construct": None,
                        "line": None,
                        "flagged": True,
                        "reason": "Not enforceable at BraneScript level. Requires human review.",
                        "note": None,
                    })

        # extracted claims from free-text (RQ3)
        for participant in config.participants:
            for claim in participant.extracted_claims:
                if claim.policy_field in PARTICIPANT_REGISTRY:
                    construct = PARTICIPANT_REGISTRY[claim.policy_field](claim.policy_value)
                    mappings.append({
                        "participant_node": participant.brane_node,
                        "participant_user_id": participant.user_id,
                        "policy_field": claim.policy_field,
                        "policy_value": claim.policy_value,
                        "generated_construct": construct,
                        "line": find_line(construct),
                        "flagged": False,
                        "note": f"Extracted from free-text field '{claim.source_field}' (confidence: {claim.confidence})",
                    })
                else:
                    mappings.append({
                        "participant_node": participant.brane_node,
                        "participant_user_id": participant.user_id,
                        "policy_field": claim.policy_field,
                        "policy_value": claim.policy_value,
                        "generated_construct": None,
                        "line": None,
                        "flagged": True,
                        "reason": "Extracted from free text but not enforceable at BraneScript level.",
                        "note": f"Source: '{claim.source_field}' (confidence: {claim.confidence})",
                    })

        return {
            "generated_workflow": "workflow.bs",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project_id": config.project.project_id,
            "mappings": mappings,
        }