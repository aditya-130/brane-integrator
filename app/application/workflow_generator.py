from app.domain.config import IntegratorConfig, InterpretedParticipant


class WorkflowGenerator:
    def generate(self, config: IntegratorConfig, interpreted: list[InterpretedParticipant]) -> str:
        lines = []

        # import
        lines.append(f"import {config.workflow.package};")
        lines.append("")

        # data references
        for i, p in enumerate(interpreted, start=1):
            lines.append(f'let data_{i} := new Data {{ name := "{p.dataset_name}" }};')
        lines.append("")

        # local function calls per participant
        stat_vars = []
        for i, p in enumerate(interpreted, start=1):
            stat_var = f"stats_{i}"
            stat_vars.append(stat_var)
            lines.append(p.on_annotation)
            lines.append(f"let {stat_var} := {config.workflow.local_function}(data_{i});")
            lines.append("")

        # combine on coordinator
        args = ", ".join(stat_vars)
        lines.append(f'#[on("{config.workflow.coordinator_node}")]')
        lines.append(f"let result := {config.workflow.combine_function}({args});")
        lines.append("")

        # return
        lines.append("return result;")

        return "\n".join(lines)