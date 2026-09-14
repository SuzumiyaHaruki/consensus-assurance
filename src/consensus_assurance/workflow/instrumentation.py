"""Recognize a deliberately narrow observation-only harness edit without trusting review flags."""
import ast


def observation_change_limitations(harness, binding_ids):
    if not harness.semantic_changes:
        return []
    reviews = harness.observation_changes
    if sorted(r.change_index for r in reviews) != list(range(len(harness.semantic_changes))):
        return ['Every instrumentation difference needs a located observation review']
    if harness.kind != 'python':
        return ['Observation-only edit verification is currently supported only for Python print statements']
    try:
        full = ast.parse(harness.source)
    except SyntaxError:
        return ['Harness cannot be parsed for observation review']
    for node in ast.walk(full):
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Store) and node.id in {'print','json'}:
            return ['Observation helpers are rebound by the harness']
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in {'print','json'}:
            return ['Observation helpers are shadowed by the harness']
        if isinstance(node,ast.arg) and node.arg in {'print','json'}:
            return ['Observation helpers are shadowed by arguments']
    lines = harness.source.splitlines()
    for review in reviews:
        if not review.rationale.strip() or not set(review.binding_ids) <= set(binding_ids) or not 1 <= review.start_line <= review.end_line <= len(lines):
            return ['Observation edit review lacks a valid range, rationale or code binding']
        import textwrap
        try:
            tree = ast.parse(textwrap.dedent('\n'.join(lines[review.start_line-1:review.end_line])))
        except SyntaxError:
            return ['Observation-only edit cannot be parsed']
        def value(node):
            if isinstance(node,(ast.Name,ast.Constant)): return True
            if isinstance(node,ast.Subscript): return value(node.value) and value(node.slice)
            if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add): return value(node.left) and value(node.right)
            if isinstance(node,ast.Call):
                return isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='json' and node.func.attr=='dumps' and not node.keywords and len(node.args)==1 and value(node.args[0])
            return False
        if not tree.body or any(not isinstance(n,ast.Expr) or not isinstance(n.value,ast.Call) or not isinstance(n.value.func,ast.Name) or n.value.func.id!='print' or n.value.keywords or not all(value(a) for a in n.value.args) for n in tree.body):
            return ['Reported edit is not in the supported observation-only print subset']
    return []
