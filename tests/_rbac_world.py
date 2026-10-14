"""Shared fixture data for the auth-on route tests: users in every role, two
projects, and one of each resource (including a ready code source) in project A. Used by tests/test_rbac_matrix.py."""

from dataclasses import dataclass, field

from backend.auth.tokens import create_access_token, create_pat
from backend.db import crud, crud_auth, crud_comments, crud_projects


@dataclass
class World:
    project_a: str
    project_b: str
    model: str
    threat: str
    asset: str
    flow: str
    boundary: str
    comment: str
    diagram: str
    attack_tree: str
    source: str
    users: dict[str, dict] = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)


async def _user(name: str, *, is_admin: bool = False) -> dict:
    return await crud_auth.create_user(
        username=name,
        email=f"{name}@test.local",
        password_hash="unusable",  # noqa: S106 - tokens are minted directly; no login
        is_admin=is_admin,
    )


async def build_world() -> World:
    """Owner/editor/viewer of project A, a stranger who only belongs to project B,
    and an instance admin. Each identity gets a JWT; `pat_b` is the owner's PAT
    scoped to project B (the owner is also a viewer of B)."""
    owner = await _user("owner")
    editor = await _user("editor")
    viewer = await _user("viewer")
    stranger = await _user("stranger")
    admin = await _user("instadmin", is_admin=True)

    project_a = (await crud_projects.create_project("A", owner["id"]))["id"]
    project_b = (await crud_projects.create_project("B", stranger["id"]))["id"]
    await crud_projects.add_member(project_a, editor["id"], "editor")
    await crud_projects.add_member(project_a, viewer["id"], "viewer")
    await crud_projects.add_member(project_b, owner["id"], "viewer")

    model = await crud.create_threat_model(
        title="M",
        description="A web app with a database",
        provider="anthropic",
        model="m",
        project_id=project_a,
    )
    threat = await crud.create_threat(
        model_id=model,
        name="T",
        description="d",
        target="db",
        impact="High",
        likelihood="Medium",
        mitigations=["m"],
        stride_category="Spoofing",
    )
    asset = await crud.create_asset(model, "Asset", "DB", "database")
    flow = await crud.create_flow(model, "data", "app to db", "app", "db")
    boundary = await crud.create_trust_boundary(model, "edge", "internet", "app")
    comment = (await crud_comments.create_comment(model, owner["id"], "hello"))["id"]
    diagram = (
        await crud.replace_model_diagrams(
            model,
            [{"name": "arch", "kind": "mermaid", "content": "graph TD; A-->B", "size_bytes": 15}],
        )
    )[0]
    attack_tree = await crud.create_attack_tree(threat, "graph TD; G-->A")
    source = await crud.create_code_source(
        name="repo-a",
        git_url="https://github.com/acme/repo-a.git",
        ref=None,
        pat=None,
        project_id=project_a,
        created_by=owner["id"],
    )
    await crud.update_code_source_status(source, status="ready")

    users = {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "stranger": stranger,
        "admin": admin,
    }
    tokens = {
        name: create_access_token(u["id"], u["username"], bool(u["is_admin"]))
        for name, u in users.items()
    }
    token_id, raw, token_hash = create_pat()
    await crud_auth.create_pat(
        token_id, owner["id"], "scoped-to-b", token_hash, project_id=project_b
    )
    tokens["pat_b"] = raw
    # The same owner's PAT with no project scope keeps the owner's memberships.
    token_id, raw, token_hash = create_pat()
    await crud_auth.create_pat(token_id, owner["id"], "unscoped", token_hash)
    tokens["pat_free"] = raw
    # An instance admin's PAT scoped to B is limited to B too.
    token_id, raw, token_hash = create_pat()
    await crud_auth.create_pat(
        token_id, admin["id"], "admin-scoped-to-b", token_hash, project_id=project_b
    )
    tokens["pat_admin_b"] = raw

    return World(
        project_a=project_a,
        project_b=project_b,
        model=model,
        threat=threat,
        asset=asset,
        flow=flow,
        boundary=boundary,
        comment=comment,
        diagram=diagram,
        attack_tree=attack_tree,
        source=source,
        users=users,
        tokens=tokens,
    )
