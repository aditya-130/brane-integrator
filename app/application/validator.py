import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel
import httpx
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)
from app.domain.config import IntegratorConfig
from app.application.policy_interpreter import (
    InterpretedWorkflow,
    PARTICIPANT_REGISTRY,
    PARTICIPANT_SKIP_FIELDS,
    WORKFLOW_REGISTRY,
    WF_SKIP_FIELDS,
)


class RuleResult(BaseModel):
    rule: str
    passed: bool
    message: Optional[str] = None


class ValidationResult(BaseModel):
    passed: bool
    rules: List[RuleResult]

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

        # Rule 4: EVERY combine call must be immediately preceded by #[on(coordinator)].
        # The original implementation broke on the first pinned call, missing un-annotated
        # calls later in a left-fold chain (e.g. call #2 or #3 for N>2 participants).
        # Fixed: scan all call sites; reset the annotation flag after each combine call
        # is consumed so that the next call must carry its own annotation.
        combine_fn = config.workflow.combine_function
        if combine_fn not in branescript:
            rules.append(RuleResult(rule="combine_pinned_to_coordinator", passed=True, message="N/A — no combine step in this workflow"))
        else:
            coordinator_on = f'#[on("{config.workflow.coordinator_node}")]'
            all_pinned = True
            missing_call = None
            missing_line = None
            call_number = 0
            prev_was_coordinator = False
            for i, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped == coordinator_on:
                    prev_was_coordinator = True
                elif stripped.startswith("#[on("):
                    prev_was_coordinator = False
                if combine_fn in stripped and "(" in stripped:
                    call_number += 1
                    if not prev_was_coordinator:
                        all_pinned = False
                        missing_call = call_number
                        missing_line = i
                        break
                    prev_was_coordinator = False  # annotation is consumed by this statement
            rules.append(RuleResult(
                rule="combine_pinned_to_coordinator",
                passed=all_pinned,
                message=None if all_pinned else (
                    f"Combine call #{missing_call} at line {missing_line} is not pinned to coordinator "
                    f"'{config.workflow.coordinator_node}' — add "
                    f'#[on("{config.workflow.coordinator_node}")] immediately before it'
                ),
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

        # Rule 8: combine function called with exactly 2 args on every call site
        import re as _re
        combine_fn = config.workflow.combine_function
        for m in _re.finditer(rf'\b{_re.escape(combine_fn)}\s*\(([^)]+)\)', branescript):
            args = [a.strip() for a in m.group(1).split(',') if a.strip()]
            if len(args) != 2:
                rules.append(RuleResult(
                    rule="combine_exactly_two_args",
                    passed=False,
                    message=f"{combine_fn} must be called with exactly 2 arguments but got {len(args)}: {m.group(0)[:60]}. For N>2 participants chain as left-fold: let acc := combine(a,b); let result := combine(acc,c);",
                ))
                break
        else:
            rules.append(RuleResult(rule="combine_exactly_two_args", passed=True, message=None))

        # Rule 9: verify package and functions are registered in the Brane API
        # brane workflow check is broken in nightly (constructs URLs without http:// scheme),
        # so we query the GraphQL API directly instead.
        rules.extend(self._check_package_registered(config, branescript))

        return ValidationResult(
            passed=all(r.passed for r in rules),
            rules=rules,
        )

    def _check_package_registered(self, config: IntegratorConfig, branescript: str = "") -> List[RuleResult]:
        query = '{ packages { name functionsAsJson } }'
        api_url = f"http://{settings.BRANE_API_URL}/graphql"
        try:
            resp = httpx.post(api_url, json={"query": query}, timeout=10)
            resp.raise_for_status()
            packages = resp.json().get("data", {}).get("packages", [])
        except Exception as e:
            logger.warning("Validator: could not reach Brane API at %s — %s", api_url, e)
            return [RuleResult(rule="package_registered", passed=False, message=f"Brane API unreachable: {e}")]

        pkg_map = {p["name"]: json.loads(p.get("functionsAsJson") or "{}") for p in packages}
        results = []

        package = config.workflow.package
        if package not in pkg_map:
            logger.warning("Validator: package '%s' not found in Brane API", package)
            results.append(RuleResult(rule="package_registered", passed=False, message=f"Package '{package}' not registered in Brane"))
            return results

        logger.info("Validator: package '%s' found in Brane API", package)
        results.append(RuleResult(rule="package_registered", passed=True, message=None))

        functions = pkg_map[package]

        # Check the two configured function names (local + combine)
        for fn_field, fn_name in [("local_function", config.workflow.local_function), ("combine_function", config.workflow.combine_function)]:
            if fn_name in functions:
                logger.info("Validator: function '%s' found in package '%s'", fn_name, package)
                results.append(RuleResult(rule=f"function_registered_{fn_field}", passed=True, message=None))
            else:
                logger.warning("Validator: function '%s' NOT found in package '%s'", fn_name, package)
                results.append(RuleResult(rule=f"function_registered_{fn_field}", passed=False, message=f"Function '{fn_name}' not found in package '{package}'"))

        # Also extract every call site from the generated BraneScript and verify each
        # against the full registry. This catches any LLM-hallucinated function names
        # beyond the two stored in WorkflowSpec — critical for non-map-reduce patterns
        # where the LLM may call additional package functions.
        if branescript:
            import re as _re
            _BS_KEYWORDS = {
                "let", "new", "return", "import", "if", "else", "while", "for",
                "fn", "true", "false", "null", "in",
            }
            known_names = {config.workflow.local_function, config.workflow.combine_function}
            # Strip annotation lines (#[...] and #![...]) before scanning for call sites
            # so that annotation keywords like on(), tag(), wf_tag() are not mistaken
            # for package function calls.
            non_annotation_code = "\n".join(
                line for line in branescript.splitlines()
                if not line.strip().startswith("#[") and not line.strip().startswith("#![")
            )
            called_names = (
                set(_re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', non_annotation_code))
                - _BS_KEYWORDS
                - known_names
            )
            for fn_name in sorted(called_names):
                if fn_name in functions:
                    logger.info("Validator: extra call site '%s' found in package '%s'", fn_name, package)
                    results.append(RuleResult(rule=f"function_registered_{fn_name}", passed=True, message=None))
                else:
                    logger.warning("Validator: extra call site '%s' NOT in package '%s'", fn_name, package)
                    results.append(RuleResult(
                        rule=f"function_registered_{fn_name}",
                        passed=False,
                        message=f"Function '{fn_name}' is called in the script but not registered in package '{package}'",
                    ))

        return results

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
                # All #![wf_tag()] constructs are stripped before Brane submission
                # (same eFLINT bug workaround as #[tag()] — see handle_execution).
                wf_note = TAG_STRIPPED_NOTE if construct.startswith("#![wf_tag(") else None
                mappings.append({
                    "participant_node": None,
                    "participant_user_id": None,
                    "policy_field": field,
                    "policy_value": value,
                    "generated_construct": construct,
                    "line": find_line(construct),
                    "flagged": False,
                    "note": wf_note,
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
                        "note": f"Aggregated from participant onboarding answers and deduplicated. {TAG_STRIPPED_NOTE}",
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