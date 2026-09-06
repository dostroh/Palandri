"""Incremental analysis for on-demand polls.

process_pipeline.py analyses the whole collection and replaces it. That is the
wrong shape for a live poll, which brings in a handful of posts and must leave
the existing analytics untouched. This module scores just the posts it is given
and hands them back, so the caller decides what to persist.

Every scoring function is imported from process_pipeline rather than reimplemented,
so a change to the batch pipeline automatically applies to polled posts too.
"""

from __future__ import annotations

from collections import Counter


def _pipeline():
    """Import the pipeline lazily.

    Importing it loads spaCy plus two transformer models (~2GB, tens of seconds),
    so the web process should only pay that cost when a poll actually runs.
    """
    from processing import process_pipeline as pp

    return pp


def topic_counts_from(documents) -> Counter:
    """Topic frequencies of already-analysed documents, for burst comparison."""
    counts: Counter = Counter()
    for document in documents:
        topic_id = ((document.get("ml_insights") or {}).get("trends") or {}).get("topic_id")
        if topic_id:
            counts[topic_id] += 1
    return counts


def analyze_documents(posts, *, baseline_topic_counts=None):
    """Score `posts` (raw ingestion documents) and return processing->analytics documents.

    `baseline_topic_counts` should be the topic distribution already in the analytics
    collection. Burst z-scores are then measured against the whole corpus instead of
    against the handful of posts in this poll, where they would be meaningless.
    """
    posts = [post for post in posts if post]
    if not posts:
        return []

    pp = _pipeline()
    centrality_scores = pp.build_network_graph(posts)

    analyses = []
    for post in posts:
        text = post.get("text", "") or ""
        user_id = (post.get("author") or {}).get("user_id", "Unknown")

        doc = pp.nlp(text)
        keywords = pp.extract_keywords(doc)
        topic_category, topic_id = pp.extract_topic(text)
        target_entity = pp.extract_target_entity(doc, keywords, topic_category)

        sentiment = pp.extract_sentiment(text)
        stance = pp.extract_stance(text, target_entity)
        network_signals = pp.extract_network_signals(post, user_id, centrality_scores)
        risk_score = pp.compute_risk_score(
            sentiment["polarity_score"], stance["label"], network_signals["bot_likelihood_score"]
        )

        analyses.append({
            "post": post,
            "keywords": keywords,
            "sentiment": sentiment,
            "stance": stance,
            "topic_category": topic_category,
            "topic_id": topic_id,
            "demographics": pp.extract_demographics(post, text),
            "network_signals": network_signals,
            "risk_score": risk_score,
        })

    # Merge this poll's topics into the corpus baseline, then reuse the pipeline's own
    # z-score routine by expanding the counts back into the list shape it expects.
    counts: Counter = Counter(baseline_topic_counts or {})
    counts.update(analysis["topic_id"] for analysis in analyses)
    expanded = [topic_id for topic_id, count in counts.items() for _ in range(count)]
    burst_z_by_topic = pp.compute_burst_signals(expanded)

    documents = []
    for analysis in analyses:
        z_score = burst_z_by_topic.get(analysis["topic_id"], 0.0)
        ml_insights = {
            "sentiment": analysis["sentiment"],
            "stance": analysis["stance"],
            "demographics": analysis["demographics"],
            "trends": {
                "extracted_keywords": analysis["keywords"][:3],
                "topic_category": analysis["topic_category"],
                "topic_id": analysis["topic_id"],
            },
            "network_signals": analysis["network_signals"],
            "burst_signal": {
                "topic_id": analysis["topic_id"],
                "z_score": z_score,
                "is_burst": z_score > pp.BURST_Z_THRESHOLD,
            },
            "risk_score": analysis["risk_score"],
        }
        documents.append(pp.build_output_document(analysis["post"], ml_insights))
    return documents
