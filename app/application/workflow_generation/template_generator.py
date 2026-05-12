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

        args = ", ".join(stat_vars)
        lines.append(f'#[on("{config.workflow.coordinator_node}")]')
        lines.append(f"let result := {config.workflow.combine_function}({args});")
        lines.append("")

        lines.append("return result;")

        return "\n".join(lines)
