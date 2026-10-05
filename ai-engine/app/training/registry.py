"""Model registry with an evaluation gate and rollback (file based, no external service).

    python -m app.training.registry register classifier classifier_baseline_202610041849 models/classifier/x.joblib models/classifier/x.metrics.json
    python -m app.training.registry promote  classifier classifier_baseline_202610041849 --by alice
    python -m app.training.registry rollback classifier --by alice
    python -m app.training.registry list

Rules (the spec: never auto-deploy, require evaluation before promotion):
  * a version can only be promoted if its metrics file contains a REAL_TEST section (human-labelled, project-held-out data);
    synthetic-only metrics are refused unless --force (and the override is recorded);
  * its REAL_TEST macro-F1 must be >= the production version's (no regression) and >= --min-macro-f1;
  * every promotion / rollback is appended to an audit history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class GateError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelRegistry:
    def __init__(self, root: str | Path = "models/registry"):
        self.root = Path(root)
        self.file = self.root / "registry.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"models": {}, "production": {}, "history": []}

    def _save(self):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.file)   # atomic

    def _log(self, **kw):
        self.data["history"].append({"at": _now(), **kw})

    # ---------------------------------------------------------------- queries
    def versions(self, name: str) -> list[dict]:
        return self.data["models"].get(name, [])

    def get(self, name: str, version: str) -> dict:
        v = next((x for x in self.versions(name) if x["version"] == version), None)
        if v is None:
            raise GateError(f"unknown model {name}:{version}")
        return v

    def production(self, name: str) -> Optional[dict]:
        ver = self.data["production"].get(name)
        return self.get(name, ver) if ver else None

    # ---------------------------------------------------------------- commands
    def register(self, name: str, version: str, path: str, metrics_path: Optional[str] = None, dataset: Optional[str] = None) -> dict:
        if any(x["version"] == version for x in self.versions(name)):
            raise GateError(f"{name}:{version} is already registered (versions are immutable)")
        metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8")) if metrics_path else {}
        entry = {"version": version, "path": str(path), "metrics_path": metrics_path, "created_at": _now(), "stage": "CANDIDATE",
                 "dataset": dataset or metrics.get("dataset"), "metrics": {k: _summ(metrics.get(k)) for k in ("REAL_TEST", "SYNTHETIC_ONLY_val", "handwritten_probe")}}
        self.data["models"].setdefault(name, []).append(entry)
        self._log(action="register", model=name, version=version)
        self._save()
        return entry

    def promote(self, name: str, version: str, by: str = "unknown", min_macro_f1: float = 0.0, force: bool = False) -> dict:
        cand = self.get(name, version)
        real = cand["metrics"].get("REAL_TEST")
        overridden = []
        if not real:
            if not force:
                raise GateError("refused: no REAL_TEST metrics (human-labelled, project-held-out). Synthetic/probe scores are not evidence for production. Use --force to override (recorded).")
            overridden.append("no REAL_TEST metrics")
        else:
            if real["macro_f1"] < min_macro_f1 and not force:
                raise GateError(f"refused: REAL_TEST macro-F1 {real['macro_f1']:.3f} < required {min_macro_f1:.3f}")
            prod = self.production(name)
            prod_real = prod["metrics"].get("REAL_TEST") if prod else None
            if prod_real and real["macro_f1"] < prod_real["macro_f1"]:
                if not force:
                    raise GateError(f"refused: REAL_TEST macro-F1 {real['macro_f1']:.3f} is below production {prod_real['macro_f1']:.3f} ({prod['version']})")
                overridden.append("regression vs production")
        prev = self.data["production"].get(name)
        for x in self.versions(name):
            if x["version"] == prev:
                x["stage"] = "ARCHIVED"
        cand["stage"] = "PRODUCTION"
        cand["promoted_at"], cand["promoted_by"], cand["previous_production"] = _now(), by, prev
        self.data["production"][name] = version
        self._log(action="promote", model=name, version=version, previous=prev, by=by, overridden=overridden)
        self._save()
        return cand

    def rollback(self, name: str, by: str = "unknown") -> dict:
        cur = self.production(name)
        if not cur or not cur.get("previous_production"):
            raise GateError("nothing to roll back to")
        prev = self.get(name, cur["previous_production"])
        cur["stage"] = "ARCHIVED"
        prev["stage"] = "PRODUCTION"
        self.data["production"][name] = prev["version"]
        self._log(action="rollback", model=name, from_version=cur["version"], to_version=prev["version"], by=by)
        self._save()
        return prev


def _summ(m: Optional[dict]) -> Optional[dict]:
    if not m:
        return None
    return {k: m[k] for k in ("n", "accuracy", "macro_f1", "weighted_f1") if k in m}


def production_path(name: str, root: Optional[str] = None) -> Optional[str]:
    """Used by the API: path of the production model, or None when the registry is not configured / empty."""
    root = root or os.getenv("MODEL_REGISTRY_DIR")
    if not root:
        return None
    p = ModelRegistry(root).production(name)
    return p["path"] if p else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getenv("MODEL_REGISTRY_DIR", "models/registry"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register"); r.add_argument("name"); r.add_argument("version"); r.add_argument("path"); r.add_argument("metrics"); r.add_argument("--dataset")
    p = sub.add_parser("promote"); p.add_argument("name"); p.add_argument("version"); p.add_argument("--by", default=os.getenv("USER", "unknown"))
    p.add_argument("--min-macro-f1", type=float, default=0.0); p.add_argument("--force", action="store_true")
    b = sub.add_parser("rollback"); b.add_argument("name"); b.add_argument("--by", default=os.getenv("USER", "unknown"))
    sub.add_parser("list")
    a = ap.parse_args(argv)
    reg = ModelRegistry(a.root)
    try:
        if a.cmd == "register":
            print(json.dumps(reg.register(a.name, a.version, a.path, a.metrics, a.dataset), indent=2))
        elif a.cmd == "promote":
            print("promoted", reg.promote(a.name, a.version, a.by, a.min_macro_f1, a.force)["version"])
        elif a.cmd == "rollback":
            print("rolled back to", reg.rollback(a.name, a.by)["version"])
        else:
            for name, vs in reg.data["models"].items():
                for v in vs:
                    rt = v["metrics"].get("REAL_TEST")
                    print(f"{name:12} {v['version']:48} {v['stage']:11} REAL_TEST macroF1={rt['macro_f1']:.3f}" if rt else f"{name:12} {v['version']:48} {v['stage']:11} (no REAL_TEST)")
    except GateError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
