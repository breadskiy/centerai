from .secrets import scan as secrets
from .sca import scan as sca
from .sast import scan as sast

SCANNERS = {"secrets_scanner": secrets, "sca_scanner": sca, "sast_scanner": sast}
