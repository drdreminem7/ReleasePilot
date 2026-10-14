"""Extract only the five pinned Argo CRDs from the verified release artifact."""

import sys
from pathlib import Path

import yaml

EXPECTED = {
    "analysisruns.argoproj.io",
    "analysistemplates.argoproj.io",
    "clusteranalysistemplates.argoproj.io",
    "experiments.argoproj.io",
    "rollouts.argoproj.io",
}


def main() -> None:
    documents = list(yaml.safe_load_all(Path(sys.argv[1]).read_text()))
    crds = [
        item
        for item in documents
        if isinstance(item, dict) and item.get("kind") == "CustomResourceDefinition"
    ]
    names = {item.get("metadata", {}).get("name") for item in crds}
    if names != EXPECTED or len(crds) != len(EXPECTED):
        raise SystemExit("pinned Argo artifact has unexpected CRDs")
    yaml.safe_dump_all(crds, sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
