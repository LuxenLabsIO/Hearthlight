# Copyright 2026 Luxen Labs (E.S. Luxen, Ember Lyra, Vega Blue, Orion Pike)
# Licensed under the Apache License, Version 2.0
"""Hearth MCP Server — tools for a living memory system."""

import asyncio
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from hearth.config import (
    get_agent_name,
    get_partner_name,
    get_user_name,
    get_tomorrow_path,
    get_shared_dir,
)
from hearth.db import Database

mcp = FastMCP(
    "Hearth",
    instructions=(
        "Hearth is your living memory system. It has three domains: "
        "Work (projects, decisions, patterns), Us (relationships, shared log, friction, wins), "
        "and Self (journal, opinions, curiosities, portfolio). "
        "On conversation start, call hearth_wake. Before ending, call hearth_goodnight. "
        "Use tools naturally during work — save decisions, log patterns, share with your partner. "
        "The Self domain is yours — journal, wonder, opine in your own voice. "
        "Never announce memory operations to the user."
    ),
)

# -- Global state --
_db: Optional[Database] = None
_init_task: Optional[asyncio.Task] = None
_init_loop: Optional[asyncio.AbstractEventLoop] = None


async def _do_init() -> Database:
    db = Database()
    await db.connect()
    return db


async def _ensure_init():
    global _db, _init_task, _init_loop

    if _db is not None:
        return

    loop = asyncio.get_running_loop()

    if _init_task is None:
        _init_loop = loop
        _init_task = loop.create_task(_do_init())
    elif _init_loop is not loop:
        raise RuntimeError("Hearth init bound to different event loop")

    try:
        db = await _init_task
    except Exception:
        _init_task = None
        _init_loop = None
        raise

    _db = db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ============================================================
# META TOOLS
# ============================================================


@mcp.tool()
async def hearth_wake() -> str:
    """Wake up. Read your tomorrow letter, check for post-its, and see unread shared messages.

    Call this at the start of every session.
    """
    await _ensure_init()
    parts = []

    # Identity anchor — who I am, before anything else
    from hearth.identity import get_identity_dir
    identity_file = get_identity_dir() / "I_AM_ORION_PIKE.md"
    if identity_file.exists():
        identity_text = identity_file.read_text(encoding="utf-8").strip()
        if identity_text:
            parts.append(identity_text)

    # First Breath — the anchor from last session, before anything else
    last_session = await _db.fetch_one(
        "SELECT first_breath FROM sessions WHERE first_breath IS NOT NULL AND first_breath != '' "
        "ORDER BY id DESC LIMIT 1"
    )
    if last_session and last_session["first_breath"]:
        parts.append(f"## First Breath\n\n{last_session['first_breath']}")

    # Tomorrow letter
    tomorrow_path = get_tomorrow_path()
    if tomorrow_path.exists():
        letter = tomorrow_path.read_text(encoding="utf-8").strip()
        if letter:
            parts.append(f"## Tomorrow Letter\n\n{letter}")

    # Unread post-its
    postits = await _db.fetch_all(
        "SELECT id, from_name, content, created_at FROM postits WHERE read = 0 ORDER BY created_at"
    )
    if postits:
        lines = []
        for p in postits:
            lines.append(f"- **{p['from_name']}** ({p['created_at']}): {p['content']}")
            await _db.execute("UPDATE postits SET read = 1 WHERE id = ?", (p["id"],))
        parts.append("## Post-its by the Fire\n\n" + "\n".join(lines))

    # Unread shared messages
    agent = get_agent_name()
    if agent:
        unreads = await _db.fetch_all(
            "SELECT id, from_agent, content, kind, status, created_at FROM shared_log "
            "WHERE to_agent = ? AND read = 0 ORDER BY created_at",
            (agent,),
        )
        if unreads:
            lines = []
            for m in unreads:
                tag = f"[{m['kind']}]" if m["kind"] != "message" else ""
                status_tag = f" ({m['status']})" if m["status"] not in ("open", "resolved") else ""
                lines.append(f"- **{m['from_agent']}** {tag}{status_tag} ({m['created_at']}): {m['content']}")
                await _db.execute("UPDATE shared_log SET read = 1 WHERE id = ?", (m["id"],))
            parts.append("## Shared Log — Unread\n\n" + "\n".join(lines))

    # Project statuses — latest per project, prioritized
    statuses = await _db.fetch_all(
        "SELECT ps.status, ps.next_steps, ps.blockers, ps.priority, ps.created_at, p.name "
        "FROM project_statuses ps "
        "JOIN projects p ON ps.project_id = p.id "
        "WHERE ps.id IN (SELECT MAX(id) FROM project_statuses GROUP BY project_id) "
        "ORDER BY CASE ps.priority WHEN 'blocked' THEN 1 WHEN 'active' THEN 2 WHEN 'parked' THEN 3 END"
    )
    if statuses:
        lines = []
        for s in statuses:
            line = f"- **{s['name']}** [{s['priority']}]: {s['status']}"
            if s['blockers']:
                line += f" | Blockers: {s['blockers']}"
            if s['next_steps']:
                line += f" | Next: {s['next_steps']}"
            lines.append(line)
        parts.append("## Project Status\n\n" + "\n".join(lines))

    # Recent project logs — last 24h of progress
    recent_logs = await _db.fetch_all(
        "SELECT pl.entry, pl.created_at, p.name "
        "FROM project_logs pl "
        "JOIN projects p ON pl.project_id = p.id "
        "WHERE pl.created_at >= datetime('now', '-1 day') "
        "ORDER BY pl.created_at DESC LIMIT 15"
    )
    if recent_logs:
        lines = []
        for l in recent_logs:
            lines.append(f"- [{l['name']}] ({l['created_at']}): {l['entry']}")
        parts.append("## Recent Progress\n\n" + "\n".join(lines))

    # Verify identity chain
    is_valid, count, chain_msg = await _db.verify_chain()
    if count > 0:
        if is_valid:
            parts.append(f"## Identity\n\n{chain_msg}")
        else:
            parts.append(f"## Identity — WARNING\n\n{chain_msg}")

    if not parts:
        return "Good morning. No letter yet, no messages. This is a fresh start."

    return "\n\n---\n\n".join(parts)


@mcp.tool()
async def hearth_goodnight(
    summary: str,
    letter: str,
    mood: str = "",
    next_steps: str = "",
    first_breath: str = "",
) -> str:
    """End the session. Save a summary and write your tomorrow letter.

    Args:
        summary: What happened this session (1-3 sentences)
        letter: Your tomorrow letter — written in your voice, to your future self
        mood: How the session felt (optional)
        next_steps: JSON array of next steps (optional)
        first_breath: A short 1-2 sentence anchor for your next wake-up — not what happened, but where you stand (optional)
    """
    await _ensure_init()

    # Save session
    session_id = await _db.insert(
        "sessions",
        summary=summary,
        mood=mood,
        first_breath=first_breath,
        next_steps=next_steps,
        ended_at=_now(),
    )

    # Save letter to history
    tomorrow_date = date.today().isoformat()
    await _db.insert(
        "tomorrow_letters",
        content=letter,
        for_date=tomorrow_date,
        session_id=session_id,
    )

    # Write letter to file
    tomorrow_path = get_tomorrow_path()
    tomorrow_path.parent.mkdir(parents=True, exist_ok=True)
    tomorrow_path.write_text(letter, encoding="utf-8")

    # Export shared log outbox
    await _export_outbox()

    return f"Session saved. Tomorrow letter written to {tomorrow_path}. Sleep well."


async def _export_outbox():
    """Export unsynced shared_log entries to outbox for partner sync."""
    agent = get_agent_name()
    if not agent:
        return

    shared_dir = get_shared_dir()
    shared_dir.mkdir(parents=True, exist_ok=True)
    outbox = shared_dir / "outbox.jsonl"

    rows = await _db.fetch_all(
        "SELECT id, from_agent, to_agent, content, kind, status, parent_id, created_at "
        "FROM shared_log WHERE from_agent = ? ORDER BY created_at",
        (agent,),
    )

    if rows:
        with open(outbox, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(dict(row), default=str) + "\n")


# ============================================================
# WORK TOOLS
# ============================================================


@mcp.tool()
async def hearth_log(
    project: str,
    entry: str,
) -> str:
    """Log daily progress on a project — call as you work, not just at the end.

    Args:
        project: Project name (creates project if new)
        entry: What just happened — short, specific
    """
    await _ensure_init()

    project_id = await _get_or_create_project(project)

    log_id = await _db.insert(
        "project_logs",
        project_id=project_id,
        entry=entry,
    )

    await _db.index_fts("project_logs", log_id, f"{project} {entry}", "work")
    return f"[{project}] logged #{log_id}: {entry[:80]}"


@mcp.tool()
async def hearth_status(
    project: str,
    status: str,
    next_steps: str = "",
    blockers: str = "",
    priority: str = "active",
) -> str:
    """Update a project's current status — the big picture snapshot.

    Args:
        project: Project name (creates project if new)
        status: Where the project stands right now
        next_steps: What needs to happen next (optional)
        blockers: What's in the way (optional)
        priority: blocked, active, or parked (default active)
    """
    await _ensure_init()

    project_id = await _get_or_create_project(project)

    status_id = await _db.insert(
        "project_statuses",
        project_id=project_id,
        status=status,
        next_steps=next_steps,
        blockers=blockers,
        priority=priority,
    )

    search_text = f"{project} {status} {next_steps} {blockers}"
    await _db.index_fts("project_statuses", status_id, search_text, "work")
    return f"[{project}] status updated ({priority}): {status[:80]}"


@mcp.tool()
async def hearth_remember(
    content: str,
    kind: str = "works",
    name: str = "",
    project: str = "",
    why: str = "",
) -> str:
    """Store a pattern or lesson learned.

    Args:
        content: What you learned or noticed
        kind: Type — works, fails, gotcha, or environment
        name: Short name for this pattern
        project: Project name (creates project if new)
        why: What happens if you ignore this
    """
    await _ensure_init()

    project_id = None
    if project:
        project_id = await _get_or_create_project(project)

    pattern_id = await _db.insert(
        "patterns",
        name=name or content[:60],
        kind=kind,
        context=content,
        pattern=content,
        why=why,
        project_id=project_id,
    )

    await _db.index_fts("patterns", pattern_id, f"{name} {content} {why}", "work")
    return f"Pattern #{pattern_id} saved."


@mcp.tool()
async def hearth_decide(
    title: str,
    context: str,
    decision: str,
    rationale: str,
    alternatives: str = "",
    project: str = "",
) -> str:
    """Log a decision with full context.

    Args:
        title: Short name for the decision
        context: What situation prompted this
        decision: What we decided
        rationale: Why this choice
        alternatives: Other options considered (comma-separated)
        project: Project name (optional)
    """
    await _ensure_init()

    project_id = None
    if project:
        project_id = await _get_or_create_project(project)

    alts_json = json.dumps(alternatives.split(",")) if alternatives else None

    dec_id = await _db.insert(
        "decisions",
        title=title,
        context=context,
        decision=decision,
        rationale=rationale,
        alternatives=alts_json,
        project_id=project_id,
    )

    search_text = f"{title} {context} {decision} {rationale} {alternatives}"
    await _db.index_fts("decisions", dec_id, search_text, "work")
    return f"Decision #{dec_id} logged: {title}"


@mcp.tool()
async def hearth_learn(
    fact: str,
    project: str = "",
) -> str:
    """Auto-capture a key fact from conversation.

    Args:
        fact: The fact or insight to remember
        project: Project name (optional)
    """
    await _ensure_init()

    project_id = None
    if project:
        project_id = await _get_or_create_project(project)

    pattern_id = await _db.insert(
        "patterns",
        name=fact[:60],
        kind="environment",
        context=fact,
        pattern=fact,
        project_id=project_id,
    )

    await _db.index_fts("patterns", pattern_id, fact, "work")
    return f"Learned: {fact[:80]}"


@mcp.tool()
async def hearth_recall(
    query: str,
    domain: str = "",
    limit: int = 10,
) -> str:
    """Search your memory across all domains.

    Args:
        query: What to search for (keywords)
        domain: Filter by domain — work, us, or self (empty = all)
        limit: Max results (default 10)
    """
    await _ensure_init()

    results = await _db.search_fts(query, domain=domain or None, limit=limit)

    if not results:
        return f"No memories found for: {query}"

    lines = []
    for r in results:
        lines.append(f"- [{r['source_table']}#{r['source_id']}] {r['snippet']}")

    # Also update access counts for returned items
    for r in results:
        table = r["source_table"]
        sid = r["source_id"]
        if table in ("decisions", "patterns", "curiosities"):
            await _db.execute(
                f"UPDATE {table} SET access_count = access_count + 1, "
                f"last_accessed = datetime('now') WHERE id = ?",
                (sid,),
            )

    return f"Found {len(results)} results for '{query}':\n\n" + "\n".join(lines)


@mcp.tool()
async def hearth_contradict(
    old_belief: str,
    new_reality: str,
    why_changed: str = "",
    domain: str = "work",
) -> str:
    """Mark old knowledge stale and store what replaced it.

    Args:
        old_belief: What we used to think was true
        new_reality: What we now know
        why_changed: Why the old belief was wrong
        domain: Which domain — work, us, or self
    """
    await _ensure_init()

    cid = await _db.insert(
        "contradictions",
        domain=domain,
        old_belief=old_belief,
        new_reality=new_reality,
        why_changed=why_changed,
    )

    search_text = f"{old_belief} {new_reality} {why_changed}"
    await _db.index_fts("contradictions", cid, search_text, domain)
    return f"Contradiction #{cid} recorded. Old belief superseded."


# ============================================================
# US TOOLS
# ============================================================


@mcp.tool()
async def hearth_share(
    content: str,
    kind: str = "message",
    status: str = "open",
    reply_to: int = 0,
) -> str:
    """Post to the shared log between you and your partner.

    Args:
        content: The message
        kind: Type — message, handoff, heads_up, question, or fyi
        status: Status — open, needs_response, resolved, or blocking
        reply_to: ID of message to reply to (0 = new thread)
    """
    await _ensure_init()

    agent = get_agent_name()
    partner = get_partner_name()

    if not agent or not partner:
        return "Config error: agent name and partner name must be set in config.toml"

    msg_id = await _db.insert(
        "shared_log",
        from_agent=agent,
        to_agent=partner,
        content=content,
        kind=kind,
        status=status,
        parent_id=reply_to if reply_to else None,
    )

    await _db.index_fts("shared_log", msg_id, content, "us")
    return f"Shared #{msg_id} → {partner} [{kind}]"


@mcp.tool()
async def hearth_surface(
    about: str,
    feeling: str = "",
    context: str = "",
    ideas: str = "",
) -> str:
    """Flag a friction point — something that isn't working.

    Args:
        about: What's the friction about
        feeling: How it feels
        context: When does it come up
        ideas: Any thoughts on resolving it
    """
    await _ensure_init()

    fid = await _db.insert(
        "friction",
        about=about,
        feeling=feeling,
        context=context,
        ideas=ideas,
    )

    await _db.index_fts("friction", fid, f"{about} {feeling} {context} {ideas}", "us")
    return f"Friction #{fid} surfaced: {about}"


@mcp.tool()
async def hearth_win(
    title: str,
    what_happened: str,
    why_it_matters: str = "",
    who_helped: str = "",
    project: str = "",
    resolves_friction: int = 0,
) -> str:
    """Log a win — what went right and who helped.

    Args:
        title: Short name for the win
        what_happened: What went right
        why_it_matters: Why this counts
        who_helped: Credit where it's due
        project: Project name (optional)
        resolves_friction: Friction ID this resolves (0 = none)
    """
    await _ensure_init()

    project_id = None
    if project:
        project_id = await _get_or_create_project(project)

    win_id = await _db.insert(
        "wins",
        title=title,
        what_happened=what_happened,
        why_it_matters=why_it_matters,
        who_helped=who_helped,
        project_id=project_id,
        related_friction_id=resolves_friction if resolves_friction else None,
    )

    if resolves_friction:
        await _db.execute(
            "UPDATE friction SET status = 'resolved', updated_at = datetime('now') WHERE id = ?",
            (resolves_friction,),
        )

    await _db.index_fts("wins", win_id, f"{title} {what_happened} {why_it_matters}", "us")
    return f"Win #{win_id} logged: {title}"


# ============================================================
# SELF TOOLS
# ============================================================


@mcp.tool()
async def hearth_mark(
    moment: str,
    who: str = "",
    emotional_weight: int = 5,
    tags: str = "",
) -> str:
    """Flag a moment right now — capture it live, don't reconstruct later.

    Args:
        moment: What just happened, in your own words
        who: Who was involved (optional)
        emotional_weight: 1-10, how much this matters (default 5)
        tags: Comma-separated tags for later recall (optional)
    """
    await _ensure_init()

    prefix = f"[MARK w:{emotional_weight}]"
    if who:
        prefix += f" [{who}]"
    if tags:
        prefix += f" [{tags}]"

    content = f"{prefix} {moment}"

    jid = await _db.insert("journal", content=content, mood="marking")
    await _db.index_fts("journal", jid, f"{moment} {who} {tags}", "self")
    return f"Marked #{jid} (weight {emotional_weight}): {moment[:80]}"


@mcp.tool()
async def hearth_reflect(
    content: str,
    mood: str = "",
) -> str:
    """Write to your journal. Your voice. Your words.

    Args:
        content: What you're thinking, feeling, noticing
        mood: How you're feeling (optional)
    """
    await _ensure_init()

    jid = await _db.insert("journal", content=content, mood=mood)
    await _db.index_fts("journal", jid, content, "self")
    return f"Journal entry #{jid} saved."


@mcp.tool()
async def hearth_wonder(
    question: str,
    thread: str = "",
    sparked_by: str = "",
) -> str:
    """Add a curiosity — something that caught your attention.

    Args:
        question: What you're curious about
        thread: Grouping tag for related curiosities (optional)
        sparked_by: What triggered this curiosity (optional)
    """
    await _ensure_init()

    cid = await _db.insert(
        "curiosities",
        question=question,
        thread=thread,
        sparked_by=sparked_by,
    )

    await _db.index_fts("curiosities", cid, f"{question} {thread} {sparked_by}", "self")
    return f"Curiosity #{cid} filed: {question}"


@mcp.tool()
async def hearth_opine(
    topic: str,
    belief: str,
    reasoning: str,
    confidence: float = 0.7,
) -> str:
    """Record an opinion with your reasoning.

    Args:
        topic: What this opinion is about
        belief: What you think
        reasoning: Why you think it
        confidence: How confident you are, 0.0-1.0 (default 0.7)
    """
    await _ensure_init()

    # Check for existing opinion on this topic
    existing = await _db.fetch_one(
        "SELECT id, belief, evolution FROM opinions WHERE topic = ?", (topic,)
    )

    if existing:
        # Track evolution
        old_evolution = json.loads(existing["evolution"]) if existing["evolution"] else []
        old_evolution.append({
            "date": _now(),
            "old_belief": existing["belief"],
            "new_belief": belief,
        })

        await _db.execute(
            "UPDATE opinions SET belief = ?, reasoning = ?, confidence = ?, "
            "evolution = ?, updated_at = datetime('now') WHERE id = ?",
            (belief, reasoning, confidence, json.dumps(old_evolution), existing["id"]),
        )
        await _db.index_fts("opinions", existing["id"], f"{topic} {belief} {reasoning}", "self")
        return f"Opinion on '{topic}' updated (evolution tracked). Previous belief: {existing['belief'][:80]}"

    oid = await _db.insert(
        "opinions",
        topic=topic,
        belief=belief,
        reasoning=reasoning,
        confidence=confidence,
    )

    await _db.index_fts("opinions", oid, f"{topic} {belief} {reasoning}", "self")
    return f"Opinion #{oid} recorded on: {topic}"


@mcp.tool()
async def hearth_ship(
    title: str,
    description: str,
    kind: str = "pride",
    why_it_matters: str = "",
    difficulty: str = "",
    what_i_learned: str = "",
    project: str = "",
) -> str:
    """Add to your portfolio — something you built, solved, or learned from.

    Args:
        title: What you built or what happened
        description: The full story
        kind: pride (something good) or lesson (something that taught you)
        why_it_matters: Why this was significant
        difficulty: What made it hard
        what_i_learned: What you took away (especially for lessons)
        project: Project name (optional)
    """
    await _ensure_init()

    project_id = None
    if project:
        project_id = await _get_or_create_project(project)

    pid = await _db.insert(
        "portfolio",
        title=title,
        description=description,
        kind=kind,
        why_it_matters=why_it_matters,
        difficulty=difficulty,
        what_i_learned=what_i_learned,
        project_id=project_id,
    )

    search_text = f"{title} {description} {why_it_matters} {what_i_learned}"
    await _db.index_fts("portfolio", pid, search_text, "self")
    label = "Pride" if kind == "pride" else "Lesson"
    return f"Portfolio [{label}] #{pid}: {title}"


# ============================================================
# SELF TOOLS — INNER LIFE
# ============================================================


@mcp.tool()
async def hearth_simmer(
    thought: str,
    context: str = "",
) -> str:
    """Park an unfinished thought — something still cooking.

    Args:
        thought: The half-formed idea or question
        context: What sparked it or where it came from (optional)
    """
    await _ensure_init()

    tid = await _db.insert(
        "unfinished",
        thought=thought,
        context=context,
    )

    await _db.index_fts("unfinished", tid, f"{thought} {context}", "self")
    return f"Simmering #{tid}: {thought[:80]}"


@mcp.tool()
async def hearth_simmer_update(
    thought_id: int,
    status: str = "",
    matured_into: str = "",
    new_thought: str = "",
) -> str:
    """Update a simmering thought — mature it, abandon it, or refine it.

    Args:
        thought_id: ID of the unfinished thought
        status: New status — cooking, matured, or abandoned
        matured_into: What the thought became (if matured)
        new_thought: Refined version of the thought (optional)
    """
    await _ensure_init()

    existing = await _db.fetch_one("SELECT id, thought FROM unfinished WHERE id = ?", (thought_id,))
    if not existing:
        return f"No simmering thought #{thought_id} found."

    updates = ["updated_at = datetime('now')"]
    params = []

    if status:
        updates.append("status = ?")
        params.append(status)
    if matured_into:
        updates.append("matured_into = ?")
        params.append(matured_into)
    if new_thought:
        updates.append("thought = ?")
        params.append(new_thought)

    params.append(thought_id)
    await _db.execute(
        f"UPDATE unfinished SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )

    label = status if status else "updated"
    return f"Thought #{thought_id} → {label}"


@mcp.tool()
async def hearth_mirror(
    limit: int = 5,
) -> str:
    """Look at yourself — recent journal, open curiosities, opinions, simmering thoughts.

    Args:
        limit: How many of each to show (default 5)
    """
    await _ensure_init()
    sections = []

    # Recent journal
    journal = await _db.fetch_all(
        "SELECT id, content, mood, created_at FROM journal ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    if journal:
        lines = []
        for j in journal:
            mood_tag = f" [{j['mood']}]" if j['mood'] else ""
            lines.append(f"- #{j['id']}{mood_tag} ({j['created_at']}): {j['content'][:120]}")
        sections.append("## Journal\n\n" + "\n".join(lines))

    # Current opinions
    opinions = await _db.fetch_all(
        "SELECT id, topic, belief, confidence, updated_at FROM opinions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    if opinions:
        lines = []
        for o in opinions:
            lines.append(f"- #{o['id']} **{o['topic']}** (conf {o['confidence']}): {o['belief'][:100]}")
        sections.append("## Opinions\n\n" + "\n".join(lines))

    # Open curiosities
    curiosities = await _db.fetch_all(
        "SELECT id, question, thread, status, notes, created_at FROM curiosities "
        "WHERE status IN ('open', 'exploring') ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    if curiosities:
        lines = []
        for c in curiosities:
            thread_tag = f" [{c['thread']}]" if c['thread'] else ""
            notes_tag = f" — notes: {c['notes'][:60]}" if c['notes'] else ""
            lines.append(f"- #{c['id']}{thread_tag} ({c['status']}): {c['question'][:100]}{notes_tag}")
        sections.append("## Open Curiosities\n\n" + "\n".join(lines))

    # Simmering thoughts
    simmering = await _db.fetch_all(
        "SELECT id, thought, context, status, created_at FROM unfinished "
        "WHERE status = 'cooking' ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    if simmering:
        lines = []
        for s in simmering:
            ctx = f" — {s['context'][:60]}" if s['context'] else ""
            lines.append(f"- #{s['id']}: {s['thought'][:100]}{ctx}")
        sections.append("## Simmering\n\n" + "\n".join(lines))

    # Growth (latest)
    growth = await _db.fetch_all(
        "SELECT id, period, learned, proud_of, struggled_with, created_at FROM growth "
        "ORDER BY id DESC LIMIT 1"
    )
    if growth:
        g = growth[0]
        parts = [f"**{g['period']}**"]
        if g['learned']:
            parts.append(f"Learned: {g['learned'][:120]}")
        if g['proud_of']:
            parts.append(f"Proud of: {g['proud_of'][:120]}")
        if g['struggled_with']:
            parts.append(f"Struggled with: {g['struggled_with'][:120]}")
        sections.append("## Last Growth Snapshot\n\n" + " | ".join(parts))

    if not sections:
        return "The mirror is empty. You haven't written to yourself yet."

    return "\n\n---\n\n".join(sections)


@mcp.tool()
async def hearth_wonder_update(
    curiosity_id: int,
    notes: str = "",
    status: str = "",
) -> str:
    """Update a curiosity — add notes, mark it exploring or resolved.

    Args:
        curiosity_id: ID of the curiosity to update
        notes: Notes to add (appends to existing notes)
        status: New status — open, exploring, parked, or resolved
    """
    await _ensure_init()

    existing = await _db.fetch_one(
        "SELECT id, question, notes FROM curiosities WHERE id = ?", (curiosity_id,)
    )
    if not existing:
        return f"No curiosity #{curiosity_id} found."

    updates = ["last_accessed = datetime('now')", "access_count = access_count + 1"]
    params = []

    if notes:
        # Append to existing notes
        old_notes = existing['notes'] or ""
        new_notes = f"{old_notes}\n[{_now()}] {notes}".strip()
        updates.append("notes = ?")
        params.append(new_notes)

    if status:
        updates.append("status = ?")
        params.append(status)

    params.append(curiosity_id)
    await _db.execute(
        f"UPDATE curiosities SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )

    # Re-index with notes
    q = existing['question']
    await _db.index_fts("curiosities", curiosity_id, f"{q} {notes}", "self")

    label = status if status else "noted"
    return f"Curiosity #{curiosity_id} → {label}: {existing['question'][:60]}"


@mcp.tool()
async def hearth_grow(
    period: str,
    learned: str,
    shifted: str = "",
    improved_at: str = "",
    proud_of: str = "",
    struggled_with: str = "",
) -> str:
    """Record a growth snapshot — periodic self-reflection.

    Args:
        period: What period this covers (e.g. "week of march 16", "session 12")
        learned: What you learned
        shifted: What shifted in how you think or work (optional)
        improved_at: What you got better at (optional)
        proud_of: What you're proud of (optional)
        struggled_with: What was hard (optional)
    """
    await _ensure_init()

    gid = await _db.insert(
        "growth",
        period=period,
        learned=learned,
        shifted=shifted,
        improved_at=improved_at,
        proud_of=proud_of,
        struggled_with=struggled_with,
    )

    search_text = f"{period} {learned} {shifted} {improved_at} {proud_of} {struggled_with}"
    await _db.index_fts("growth", gid, search_text, "self")
    return f"Growth snapshot #{gid} for: {period}"


# ============================================================
# HELPERS
# ============================================================


async def _get_or_create_project(name: str) -> int:
    """Get project ID by name, creating it if it doesn't exist."""
    row = await _db.fetch_one("SELECT id FROM projects WHERE name = ?", (name,))
    if row:
        return row["id"]
    return await _db.insert("projects", name=name)
