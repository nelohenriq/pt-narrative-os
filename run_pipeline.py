"""
pt-media-os — Pipeline Runner

Runs all pipeline services in sequence. Can be used as a cron job
or invoked directly for development/testing.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_full_pipeline():
    """Run all pipeline services in order."""
    from services.ingestion.feed_reader import ingest_all_feeds
    from services.ingestion.institutional import ingest_institutional
    from services.normalization.parser import normalize_batch
    from services.clustering.embedder import embed_batch
    from services.clustering.clusterer import cluster_batch
    from services.analysis.article_analyzer import analyze_batch
    from services.enrichment.enricher import enrich_batch
    from services.scoring.scorer import score_batch
    from services.generation.generator import generate_batch

    logger.info("=== Pipeline run starting ===")

    # 1. Ingestion
    logger.info("Step 1: Ingestion (RSS feeds)")
    feeds = await ingest_all_feeds()
    total_inserted = sum(f.get("inserted", 0) for f in feeds)
    total_fetched = sum(f.get("fetched", 0) for f in feeds)
    logger.info("Fetched %d items, inserted %d new from %d outlets",
                total_fetched, total_inserted, len(feeds))

    # 1b. Institutional
    logger.info("Step 1b: Institutional ingestion")
    inst = await ingest_institutional()
    logger.info("Institutional: %s", inst)

    # 2. Normalization
    logger.info("Step 2: Normalization")
    norm = await normalize_batch()
    logger.info("Normalized: processed=%s parsed=%s failed=%s skipped=%s",
                norm.get("processed"), norm.get("parsed"),
                norm.get("failed"), norm.get("skipped"))

    # 3. Embedding
    logger.info("Step 3: Embedding")
    emb = await embed_batch()
    logger.info("Embedded: processed=%s embedded=%s failed=%s lusa_detected=%s",
                emb.get("processed"), emb.get("embedded"),
                emb.get("failed"), emb.get("lusa_detected"))

    # 4. Clustering
    logger.info("Step 4: Clustering")
    clust = await cluster_batch()
    logger.info("Clustered: processed=%s clustered=%s failed=%s",
                clust.get("processed"), clust.get("clustered"), clust.get("failed"))

    # 5. Analysis
    logger.info("Step 5: Analysis (AI extraction)")
    ana = await analyze_batch()
    logger.info("Analyzed: processed=%s analyzed=%s failed=%s",
                ana.get("processed"), ana.get("analyzed"), ana.get("failed"))

    # 6. Enrichment
    logger.info("Step 6: Enrichment")
    enr = await enrich_batch()
    logger.info("Enriched: processed=%s enriched=%s failed=%s",
                enr.get("processed"), enr.get("enriched"), enr.get("failed"))

    # 7. Scoring
    logger.info("Step 7: Scoring")
    sco = await score_batch()
    logger.info("Scored: processed=%s scored=%s failed=%s",
                sco.get("processed"), sco.get("scored"), sco.get("failed"))

    # 8. Generation
    logger.info("Step 8: Generation (AI summaries)")
    gen = await generate_batch()
    logger.info("Generated: processed=%s generated=%s failed=%s",
                gen.get("processed"), gen.get("generated"), gen.get("failed"))

    logger.info("=== Pipeline run complete ===")
    return {
        "ingestion": {"fetched": total_fetched, "inserted": total_inserted, "outlets": len(feeds)},
        "institutional": inst,
        "normalization": norm,
        "embedding": {"embedded": emb.get("embedded"), "failed": emb.get("failed")},
        "clustering": clust,
        "analysis": {"analyzed": ana.get("analyzed"), "failed": ana.get("failed")},
        "enrichment": enr,
        "scoring": sco,
        "generation": {"generated": gen.get("generated"), "failed": gen.get("failed")},
    }


def main():
    """Entry point for the pipeline runner."""
    result = asyncio.run(run_full_pipeline())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import json
    main()
