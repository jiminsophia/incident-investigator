from __future__ import annotations


def retrieve_relevant_artifacts(
    artifacts: list[dict], error_component: str, latency_service: str, span_names: list[str]
) -> list[dict]:
    search_terms = {
        error_component.lower(),
        latency_service.lower(),
        *[name.lower() for name in span_names],
    }

    scored = []
    for artifact in artifacts:
        haystack = " ".join(
            [
                artifact["title"],
                artifact["location"],
                artifact["summary"],
                " ".join(artifact.get("keywords", [])),
            ]
        ).lower()
        score = sum(term in haystack for term in search_terms)
        if score:
            scored.append((score, artifact))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [artifact for _, artifact in scored[:5]]

