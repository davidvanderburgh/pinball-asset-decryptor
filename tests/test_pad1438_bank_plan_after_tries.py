"""PAD-1438: the bank plan's clean-up runs after the plan's tries, not inside them.

PAD-1378 put ``_plan_sound_banks`` in a two-try loop (a song file with no bank room is left
out and the plan tried again) and the block after it, which takes the banked sounds out of
``_user_grows`` and keeps the earlier Write's bank map, went into the loop too, after the
``break`` a plan that comes out at once takes.  It never ran: every sound the banks play was
grown in image.bin as well, and Godzilla Pro 1.16's idx 456 (a song the game plays in parts,
sound ids 2489 and 2527) then carried its longer record's key into the bank, refused as
"sound id 2489's descriptor names a record outside its sound bank".
"""
import ast
import inspect
import textwrap

from pinball_decryptor.plugins.stern import engine as E


def _tries_loop(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id == "_bank_try"):
            return node
    raise AssertionError("no _bank_try loop")


def _sets_old_map(node):
    return any(isinstance(n, ast.Attribute) and n.attr == "old_map"
               and isinstance(n.ctx, ast.Store) for n in ast.walk(node))


def test_the_bank_plan_clean_up_follows_the_tries_loop():
    src = inspect.getsource(E._compute_patches_inner)
    tree = ast.parse(textwrap.dedent(src))
    loop = _tries_loop(tree)
    assert not _sets_old_map(loop), "the clean-up is inside the tries: a break skips it"
    # it is the statement straight after the loop, in the same block
    for parent in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(parent, field, None)
            if isinstance(stmts, list) and loop in stmts:
                after = stmts[stmts.index(loop) + 1]
                assert isinstance(after, ast.If) and _sets_old_map(after)
                assert "_user_grows" in ast.unparse(after)
                return
    raise AssertionError("the tries loop's block not found")

