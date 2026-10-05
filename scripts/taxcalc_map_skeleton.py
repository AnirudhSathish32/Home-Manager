"""A starting point for Engine 2's worksheet map (docs/taxes.md "The tax engines", finance/engines/taxcalc_maps/).

Usage:  python scripts/taxcalc_map_skeleton.py [output ...]

Reads the installed Tax-Calculator's calcfunctions.py (its source only; nothing is run) and prints, for each output
named (or every output), the function that works it out, its inputs (record variables and other outputs), the law
parameters it reads, and the first lines of the function's docstring (the form lines it cites). Each function names its
inputs as parameters and returns its outputs by name, so the edges come from the source; the formula for each node is
then written by hand in the map, and the conformance test checks it against the engine's values.
"""
import ast
from importlib import util
import json
from pathlib import Path
import sys

spec = util.find_spec("taxcalc")
if spec is None or not spec.origin:
    sys.exit('Tax-Calculator isn\'t installed (pip install "home-manager[engine2]").')
folder = Path(spec.origin).parent
law = {name.lstrip("_") for name in json.loads((folder / "policy_current_law.json").read_text(encoding="utf-8"))}
tree = ast.parse((folder / "calcfunctions.py").read_text(encoding="utf-8"))
outputs = {}
for function in tree.body:
    if not isinstance(function, ast.FunctionDef) or not function.decorator_list:
        continue
    returned = next((node.value for node in ast.walk(function) if isinstance(node, ast.Return) and node.value is not None), None)
    names = [item.id for item in returned.elts] if isinstance(returned, ast.Tuple) else [returned.id] if isinstance(returned, ast.Name) else []
    parameters = [argument.arg for argument in function.args.args]
    doc = (ast.get_docstring(function) or "").strip().splitlines()[:3]
    for name in names:  # An output can be worked out, then changed, by several functions: each is listed, in order.
        outputs.setdefault(name, []).append({"function": function.name, "inputs": [item for item in parameters if item not in names and item not in law],
                                             "law": [item for item in parameters if item in law], "doc": " ".join(line.strip() for line in doc)})
wanted = sys.argv[1:] or sorted(outputs)
for name in wanted:
    if name not in outputs:
        print(f"{name}: not an output of calcfunctions.py (a record input, or worked out elsewhere)")
        continue
    for found in outputs[name]:
        print(f"{name}  ({found['function']})  {found['doc'][:160]}")
        print(f"  inputs: {', '.join(found['inputs'])}")
        if found["law"]:
            print(f"  law:    {', '.join(found['law'])}")
    if len(outputs[name]) > 1:
        print(f"  ({len(outputs[name])} functions set {name}: the value read back is the last one's)")
