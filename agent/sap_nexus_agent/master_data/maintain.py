"""Master-data maintenance CLI: edit entities via governed full snapshots.

The projection stays write-only-through-batches: every edit reads the
current active snapshot, applies the change in memory, and publishes a NEW
full snapshot through ``import_snapshot`` (dry-run by default). All batch
guarantees — validation, atomic publish, idempotency, rollback to the
previous snapshot — hold unchanged. No direct UPDATE/DELETE is ever issued
against md.* tables.

Connection: SAP_NEXUS_MD_DSN or peer-auth defaults (SAP_NEXUS_MD_DBNAME,
default sap_nexus_dev). Never pass credentials on the command line.

Examples:
    python -m sap_nexus_agent.master_data.maintain list sapnexus:Material
    python -m sap_nexus_agent.master_data.maintain show sapnexus:Material DEMOA1
    python -m sap_nexus_agent.master_data.maintain upsert sapnexus:Material DEMOX1 \
        --name-zh "丁腈密封垫 3mm" --attr materialGroup=GASKET --attr sizeDimension=3mm \
        --attr baseUnitOfMeasure=EA --org plant=1000 --apply
    python -m sap_nexus_agent.master_data.maintain deactivate sapnexus:Customer C10001 --apply
    python -m sap_nexus_agent.master_data.maintain remove sapnexus:Supplier V90000 --apply
    python -m sap_nexus_agent.master_data.maintain export sapnexus:Material backup-materials.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping

import psycopg

from sap_nexus_agent.master_data.importer import import_snapshot

OBJECT_TYPES = ("sapnexus:Material", "sapnexus:Customer", "sapnexus:Supplier")

# Display order for attributes per object type (projection columns).
_ATTRIBUTE_ORDER = {
    "sapnexus:Material": ("materialGroup", "sizeDimension", "baseUnitOfMeasure", "basicText"),
    "sapnexus:Customer": ("city", "country", "searchTerm"),
    "sapnexus:Supplier": ("city", "country", "searchTerm"),
}


def _connect():
    dsn = os.environ.get("SAP_NEXUS_MD_DSN")
    if dsn:
        return psycopg.connect(dsn)
    return psycopg.connect(dbname=os.environ.get("SAP_NEXUS_MD_DBNAME", "sap_nexus_dev"))


def load_active_batch(object_type: str) -> dict[str, Any] | None:
    """Read the active snapshot of one object type as a batch document."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id, source_system, client, coverage::text, source_extracted_at"
            " FROM md.v_snapshot_current WHERE object_type=%s"
            " ORDER BY loaded_at DESC LIMIT 1",
            (object_type,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        snapshot_id, source_system, client, coverage, extracted_at = row
        cur.execute(
            "SELECT canonical_code, status, attributes::text FROM md.v_entity_current"
            " WHERE object_type=%s AND source_system=%s AND client=%s"
            " ORDER BY canonical_code",
            (object_type, source_system, client),
        )
        entities: dict[str, dict[str, Any]] = {}
        for code, status, attributes in cur.fetchall():
            entities[code] = {
                "canonicalCode": code,
                "status": status,
                "descriptions": [],
                "attributes": json.loads(attributes or "{}"),
                "aliases": [],
                "orgScopes": [],
            }
        cur.execute(
            "SELECT canonical_code, language, description, is_official"
            " FROM md.v_entity_description_current WHERE object_type=%s",
            (object_type,),
        )
        for code, language, description, official in cur.fetchall():
            if code in entities:
                entities[code]["descriptions"].append(
                    {"language": language, "text": description, "official": official}
                )
        cur.execute(
            "SELECT canonical_code, alias, alias_source, scope, active"
            " FROM md.v_entity_alias_current WHERE object_type=%s",
            (object_type,),
        )
        for code, alias, source, scope, active in cur.fetchall():
            if code in entities:
                entities[code]["aliases"].append(
                    {"alias": alias, "source": source, "scope": scope, "active": active}
                )
        cur.execute(
            "SELECT canonical_code, org_field, org_value"
            " FROM md.v_entity_org_scope_current WHERE object_type=%s",
            (object_type,),
        )
        for code, field, value in cur.fetchall():
            if code in entities:
                entities[code]["orgScopes"].append({"field": field, "value": value})
        return {
            "batch": {
                "sourceSystem": source_system,
                "client": client,
                "objectType": object_type,
                "snapshotKind": "full",
                "sourceExtractedAt": extracted_at.isoformat() if extracted_at else None,
                "coverage": json.loads(coverage),
            },
            "entities": list(entities.values()),
            "_snapshotId": snapshot_id,
        }


def _entity_view(entity: Mapping[str, Any], object_type: str) -> str:
    attrs = entity.get("attributes") or {}
    ordered = [f"{k}={attrs[k]}" for k in _ATTRIBUTE_ORDER.get(object_type, ()) if attrs.get(k)]
    official = next(
        (d["text"] for d in entity.get("descriptions", []) if d.get("official")),
        entity.get("descriptions", [{}])[0].get("text", "") if entity.get("descriptions") else "",
    )
    orgs = ",".join(f"{s['field']}:{s['value']}" for s in entity.get("orgScopes", []))
    parts = [f"{entity['canonicalCode']:<12} [{entity['status']:<8}] {official}"]
    if ordered:
        parts.append(" ".join(ordered))
    if orgs:
        parts.append(f"({orgs})")
    return "  ".join(parts)


def _require_object_type(value: str) -> str:
    if value not in OBJECT_TYPES:
        raise SystemExit(f"objectType must be one of {', '.join(OBJECT_TYPES)}")
    return value


def _set_description(entity: dict[str, Any], language: str, text: str, *, official: bool) -> None:
    descriptions = entity.setdefault("descriptions", [])
    for desc in descriptions:
        if desc["language"] == language:
            desc["text"] = text
            desc["official"] = official
            break
    else:
        descriptions.append({"language": language, "text": text, "official": official})
    # Exactly one official description per entity (batch contract).
    if official:
        for desc in descriptions:
            if desc["language"] != language:
                desc["official"] = False


def _apply_edit(
    batch: dict[str, Any],
    code: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, str]:
    """Apply one edit op; returns (entity-or-None-after-edit, summary)."""
    entities = {e["canonicalCode"]: e for e in batch["entities"]}
    op = args.command
    if op == "remove":
        if code not in entities:
            return None, f"未找到 {code}（无需移除）"
        removed = entities.pop(code)
        batch["entities"] = [e for e in batch["entities"] if e["canonicalCode"] != code]
        return None, f"移除 {code}（原描述：{removed.get('descriptions', [{}])[0].get('text', '')}）"

    entity = entities.get(code)
    if op in ("activate", "deactivate"):
        if entity is None:
            raise SystemExit(f"实体不存在：{code}")
        target = "active" if op == "activate" else "inactive"
        if entity["status"] == target:
            return entity, f"{code} 已是 {target}（无变化）"
        entity["status"] = target
        return entity, f"{code} 状态 → {target}"

    # upsert
    if entity is None:
        entity = {
            "canonicalCode": code,
            "status": "active",
            "descriptions": [],
            "attributes": {},
            "aliases": [],
            "orgScopes": [],
        }
        batch["entities"].append(entity)
        summary = f"新增 {code}"
    else:
        summary = f"更新 {code}"
    if args.status:
        entity["status"] = args.status
    if args.name_zh:
        _set_description(entity, "zh-CN", args.name_zh, official=True)
    if args.name_en:
        _set_description(entity, "en", args.name_en, official=not any(
            d.get("official") for d in entity["descriptions"] if d["language"] != "en"
        ))
    for pair in args.attr or ():
        key, _, value = pair.partition("=")
        if not key or not value:
            raise SystemExit(f"--attr 需要 key=value 形式：{pair}")
        entity["attributes"][key] = value
    for alias in args.alias or ():
        if not any(a["alias"] == alias for a in entity["aliases"]):
            entity["aliases"].append(
                {"alias": alias, "source": "local-maintain", "scope": "sandbox", "active": True}
            )
    for pair in args.org or ():
        field, _, value = pair.partition("=")
        if not field or not value:
            raise SystemExit(f"--org 需要 field=value 形式：{pair}")
        if not any(s["field"] == field and s["value"] == value for s in entity["orgScopes"]):
            entity["orgScopes"].append({"field": field, "value": value})
    return entity, summary


def _publish(batch: dict[str, Any], args: argparse.Namespace) -> int:
    if args.source_time:
        batch["batch"]["sourceExtractedAt"] = args.source_time
    apply = args.apply
    report = import_snapshot(batch, dry_run=not apply)
    if report.errors:
        for error in report.errors:
            print(f"ERROR {error}")
        return 1
    mode = "DRY-RUN（未发布，加 --apply 生效）" if not apply else (
        "IDEMPOTENT（内容未变化，复用当前快照）" if report.idempotent_reuse else "PUBLISHED"
    )
    print(f"{mode} snapshot={report.snapshot_id} entities={report.entity_count}")
    for superseded in report.superseded_snapshot_ids:
        print(f"superseded {superseded}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="maintain",
        description="维护主数据投影（物料/客户/供应商）——所有编辑经 full snapshot 原子发布",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("list", "show", "export"):
        p = sub.add_parser(name)
        p.add_argument("object_type", type=_require_object_type)
        if name == "show":
            p.add_argument("code")
        if name == "export":
            p.add_argument("file", nargs="?", help="输出文件（缺省打印到 stdout）")

    p = sub.add_parser("upsert")
    p.add_argument("object_type", type=_require_object_type)
    p.add_argument("code")
    p.add_argument("--name-zh", help="中文正式描述（设为 official）")
    p.add_argument("--name-en", help="英文描述")
    p.add_argument("--attr", action="append", help="区分属性 key=value（可重复）")
    p.add_argument("--alias", action="append", help="本地别名（可重复）")
    p.add_argument("--org", action="append", help="组织范围 field=value，如 plant=1000（可重复）")
    p.add_argument("--status", choices=["active", "inactive"])
    p.add_argument("--source-time", help="来源提取时间（ISO）；缺省如实记录 unknown")
    p.add_argument("--apply", action="store_true", help="发布新快照（缺省干跑）")

    for name in ("activate", "deactivate", "remove"):
        p = sub.add_parser(name)
        p.add_argument("object_type", type=_require_object_type)
        p.add_argument("code")
        p.add_argument("--source-time", help="来源提取时间（ISO）；缺省如实记录 unknown")
        p.add_argument("--apply", action="store_true", help="发布新快照（缺省干跑）")

    args = parser.parse_args(argv)

    if args.command == "list":
        batch = load_active_batch(args.object_type)
        if batch is None:
            print(f"{args.object_type} 无 active 快照")
            return 1
        print(f"snapshot={batch['_snapshotId']}  entities={len(batch['entities'])}")
        for entity in batch["entities"]:
            print(_entity_view(entity, args.object_type))
        return 0

    if args.command == "show":
        batch = load_active_batch(args.object_type)
        entity = next(
            (e for e in (batch or {}).get("entities", []) if e["canonicalCode"] == args.code),
            None,
        )
        if entity is None:
            print(f"未找到 {args.code}")
            return 1
        print(_entity_view(entity, args.object_type))
        print(json.dumps(entity, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export":
        batch = load_active_batch(args.object_type)
        if batch is None:
            print(f"{args.object_type} 无 active 快照")
            return 1
        batch.pop("_snapshotId", None)
        payload = json.dumps(batch, ensure_ascii=False, indent=2) + "\n"
        if args.file:
            with open(args.file, "w", encoding="utf-8") as handle:
                handle.write(payload)
            print(f"已导出 {len(batch['entities'])} 个实体到 {args.file}（可作为回滚导入输入）")
        else:
            sys.stdout.write(payload)
        return 0

    # edit operations
    batch = load_active_batch(args.object_type)
    if batch is None:
        print(f"{args.object_type} 无 active 快照；请先用 importer 导入基线批次")
        return 1
    batch.pop("_snapshotId", None)
    _entity, summary = _apply_edit(batch, args.code, args)
    print(summary)
    return _publish(batch, args)


if __name__ == "__main__":
    raise SystemExit(main())
