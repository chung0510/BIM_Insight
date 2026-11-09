from datetime import datetime, timezone
import json
import re
from app.schemas import ASSET_FILES
from app.limits import MAX_REPORT_BYTES
from app.ifc_policy import IFC_GEOMETRY_POLICY

from fastapi import HTTPException
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class ProjectStore:
    def __init__(self, database, directory, storage=None, access=None):
        self.database = database
        self.directory = directory
        self.storage = storage
        self.access = access
        self.indexed = False

    def ensure_local(self, relative):
        return self.storage.ensure_local(relative) if self.storage else self.directory / relative

    def ensure_indexes(self):
        if self.indexed:
            return
        self.database.project_inspections.create_index([("project_id", ASCENDING), ("logical_source", ASCENDING), ("revision", ASCENDING)], unique=True, partialFilterExpression={"published_version": True})
        for collection in [self.database.project_inspections, self.database.project_runs]:
            collection.create_index([("project_id", ASCENDING), ("created_at", DESCENDING), ("_id", ASCENDING)])
        self.database.project_issues.create_index([("project_id", ASCENDING), ("run_id", ASCENDING), ("issue_id", ASCENDING)], unique=True)
        self.database.project_cases.create_index([("project_id", ASCENDING), ("run_id", ASCENDING), ("case_id", ASCENDING)], unique=True)
        self.indexed = True

    def require_project(self, identifier, permission="view"):
        project = self.access.require_project(identifier, permission) if self.access else self.database.projects.find_one({"_id": str(identifier)})
        if project is None:
            raise HTTPException(404, "project_not_found")
        self.ensure_indexes()
        return project

    def list_projects(self, offset, limit, scope="all"):
        collection = self.database.projects
        if self.access:
            query = self.access.project_scope(scope)
            items = list(collection.find(query).sort([("created_at", DESCENDING), ("_id", ASCENDING)]).skip(offset).limit(limit))
            return {"items": [self.access.project_info(item) for item in items], "total": collection.count_documents(query), "offset": offset, "limit": limit}
        items = list(collection.find({}, {"_id": 1, "name": 1, "description": 1, "created_at": 1}).sort([("created_at", DESCENDING), ("_id", ASCENDING)]).skip(offset).limit(limit))
        return {"items": [{"id": item.pop("_id"), **item} for item in items], "total": collection.count_documents({}), "offset": offset, "limit": limit}

    def read_report(self, identifier, folder="reports"):
        kinds = {"reports": "report", "clashes": "clash", "links": "link"}
        if folder not in kinds or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "report_not_found")
        if self.access:
            self.access.require_artifact(kinds[folder], identifier)
        path = self.ensure_local(f"{folder}/{identifier}.json")
        try:
            if path.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError
            report = json.loads(path.read_text(encoding="utf-8"))
            if report["id"] != identifier:
                raise ValueError
            return report
        except (OSError, ValueError, KeyError):
            raise HTTPException(409, "project_artifact_missing") from None

    def existing_version(self, context, digest, *, automatic=False):
        self.require_project(context["project_id"], "edit")
        query = {**context, "published_version": True}
        if automatic:
            query.pop("revision", None)
        existing = self.database.project_inspections.find_one(query, sort=[("created_at", DESCENDING), ("_id", ASCENDING)])
        if existing is None:
            return None
        if existing["sha256"] != digest:
            if automatic:
                return None
            raise HTTPException(409, "source_revision_conflict")
        report = self.read_report(existing["_id"])
        if automatic and report["kind"] == "ifc" and (report.get("result") or {}).get("geometry_policy") != IFC_GEOMETRY_POLICY:
            return None
        if report["kind"] == "dwg" and not (report.get("result") or {}).get("conversion"):
            raise HTTPException(409, "dwg_reimport_required")
        for filename, key in ASSET_FILES.items():
            if not report.get("assets", {}).get(key):
                continue
            if not self.ensure_local(f"assets/{existing['_id']}/{filename}").is_file():
                raise HTTPException(409, "project_artifact_missing")
        return report

    def backup_paths(self, identifier):
        self.require_project(identifier)
        identifier, paths = str(identifier), set()
        for row in self.database.project_inspections.find({"project_id": identifier, "published_version": True}):
            report = self.read_report(row["_id"])
            paths.add(f"reports/{row['_id']}.json")
            cache = "models" if report["kind"] == "ifc" else "files"
            paths.add(f"cache/{cache}/{report['sha256']}.{report['kind']}")
            for filename, key in ASSET_FILES.items():
                if report.get("assets", {}).get(key):
                    paths.add(f"assets/{row['_id']}/{filename}")
        for row in self.database.project_runs.find({"project_id": identifier, "ready": True}):
            paths.add(f"clashes/{row['_id']}.json")
            report = self.read_report(row["_id"], "clashes")
            link = report.get("drawing_link")
            if link and link.get("id"):
                paths.add(f"links/{link['id']}.json")
        for row in self.database.project_links.find({"project_id": identifier}):
            paths.add(f"links/{row['_id']}.json")
        return sorted(paths)

    def save_inspection(self, report):
        self.require_project(report["project_id"])
        record = {"_id": report["id"], "project_id": report["project_id"], "logical_source": report["logical_source"], "revision": report["revision"], "sha256": report["sha256"], "status": report["status"], "created_at": report["created_at"], "published_version": report["status"] in {"completed", "partial"}}
        try:
            self.database.project_inspections.insert_one(record)
        except DuplicateKeyError:
            context = {key: report[key] for key in ["project_id", "logical_source", "revision"]}
            existing = self.existing_version(context, report["sha256"])
            if existing:
                return existing
            raise HTTPException(409, "source_revision_conflict") from None
        return report

    def inspections(self, identifier, offset, limit, revision=None):
        self.require_project(identifier)
        query = {"project_id": str(identifier), "published_version": True}
        if revision:
            query["revision"] = revision
        collection = self.database.project_inspections
        if not revision:
            # The workspace opens the latest source; run history retains its original report IDs.
            result = next(collection.aggregate([
                {"$match": query}, {"$sort": {"created_at": -1, "_id": 1}},
                {"$group": {"_id": "$logical_source", "source": {"$first": "$$ROOT"}}},
                {"$replaceWith": "$source"}, {"$sort": {"created_at": -1, "_id": 1}},
                {"$facet": {"items": [{"$skip": offset}, {"$limit": limit}], "count": [{"$count": "total"}]}}
            ]))
            return {"items": [self.read_report(item["_id"]) for item in result["items"]], "total": next(iter(result["count"]), {}).get("total", 0), "offset": offset, "limit": limit}
        records = collection.find(query).sort([("created_at", DESCENDING), ("_id", ASCENDING)]).skip(offset).limit(limit)
        return {"items": [self.read_report(item["_id"]) for item in records], "total": collection.count_documents(query), "offset": offset, "limit": limit}

    def delete_project(self, identifier):
        from app.project_cleanup import delete_project
        return delete_project(self, str(identifier))

    def save_run(self, report):
        self.require_project(report["project_id"])
        record = {"_id": report["id"], **{key: report.get(key) for key in ["project_id", "revision", "created_at", "status", "verdict", "dataset", "parameters", "coverage", "counts"]}, "issue_count": len(report["issues"]), "ready": False}
        self.database.project_runs.insert_one(record)
        if report["issues"]:
            self.database.project_issues.insert_many([{"_id": f"{report['id']}:{issue['id']}", "project_id": report["project_id"], "run_id": report["id"], "issue_id": issue["id"], "review": {"revision": 0, "state": "unreviewed", "reviewer": "", "note": "", "updated_at": None}} for issue in report["issues"]])
        cases = (report.get("evaluation") or {}).get("case_results", [])
        if cases:
            self.database.project_cases.insert_many([{"_id": f"{report['id']}:{case['case_id']}", "project_id": report["project_id"], "run_id": report["id"], **case, "review": {"revision": 0, "label": "unreviewed", "reviewer": "", "note": "", "updated_at": None}} for case in cases])
        self.database.project_runs.update_one({"_id": report["id"]}, {"$set": {"ready": True}})

    def runs(self, identifier, offset, limit):
        self.require_project(identifier)
        query = {"project_id": str(identifier), "ready": True}
        collection = self.database.project_runs
        records = list(collection.find(query).sort([("created_at", DESCENDING), ("_id", ASCENDING)]).skip(offset).limit(limit))
        return {"items": [{"id": item.pop("_id"), **item} for item in records], "total": collection.count_documents(query), "offset": offset, "limit": limit}

    def require_run(self, identifier, run_id):
        self.require_project(identifier)
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or self.database.project_runs.find_one({"_id": run_id, "project_id": str(identifier), "ready": True}) is None:
            raise HTTPException(404, "run_not_found")

    def restore_run(self, identifier, run_id):
        self.require_run(identifier, run_id)
        report = self.read_report(run_id, "clashes")
        if report.get("project_id") != str(identifier):
            raise HTTPException(404, "run_not_found")
        source_ids = [source["id"] for source in report["sources"]]
        if report.get("drawing_link"):
            source_ids.append(report["drawing_link"]["drawing_id"])
        inspections = [self.read_report(source_id) for source_id in dict.fromkeys(source_ids)]
        if any(item.get("project_id") != str(identifier) for item in inspections):
            raise HTTPException(409, "project_artifact_missing")
        return {"report": report, "inspections": inspections}

    def reviews(self, identifier, run_id):
        self.require_run(identifier, run_id)
        records = self.database.project_issues.find({"project_id": str(identifier), "run_id": run_id}, {"_id": 0, "issue_id": 1, "review": 1}).sort("issue_id", ASCENDING)
        cases = self.database.project_cases.find({"project_id": str(identifier), "run_id": run_id}, {"_id": 0}).sort("case_id", ASCENDING)
        return {"issues": list(records), "cases": list(cases)}

    def review_issue(self, identifier, run_id, issue_id, payload):
        self.require_run(identifier, run_id)
        if not re.fullmatch(r"[a-f0-9]{24}", issue_id):
            raise HTTPException(404, "issue_not_found")
        query = {"project_id": str(identifier), "run_id": run_id, "issue_id": issue_id}
        review = {**payload.model_dump(exclude={"expected_revision"}), "revision": payload.expected_revision + 1, "updated_at": utc_now(), "origin": "human", "expert_accepted": False, **(self.access.review_identity() if self.access else {})}
        saved = self.database.project_issues.find_one_and_update({**query, "review.revision": payload.expected_revision}, {"$set": {"review": review}}, return_document=ReturnDocument.AFTER)
        if saved is None:
            if self.database.project_issues.find_one(query, {"_id": 1}) is None:
                raise HTTPException(404, "issue_not_found")
            raise HTTPException(409, "review_revision_conflict")
        return {"issue_id": issue_id, "review": saved["review"]}

    def review_case(self, identifier, run_id, case_id, payload):
        self.require_run(identifier, run_id)
        if not re.fullmatch(r"[a-z0-9_]{1,64}", case_id):
            raise HTTPException(404, "case_not_found")
        query = {"project_id": str(identifier), "run_id": run_id, "case_id": case_id}
        review = {**payload.model_dump(exclude={"expected_revision"}), "revision": payload.expected_revision + 1, "updated_at": utc_now(), "origin": "human", "expert_accepted": False, **(self.access.review_identity() if self.access else {})}
        saved = self.database.project_cases.find_one_and_update({**query, "review.revision": payload.expected_revision}, {"$set": {"review": review}}, return_document=ReturnDocument.AFTER)
        if saved is None:
            if self.database.project_cases.find_one(query, {"_id": 1}) is None:
                raise HTTPException(404, "case_not_found")
            raise HTTPException(409, "review_revision_conflict")
        return {"case_id": case_id, "review": saved["review"]}

    def export_dataset(self, identifier, run_id):
        restored = self.restore_run(identifier, run_id)
        report = restored["report"]
        reviews = self.reviews(identifier, run_id)
        by_id = {item["issue_id"]: item["review"] for item in reviews["issues"]}
        return {"schema_version": 1, "project_id": str(identifier), "run_id": run_id, "created_at": utc_now(), "dataset": report["dataset"], "sources": report["sources"], "parameters": report["parameters"], "coverage": report["coverage"], "evaluation": {key: value for key, value in (report.get("evaluation") or {}).items() if key != "case_results"}, "cases": reviews["cases"], "issues": [{**issue, "review": by_id[issue["id"]]} for issue in report["issues"]], "reviewed_cases": sum(case["review"]["label"] != "unreviewed" for case in reviews["cases"]), "expert_accepted": False, "split_policy": "Keep a project, all its revisions, and all variants of one parametric family in the same split."}
