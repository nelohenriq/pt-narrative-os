"""
Mount Mission Control routes onto the main review app.
"""

from review.mission_control import app as mission_control_app, mount_to_app
from review.app import app as review_app

# Mount Mission Control onto Review UI
mount_to_app(review_app)

# Export the combined app
app = review_app
