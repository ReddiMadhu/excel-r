import logging
from src.server.models.database import Database
from src.rationalization.overlap_scorer import compute_pairwise_overlaps, compute_uniqueness_scores
from src.rationalization.recommender import Recommender

logging.basicConfig(level=logging.INFO)
db = Database()

print("Recalculating overlap scores and recommendations...")
pairwise = compute_pairwise_overlaps(db)
uniqueness = compute_uniqueness_scores(db, pairwise)

recommender = Recommender(db)
recs = recommender.run(pairwise, uniqueness)

print(f"Successfully generated {len(recs)} recommendations and saved to database.")
