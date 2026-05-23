from app.domain.config import IntegratorConfig
from app.application.policy_interpreter import InterpretedWorkflow


class TemplateGenerator:
    """
    Deterministic map-reduce template generator.
    Each participant runs a local function; results are aggregated on the coordinator.

    To add a new template pattern in future, add a method here (e.g. generate_local_only,
    generate_iterative) and dispatch from WorkflowJobHandler based on invocation_pattern.
    """

    def generate(self, config: IntegratorConfig, interpreted: InterpretedWorkflow) -> str:
        lines = []

        lines.append(f"import {config.workflow.package};")
        lines.append("")

        for wf_tag in interpreted.wf_tags:
            lines.append(wf_tag)
        if interpreted.wf_tags:
            lines.append("")

        for i, p in enumerate(interpreted.participants, start=1):
            lines.append(f"let data_{i} := {p.dataset_name};")
        lines.append("")

        stat_vars = []
        for i, p in enumerate(interpreted.participants, start=1):
            stat_var = f"stats_{i}"
            stat_vars.append(stat_var)
            lines.append(p.on_annotation)
            for tag in p.tag_annotations:
                lines.append(tag)
            lines.append(f"let {stat_var} := {config.workflow.local_function}(data_{i});")
            lines.append("")

        # Pairwise left-fold: combine takes exactly 2 inputs, so chain for N > 2.
        # e.g. 4 participants → combine(combine(combine(s1,s2), s3), s4)
        lines.append(f'#[on("{config.workflow.coordinator_node}")]')
        combine_fn = config.workflow.combine_function
        coordinator = config.workflow.coordinator_node
        if len(stat_vars) == 1:
            lines.append(f"let result := {stat_vars[0]};")
        else:
            acc_var = "acc_0"
            lines.append(f"let {acc_var} := {combine_fn}({stat_vars[0]}, {stat_vars[1]});")
            for i in range(2, len(stat_vars)):
                next_var = f"acc_{i - 1}"
                lines.append(f'#[on("{coordinator}")]')
                lines.append(f"let {next_var} := {combine_fn}({acc_var}, {stat_vars[i]});")
                acc_var = next_var
            lines.append(f"let result := {acc_var};")
        lines.append("")

        if config.workflow.finalize_function:
            lines.append(f'#[on("{config.workflow.coordinator_node}")]')
            lines.append(f"let final_result := {config.workflow.finalize_function}(result);")
            lines.append("")
            lines.append("return final_result;")
        else:
            lines.append("return result;")

        return "\n".join(lines)
