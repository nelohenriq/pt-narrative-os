import sys
print("Python:", sys.executable)

modules = [
    ("ai.clients", "clients"),
    ("ai.router", "router"),
    ("services.ingestion.feed_reader", "feed_reader"),
    ("services.ingestion.institutional", "institutional"),
    ("services.normalization.parser", "parser"),
    ("services.clustering.embedder", "embedder"),
    ("services.clustering.clusterer", "clusterer"),
    ("services.analysis.article_analyzer", "article_analyzer"),
    ("services.enrichment.enricher", "enricher"),
    ("services.scoring.scorer", "scorer"),
    ("services.generation.generator", "generator"),
    ("services.digest.digest_builder", "digest_builder"),
    ("db.pool", "pool"),
    ("api.main", "api_main"),
    ("review.app", "review_app"),
]

results = {}
for mod_path, label in modules:
    try:
        __import__(mod_path)
        results[label] = "OK"
    except Exception as e:
        results[label] = f"FAIL: {e}"

for k, v in results.items():
    print(f"  {k}: {v}")