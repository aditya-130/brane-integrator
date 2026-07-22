import ast
import json
import os

REPO = "/home/aditya/thesis/integrator/brane-integrator"
RESULTS_DIR = os.path.join(REPO, "evaluation/results/generated_packages")
PACKAGES = ["pkg_1", "pkg_2", "pkg_3", "pkg_4", "pkg_5"]
N_RUNS = 5


class Canonicalizer(ast.NodeVisitor):
    """Walks an AST and emits a token stream where identifier names are replaced
    by positional placeholders (VAR0, VAR1, ...) based on order of first
    appearance, so variable/function naming choices don't count as structural
    differences. Node type and literal values are kept as-is."""

    def __init__(self):
        self.tokens = []
        self.name_map = {}
        self.counter = 0

    def _canon(self, name):
        if name not in self.name_map:
            self.name_map[name] = f"VAR{self.counter}"
            self.counter += 1
        return self.name_map[name]

    def generic_visit(self, node):
        self.tokens.append(type(node).__name__)
        if isinstance(node, ast.Name):
            self.tokens.append(self._canon(node.id))
        elif isinstance(node, ast.FunctionDef):
            self.tokens.append(self._canon(node.name))
        elif isinstance(node, ast.arg):
            self.tokens.append(self._canon(node.arg))
        elif isinstance(node, ast.Constant):
            self.tokens.append(f"CONST:{repr(node.value)}")
        super().generic_visit(node)


def ast_tokens(source):
    tree = ast.parse(source)
    c = Canonicalizer()
    c.visit(tree)
    return c.tokens


def jaccard(tokens_a, tokens_b):
    a, b = set(tokens_a), set(tokens_b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def raw_line_jaccard(source_a, source_b):
    a = set(l.strip() for l in source_a.splitlines() if l.strip())
    b = set(l.strip() for l in source_b.splitlines() if l.strip())
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


results = {}
for pkg in PACKAGES:
    sources = []
    for i in range(1, N_RUNS + 1):
        path = os.path.join(RESULTS_DIR, f"{pkg}_run{i}.py")
        with open(path) as f:
            sources.append(f.read())

    token_sets = [ast_tokens(s) for s in sources]
    pairs = [(i, j) for i in range(N_RUNS) for j in range(i + 1, N_RUNS)]

    ast_scores = [jaccard(token_sets[i], token_sets[j]) for i, j in pairs]
    raw_scores = [raw_line_jaccard(sources[i], sources[j]) for i, j in pairs]

    results[pkg] = {
        "ast_jaccard_avg": round(sum(ast_scores) / len(ast_scores), 4),
        "raw_line_jaccard_avg": round(sum(raw_scores) / len(raw_scores), 4),
    }
    print(f"{pkg}: AST={results[pkg]['ast_jaccard_avg']}  raw-line={results[pkg]['raw_line_jaccard_avg']}")

overall_ast = round(sum(v["ast_jaccard_avg"] for v in results.values()) / len(results), 4)
overall_raw = round(sum(v["raw_line_jaccard_avg"] for v in results.values()) / len(results), 4)
print(f"\nOverall AST Jaccard avg:      {overall_ast}")
print(f"Overall raw-line Jaccard avg: {overall_raw}")

out = {"per_package": results, "overall_ast_jaccard": overall_ast, "overall_raw_line_jaccard": overall_raw}
out_path = os.path.join(REPO, "evaluation/results/m413_ast_comparison.json")
with open(out_path, "w") as f:
    json.dump(out, f, indent=2)
print(f"\nWritten: {out_path}")
