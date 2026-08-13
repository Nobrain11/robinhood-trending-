from detectors.pons import PonsDetector


def build_detectors():

    # Only currently verified detector data
    # is enabled by default.

    # Additional launchpads should be added
    # after their current factory addresses
    # and event ABIs are verified.

    return [
        PonsDetector()
    ]
