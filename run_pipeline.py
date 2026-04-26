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
    from services.ingestion.feed_reader import run_ingestion
    from services.ingestion.institutional import run_institutional_ingestion
    from services.normalization.parser import run_normalization
    from services.clustering.embedder import run_embedding
    from services.clustering.clusterer import run_clustering
    from services.analysis.article_analyzer import run_analysis
    from services.enrichment.enricher import run_enrichment
    from services.scoring.scorer import run_scoring
    from services.generation.generator import run_generation

    logger.info("=== Pipeline run starting ===")

    # 1. Ingestion
    logger.info("Step 1: Ingestion")
    results = await run_ingestion()
    total_ingested = sum(v for v in results.values() if v > 0)
    logger.info("Ingested %d new items from %d outlets", total_ingested, len(results))

    # 1b. Institutional
    inst_results = await run_institutional_ingestion()
    logger.info("Institutional: %s", inst_results)

    # 2. Normalization
    logger.info("Step 2: Normalization")
    normalized = await run_normalization()
    logger.info("Normalized %d articles", normalized)

    # 3. Embedding
    logger.info("Step 3: Embedding")
    embedded = await run_embedding()
    logger.info("Embedded %d articles", embedded)

    # 4. Clustering
    logger.info("Step 4: Clustering")
    clustered = await run_clustering()
    logger.info("Clustered %d articles", clustered)

    # 5. Analysis
    logger.info("Step 5: Analysis")
    analyzed = await run_analysis()
    logger.info("Analyzed %d articles", analyzed)

    # 6. Enrichment
    logger.info("Step 6: Enrichment")
    enriched = await run_enrichment()
    logger.info("Enriched %d events", enriched)

    # 7. Scoring
    logger.info("Step 7: Scoring")
    scored = await run_scoring()
    logger.info("Scored %d events", scored)

    # 8. Generation
    logger.info("Step 8: Generation")
    generated = await run_generation()
    logger.info("Generated summaries for %d events", generated)

    logger.info("=== Pipeline run complete ===")
    return {
        "ingested": total_ingested,
        "normalized": normalized,
        "embedded": embedded,
        "clustered": clustered,
        "analyzed": analyzed,
        "enriched": enriched,
        "scored": scored,
        "generated": generated,
    }


def main():
    """Entry point for the pipeline runner."""
    result = asyncio.run(run_full_pipeline())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import json
    main()
