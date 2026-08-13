# ==================================================================
# SCANNING
# ==================================================================

def scan_range(
    self,
    from_block: int,
    to_block: int,
):

    if to_block < from_block:
        return

    logger.info(
        "Scanning %s -> %s",
        from_block,
        to_block,
    )

    # --------------------------------------------------------------
    # Pons RPC filter
    # --------------------------------------------------------------

    address = None
    topics = None

    try:

        from detectors.pons import (
            PonsDetector,
        )

        address = PonsDetector.address

        topics = [
            PonsDetector.topic0
        ]

        logger.debug(
            "Using Pons filter: address=%s topic=%s",
            address,
            PonsDetector.topic0,
        )

    except Exception:

        logger.exception(
            "Unable to load Pons RPC filter"
        )

    # --------------------------------------------------------------
    # Get logs
    # --------------------------------------------------------------

    logs = self.chain.get_logs(
        from_block,
        to_block,
        address=address,
        topics=topics,
    )

    # --------------------------------------------------------------
    # IMPORTANT DEBUG LOG
    # --------------------------------------------------------------

    logger.info(
        "Pons logs found: %s for blocks %s -> %s",
        len(logs),
        from_block,
        to_block,
    )

    # --------------------------------------------------------------
    # Process logs
    # --------------------------------------------------------------

    for log in logs:

        self.process_launch_log(
            log
        )

    # --------------------------------------------------------------
    # Only checkpoint after the entire range succeeds.
    # --------------------------------------------------------------

    self.db.set_state(
        "last_scanned_block",
        str(to_block),
    )
