"""The action table (GitLab #53, stage 3a): every order's target, action, arguments and an example, and every
object's views, printed from the validator's own data so the words can never drift from the shape.

`reference(book="playbook", section="orders")` and `how_to_play("orders")` serve `render()`. The rows come
from the vocabulary (`harness.surface.vocabulary`: the targets, actions, objects and views), the retirement map
(`harness.surface.retirement`: which old handler each row runs, so its arguments are the handler's own schema)
and the forward map (`harness.surface.forward`: the example row with a placeholder per required argument).
Nothing here is written by hand but the headings.
"""
from __future__ import annotations

from harness.surface import forward as F
from harness.surface import retirement as R
from harness.surface import schemas as S
from harness.surface import vocabulary as V
from harness.surface.dispatch import INDEX

#: The city-state screen's own buttons, the open list `order(to="city_state", action=<button>)` takes.


def _arguments(old: str) -> tuple[list[str], list[str]]:
    """The arguments of a row by their new names: required (those the row does not fix), then optional."""
    row = R.RETIRED[old]
    fixed = {v.name for v in row.fixed.values() if isinstance(v, R.FromArg)}
    rename = row.renames
    required = sorted(rename.get(a, a) for a in S.required(old) if a not in fixed)
    optional = sorted(rename.get(a, a) for a in S.properties(old) - S.required(old) if a not in fixed)
    return required, optional


def order_rows() -> list[dict]:
    """One row per (target, action, handler): the arguments and the example."""
    out = []
    for to, actions in V.ACTIONS.items():
        for action in actions:
            label = R.show(action)
            if action == V.SCREEN_BUTTON:    # the map's row fixes the button from the old argument: its own placeholder
                label = next(k[1] for k in INDEX if k[0] == f"order:{to}" and k[1].startswith("<"))
            for old in INDEX.get((f"order:{to}", label), []):
                required, optional = _arguments(old)
                out.append({"to": to, "action": action, "required": required, "optional": optional,
                            "example": F.render(F.example(old)), "handler": old})
    return out


def inspect_rows() -> list[dict]:
    """One row per (object, view, handler): the selectors and the example."""
    out = []
    for what, views in V.VIEWS.items():
        for view in views:
            for old in INDEX.get((f"inspect:{what}", view), []):
                required, optional = _arguments(old)
                out.append({"what": what, "view": view, "required": required, "optional": optional,
                            "example": F.render(F.example(old)), "handler": old})
    return out


def _words(tool: str) -> list[tuple[str, list[str]]]:
    """The fixed words of a tool (turn's actions, notebook's, session's, answer's choices) with their examples."""
    out = []
    for key, names in INDEX.items():
        if key[0] == tool and key[1]:
            out.append((key[1], [F.render(F.example(n)) for n in names]))
    return out


def _cell(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items) if items else "--"


def render() -> str:
    """The table as Markdown."""
    lines = ["## orders", "",
             "Every order and every read, from the validator's own data (`harness/surface/table.py`): the arguments "
             "a row takes by their names in the new call (`id` is the object; the rest ride under `args` unless the "
             "example shows them at the top level), and one example with a placeholder per required argument. A "
             "refusal names the same shape.", "",
             "### order(to, action, id, args)", "",
             "| to | action | required | optional | example |", "|---|---|---|---|---|"]
    for r in order_rows():
        action = r["action"]
        if action == V.SCREEN_BUTTON:
            action = "a screen button: " + ", ".join(V.SCREEN_BUTTONS)
        lines.append(f"| {r['to']} | {action} | {_cell(r['required'])} | {_cell(r['optional'])} | `{r['example']}` |")
    lines += ["", "### inspect(what, view, id, ...)", "",
              "| what | view | required | optional | example |", "|---|---|---|---|---|"]
    for r in inspect_rows():
        lines.append(f"| {r['what']} | {r['view']} | {_cell(r['required'])} | {_cell(r['optional'])} | `{r['example']}` |")
    for tool, title in (("turn", "turn(action, ...)"), ("answer", "answer(choice, args)"),
                        ("notebook", "notebook(action, args)"), ("session", "session(action, args)")):
        lines += ["", f"### {title}", "", "| word | example |", "|---|---|"]
        for word, examples in _words(tool):
            lines.append(f"| {word} | {' / '.join(f'`{e}`' for e in examples)} |")
    lines += ["", "`question()` takes nothing and shows what the game asks, with its `answers` rows; "
              "`batch(actions=[{tool, args}])` runs rows in order; `reference(book, section)` is the rule book "
              "(`rules`, the default) or this playbook (`playbook`).", ""]
    return "\n".join(lines)
