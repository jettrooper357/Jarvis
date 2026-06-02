"""`jarvis org` — bootstrap and inspect the default agent org."""

from __future__ import annotations

import click


@click.group(help="Manage the default agent org (bootstrap / show).")
def org() -> None:
    """Agent org commands."""


def _manager(db_path: str):
    from openjarvis.agents.manager import AgentManager

    return AgentManager(db_path=db_path) if db_path else AgentManager()


@org.command("bootstrap", help="Instantiate the default org (idempotent).")
@click.option("--db-path", default="", help="Agent DB path (default: configured).")
def bootstrap_cmd(db_path: str) -> None:
    from openjarvis.agents.org import bootstrap_default_org

    manager = _manager(db_path)
    summary = bootstrap_default_org(manager)
    click.echo(
        f"created {len(summary['created'])}, "
        f"skipped {len(summary['skipped'])}; chief={summary['chief_id']}"
    )


def _print_node(node: dict, depth: int = 0) -> None:
    click.echo("  " * depth + f"- {node['name']} ({node['org_role']})")
    for child in node.get("reports", []):
        _print_node(child, depth + 1)


@org.command("show", help="Print the current agent org tree.")
@click.option("--db-path", default="", help="Agent DB path (default: configured).")
def show_cmd(db_path: str) -> None:
    from openjarvis.agents.org import build_org_tree

    manager = _manager(db_path)
    tree = build_org_tree(manager)
    if tree is None:
        click.echo("No org configured (no chief). Run `jarvis org bootstrap`.")
        return
    _print_node(tree)
